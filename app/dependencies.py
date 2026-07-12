import hmac
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .database import get_db
from .models import PlexUser, Settings


def get_settings_or_404(db: Session = Depends(get_db)) -> Settings:
    s = db.query(Settings).first()
    if not s:
        raise HTTPException(status_code=404, detail="Paramètres non initialisés")
    return s


def _valid_api_key(request: Request, db: Session) -> bool:
    """Vrai si l'en-tête X-Api-Key correspond au token API (niveau admin)."""
    token = request.headers.get("X-Api-Key")
    if not token:
        return False
    s = db.query(Settings).first()
    return bool(s and s.api_token and hmac.compare_digest(s.api_token, token))


def _configured_api_scopes(settings: Settings | None) -> set[str]:
    if not settings or not settings.api_token_scopes:
        return {"*"}
    return {scope.strip() for scope in settings.api_token_scopes.split(",") if scope.strip()}


def _api_key_has_scope(request: Request, db: Session, required_scope: str) -> bool:
    token = request.headers.get("X-Api-Key")
    if not token:
        return False
    settings = db.query(Settings).first()
    if not settings or not settings.api_token or not hmac.compare_digest(settings.api_token, token):
        return False
    scopes = _configured_api_scopes(settings)
    return "*" in scopes or required_scope in scopes


def current_user(request: Request, db: Session = Depends(get_db)) -> dict | None:
    """Décrit l'appelant authentifié par session (pour les pages et l'affichage conditionnel).
    
    Retourne None si non authentifié. L'API token n'accorde plus le statut d'admin global
    sur l'interface interne (voir require_api_scope pour les routes d'API externes).
    """
    if request.session.get("authenticated"):
        return {
            "id": request.session.get("user_id"),
            "is_owner": bool(request.session.get("is_owner")),
            "role": request.session.get("role") or "admin",
            "plex_user_id": request.session.get("plex_user_id"),
            "username": request.session.get("username"),
        }
    return None


def _is_admin(user: dict | None) -> bool:
    return bool(user and (user.get("is_owner") or user.get("role") == "admin"))


def require_auth(request: Request, db: Session = Depends(get_db)):
    """Dépendance : n'importe quel utilisateur authentifié (session ou token API)."""
    if request.session.get("authenticated") or _valid_api_key(request, db):
        return
    raise HTTPException(status_code=401, detail="Non authentifié")


def require_api_scope(scope: str) -> Callable:
    def _dependency(request: Request, db: Session = Depends(get_db)):
        if request.session.get("authenticated"):
            return
        if not request.headers.get("X-Api-Key"):
            return
        if _api_key_has_scope(request, db, scope):
            return
        raise HTTPException(status_code=403, detail=f"Scope API requis: {scope}")

    return _dependency


def require_admin(request: Request, db: Session = Depends(get_db)):
    """Dépendance : réservé aux administrateurs (owner, rôle admin, ou token API).

    Les comptes Plex avec le rôle 'user' sont refusés (403) — ils n'accèdent qu'à
    Discover et à leurs propres demandes.
    """
    user = current_user(request, db)
    if _is_admin(user):
        return
    if user:  # authentifié mais rôle insuffisant
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")
    raise HTTPException(status_code=401, detail="Non authentifié")


def get_current_plex_user(request: Request, db: Session = Depends(get_db)) -> PlexUser | None:
    """Retourne l'enregistrement PlexUser de l'appelant, si connecté via Plex SSO."""
    uid = request.session.get("plex_user_id")
    if not uid:
        return None
    return db.query(PlexUser).filter(PlexUser.plex_user_id == uid).first()
