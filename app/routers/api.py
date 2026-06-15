"""
API REST JSON de l'application.

Endpoints regroupés par domaine :
- /api/settings          : lecture et mise à jour de la configuration
- /api/test/*            : tests de connectivité (Plex, Sonarr, Radarr, SMTP, Discord, Telegram)
- /api/sonarr|radarr/*  : helpers de configuration (profils, dossiers)
- /api/users             : CRUD utilisateurs Plex
- /api/requests          : lecture, retry, suppression, polling manuel
- /api/stats/*           : compteurs, timeline, par utilisateur
- /api/health            : état des services
- /api/activity          : journal d'événements récents
- /api/notifications/*   : médias récemment disponibles
- /api/next-poll         : temps restant avant le prochain polling
- /api/onboarding        : checklist de configuration initiale
"""

import json as _json
import os as _os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import metrics as app_metrics
from ..database import get_db
from ..models import MediaRequest, NotificationLog, PlexUser, Settings
from ..notification_queue import enqueue as enqueue_notification
from ..scheduler import _send_digest, check_arr_statuses, poll_watchlists, update_poll_interval
from ..scheduler import scheduler as _scheduler
from ..services import email_service, radarr, sonarr
from ..services.email_service import DEFAULT_AVAILABLE_TEMPLATE, DEFAULT_REQUEST_TEMPLATE, render_template
from ..services.email_service import _send as smtp_send
from ..services.plex_api import check_connection as plex_test
from ..services.plex_rss import test_rss
from ..services.seer import check_connection as seer_test
from ..utils import get_or_404, parse_email_list


def _format_datetime(dt: Optional[datetime]) -> Optional[str]:
    """Force timezone info to UTC for serialization, resolving timezone offset issues in client-side JS."""
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.isoformat()


def require_auth(request: Request, db: Session = Depends(get_db)):
    """Dépendance API : session cookie OU header X-Api-Key."""
    if request.session.get("authenticated"):
        return
    token = request.headers.get("X-Api-Key")
    if token:
        s = db.query(Settings).first()
        if s and s.api_token and s.api_token == token:
            return
    raise HTTPException(status_code=401, detail="Non authentifié")


router = APIRouter(prefix="/api", tags=["api"], dependencies=[Depends(require_auth)])


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class SettingsUpdate(BaseModel):
    plex_url: Optional[str] = None
    plex_token: Optional[str] = None
    plex_rss_url: Optional[str] = None
    watchlist_source_priority: Optional[str] = None
    watchlist_fallback_enabled: Optional[bool] = None
    poll_interval_minutes: Optional[int] = None
    sonarr_url: Optional[str] = None
    sonarr_api_key: Optional[str] = None
    sonarr_quality_profile_id: Optional[int] = None
    sonarr_root_folder: Optional[str] = None
    sonarr_enabled: Optional[bool] = None
    radarr_url: Optional[str] = None
    radarr_api_key: Optional[str] = None
    radarr_quality_profile_id: Optional[int] = None
    radarr_root_folder: Optional[str] = None
    radarr_enabled: Optional[bool] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_tls: Optional[bool] = None
    email_on_request: Optional[bool] = None
    email_on_available: Optional[bool] = None
    discord_webhook_url: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    admin_notification_email: Optional[str] = None
    radarr_minimum_availability: Optional[str] = None
    seer_url: Optional[str] = None
    seer_api_key: Optional[str] = None
    seer_enabled: Optional[bool] = None
    notification_log_retention_days: Optional[int] = None
    email_request_template: Optional[str] = None
    email_available_template: Optional[str] = None
    email_request_subject: Optional[str] = None
    email_available_subject: Optional[str] = None
    digest_enabled: Optional[bool] = None
    digest_hour: Optional[int] = None


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    """Retourne la configuration complète. Le mot de passe SMTP est masqué."""
    s = db.query(Settings).first()
    if not s:
        raise HTTPException(404, "Settings not found")
    d = {c.name: getattr(s, c.name) for c in s.__table__.columns}
    if d.get("smtp_password"):
        d["smtp_password"] = "••••••••"
    return d


@router.put("/settings")
def update_settings(data: SettingsUpdate, db: Session = Depends(get_db)):
    """Met à jour la configuration. Ignore la valeur masquée du mot de passe SMTP."""
    s = db.query(Settings).first()
    if not s:
        raise HTTPException(status_code=404, detail="Paramètres non initialisés")
    # Champs qui peuvent être explicitement effacés avec null (template custom → retour au défaut)
    _nullable_fields = {
        "email_request_template",
        "email_available_template",
        "email_request_subject",
        "email_available_subject",
    }
    payload = data.model_dump()
    for key, val in payload.items():
        if val is None and key not in _nullable_fields:
            continue
        if key == "smtp_password" and val == "••••••••":
            continue
        if key == "notification_log_retention_days" and val == 0:
            val = None
        setattr(s, key, val)
    db.commit()
    if data.poll_interval_minutes:
        update_poll_interval(data.poll_interval_minutes)
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
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Authentification Plex SSO (OAuth)
# ---------------------------------------------------------------------------


@router.post("/plex/sso/pin")
async def plex_sso_pin(request: Request):
    """Crée une demande de PIN Plex SSO et retourne l'URL d'authentification."""
    from ..services.plex_api import get_auth_pin

    try:
        # Reconstruit l'URL de base en respectant X-Forwarded-Proto (reverse proxy HTTPS)
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.url.netloc)
        forward_url = f"{scheme}://{host}/settings"
        return await get_auth_pin(forward_url=forward_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur d'initialisation SSO Plex : {str(e)}")


@router.get("/plex/sso/check/{pin_id}")
async def plex_sso_check(pin_id: int):
    """Vérifie si le PIN Plex a été validé et retourne le token."""
    from ..services.plex_api import check_auth_pin

    try:
        token = await check_auth_pin(pin_id)
        return {"authenticated": bool(token), "token": token}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Tests de connectivité
# ---------------------------------------------------------------------------


@router.post("/test/plex-api")
async def test_plex_api(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s:
        return {"success": False, "message": "Paramètres non initialisés"}
    ok, msg = await plex_test(s.plex_url or "", s.plex_token or "")
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
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(s.discord_webhook_url, json={"content": "Test Plex RSS Monitor — Discord OK !"})
            r.raise_for_status()
        return {"success": True, "message": "Message Discord envoyé !"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/test/telegram")
async def test_telegram(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s or not s.telegram_bot_token or not s.telegram_chat_id:
        return {"success": False, "message": "Telegram non configuré"}
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
                json={"chat_id": s.telegram_chat_id, "text": "Test Plex RSS Monitor — Telegram OK !"},
            )
            r.raise_for_status()
        return {"success": True, "message": "Message Telegram envoyé !"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/test/seer")
async def test_seer(db: Session = Depends(get_db)):
    from ..services.seer import check_connection as seer_test

    s = db.query(Settings).first()
    if not s or not s.seer_url or not s.seer_api_key:
        return {"success": False, "message": "Seer non configuré"}
    ok, msg = await seer_test(s.seer_url, s.seer_api_key)
    return {"success": ok, "message": msg}


class SmtpTestRequest(BaseModel):
    recipient: str


@router.post("/test/smtp")
async def test_smtp(body: SmtpTestRequest, db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    ok, msg = await email_service.test_smtp(s, body.recipient)
    return {"success": ok, "message": msg}


# ---------------------------------------------------------------------------
# Helpers Sonarr / Radarr (pour les selects de configuration)
# ---------------------------------------------------------------------------


@router.get("/sonarr/profiles")
async def sonarr_profiles(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    return await sonarr.get_quality_profiles(s.sonarr_url, s.sonarr_api_key)


@router.get("/sonarr/folders")
async def sonarr_folders(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    return await sonarr.get_root_folders(s.sonarr_url, s.sonarr_api_key)


@router.get("/radarr/profiles")
async def radarr_profiles(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    return await radarr.get_quality_profiles(s.radarr_url, s.radarr_api_key)


@router.get("/radarr/folders")
async def radarr_folders(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    return await radarr.get_root_folders(s.radarr_url, s.radarr_api_key)


# ---------------------------------------------------------------------------
# Utilisateurs Plex
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    plex_user_id: str
    display_name: Optional[str] = None
    custom_name: Optional[str] = None
    plex_email: Optional[str] = None
    notification_email: Optional[str] = None
    enabled: bool = True
    notify_admin: bool = True
    notify_on_request: Optional[bool] = True
    notify_on_available: Optional[bool] = True
    notify_digest: Optional[bool] = False
    discord_webhook_url: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    seer_active: Optional[bool] = None


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    return db.query(PlexUser).all()


@router.post("/users")
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(PlexUser).filter(PlexUser.plex_user_id == data.plex_user_id).first()
    if existing:
        raise HTTPException(409, "User already exists")
    user = PlexUser(**data.model_dump())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/users/{user_id}")
def update_user(user_id: int, data: UserCreate, db: Session = Depends(get_db)):
    user = get_or_404(db, PlexUser, user_id, "User not found")
    for k, v in data.model_dump().items():
        setattr(user, k, v)
    # Propager le nouveau display_name sur les demandes existantes
    resolved = data.display_name or user.plex_user_id
    db.query(MediaRequest).filter(MediaRequest.plex_user_id == user.plex_user_id).update({"plex_user": resolved})
    db.commit()
    return user


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = get_or_404(db, PlexUser, user_id, "User not found")
    db.delete(user)
    db.commit()
    return {"status": "deleted"}


@router.post("/seer/sync/users")
async def seer_sync_users():
    """Synchronise uniquement les liaisons utilisateurs Plex ↔ Seer."""
    from ..scheduler import sync_seer_users

    await sync_seer_users()
    return {"status": "ok"}


@router.post("/seer/sync/requests")
async def seer_sync_requests():
    """Synchronise uniquement les demandes Seer (titres, statuts, historique)."""
    from ..scheduler import sync_seer_requests

    await sync_seer_requests()
    return {"status": "ok"}


@router.post("/seer/sync")
async def seer_sync():
    """Déclenche manuellement la synchronisation Seer complète : utilisateurs + demandes."""
    from ..scheduler import sync_seer_requests, sync_seer_users

    await sync_seer_users()
    await sync_seer_requests()
    return {"status": "ok"}


@router.get("/seer/users")
async def list_seer_users(db: Session = Depends(get_db)):
    """Retourne la liste des utilisateurs Seer avec leur statut de liaison."""
    from ..services.seer import get_users as seer_get_users

    s = db.query(Settings).first()
    if not s or not s.seer_enabled or not s.seer_url or not s.seer_api_key:
        return {"seer_users": [], "error": "Seer non configuré"}

    seer_users = await seer_get_users(s.seer_url, s.seer_api_key)
    linked_ids = {u.seer_user_id for u in db.query(PlexUser).filter(PlexUser.seer_user_id.isnot(None)).all()}

    result = []
    for email, info in seer_users.items():
        result.append(
            {
                "id": info["id"],
                "email": email,
                "display_name": info["display_name"],
                "plex_username": info.get("plex_username", ""),
                "plex_id": info.get("plex_id"),
                "user_type": info.get("user_type", 1),
                "request_count": info["request_count"],
                "linked": info["id"] in linked_ids,
            }
        )
    result.sort(key=lambda x: (x["display_name"] or x["email"]).lower())
    return {"seer_users": result}


@router.put("/users/{user_id}/seer-link")
def link_seer_user(user_id: int, data: dict, db: Session = Depends(get_db)):
    """Lie manuellement un PlexUser à un compte Seer."""
    user = get_or_404(db, PlexUser, user_id, "User not found")
    seer_id = data.get("seer_user_id")
    seer_email = data.get("seer_email")
    if seer_id is None:
        raise HTTPException(400, "seer_user_id requis")
    user.seer_user_id = int(seer_id)
    if seer_email and not user.plex_email:
        user.plex_email = seer_email
    # Liaison Seer = désactiver les emails par défaut (Seer gère ses propres notifs)
    user.notify_on_request = False
    user.notify_on_available = False
    db.commit()
    return {"status": "linked", "seer_user_id": user.seer_user_id}


@router.delete("/users/{user_id}/seer-link")
def unlink_seer_user(user_id: int, db: Session = Depends(get_db)):
    """Supprime la liaison Seer d'un PlexUser."""
    user = get_or_404(db, PlexUser, user_id, "User not found")
    user.seer_user_id = None
    user.seer_active = None
    db.commit()
    return {"status": "unlinked"}


@router.post("/users/{user_id}/seer-automatch")
async def seer_automatch_user(user_id: int, db: Session = Depends(get_db)):
    """Lance l'automatch Seer (3 passes) pour un seul utilisateur."""
    from ..models import MediaRequest as MR
    from ..services.seer import get_user_requests as seer_get_user_requests
    from ..services.seer import get_users as seer_get_users

    user = get_or_404(db, PlexUser, user_id, "User not found")
    s = db.query(Settings).first()
    if not s or not s.seer_url or not s.seer_api_key:
        raise HTTPException(400, "Seer non configuré")

    seer_users = await seer_get_users(s.seer_url, s.seer_api_key)
    if not seer_users:
        return {"matched": False, "method": None}

    matched_ids = {
        u.seer_user_id
        for u in db.query(PlexUser).filter(PlexUser.id != user_id, PlexUser.seer_user_id.isnot(None)).all()
    }
    by_plex_username = {
        (info.get("plex_username") or "").lower().strip(): info
        for info in seer_users.values()
        if info.get("plex_username")
    }

    info = None
    method = None

    email = (user.plex_email or "").lower().strip()
    if email and email in seer_users:
        cand = seer_users[email]
        if cand["id"] not in matched_ids:
            info, method = cand, "email"

    if not info:
        name = (user.display_name or "").lower().strip()
        if name and name in by_plex_username:
            cand = by_plex_username[name]
            if cand["id"] not in matched_ids:
                info, method = cand, "plex_username"

    if not info:
        rows = db.query(MR.tmdb_id).filter(MR.plex_user_id == user.plex_user_id, MR.tmdb_id.isnot(None)).all()
        user_tmdb_ids = {r[0] for r in rows}
        if len(user_tmdb_ids) >= 2:
            best_count = 0
            for seer_info in seer_users.values():
                if seer_info["id"] in matched_ids:
                    continue
                reqs = await seer_get_user_requests(s.seer_url, s.seer_api_key, seer_info["id"])
                common = len(user_tmdb_ids & {r["tmdb_id"] for r in reqs if r.get("tmdb_id")})
                if common >= 2 and common > best_count:
                    best_count, info = common, seer_info
                    method = f"media/{common}"

    if info:
        user.seer_user_id = info["id"]
        user.seer_active = info["request_count"] > 0
        db.commit()
        return {"matched": True, "method": method, "seer_user_id": info["id"], "display_name": info["display_name"]}

    return {"matched": False, "method": None}


@router.post("/users/{seer_only_id}/merge-into/{target_id}")
def merge_seer_only_into_rss(seer_only_id: int, target_id: int, db: Session = Depends(get_db)):
    """Fusionne un utilisateur Seer-only vers un utilisateur RSS existant.

    - Copie seer_user_id + seer_active sur le user cible
    - Réattribue les MediaRequest du user seer-only vers le user cible
    - Supprime l'entrée seer-only
    """
    seer_user = get_or_404(db, PlexUser, seer_only_id, "Utilisateur Seer-only introuvable")
    if seer_user.source != "seer":
        raise HTTPException(400, "Cet utilisateur n'est pas un utilisateur Seer-only")

    target = get_or_404(db, PlexUser, target_id, "Utilisateur cible introuvable")
    if target.source == "seer":
        raise HTTPException(400, "La cible ne peut pas être un utilisateur Seer-only")

    # Transférer la liaison Seer
    target.seer_user_id = seer_user.seer_user_id
    target.seer_active = seer_user.seer_active

    # Réattribuer les demandes
    old_pid = seer_user.plex_user_id
    new_pid = target.plex_user_id
    new_name = target.custom_name or target.display_name or new_pid
    requests_moved = (
        db.query(MediaRequest)
        .filter(MediaRequest.plex_user_id == old_pid)
        .update({"plex_user_id": new_pid, "plex_user": new_name})
    )

    db.delete(seer_user)
    db.commit()

    return {
        "status": "merged",
        "requests_moved": requests_moved,
        "target_plex_user_id": new_pid,
        "seer_user_id": target.seer_user_id,
    }


@router.put("/users/{user_id}/custom-name")
def update_custom_name(user_id: int, data: dict, db: Session = Depends(get_db)):
    """Met à jour le nom d'usage personnalisé d'un utilisateur."""
    user = get_or_404(db, PlexUser, user_id, "User not found")
    user.custom_name = data.get("custom_name") or None
    db.commit()
    return {"status": "ok", "custom_name": user.custom_name}


@router.post("/users/{user_id}/seer-complete")
async def seer_complete_user(user_id: int, db: Session = Depends(get_db)):
    """Complète les infos d'un PlexUser depuis son compte Seer lié.

    Copie : display_name Seer → custom_name (si vide), email Seer → plex_email (si vide).
    """
    user = get_or_404(db, PlexUser, user_id, "User not found")
    if not user.seer_user_id:
        raise HTTPException(400, "Utilisateur non lié à Seer")
    s = db.query(Settings).first()
    if not s or not s.seer_url or not s.seer_api_key:
        raise HTTPException(400, "Seer non configuré")

    from ..services.seer import get_users as seer_get_users

    seer_users = await seer_get_users(s.seer_url, s.seer_api_key)
    seer_email = None
    seer_info = None
    for email, info in seer_users.items():
        if info["id"] == user.seer_user_id:
            seer_email = email
            seer_info = info
            break

    if not seer_info:
        raise HTTPException(404, "Compte Seer introuvable (id inconnu)")

    changes: dict = {}
    if seer_info.get("display_name") and not user.custom_name:
        user.custom_name = seer_info["display_name"]
        changes["custom_name"] = user.custom_name
    if seer_email:
        if not user.plex_email:
            user.plex_email = seer_email
            changes["plex_email"] = user.plex_email
        if not user.notification_email:
            user.notification_email = seer_email
            changes["notification_email"] = user.notification_email
    db.commit()
    return {"status": "ok", "changes": changes}


@router.post("/users/discover")
async def discover_users(db: Session = Depends(get_db)):
    """Scanne le flux RSS, auto-crée les nouveaux utilisateurs et retourne un résumé."""
    from ..scheduler import sync_users_from_feed
    from ..services.plex_rss import fetch_watchlist_rss

    s = db.query(Settings).first()
    if not s or not s.plex_rss_url:
        raise HTTPException(400, "URL RSS non configurée")

    known_before = {u.plex_user_id for u in db.query(PlexUser).all()}
    items = await fetch_watchlist_rss(s.plex_rss_url)
    await sync_users_from_feed(items, db)

    all_users = db.query(PlexUser).all()
    new_ids = {u.plex_user_id for u in all_users} - known_before

    return {
        "total": len(all_users),
        "added": len(new_ids),
        "users": [
            {"plex_user_id": u.plex_user_id, "display_name": u.display_name, "enabled": u.enabled} for u in all_users
        ],
    }


# ---------------------------------------------------------------------------
# Santé des services
# ---------------------------------------------------------------------------


@router.get("/onboarding")
def onboarding_status(db: Session = Depends(get_db)):
    """Retourne l'état d'avancement de la configuration initiale (checklist)."""
    s = db.query(Settings).first()
    users_count = db.query(PlexUser).count()
    steps = [
        {"id": "rss", "label": "Flux RSS Plex configuré", "done": bool(s and s.plex_rss_url)},
        {"id": "sonarr", "label": "Sonarr configuré", "done": bool(s and s.sonarr_url and s.sonarr_api_key)},
        {"id": "radarr", "label": "Radarr configuré", "done": bool(s and s.radarr_url and s.radarr_api_key)},
        {"id": "smtp", "label": "Email (SMTP) configuré", "done": bool(s and s.smtp_host)},
        {"id": "users", "label": "Au moins un utilisateur détecté", "done": users_count > 0},
        {
            "id": "webhooks",
            "label": "Webhooks Sonarr/Radarr configurés",
            "done": bool(s and s.sonarr_url),
            "optional": True,
        },
    ]
    return {"steps": steps, "complete": all(s["done"] for s in steps if not s.get("optional"))}


async def _timed_check(coro) -> tuple[bool | None, str, float | None]:
    """Exécute une coroutine de connectivité et retourne (ok, message, latence_ms)."""
    t0 = time.monotonic()
    ok, msg = await coro
    return ok, msg, round((time.monotonic() - t0) * 1000, 1)


@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """État structuré de tous les services connectés avec latences."""
    s = db.query(Settings).first()
    services: dict[str, dict] = {}
    failed = 0
    degraded = 0

    # Sonarr
    if s and s.sonarr_url and s.sonarr_api_key:
        ok, msg, ms = await _timed_check(sonarr.check_connection(s.sonarr_url, s.sonarr_api_key))
        services["sonarr"] = {"ok": ok, "message": msg, "response_ms": ms}
        if not ok:
            failed += 1
    else:
        services["sonarr"] = {"ok": None, "message": "Non configuré", "response_ms": None}

    # Radarr
    if s and s.radarr_url and s.radarr_api_key:
        ok, msg, ms = await _timed_check(radarr.check_connection(s.radarr_url, s.radarr_api_key))
        services["radarr"] = {"ok": ok, "message": msg, "response_ms": ms}
        if not ok:
            failed += 1
    else:
        services["radarr"] = {"ok": None, "message": "Non configuré", "response_ms": None}

    # Seer
    if s and s.seer_enabled and s.seer_url and s.seer_api_key:
        ok, msg, ms = await _timed_check(seer_test(s.seer_url, s.seer_api_key))
        services["seer"] = {"ok": ok, "message": msg, "response_ms": ms}
        if not ok:
            degraded += 1
    else:
        services["seer"] = {"ok": None, "message": "Non configuré", "response_ms": None}

    # Plex API
    if s and s.plex_url and s.plex_token:
        ok, msg, ms = await _timed_check(plex_test(s.plex_url, s.plex_token))
        services["plex"] = {"ok": ok, "message": msg, "response_ms": ms}
        if not ok:
            failed += 1
    else:
        services["plex"] = {"ok": None, "message": "Non configuré", "response_ms": None}

    # SMTP & RSS — pas de test réseau, on vérifie juste la configuration
    services["smtp"] = {
        "ok": bool(s and s.smtp_host),
        "message": "Configuré" if s and s.smtp_host else "Non configuré",
        "response_ms": None,
    }
    services["rss"] = {
        "ok": bool(s and s.plex_rss_url),
        "message": "Configuré" if s and s.plex_rss_url else "Non configuré",
        "response_ms": None,
    }

    if failed > 0:
        overall = "down"
    elif degraded > 0:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "services": services,
    }


# ---------------------------------------------------------------------------
# Statistiques
# ---------------------------------------------------------------------------


@router.get("/stats/timeline")
def stats_timeline(db: Session = Depends(get_db)):
    """Retourne le nombre de demandes par jour sur les 30 derniers jours."""
    from sqlalchemy import func

    days = 30
    start = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(
            func.date(MediaRequest.requested_at).label("day"),
            func.count().label("count"),
        )
        .filter(MediaRequest.requested_at >= start)
        .group_by(func.date(MediaRequest.requested_at))
        .all()
    )
    data = {r.day: r.count for r in rows}
    labels, values = [], []
    for i in range(days):
        d = (start + timedelta(days=i + 1)).strftime("%Y-%m-%d")
        labels.append(d)
        values.append(data.get(d, 0))
    return {"labels": labels, "values": values}


@router.get("/stats/by-user")
def stats_by_user(db: Session = Depends(get_db)):
    """Retourne le nombre de demandes par utilisateur, trié par volume décroissant."""
    from sqlalchemy import func

    rows = (
        db.query(MediaRequest.plex_user_id, func.count().label("total"))
        .group_by(MediaRequest.plex_user_id)
        .order_by(func.count().desc())
        .all()
    )
    users = {u.plex_user_id: (u.display_name or u.plex_user_id) for u in db.query(PlexUser).all()}
    return [
        {"plex_user_id": r.plex_user_id, "display_name": users.get(r.plex_user_id, r.plex_user_id), "total": r.total}
        for r in rows
    ]


@router.get("/stats/counts")
def stats_counts(db: Session = Depends(get_db)):
    """Retourne les compteurs par statut (utilisé pour le badge de navigation)."""
    from sqlalchemy import func

    rows = db.query(MediaRequest.status, func.count().label("n")).group_by(MediaRequest.status).all()
    counts = {r.status: r.n for r in rows}
    return {
        "failed": counts.get("failed", 0),
        "pending": counts.get("pending", 0),
        "sent_to_arr": counts.get("sent_to_arr", 0),
        "available": counts.get("available", 0),
        "total": sum(counts.values()),
    }


@router.get("/metrics")
def get_metrics(db: Session = Depends(get_db)):
    """Métriques runtime (session courante) + agrégats DB (total historique).

    Les compteurs runtime se réinitialisent au redémarrage du serveur.
    Les agrégats DB reflètent l'ensemble de l'historique.
    """
    from sqlalchemy import func

    # Agrégats DB
    total = db.query(MediaRequest).count()
    available = db.query(MediaRequest).filter(MediaRequest.status == "available").count()
    failed = db.query(MediaRequest).filter(MediaRequest.status == "failed").count()
    notif_sent = db.query(MediaRequest).filter(MediaRequest.available_mail_sent.is_(True)).count()
    notif_missed = (
        db.query(MediaRequest)
        .filter(
            MediaRequest.status == "available",
            MediaRequest.available_mail_sent.is_(False),
        )
        .count()
    )
    notif_total = notif_sent + notif_missed
    notif_failure_pct_db = round(notif_missed / notif_total * 100, 1) if notif_total else None

    return {
        "runtime": app_metrics.snapshot(),
        "db": {
            "total_requests": total,
            "available": available,
            "failed": failed,
            "success_rate_pct": round(available / total * 100, 1) if total else None,
            "notifications": {
                "sent": notif_sent,
                "missed": notif_missed,
                "failure_rate_pct": notif_failure_pct_db,
            },
        },
    }


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


@router.get("/next-poll")
def next_poll_info():
    """Retourne le nombre de secondes avant le prochain polling (pour le countdown UI)."""

    from ..scheduler import scheduler

    job = scheduler.get_job("watchlist_poll")
    if not job or not job.next_run_time:
        return {"next_run_seconds": None, "next_run_iso": None}
    now = datetime.now(timezone.utc)
    delta = (job.next_run_time - now).total_seconds()
    return {
        "next_run_seconds": max(0, int(delta)),
        "next_run_iso": job.next_run_time.isoformat(),
    }


# ---------------------------------------------------------------------------
# Demandes (MediaRequest)
# ---------------------------------------------------------------------------


@router.get("/requests")
def list_requests(db: Session = Depends(get_db)):
    return db.query(MediaRequest).order_by(MediaRequest.requested_at.desc()).limit(200).all()


@router.get("/requests/{request_id}")
def get_request(request_id: int, db: Session = Depends(get_db)):
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    d = {c.name: getattr(req, c.name) for c in req.__table__.columns}
    d["requested_at"] = _format_datetime(req.requested_at)
    d["available_at"] = _format_datetime(req.available_at)

    settings = db.query(Settings).first()
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    raw = (user_obj.notification_email if user_obj else None) or (settings.smtp_from if settings else "") or ""
    user_emails = parse_email_list(raw)
    notify_admin = bool(user_obj and getattr(user_obj, "notify_admin", True))
    admin_emails = parse_email_list(settings.admin_notification_email if settings and notify_admin else None)
    d["_user_emails"] = user_emails
    d["_admin_emails"] = admin_emails
    d["_notify_admin"] = notify_admin
    return d


@router.get("/email/preview")
def preview_email_template(event: str = "request", user_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Rend le template email avec des données fictives et retourne le HTML."""
    settings = db.query(Settings).first()

    plex_user_name = "Jean Dupont"
    recipient_email = "jean.dupont@plex.local"
    if user_id:
        user = db.query(PlexUser).filter(PlexUser.id == user_id).first()
        if user:
            plex_user_name = user.custom_name or user.display_name or user.plex_user_id
            recipient_email = user.notification_email or user.plex_email or "utilisateur@plex.local"

    fake = MediaRequest(
        title="Dune : Deuxième Partie",
        year=2024,
        media_type="movie",
        plex_user=plex_user_name,
        overview="Paul Atréides s'unit aux Fremen pour mener la guerre sainte contre ceux qui ont détruit sa famille.",
        poster_url="https://image.tmdb.org/t/p/w300/1pdfLvkbY9ohJlCjQH2CZjjYVvJ.jpg",
    )
    ctx = {
        "title": fake.title,
        "year": fake.year,
        "poster_url": fake.poster_url,
        "plex_user": fake.plex_user,
        "media_type": fake.media_type,
        "media_type_label": "Film",
        "media_type_label_cap": "Le film",
        "overview": fake.overview,
        "genres": "Science-Fiction, Aventure",
    }

    if event == "available":
        tpl = (
            settings.email_available_template
            if (settings and isinstance(settings.email_available_template, str))
            else None
        ) or DEFAULT_AVAILABLE_TEMPLATE
        subject_tmpl = (
            settings.email_available_subject
            if (settings and isinstance(settings.email_available_subject, str))
            else None
        ) or "[Plex] Disponible : {{ title }}"
    else:
        tpl = (
            settings.email_request_template if (settings and isinstance(settings.email_request_template, str)) else None
        ) or DEFAULT_REQUEST_TEMPLATE
        subject_tmpl = (
            settings.email_request_subject if (settings and isinstance(settings.email_request_subject, str)) else None
        ) or "[Plex] Nouvelle demande : {{ title }}"

    rendered_subject = render_template(subject_tmpl, ctx)
    if rendered_subject.startswith("<p>Erreur de template"):
        rendered_subject = (
            f"[Plex] Nouvelle demande : {fake.title}" if event == "request" else f"[Plex] Disponible : {fake.title}"
        )

    html = render_template(tpl, ctx)

    # Prepend email client headers
    header_html = f"""
    <div style="background:#2a2a2a; color:#fff; font-family:sans-serif; padding:12px 20px; border-bottom:1px solid #333; margin-bottom:15px; font-size:13px;">
      <div style="margin-bottom:4px;"><strong>Objet :</strong> <span style="color:#e5a00d; font-weight:bold;">{rendered_subject}</span></div>
      <div style="margin-bottom:4px;"><strong>De :</strong> {(settings.smtp_from if settings else None) or "plex-rss@monitor.local"}</div>
      <div><strong>À :</strong> {recipient_email}</div>
    </div>
    """

    if "<body>" in html:
        html = html.replace("<body>", f"<body>{header_html}")
    elif "<body style=" in html:
        parts = html.split("<body", 1)
        if len(parts) == 2:
            body_tag, rest = parts[1].split(">", 1)
            html = f"{parts[0]}<body{body_tag}>{header_html}{rest}"
    else:
        html = header_html + html

    return HTMLResponse(content=html)


@router.get("/notifications/log")
def list_notification_logs(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    q = db.query(NotificationLog).order_by(NotificationLog.sent_at.desc())
    total = q.count()
    logs = q.offset(offset).limit(min(limit, 200)).all()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": log.id,
                "sent_at": _format_datetime(log.sent_at),
                "event": log.event,
                "recipient": log.recipient,
                "is_admin": log.is_admin,
                "media_title": log.media_title,
                "media_type": log.media_type,
                "success": log.success,
                "error_msg": log.error_msg,
                "req_id": log.req_id,
            }
            for log in logs
        ],
    }


@router.post("/notifications/{log_id}/resend")
async def resend_notification(log_id: int, db: Session = Depends(get_db)):
    log = db.query(NotificationLog).filter(NotificationLog.id == log_id).first()
    if not log:
        raise HTTPException(404, "Log introuvable")
    if not log.req_id:
        raise HTTPException(400, "req_id manquant sur cette entrée de log (envoi antérieur à la v2.1)")
    req = get_or_404(db, MediaRequest, log.req_id, "Demande originale introuvable")
    enqueue_notification(log.event, req.id, [log.recipient])
    return {"status": "queued", "recipient": log.recipient, "event": log.event}


@router.post("/users/{user_id}/test-email")
async def send_test_email(user_id: int, db: Session = Depends(get_db)):
    user = get_or_404(db, PlexUser, user_id, "User not found")
    settings = db.query(Settings).first()
    if not settings:
        raise HTTPException(500, "Settings manquants")
    recipient = user.notification_email or user.plex_email
    if not recipient:
        raise HTTPException(400, "Aucune adresse email configurée pour cet utilisateur")
    name = user.custom_name or user.display_name or user.plex_user_id
    html = f"""<!DOCTYPE html>
<html><body style="background:#141414;font-family:Arial,sans-serif;padding:32px">
<div style="max-width:480px;margin:auto;background:#1f1f1f;border-radius:10px;padding:28px;color:#fff">
  <h2 style="color:#e5a00d;margin:0 0 16px">Test de notification</h2>
  <p style="color:#ccc">Bonjour <strong>{name}</strong>,</p>
  <p style="color:#ccc">Cet email confirme que les notifications fonctionnent correctement pour ton compte Plex RSS Monitor.</p>
  <p style="color:#888;font-size:12px;margin-top:24px">Plex RSS Monitor — email de test</p>
</div>
</body></html>"""
    try:
        await smtp_send(settings, recipient, "[Plex RSS] Test de notification", html)
    except Exception as e:
        raise HTTPException(500, f"Échec SMTP : {e}")
    return {"status": "sent", "recipient": recipient}


class BulkAction(BaseModel):
    ids: list[int]


@router.post("/requests/bulk/retry")
async def bulk_retry_requests(body: BulkAction, db: Session = Depends(get_db)):
    """Repasse plusieurs demandes en pending et lance un polling."""
    reqs = db.query(MediaRequest).filter(MediaRequest.id.in_(body.ids)).all()
    count = 0
    for req in reqs:
        if req.status in ("failed", "pending"):
            req.status = "pending"
            count += 1
    if count > 0:
        db.commit()
        await poll_watchlists()
    return {"status": "success", "count": count}


@router.post("/requests/bulk/mark-processed")
def bulk_mark_requests_processed(body: BulkAction, db: Session = Depends(get_db)):
    """Marque plusieurs demandes comme traitées (disponibles) sans email."""
    reqs = db.query(MediaRequest).filter(MediaRequest.id.in_(body.ids)).all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for req in reqs:
        req.status = "available"
        req.request_mail_sent = True
        req.available_mail_sent = True
        if not req.available_at:
            req.available_at = now
    db.commit()
    return {"status": "success", "count": len(reqs)}


@router.post("/requests/bulk/delete")
def bulk_delete_requests(body: BulkAction, db: Session = Depends(get_db)):
    """Supprime plusieurs demandes définitivement."""
    reqs = db.query(MediaRequest).filter(MediaRequest.id.in_(body.ids)).all()
    count = len(reqs)
    for req in reqs:
        db.delete(req)
    db.commit()
    return {"status": "success", "count": count}


@router.post("/requests/{request_id}/retry")
async def retry_request(request_id: int, db: Session = Depends(get_db)):
    """Repasse une demande en `pending` et déclenche un polling immédiat."""
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    if req.status not in ("failed", "pending"):
        raise HTTPException(400, "Only failed or pending requests can be retried")
    req.status = "pending"
    db.commit()
    await poll_watchlists()
    return {"status": "retrying"}


@router.post("/requests/retry-failed")
async def retry_all_failed(db: Session = Depends(get_db)):
    """Repasse toutes les demandes 'failed' en 'pending' et déclenche un polling."""
    failed = db.query(MediaRequest).filter(MediaRequest.status == "failed").all()
    count = len(failed)
    for req in failed:
        req.status = "pending"
    db.commit()
    await poll_watchlists()
    return {"status": "ok", "retried": count}


@router.post("/requests/recalculate-dates")
async def recalculate_dates():
    """Re-joue sync_seer_requests pour corriger requested_at et available_at depuis Seer."""
    from ..scheduler import sync_seer_requests

    await sync_seer_requests()
    return {"status": "ok"}


@router.post("/requests/merge-duplicates")
def merge_duplicates_endpoint():
    """Fusionne les MediaRequest en double (même tmdb_id toutes sources)."""
    from scripts.merge_duplicate_requests import merge_duplicates

    merge_duplicates(dry_run=False)
    return {"status": "ok"}


@router.post("/requests/poll")
async def trigger_poll():
    """Déclenche manuellement le polling des watchlists ET la vérification des statuts *arr."""
    await poll_watchlists()
    await check_arr_statuses()
    return {"status": "poll triggered"}


@router.delete("/requests/{request_id}")
def delete_request(request_id: int, db: Session = Depends(get_db)):
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    db.delete(req)
    db.commit()
    return {"status": "deleted"}


@router.post("/requests/{request_id}/mark-processed")
def mark_request_processed(request_id: int, db: Session = Depends(get_db)):
    """Marque une demande comme traitée / disponible sans envoyer d'emails."""
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    req.status = "available"
    req.request_mail_sent = True
    req.available_mail_sent = True
    if not req.available_at:
        req.available_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return {"status": "success", "message": "Demande marquée comme traitée"}


# ---------------------------------------------------------------------------
# Activité et notifications
# ---------------------------------------------------------------------------


@router.get("/activity")
def activity_log(db: Session = Depends(get_db)):
    """Retourne les 25 événements les plus récents (7 derniers jours) pour le journal."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    reqs = (
        db.query(MediaRequest)
        .filter(MediaRequest.requested_at >= cutoff)
        .order_by(MediaRequest.requested_at.desc())
        .limit(50)
        .all()
    )
    events = []
    for r in reqs:
        if r.requested_at:
            events.append(
                {
                    "type": r.status if r.status in ("failed",) else "request",
                    "title": r.title,
                    "user": r.plex_user or r.plex_user_id or "?",
                    "media_type": r.media_type,
                    "time": _format_datetime(r.requested_at),
                }
            )
        if r.available_at and r.available_at >= cutoff:
            events.append(
                {
                    "type": "available",
                    "title": r.title,
                    "user": r.plex_user or r.plex_user_id or "?",
                    "media_type": r.media_type,
                    "time": _format_datetime(r.available_at),
                }
            )
    events.sort(key=lambda e: e["time"], reverse=True)
    return events[:25]


@router.get("/notifications/recent-available")
def recent_available(since: str = None, db: Session = Depends(get_db)):
    """Retourne les médias devenus disponibles depuis `since` (ISO 8601).

    Utilisé par le dashboard pour afficher des toasts de disponibilité
    lors de la visite de la page.
    """
    from datetime import datetime, timezone

    q = db.query(MediaRequest).filter(MediaRequest.status == "available")
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            q = q.filter(MediaRequest.available_at >= since_dt)
        except ValueError:
            pass
    items = q.order_by(MediaRequest.available_at.desc()).limit(10).all()
    return [{"id": r.id, "title": r.title, "available_at": _format_datetime(r.available_at)} for r in items]


# ---------------------------------------------------------------------------
# Logs applicatifs
# ---------------------------------------------------------------------------


@router.get("/logs")
def get_logs(_: None = Depends(require_auth)):
    """Retourne les derniers logs applicatifs (buffer mémoire circulaire)."""
    from ..log_buffer import get_logs as _get_logs

    return _get_logs()


# ---------------------------------------------------------------------------
# API token
# ---------------------------------------------------------------------------


@router.post("/settings/token")
def generate_api_token(db: Session = Depends(get_db)):
    """Génère un nouveau token d'API et le stocke dans les paramètres."""
    import secrets

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


# ---------------------------------------------------------------------------
# Métriques Prometheus
# ---------------------------------------------------------------------------


@router.get("/metrics/prometheus", response_class=__import__("fastapi").responses.PlainTextResponse)
def prometheus_metrics(db: Session = Depends(get_db)):
    """Expose les métriques au format Prometheus text (scraping externe)."""
    from fastapi.responses import PlainTextResponse
    from sqlalchemy import func

    snap = app_metrics.snapshot()

    total = db.query(MediaRequest).count()
    available = db.query(MediaRequest).filter(MediaRequest.status == "available").count()
    failed_db = db.query(MediaRequest).filter(MediaRequest.status == "failed").count()
    pending = db.query(MediaRequest).filter(MediaRequest.status == "pending").count()
    sent = db.query(MediaRequest).filter(MediaRequest.status == "sent_to_arr").count()

    lines = [
        "# HELP plex_rss_poll_total Total number of watchlist polls since startup",
        "# TYPE plex_rss_poll_total counter",
        f"plex_rss_poll_total {snap['poll']['count']}",
        "# HELP plex_rss_poll_errors_total Total number of failed polls since startup",
        "# TYPE plex_rss_poll_errors_total counter",
        f"plex_rss_poll_errors_total {snap['poll']['errors']}",
        "# HELP plex_rss_arr_submissions_total Total submissions to Sonarr/Radarr/Seer since startup",
        "# TYPE plex_rss_arr_submissions_total counter",
        f"plex_rss_arr_submissions_total {snap['arr']['submissions']}",
        "# HELP plex_rss_arr_errors_total Total failed submissions since startup",
        "# TYPE plex_rss_arr_errors_total counter",
        f"plex_rss_arr_errors_total {snap['arr']['errors']}",
        "# HELP plex_rss_notifications_sent_total Total notifications sent since startup",
        "# TYPE plex_rss_notifications_sent_total counter",
        f"plex_rss_notifications_sent_total {snap['notifications']['sent']}",
        "# HELP plex_rss_notifications_failed_total Total failed notifications since startup",
        "# TYPE plex_rss_notifications_failed_total counter",
        f"plex_rss_notifications_failed_total {snap['notifications']['failed']}",
        "# HELP plex_rss_sonarr_response_ms Average Sonarr response time (ms, last 50 calls)",
        "# TYPE plex_rss_sonarr_response_ms gauge",
        f"plex_rss_sonarr_response_ms {snap['arr']['sonarr_avg_response_ms'] or 0}",
        "# HELP plex_rss_radarr_response_ms Average Radarr response time (ms, last 50 calls)",
        "# TYPE plex_rss_radarr_response_ms gauge",
        f"plex_rss_radarr_response_ms {snap['arr']['radarr_avg_response_ms'] or 0}",
        "# HELP plex_rss_requests_total Total media requests in database",
        "# TYPE plex_rss_requests_total gauge",
        f"plex_rss_requests_total {total}",
        "# HELP plex_rss_requests_by_status Media requests grouped by status",
        "# TYPE plex_rss_requests_by_status gauge",
        f'plex_rss_requests_by_status{{status="available"}} {available}',
        f'plex_rss_requests_by_status{{status="failed"}} {failed_db}',
        f'plex_rss_requests_by_status{{status="pending"}} {pending}',
        f'plex_rss_requests_by_status{{status="sent_to_arr"}} {sent}',
    ]

    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


# ---------------------------------------------------------------------------
# Conflits de déduplication
# ---------------------------------------------------------------------------

_IGNORED_FILE = "data/ignored_conflicts.json"


def _load_ignored() -> set[str]:
    try:
        with open(_IGNORED_FILE) as f:
            return set(_json.load(f))
    except Exception:
        return set()


def _save_ignored(keys: set[str]):
    _os.makedirs("data", exist_ok=True)
    with open(_IGNORED_FILE, "w") as f:
        _json.dump(sorted(keys), f)


def _req_dict(r: MediaRequest) -> dict:
    return {
        "id": r.id,
        "title": r.title,
        "tmdb_id": r.tmdb_id,
        "tvdb_id": r.tvdb_id,
        "source": r.source,
        "status": r.status,
        "plex_user": r.plex_user,
        "plex_user_id": r.plex_user_id,
        "arr_id": r.arr_id,
        "poster_url": r.poster_url,
        "requested_at": _format_datetime(r.requested_at),
        "available_at": _format_datetime(r.available_at),
    }


def _merge_entries(keeper: MediaRequest, dup: MediaRequest, db):
    """Fusionne dup dans keeper : co-demandeurs + champs manquants."""
    extras: list[dict] = _json.loads(keeper.extra_requesters or "[]")
    existing_ids = {keeper.plex_user_id} | {e["plex_user_id"] for e in extras}
    for e in _json.loads(dup.extra_requesters or "[]"):
        if e["plex_user_id"] not in existing_ids:
            extras.append(e)
            existing_ids.add(e["plex_user_id"])
    if dup.plex_user_id not in existing_ids:
        extras.append({"plex_user_id": dup.plex_user_id, "display_name": dup.plex_user or dup.plex_user_id})
    # Seer tmdb_id fait référence
    if dup.source == "seer" and dup.tmdb_id:
        keeper.tmdb_id = dup.tmdb_id
    elif not keeper.tmdb_id and dup.tmdb_id:
        keeper.tmdb_id = dup.tmdb_id
    if not keeper.tvdb_id and dup.tvdb_id:
        keeper.tvdb_id = dup.tvdb_id
    if not keeper.poster_url and dup.poster_url:
        keeper.poster_url = dup.poster_url
    keeper.extra_requesters = _json.dumps(extras, ensure_ascii=False)
    db.delete(dup)


@router.get("/conflicts")
def list_conflicts(db: Session = Depends(get_db), _: None = Depends(require_auth)):
    """Retourne tous les conflits détectés, filtrés des ignorés."""
    ignored = _load_ignored()
    all_reqs = db.query(MediaRequest).all()
    known_user_ids = {u.plex_user_id for u in db.query(PlexUser).all()}
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # ── 1. Conflit tmdb via tvdb (Plex ≠ Seer) ──────────────────────────────
    tvdb_groups: dict[tuple, list[MediaRequest]] = defaultdict(list)
    for r in all_reqs:
        if r.tvdb_id:
            tvdb_groups[(r.media_type, r.tvdb_id)].append(r)

    tmdb_conflicts = []
    for (media_type, tvdb_id), rows in tvdb_groups.items():
        tmdb_ids = {r.tmdb_id for r in rows if r.tmdb_id}
        if len(tmdb_ids) <= 1:
            continue
        key = f"tmdb:{media_type}:{tvdb_id}"
        if key in ignored:
            continue
        seer_entry = next((r for r in rows if r.source == "seer"), None)
        recommended_id = seer_entry.id if seer_entry else None
        tmdb_conflicts.append(
            {
                "type": "tmdb_conflict",
                "key": key,
                "media_type": media_type,
                "tvdb_id": tvdb_id,
                "recommended_id": recommended_id,
                "entries": [_req_dict(r) for r in sorted(rows, key=lambda x: (x.source != "seer", x.id))],
            }
        )

    # ── 2. Demandes orphelines (utilisateur supprimé) ────────────────────────
    orphaned = []
    for r in all_reqs:
        if r.plex_user_id not in known_user_ids:
            key = f"orphan:{r.id}"
            if key in ignored:
                continue
            orphaned.append({"key": key, **_req_dict(r)})

    # ── 3. Jamais transmis à Sonarr/Radarr depuis >30 jours ─────────────────
    long_pending = []
    for r in all_reqs:
        if r.status != "pending":
            continue
        if not r.requested_at:
            continue
        age = (now - r.requested_at).days
        if age < 30:
            continue
        key = f"pending:{r.id}"
        if key in ignored:
            continue
        long_pending.append({"key": key, "age_days": age, **_req_dict(r)})

    return {
        "tmdb_conflicts": tmdb_conflicts,
        "orphaned": orphaned,
        "long_pending": long_pending,
    }


@router.post("/conflicts/resolve")
def resolve_conflict(body: dict, db: Session = Depends(get_db), _: None = Depends(require_auth)):
    keep_id: int = body.get("keep_id")
    delete_ids: list[int] = body.get("delete_ids", [])
    if not keep_id or not delete_ids:
        raise HTTPException(400, "keep_id et delete_ids requis")
    keeper = db.get(MediaRequest, keep_id)
    if not keeper:
        raise HTTPException(404, f"Entrée {keep_id} introuvable")
    for del_id in delete_ids:
        dup = db.get(MediaRequest, del_id)
        if dup:
            _merge_entries(keeper, dup, db)
    db.commit()
    return {"ok": True, "kept": keep_id, "deleted": delete_ids}


@router.post("/conflicts/auto-resolve")
def auto_resolve_conflicts(db: Session = Depends(get_db), _: None = Depends(require_auth)):
    """Résout automatiquement tous les conflits tmdb : garde l'entrée Seer."""
    all_reqs = db.query(MediaRequest).all()
    tvdb_groups: dict[tuple, list[MediaRequest]] = defaultdict(list)
    for r in all_reqs:
        if r.tvdb_id:
            tvdb_groups[(r.media_type, r.tvdb_id)].append(r)

    resolved = 0
    for (media_type, tvdb_id), rows in tvdb_groups.items():
        tmdb_ids = {r.tmdb_id for r in rows if r.tmdb_id}
        if len(tmdb_ids) <= 1:
            continue
        seer = next((r for r in rows if r.source == "seer"), None)
        keeper = seer or min(rows, key=lambda x: x.id)
        for dup in rows:
            if dup.id != keeper.id:
                _merge_entries(keeper, dup, db)
        resolved += 1

    db.commit()
    return {"ok": True, "resolved": resolved}


@router.post("/conflicts/ignore")
def ignore_conflict(body: dict, _: None = Depends(require_auth)):
    """Marque un conflit comme ignoré (ne réapparaîtra plus)."""
    key: str = body.get("key")
    if not key:
        raise HTTPException(400, "key requis")
    ignored = _load_ignored()
    ignored.add(key)
    _save_ignored(ignored)
    return {"ok": True}


@router.delete("/conflicts/ignore/{key:path}")
def unignore_conflict(key: str, _: None = Depends(require_auth)):
    """Retire un conflit de la liste des ignorés."""
    ignored = _load_ignored()
    ignored.discard(key)
    _save_ignored(ignored)
    return {"ok": True}


@router.delete("/conflicts/no-tmdb/{request_id}")
def delete_no_tmdb(request_id: int, db: Session = Depends(get_db), _: None = Depends(require_auth)):
    req = db.get(MediaRequest, request_id)
    if not req:
        raise HTTPException(404, "Entrée introuvable")
    if req.tmdb_id:
        raise HTTPException(400, "Cette entrée a un tmdb_id — utilisez /conflicts/resolve")
    db.delete(req)
    db.commit()
    return {"ok": True}


@router.delete("/conflicts/orphan/{request_id}")
def delete_orphan(request_id: int, db: Session = Depends(get_db), _: None = Depends(require_auth)):
    req = db.get(MediaRequest, request_id)
    if not req:
        raise HTTPException(404, "Entrée introuvable")
    db.delete(req)
    db.commit()
    return {"ok": True}
