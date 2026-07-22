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
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from webauthn import (
    generate_authentication_options,
    verify_authentication_response,
)
from webauthn.helpers import options_to_json

from ..database import get_db_async
from ..dependencies import current_user, require_auth
from ..models import LoginAttempt, PasskeyCredential, PlexUser, Settings
from ..services.auth import hash_password, verify_password
from ..services.plex_api import get_auth_pin, get_plex_account, has_server_access
from ..services.totp import verify_code
from ..utils import now_utc_naive, safe_redirect_path

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")

_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 600


@router.get("/api/session", dependencies=[Depends(require_auth)])
async def session_info(request: Request, db: AsyncSession = Depends(get_db_async)):
    """Return the authenticated identity used by the SPA shell."""
    return current_user(request, db)


async def _is_rate_limited(db: AsyncSession, ip: str) -> bool:
    cutoff = now_utc_naive() - timedelta(seconds=_WINDOW_SECONDS)
    res = await db.execute(
        select(func.count(LoginAttempt.id))
        .filter(
            LoginAttempt.ip_address == ip,
            LoginAttempt.success == False,  # noqa: E712
            LoginAttempt.attempted_at >= cutoff,
        )
    )
    count = res.scalar()
    return count >= _MAX_ATTEMPTS


async def _record_login_attempt(db: AsyncSession, ip: str, username: str | None, success: bool, reason: str | None = None) -> None:
    db.add(LoginAttempt(ip_address=ip, username=username, success=success, reason=reason, attempted_at=now_utc_naive()))
    await db.commit()


@router.get("/setup", response_class=HTMLResponse)
async def setup_get(request: Request, db: AsyncSession = Depends(get_db_async)):
    """Affiche le wizard si aucun compte n'est défini. Redirige sinon."""
    s = (await db.execute(select(Settings))).scalars().first()
    if s and s.auth_username:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "setup.html", {"error": None})


@router.post("/setup", response_class=HTMLResponse)
async def setup_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: AsyncSession = Depends(get_db_async),
):
    """Crée le compte admin. Redirige vers le login une fois enregistré."""
    s = (await db.execute(select(Settings))).scalars().first()

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
    await db.commit()

    # Connecter l'utilisateur immédiatement après la création du compte
    request.session["authenticated"] = True
    request.session["username"] = username
    request.session["is_owner"] = True
    request.session["role"] = "admin"
    # Enchaîner sur l'assistant de configuration adaptatif (Plex, *arr, notifications…)
    return RedirectResponse("/setup/wizard?first=1", status_code=302)


@router.get("/login", response_class=HTMLResponse)
async def login_get(request: Request, next: str = "/", db: AsyncSession = Depends(get_db_async)):
    """Affiche le formulaire de connexion. Redirige vers /setup si aucun compte."""
    s = (await db.execute(select(Settings))).scalars().first()
    if not s or not s.auth_username:
        return RedirectResponse("/setup", status_code=302)
    if request.session.get("authenticated"):
        return RedirectResponse(safe_redirect_path(next), status_code=302)
    return templates.TemplateResponse(request, "login.html", {"next": next, "error": None})


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy(request: Request, db: AsyncSession = Depends(get_db_async)):
    """Page publique, sans authentification -- liee depuis la connexion, la barre
    laterale et le pied de page des emails.

    Rendue avec les reglages reels de l'instance (retention, canaux actifs) plutot
    qu'un texte generique fige, pour que le contenu reste vrai sans maintenance manuelle."""
    s = (await db.execute(select(Settings))).scalars().first()
    channels = []
    if s:
        if s.email_enabled:
            channels.append("Email")
        if s.discord_enabled and s.discord_webhook_url:
            channels.append("Discord")
        if s.telegram_enabled and s.telegram_bot_token:
            channels.append("Telegram")
        if s.ntfy_enabled and s.ntfy_url:
            channels.append("ntfy")
        if s.gotify_enabled and s.gotify_url:
            channels.append("Gotify")
    context = {
        "notification_retention_days": s.notification_log_retention_days if s else None,
        "poll_history_retention_days": s.poll_history_retention_days if s else None,
        "active_channels": channels,
        "gdpr_contact_name": (s.gdpr_contact_name if s else None) or None,
        "gdpr_contact_email": (s.gdpr_contact_email if s else None) or None,
    }
    return templates.TemplateResponse(request, "privacy.html", context)


@router.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    otp_code: str = Form(default=""),
    next: str = Form(default="/"),
    db: AsyncSession = Depends(get_db_async),
):
    """Vérifie les identifiants et ouvre une session."""
    ip = request.client.host if request.client else "unknown"
    if await _is_rate_limited(db, ip):
        raise HTTPException(status_code=429, detail="Trop de tentatives. Réessayez dans 10 minutes.")

    s = (await db.execute(select(Settings))).scalars().first()

    def error(msg: str):
        return templates.TemplateResponse(request, "login.html", {"next": next, "error": msg})

    if not s or not s.auth_username or not s.auth_password_hash:
        return RedirectResponse("/setup", status_code=302)

    # 1. Vérifier dans la table PlexUser si l'utilisateur existe localement
    user = (await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == username))).scalars().first()
    if user and user.password_hash:
        if not user.enabled or not user.can_login:
            return error("Ce compte n'est pas autorisé à se connecter.")

        if not verify_password(password, user.password_hash):
            await _record_login_attempt(db, ip, username, False, "bad_credentials")
            return error("Identifiants incorrects.")

        if user.totp_enabled and not verify_code(user.totp_secret, otp_code):
            await _record_login_attempt(db, ip, username, False, "bad_totp")
            return error("Code 2FA incorrect.")

        request.session["authenticated"] = True
        request.session["username"] = user.plex_user_id
        request.session["is_owner"] = user.role == "admin"
        request.session["role"] = user.role or "user"
        request.session["plex_user_id"] = user.plex_user_id if user.source == "plex_sso" else None
        request.session["user_id"] = user.id
        await _record_login_attempt(db, ip, username, True)

        return RedirectResponse(safe_redirect_path(next), status_code=302)

    # 2. Repli historique (Settings global admin)
    if not hmac.compare_digest(username, s.auth_username) or not verify_password(password, s.auth_password_hash):
        await _record_login_attempt(db, ip, username, False, "bad_credentials")
        return error("Identifiants incorrects.")

    if s.totp_enabled and not verify_code(s.totp_secret, otp_code):
        await _record_login_attempt(db, ip, username, False, "bad_totp")
        return error("Code 2FA incorrect.")

    admin_user = (await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == username))).scalars().first()
    user_id = admin_user.id if admin_user else None

    request.session["authenticated"] = True
    request.session["username"] = username
    request.session["is_owner"] = True
    request.session["role"] = "admin"
    request.session["user_id"] = user_id
    await _record_login_attempt(db, ip, username, True)

    return RedirectResponse(safe_redirect_path(next), status_code=302)


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
async def login_plex_check(pin_id: int, request: Request, db: AsyncSession = Depends(get_db_async)):
    """Vérifie si le PIN Plex a été validé ; si oui, ouvre la session du bon utilisateur.

    Le token Plex ne sert qu'à identifier le compte (plex.tv /api/v2/user) — il n'est
    jamais persisté. Un compte inconnu est créé avec le rôle 'user' ; il doit être
    autorisé (can_login) et actif (enabled) pour se connecter.
    """
    from ..services.plex_api import check_auth_pin

    logger.info("SSO Login check: pin_id=%s", pin_id)
    try:
        token = await check_auth_pin(pin_id)
    except Exception as e:
        logger.error("SSO Login check error calling check_auth_pin: %s", e)
        raise HTTPException(status_code=502, detail=str(e))

    if not token:
        logger.info("SSO Login check: token not ready yet for pin_id=%s", pin_id)
        return {"authenticated": False}

    logger.info("SSO Login check: token obtained successfully! Resolving Plex account...")
    account = await get_plex_account(token)
    if not account:
        logger.error("SSO Login check: failed to resolve Plex account from token.")
        raise HTTPException(status_code=502, detail="Impossible de résoudre le compte Plex.")

    logger.info("SSO Login check: resolved Plex account: %s", account)

    # Rattachement : uuid stable en priorité, sinon username (users legacy RSS/API).
    user = None
    if account["uuid"]:
        user = (await db.execute(select(PlexUser).filter(PlexUser.plex_account_uuid == account["uuid"]))).scalars().first()
        if user:
            logger.info(
                "SSO Login check: matched existing user by UUID: id=%s, plex_user_id=%s", user.id, user.plex_user_id
            )
    if not user:
        user = (await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == account["username"]))).scalars().first()
        if user:
            logger.info(
                "SSO Login check: matched existing user by username: id=%s, plex_user_id=%s", user.id, user.plex_user_id
            )

    s = (await db.execute(select(Settings))).scalars().first()
    is_admin_username = bool(s and s.auth_username and account["username"] == s.auth_username)
    logger.info(
        "SSO Login check: is_admin_username check: %s (auth_username: %s)",
        is_admin_username,
        s.auth_username if s else "None",
    )

    if s and s.plex_token:
        logger.info("SSO Login check: checking server access via admin token...")
        has_access = await has_server_access(
            admin_token=s.plex_token,
            user_username=account["username"],
            user_email=account.get("email"),
            user_uuid=account["uuid"],
        )
        logger.info("SSO Login check: server access result: %s", has_access)
        if not has_access:
            logger.warning("SSO Login check: access denied. User %s has no access to Plex server.", account["username"])
            raise HTTPException(
                status_code=403, detail="Ce compte Plex n'a pas accès au serveur Plex de l'application."
            )

    if not user:
        logger.info("SSO Login check: user does not exist in DB, creating new PlexUser for %s", account["username"])
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
        await db.flush()
        logger.info("SSO Login check: new user created with id=%s, role=%s", user.id, user.role)
    else:
        # Enrichit / met à jour l'enregistrement existant sans écraser les choix admin.
        logger.info("SSO Login check: enriching existing user id=%s", user.id)
        if account["uuid"] and not user.plex_account_uuid:
            user.plex_account_uuid = account["uuid"]
        if account.get("thumb"):
            user.avatar_url = account["thumb"]
        if account.get("email") and not user.plex_email:
            user.plex_email = account["email"]
        if is_admin_username:
            user.role = "admin"

    if not user.enabled or not user.can_login:
        logger.warning(
            "SSO Login check: user found but is disabled/cannot login (enabled=%s, can_login=%s)",
            user.enabled,
            user.can_login,
        )
        await db.commit()
        raise HTTPException(
            status_code=403, detail="Ce compte n'est pas autorisé à se connecter. Contactez l'administrateur."
        )

    user.last_login_at = now_utc_naive()
    await db.commit()

    request.session["authenticated"] = True
    request.session["is_owner"] = user.role == "admin"
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
    db: AsyncSession = Depends(get_db_async),
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
    db: AsyncSession = Depends(get_db_async),
):
    challenge = request.session.pop("auth_challenge", None)
    if not challenge:
        raise HTTPException(status_code=400, detail="Défi d'authentification expiré ou invalide.")

    rp_id = request.url.hostname
    if rp_id == "127.0.0.1":
        rp_id = "localhost"

    host = request.headers.get("x-forwarded-host", request.url.netloc)
    expected_origin = [f"https://{host}", f"http://{host}"]

    cred_id_str = credential.get("id")
    db_cred = (await db.execute(select(PasskeyCredential).filter(PasskeyCredential.credential_id == cred_id_str))).scalars().first()
    if not db_cred:
        raise HTTPException(status_code=401, detail="Passkey non reconnue.")

    user = (await db.execute(select(PlexUser).filter(PlexUser.id == db_cred.user_id))).scalars().first()
    if not user or not user.enabled or not user.can_login:
        raise HTTPException(status_code=403, detail="Ce compte n'est pas autorisé à se connecter.")

    try:
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=b64decode(challenge),
            expected_origin=expected_origin,
            expected_rp_id=rp_id,
            credential_public_key=b64decode(db_cred.public_key),
            credential_current_sign_count=db_cred.sign_count,
            require_user_verification=False,
        )
    except Exception as e:
        logger.error(f"WebAuthn assertion failed: {e}")
        raise HTTPException(status_code=400, detail=f"Échec de la validation de la Passkey: {e}")

    db_cred.sign_count = verification.new_sign_count
    await db.commit()

    request.session["authenticated"] = True
    request.session["username"] = user.plex_user_id
    request.session["is_owner"] = user.role == "admin"
    request.session["role"] = user.role or "user"
    request.session["plex_user_id"] = user.plex_user_id if user.source == "plex_sso" else None
    request.session["user_id"] = user.id

    return {"success": True}
