"""
Router d'authentification.

Trois routes :
- GET  /setup  : wizard de création du premier compte (affiché si aucun compte n'existe)
- POST /setup  : enregistrement du compte admin
- GET  /login  : formulaire de connexion
- POST /login  : vérification des identifiants et création de session
- GET  /logout : destruction de la session
"""

import hmac
import json
import logging
from base64 import b64decode, b64encode
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    verify_authentication_response,
)
from webauthn.helpers import options_to_json

from ..database import get_db
from ..models import LoginAttempt, PasskeyCredential, PlexUser, Settings
from ..services.auth import hash_password, verify_password
from ..services.plex_api import get_auth_pin, get_plex_account, has_server_access
from ..services.totp import verify_code
from ..utils import now_utc

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")

_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 600


def _is_rate_limited(db: Session, ip: str) -> bool:
    cutoff = now_utc() - timedelta(seconds=_WINDOW_SECONDS)
    count = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.ip_address == ip,
            LoginAttempt.success == False,  # noqa: E712
            LoginAttempt.attempted_at >= cutoff,
        )
        .count()
    )
    return count >= _MAX_ATTEMPTS


def _record_login_attempt(db: Session, ip: str, username: str | None, success: bool, reason: str | None = None) -> None:
    db.add(LoginAttempt(ip_address=ip, username=username, success=success, reason=reason, attempted_at=now_utc()))
    db.commit()


@router.get("/setup", response_class=HTMLResponse)
def setup_get(request: Request, db: Session = Depends(get_db)):
    """Affiche le wizard si aucun compte n'est défini. Redirige sinon."""
    s = db.query(Settings).first()
    if s and s.auth_username:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "setup.html", {"error": None})


@router.post("/setup", response_class=HTMLResponse)
async def setup_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    """Crée le compte admin. Redirige vers le login une fois enregistré."""
    s = db.query(Settings).first()

    # Ne pas permettre de redéfinir les identifiants via ce wizard
    if s and s.auth_username:
        return RedirectResponse("/", status_code=302)

    def error(msg: str):
        return templates.TemplateResponse(request, "setup.html", {"error": msg})

    username = username.strip()
    if not username:
        return error("Le nom d'utilisateur ne peut pas être vide.")
    if len(password) < 8:
        return error("Le mot de passe doit contenir au moins 8 caractères.")
    if password != password_confirm:
        return error("Les mots de passe ne correspondent pas.")

    if not s:
        s = Settings(id=1)
        db.add(s)

    s.auth_username = username
    s.auth_password_hash = hash_password(password)
    db.commit()

    # Connecter l'utilisateur immédiatement après la création du compte
    request.session["authenticated"] = True
    request.session["username"] = username
    request.session["is_owner"] = True
    request.session["role"] = "admin"
    # Enchaîner sur l'assistant de configuration adaptatif (Plex, *arr, notifications…)
    return RedirectResponse("/setup/wizard?first=1", status_code=302)


@router.get("/login", response_class=HTMLResponse)
def login_get(request: Request, next: str = "/", db: Session = Depends(get_db)):
    """Affiche le formulaire de connexion. Redirige vers /setup si aucun compte."""
    s = db.query(Settings).first()
    if not s or not s.auth_username:
        return RedirectResponse("/setup", status_code=302)
    if request.session.get("authenticated"):
        return RedirectResponse(next or "/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"next": next, "error": None})


@router.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    otp_code: str = Form(default=""),
    next: str = Form(default="/"),
    db: Session = Depends(get_db),
):
    """Vérifie les identifiants et ouvre une session."""
    ip = request.client.host if request.client else "unknown"
    if _is_rate_limited(db, ip):
        raise HTTPException(status_code=429, detail="Trop de tentatives. Réessayez dans 10 minutes.")

    s = db.query(Settings).first()

    def error(msg: str):
        return templates.TemplateResponse(request, "login.html", {"next": next, "error": msg})

    if not s or not s.auth_username or not s.auth_password_hash:
        return RedirectResponse("/setup", status_code=302)

    # 1. Vérifier dans la table PlexUser si l'utilisateur existe localement
    user = db.query(PlexUser).filter(PlexUser.plex_user_id == username).first()
    if user and user.password_hash:
        if not user.enabled or not user.can_login:
            return error("Ce compte n'est pas autorisé à se connecter.")

        if not verify_password(password, user.password_hash):
            _record_login_attempt(db, ip, username, False, "bad_credentials")
            return error("Identifiants incorrects.")

        if user.totp_enabled and not verify_code(user.totp_secret, otp_code):
            _record_login_attempt(db, ip, username, False, "bad_totp")
            return error("Code 2FA incorrect.")

        request.session["authenticated"] = True
        request.session["username"] = user.plex_user_id
        request.session["is_owner"] = (user.role == "admin")
        request.session["role"] = user.role or "user"
        request.session["plex_user_id"] = user.plex_user_id if user.source == "plex_sso" else None
        request.session["user_id"] = user.id
        _record_login_attempt(db, ip, username, True)

        safe_next = next if next and next.startswith("/") else "/"
        return RedirectResponse(safe_next, status_code=302)

    # 2. Repli historique (Settings global admin)
    if not hmac.compare_digest(username, s.auth_username) or not verify_password(password, s.auth_password_hash):
        _record_login_attempt(db, ip, username, False, "bad_credentials")
        return error("Identifiants incorrects.")

    if s.totp_enabled and not verify_code(s.totp_secret, otp_code):
        _record_login_attempt(db, ip, username, False, "bad_totp")
        return error("Code 2FA incorrect.")

    admin_user = db.query(PlexUser).filter(PlexUser.plex_user_id == username).first()
    user_id = admin_user.id if admin_user else None

    request.session["authenticated"] = True
    request.session["username"] = username
    request.session["is_owner"] = True
    request.session["role"] = "admin"
    request.session["user_id"] = user_id
    _record_login_attempt(db, ip, username, True)

    safe_next = next if next and next.startswith("/") else "/"
    return RedirectResponse(safe_next, status_code=302)


@router.post("/login/plex/pin")
async def login_plex_pin(request: Request):
    """Initie une connexion Plex SSO : crée un PIN et retourne l'URL d'auth Plex.

    Le front ouvre `auth_url` dans une popup, puis interroge /login/plex/check/{id}.
    """
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    forward_url = f"{scheme}://{host}/login"
    try:
        return await get_auth_pin(forward_url=forward_url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur d'initialisation SSO Plex : {e}")


@router.get("/login/plex/check/{pin_id}")
async def login_plex_check(pin_id: int, request: Request, db: Session = Depends(get_db)):
    """Vérifie si le PIN Plex a été validé ; si oui, ouvre la session du bon utilisateur.

    Le token Plex ne sert qu'à identifier le compte (plex.tv /api/v2/user) — il n'est
    jamais persisté. Un compte inconnu est créé avec le rôle 'user' ; il doit être
    autorisé (can_login) et actif (enabled) pour se connecter.
    """
    from ..services.plex_api import check_auth_pin

    try:
        token = await check_auth_pin(pin_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    if not token:
        return {"authenticated": False}

    account = await get_plex_account(token)
    if not account:
        raise HTTPException(status_code=502, detail="Impossible de résoudre le compte Plex.")

    # Rattachement : uuid stable en priorité, sinon username (users legacy RSS/API).
    user = None
    if account["uuid"]:
        user = db.query(PlexUser).filter(PlexUser.plex_account_uuid == account["uuid"]).first()
    if not user:
        user = db.query(PlexUser).filter(PlexUser.plex_user_id == account["username"]).first()
    s = db.query(Settings).first()
    is_admin_username = bool(s and s.auth_username and account["username"] == s.auth_username)

    if s and s.plex_token:
        has_access = await has_server_access(
            admin_token=s.plex_token,
            user_username=account["username"],
            user_email=account.get("email"),
            user_uuid=account["uuid"],
        )
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="Ce compte Plex n'a pas accès au serveur Plex de l'application."
            )

    if not user:
        user = PlexUser(
            plex_user_id=account["username"],
            display_name=account["username"],
            plex_email=account.get("email"),
            plex_account_uuid=account["uuid"] or None,
            avatar_url=account.get("thumb"),
            role="admin" if is_admin_username else "user",
            can_login=True,
            enabled=True,
            source="plex_sso",
        )
        db.add(user)
        db.flush()
    else:
        # Enrichit / met à jour l'enregistrement existant sans écraser les choix admin.
        if account["uuid"] and not user.plex_account_uuid:
            user.plex_account_uuid = account["uuid"]
        if account.get("thumb"):
            user.avatar_url = account["thumb"]
        if account.get("email") and not user.plex_email:
            user.plex_email = account["email"]
        if is_admin_username:
            user.role = "admin"

    if not user.enabled or not user.can_login:
        db.commit()
        raise HTTPException(
            status_code=403, detail="Ce compte n'est pas autorisé à se connecter. Contactez l'administrateur."
        )

    user.last_login_at = now_utc()
    db.commit()

    request.session["authenticated"] = True
    request.session["is_owner"] = (user.role == "admin")
    request.session["role"] = user.role or "user"
    request.session["plex_user_id"] = user.plex_user_id
    request.session["username"] = user.custom_name or user.display_name or user.plex_user_id
    request.session["user_id"] = user.id
    return {"authenticated": True, "role": user.role or "user"}


@router.get("/logout")
def logout(request: Request):
    """Détruit la session et redirige vers /login."""
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


@router.post("/api/webauthn/login/options")
async def webauthn_login_options(
    request: Request,
    db: Session = Depends(get_db),
):
    rp_id = request.url.hostname
    if rp_id == "127.0.0.1":
        rp_id = "localhost"

    options = generate_authentication_options(
        rp_id=rp_id,
    )

    request.session["auth_challenge"] = b64encode(options.challenge).decode("utf-8")
    return json.loads(options_to_json(options))


@router.post("/api/webauthn/login/verify")
async def webauthn_login_verify(
    request: Request,
    credential: dict,
    db: Session = Depends(get_db),
):
    challenge = request.session.pop("auth_challenge", None)
    if not challenge:
        raise HTTPException(status_code=400, detail="Défi d'authentification expiré ou invalide.")

    rp_id = request.url.hostname
    if rp_id == "127.0.0.1":
        rp_id = "localhost"

    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    expected_origin = f"{scheme}://{host}"

    cred_id_str = credential.get("id")
    db_cred = db.query(PasskeyCredential).filter(PasskeyCredential.credential_id == cred_id_str).first()
    if not db_cred:
        raise HTTPException(status_code=401, detail="Passkey non reconnue.")

    user = db.query(PlexUser).filter(PlexUser.id == db_cred.user_id).first()
    if not user or not user.enabled or not user.can_login:
        raise HTTPException(status_code=403, detail="Ce compte n'est pas autorisé à se connecter.")

    try:
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=b64decode(challenge),
            expected_origin=expected_origin,
            expected_rp_id=rp_id,
            credential_public_key=db_cred.public_key,
            credential_current_sign_count=db_cred.sign_count,
            require_user_verification=False,
        )
    except Exception as e:
        logger.error(f"WebAuthn assertion failed: {e}")
        raise HTTPException(status_code=400, detail=f"Échec de la validation de la Passkey: {e}")

    db_cred.sign_count = verification.new_sign_count
    db.commit()

    request.session["authenticated"] = True
    request.session["username"] = user.plex_user_id
    request.session["is_owner"] = (user.role == "admin")
    request.session["role"] = user.role or "user"
    request.session["plex_user_id"] = user.plex_user_id if user.source == "plex_sso" else None
    request.session["user_id"] = user.id

    return {"success": True}
