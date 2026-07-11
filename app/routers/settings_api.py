import hmac
import logging
import secrets
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_settings_or_404, require_admin
from ..models import Settings
from ..scheduler import _send_digest, update_poll_interval
from ..scheduler import scheduler as _scheduler
from ..services import email_service, radarr, sonarr
from ..services.notifications import send_gotify, send_ntfy
from ..services.plex_api import check_connection as plex_test
from ..services.plex_rss import test_rss
from ..services.seer import check_connection as seer_test
from ..services.totp import generate_secret, provisioning_uri, verify_code

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["settings"], dependencies=[Depends(require_admin)])

GRANULARITY_MODES = {"minimal", "jalons", "tout"}


def _validate_notify_settings(payload: dict):
    granularity = payload.get("series_notify_granularity")
    if granularity is not None and granularity not in GRANULARITY_MODES:
        raise HTTPException(status_code=400, detail=f"Granularité de notification invalide: {granularity}")


class SettingsUpdate(BaseModel):
    plex_url: Optional[str] = None
    plex_token: Optional[str] = None
    plex_verify_ssl: Optional[bool] = None
    plex_rss_url: Optional[str] = None
    watchlist_source_priority: Optional[str] = None
    watchlist_fallback_enabled: Optional[bool] = None
    poll_interval_minutes: Optional[int] = None
    poll_interval_seconds: Optional[int] = None
    # --- SMTP / Mail ---
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_tls: Optional[bool] = None
    admin_notification_email: Optional[str] = None
    email_on_request: Optional[bool] = None
    email_on_available: Optional[bool] = None
    email_on_failure: Optional[bool] = None
    email_recipients: Optional[str] = None
    email_send_available: Optional[bool] = None
    email_send_request: Optional[bool] = None
    email_send_failure: Optional[bool] = None
    email_request_template: Optional[str] = None
    email_available_template: Optional[str] = None
    email_upgrade_template: Optional[str] = None
    email_failure_template: Optional[str] = None
    email_request_subject: Optional[str] = None
    email_available_subject: Optional[str] = None
    email_upgrade_subject: Optional[str] = None
    email_failure_subject: Optional[str] = None
    email_templates_backup: Optional[str] = None
    # --- Discord ---
    discord_enabled: Optional[bool] = None
    discord_webhook_url: Optional[str] = None
    discord_send_available: Optional[bool] = None
    discord_send_request: Optional[bool] = None
    discord_send_failure: Optional[bool] = None
    # --- Telegram ---
    telegram_enabled: Optional[bool] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_send_available: Optional[bool] = None
    telegram_send_request: Optional[bool] = None
    telegram_send_failure: Optional[bool] = None
    # --- Gotify ---
    gotify_enabled: Optional[bool] = None
    gotify_url: Optional[str] = None
    gotify_token: Optional[str] = None
    gotify_send_available: Optional[bool] = None
    gotify_send_request: Optional[bool] = None
    gotify_send_failure: Optional[bool] = None
    # --- Ntfy ---
    ntfy_enabled: Optional[bool] = None
    ntfy_url: Optional[str] = None
    ntfy_topic: Optional[str] = None
    ntfy_token: Optional[str] = None
    ntfy_send_available: Optional[bool] = None
    ntfy_send_request: Optional[bool] = None
    ntfy_send_failure: Optional[bool] = None
    # --- Overseerr/Jellyseerr ---
    seer_enabled: Optional[bool] = None
    seer_url: Optional[str] = None
    seer_api_key: Optional[str] = None
    seer_send_requests: Optional[bool] = None
    seer_fallback_arr: Optional[bool] = None
    # --- TMDB (découverte) ---
    tmdb_api_key: Optional[str] = None
    # --- Retention & Purges ---
    notification_log_retention_days: Optional[int] = None
    arr_poll_interval_hours: Optional[int] = None
    # --- RSS Output ---
    rss_hash: Optional[str] = None
    # --- Torrent client config ---
    torrent_client_type: Optional[str] = None
    torrent_client_url: Optional[str] = None
    torrent_client_username: Optional[str] = None
    torrent_client_password: Optional[str] = None
    torrent_auto_add: Optional[bool] = None
    torrent_required_keywords: Optional[str] = None
    torrent_forbidden_keywords: Optional[str] = None
    torrent_min_size_gb: Optional[float] = None
    torrent_max_size_gb: Optional[float] = None
    digest_enabled: Optional[bool] = None
    digest_hour: Optional[int] = None
    torrent_ratio_limit: Optional[float] = None
    torrent_seed_time_limit_hours: Optional[int] = None
    torrent_auto_delete_files: Optional[bool] = None
    # --- VFF ---
    vff_enabled: Optional[bool] = None
    vff_libraries: Optional[str] = None
    vff_recheck_interval_minutes: Optional[int] = None
    vff_auto_search: Optional[bool] = None
    email_on_vf_available: Optional[bool] = None
    movie_notify_language: Optional[bool] = None
    series_notify_language: Optional[bool] = None
    series_notify_granularity: Optional[str] = None
    require_approval: Optional[bool] = None
    default_locale: Optional[str] = None


class SmtpTestRequest(BaseModel):
    recipient: str


class ApiTokenCreate(BaseModel):
    scopes: list[str] = ["*"]


class TotpEnableRequest(BaseModel):
    code: str


@router.get("/settings")
def get_settings(s: Settings = Depends(get_settings_or_404)):
    """Retourne la configuration complète. Le mot de passe SMTP est masqué."""
    d = {c.name: getattr(s, c.name) for c in s.__table__.columns}
    if d.get("smtp_password"):
        d["smtp_password"] = "••••••••"
    if d.get("totp_secret"):
        d["totp_secret"] = "configured"
    return d


@router.put("/settings")
def update_settings(data: SettingsUpdate, db: Session = Depends(get_db), s: Settings = Depends(get_settings_or_404)):
    """Met à jour la configuration. Ignore la valeur masquée du mot de passe SMTP."""
    # Champs qui peuvent être explicitement effacés avec null (template custom → retour au défaut)
    _nullable_fields = {
        "email_request_template",
        "email_available_template",
        "email_upgrade_template",
        "email_request_subject",
        "email_available_subject",
        "email_upgrade_subject",
        "email_templates_backup",
        "torrent_required_keywords",
        "torrent_forbidden_keywords",
        "torrent_min_size_gb",
        "torrent_max_size_gb",
        "torrent_ratio_limit",
        "torrent_seed_time_limit_hours",
    }
    payload = data.model_dump()
    _validate_notify_settings(payload)
    for key, val in payload.items():
        if val is None and key not in _nullable_fields:
            continue
        if key == "smtp_password" and val == "••••••••":
            continue
        if key == "notification_log_retention_days" and val == 0:
            val = None
        setattr(s, key, val)
    db.commit()
    # Priorité aux secondes (polling sous la minute) ; repli sur les minutes.
    if data.poll_interval_seconds:
        update_poll_interval(data.poll_interval_seconds)
    elif data.poll_interval_minutes:
        update_poll_interval(data.poll_interval_minutes * 60)
    # Replanifier le digest si l'heure ou l'activation change
    if data.digest_enabled is not None or data.digest_hour is not None:
        hour = s.digest_hour or 8
        if s.digest_enabled:
            _scheduler.add_job(_send_digest, "cron", hour=hour, minute=0, id="digest", replace_existing=True)
        else:
            try:
                _scheduler.remove_job("digest")
            except Exception:
                pass
    # Replanifier le job VFF si l'intervalle a changé
    if data.vff_recheck_interval_minutes:
        from apscheduler.triggers.interval import IntervalTrigger

        try:
            _scheduler.reschedule_job(
                "vf_status_check", trigger=IntervalTrigger(minutes=data.vff_recheck_interval_minutes)
            )
        except Exception:
            pass
    return {"status": "ok"}


@router.post("/settings/token")
def generate_api_token(body: ApiTokenCreate | None = None, db: Session = Depends(get_db)):
    """Génère un nouveau token d'API et le stocke dans les paramètres."""
    s = db.query(Settings).first()
    if not s:
        raise HTTPException(404, "Paramètres non initialisés")
    token = secrets.token_urlsafe(32)
    scopes = body.scopes if body else ["*"]
    scopes = [scope.strip() for scope in scopes if scope.strip()]
    s.api_token = token
    s.api_token_scopes = ",".join(scopes or ["*"])
    db.commit()
    return {"api_token": token, "scopes": scopes or ["*"]}


@router.delete("/settings/token")
def revoke_api_token(db: Session = Depends(get_db)):
    """Révoque le token d'API courant."""
    s = db.query(Settings).first()
    if not s:
        raise HTTPException(404, "Paramètres non initialisés")
    s.api_token = None
    s.api_token_scopes = None
    db.commit()
    return {"status": "revoked"}


@router.get("/settings/token")
def get_api_token_status(db: Session = Depends(get_db)):
    """Indique si un token d'API est actif (sans révéler sa valeur)."""
    s = db.query(Settings).first()
    scopes = [scope.strip() for scope in (s.api_token_scopes or "*").split(",") if scope.strip()] if s else []
    return {"active": bool(s and s.api_token), "scopes": scopes}


@router.post("/settings/totp/setup")
def setup_totp(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s:
        raise HTTPException(404, "Parametres non initialises")
    secret = generate_secret()
    s.totp_secret = secret
    s.totp_enabled = False
    db.commit()
    account = s.auth_username or "admin"
    return {"secret": secret, "provisioning_uri": provisioning_uri(secret, account), "enabled": False}


@router.post("/settings/totp/enable")
def enable_totp(body: TotpEnableRequest, db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s or not s.totp_secret:
        raise HTTPException(400, "Aucun secret 2FA en attente")
    if not verify_code(s.totp_secret, body.code):
        raise HTTPException(400, "Code 2FA invalide")
    s.totp_enabled = True
    db.commit()
    return {"enabled": True}


@router.delete("/settings/totp")
def disable_totp(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s:
        raise HTTPException(404, "Parametres non initialises")
    s.totp_secret = None
    s.totp_enabled = False
    db.commit()
    return {"enabled": False}


@router.post("/settings/webhook-secret")
def generate_webhook_secret(db: Session = Depends(get_db)):
    """Génère un nouveau secret de webhook et le stocke dans les paramètres."""
    s = db.query(Settings).first()
    if not s:
        raise HTTPException(404, "Paramètres non initialisés")
    secret = secrets.token_urlsafe(32)
    s.webhook_secret = secret
    db.commit()
    return {"webhook_secret": secret}


@router.delete("/settings/webhook-secret")
def revoke_webhook_secret(db: Session = Depends(get_db)):
    """Révoque le secret de webhook courant (désactive l'authentification des webhooks)."""
    s = db.query(Settings).first()
    if not s:
        raise HTTPException(404, "Paramètres non initialisés")
    s.webhook_secret = None
    db.commit()
    return {"status": "revoked"}


@router.get("/settings/webhook-secret")
def get_webhook_secret_status(db: Session = Depends(get_db)):
    """Indique si un secret de webhook est actif (sans révéler sa valeur)."""
    s = db.query(Settings).first()
    return {"active": bool(s and s.webhook_secret)}


@router.post("/test/plex-api")
async def test_plex_api(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s:
        return {"success": False, "message": "Paramètres non initialisés"}
    ok, msg = await plex_test(s.plex_url or "", s.plex_token or "", verify_ssl=s.plex_verify_ssl)
    return {"success": ok, "message": msg}


@router.post("/test/plex-rss")
async def test_plex_rss(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s:
        return {"success": False, "message": "Paramètres non initialisés"}
    ok, msg = await test_rss(s.plex_rss_url or "")
    return {"success": ok, "message": msg}


@router.post("/test/sonarr")
async def test_sonarr(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s:
        return {"success": False, "message": "Paramètres non initialisés"}
    ok, msg = await sonarr.check_connection(s.sonarr_url or "", s.sonarr_api_key or "")
    return {"success": ok, "message": msg}


@router.post("/test/radarr")
async def test_radarr(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s:
        return {"success": False, "message": "Paramètres non initialisés"}
    ok, msg = await radarr.check_connection(s.radarr_url or "", s.radarr_api_key or "")
    return {"success": ok, "message": msg}


@router.post("/test/discord")
async def test_discord(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s or not s.discord_webhook_url:
        return {"success": False, "message": "Webhook Discord non configuré"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(s.discord_webhook_url, json={"content": "Test Plexarr — Discord OK !"})
            r.raise_for_status()
        return {"success": True, "message": "Message Discord envoyé !"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/test/telegram")
async def test_telegram(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s or not s.telegram_bot_token or not s.telegram_chat_id:
        return {"success": False, "message": "Telegram non configuré"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
                json={"chat_id": s.telegram_chat_id, "text": "Test Plexarr — Telegram OK !"},
            )
            r.raise_for_status()
        return {"success": True, "message": "Message Telegram envoyé !"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/test/ntfy")
async def test_ntfy(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s or not s.ntfy_url:
        return {"success": False, "message": "ntfy non configuré"}

    try:
        await send_ntfy(s.ntfy_url, s.ntfy_token, "Test Plexarr", "Test de notification ntfy OK !")
        return {"success": True, "message": "Notification ntfy envoyée !"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/test/gotify")
async def test_gotify(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s or not s.gotify_url or not s.gotify_token:
        return {"success": False, "message": "Gotify non configuré"}

    try:
        await send_gotify(s.gotify_url, s.gotify_token, "Test Plexarr", "Test de notification Gotify OK !")
        return {"success": True, "message": "Notification Gotify envoyée !"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/test/tmdb")
async def test_tmdb(db: Session = Depends(get_db)):
    from ..services import tmdb as tmdb_service

    ok, msg = await tmdb_service.check_connection(db)
    return {"success": ok, "message": msg}


@router.post("/test/seer")
async def test_seer(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s or not s.seer_url or not s.seer_api_key:
        return {"success": False, "message": "Seer non configuré"}
    ok, msg = await seer_test(s.seer_url, s.seer_api_key)
    return {"success": ok, "message": msg}


@router.post("/test/smtp")
async def test_smtp(body: SmtpTestRequest, db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    ok, msg = await email_service.test_smtp(s, body.recipient)
    return {"success": ok, "message": msg}
