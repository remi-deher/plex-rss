"""
Router d'authentification.

Trois routes :
- GET  /setup  : wizard de création du premier compte (affiché si aucun compte n'existe)
- POST /setup  : enregistrement du compte admin
- GET  /login  : formulaire de connexion
- POST /login  : vérification des identifiants et création de session
- GET  /logout : destruction de la session
"""

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Settings
from ..services.auth import hash_password, verify_password

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")

_login_attempts: dict[str, list[float]] = defaultdict(list)
_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 600


def _is_rate_limited(ip: str) -> bool:
    now = time.monotonic()
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < _WINDOW_SECONDS]
    return len(_login_attempts[ip]) >= _MAX_ATTEMPTS


def _record_failed_attempt(ip: str) -> None:
    _login_attempts[ip].append(time.monotonic())


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
    return RedirectResponse("/", status_code=302)


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
    next: str = Form(default="/"),
    db: Session = Depends(get_db),
):
    """Vérifie les identifiants et ouvre une session."""
    ip = request.client.host if request.client else "unknown"
    if _is_rate_limited(ip):
        raise HTTPException(status_code=429, detail="Trop de tentatives. Réessayez dans 10 minutes.")

    s = db.query(Settings).first()

    def error(msg: str):
        return templates.TemplateResponse(request, "login.html", {"next": next, "error": msg})

    if not s or not s.auth_username or not s.auth_password_hash:
        return RedirectResponse("/setup", status_code=302)

    if username != s.auth_username or not verify_password(password, s.auth_password_hash):
        _record_failed_attempt(ip)
        return error("Identifiants incorrects.")

    request.session["authenticated"] = True
    request.session["username"] = username

    # Rediriger vers la page demandée initialement (paramètre ?next=)
    safe_next = next if next and next.startswith("/") else "/"
    return RedirectResponse(safe_next, status_code=302)


@router.get("/logout")
def logout(request: Request):
    """Détruit la session et redirige vers /login."""
    request.session.clear()
    return RedirectResponse("/login", status_code=302)
