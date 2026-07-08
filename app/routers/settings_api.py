import hmac
import logging
import secrets
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_settings_or_404, require_auth
from ..models import Settings
from ..scheduler import _send_digest, scheduler as _scheduler, update_poll_interval
from ..services import email_service, radarr, sonarr
from ..services.notifications import send_gotify, send_ntfy
from ..services.plex_api import check_connection as plex_test
from ..services.plex_rss import test_rss
from ..services.seer import check_connection as seer_test

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["settings"], dependencies=[Depends(require_auth)])

SERIES_NOTIFY_MODES = {
    "every_episode",
    "season_complete",
    "series_complete",
    "season_start_and_complete",
}


def _validate_series_notify_modes(payload: dict):
    for key in ("series_vo_notify_mode", "series_vf_notify_mode", "series_episode_notify_mode"):
        value = payload.get(key)
        if value is not None and value not in SERIES_NOTIFY_MODES:
            raise HTTPException(status_code=400, detail=f"Mode de notification invalide: {value}")
    tracking_mode = payload.get("series_tracking_mode")
    if tracking_mode is not None and tracking_mode not in ("language", "simple"):
        raise HTTPException(status_code=400, detail=f"Mode de suivi invalide: {tracking_mode}")


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
    email_recipients: Optional[str] = None
    email_send_available: Optional[bool] = None
    email_send_request: Optional[bool] = None
    email_send_failure: Optional[bool] = None
    email_request_template: Optional[str] = None
    email_available_template: Optional[str] = None
    email_failure_template: Optional[str] = None
    email_request_subject: Optional[str] = None
    email_available_subject: Optional[str] = None
    email_failure_subject: Optional[str] = None
    email_available_vf_template: Optional[str] = None
    email_available_vf_subject: Optional[str] = None
    email_available_vo_tracking_template: Optional[str] = None
    email_available_vo_tracking_subject: Optional[str] = None
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
    partial_notify_frequency: Optional[str] = None
    movie_vo_notify: Optional[bool] = None
    movie_vf_notify: Optional[bool] = None
    series_vo_notify_mode: Optional[str] = None
    series_vf_notify_mode: Optional[str] = None
    series_tracking_mode: Optional[str] = None
    series_episode_notify_mode: Optional[str] = None


class SmtpTestRequest(BaseModel):
    recipient: str


@router.get("/settings")
def get_settings(s: Settings = Depends(get_settings_or_404)):
    """Retourne la configuration complète. Le mot de passe SMTP est masqué."""
    d = {c.name: getattr(s, c.name) for c in s.__table__.columns}
    if d.get("smtp_password"):
        d["smtp_password"] = "••••••••"
    return d


@router.put("/settings")
def update_settings(data: SettingsUpdate, db: Session = Depends(get_db), s: Settings = Depends(get_settings_or_404)):
    """Met à jour la configuration. Ignore la valeur masquée du mot de passe SMTP."""
    # Champs qui peuvent être explicitement effacés avec null (template custom → retour au défaut)
    _nullable_fields = {
        "email_request_template",
        "email_available_template",
        "email_request_subject",
        "email_available_subject",
        "torrent_required_keywords",
        "torrent_forbidden_keywords",
        "torrent_min_size_gb",
        "torrent_max_size_gb",
        "torrent_ratio_limit",
        "torrent_seed_time_limit_hours",
    }
    payload = data.model_dump()
    _validate_series_notify_modes(payload)
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
def generate_api_token(db: Session = Depends(get_db)):
    """Génère un nouveau token d'API et le stocke dans les paramètres."""
    s = db.query(Settings).first()
    if not s:
        raise HTTPException(404, "Paramètres non initialisés")
    token = secrets.token_urlsafe(32)
    s.api_token = token
    db.commit()
    return {"api_token": token}


@router.delete("/settings/token")
def revoke_api_token(db: Session = Depends(get_db)):
    """Révoque le token d'API courant."""
    s = db.query(Settings).first()
    if not s:
        raise HTTPException(404, "Paramètres non initialisés")
    s.api_token = None
    db.commit()
    return {"status": "revoked"}


@router.get("/settings/token")
def get_api_token_status(db: Session = Depends(get_db)):
    """Indique si un token d'API est actif (sans révéler sa valeur)."""
    s = db.query(Settings).first()
    return {"active": bool(s and s.api_token)}


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
