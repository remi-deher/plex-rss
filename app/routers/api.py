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

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from ..database import get_db
from ..models import Settings, PlexUser, MediaRequest
from ..services import sonarr, radarr, email_service
from ..services.plex_api import test_connection as plex_test
from ..services.plex_rss import test_rss
from ..scheduler import poll_watchlists, update_poll_interval, check_arr_statuses

def require_auth(request: Request):
    """Dépendance API : retourne 401 si la session n'est pas authentifiée."""
    if not request.session.get("authenticated"):
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
    for key, val in data.model_dump(exclude_none=True).items():
        # Ne pas écraser le vrai mot de passe par la valeur masquée affichée dans l'UI
        if key == "smtp_password" and val == "••••••••":
            continue
        setattr(s, key, val)
    db.commit()
    if data.poll_interval_minutes:
        update_poll_interval(data.poll_interval_minutes)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Authentification Plex SSO (OAuth)
# ---------------------------------------------------------------------------

@router.post("/plex/sso/pin")
async def plex_sso_pin():
    """Crée une demande de PIN Plex SSO et retourne l'URL d'authentification."""
    from ..services.plex_api import get_auth_pin
    try:
        return await get_auth_pin()
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
    ok, msg = await plex_test(s.plex_url or "", s.plex_token or "")
    return {"success": ok, "message": msg}


@router.post("/test/plex-rss")
async def test_plex_rss(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    ok, msg = await test_rss(s.plex_rss_url or "")
    return {"success": ok, "message": msg}


@router.post("/test/sonarr")
async def test_sonarr(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    ok, msg = await sonarr.test_connection(s.sonarr_url or "", s.sonarr_api_key or "")
    return {"success": ok, "message": msg}


@router.post("/test/radarr")
async def test_radarr(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    ok, msg = await radarr.test_connection(s.radarr_url or "", s.radarr_api_key or "")
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
    plex_email: Optional[str] = None
    notification_email: Optional[str] = None
    enabled: bool = True


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
    user = db.query(PlexUser).filter(PlexUser.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    for k, v in data.model_dump().items():
        setattr(user, k, v)
    # Propager le nouveau display_name sur les demandes existantes
    resolved = data.display_name or user.plex_user_id
    db.query(MediaRequest).filter(MediaRequest.plex_user_id == user.plex_user_id).update(
        {"plex_user": resolved}
    )
    db.commit()
    return user


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(PlexUser).filter(PlexUser.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    db.delete(user)
    db.commit()
    return {"status": "deleted"}


@router.post("/users/discover")
async def discover_users(db: Session = Depends(get_db)):
    """Scanne le flux RSS, auto-crée les nouveaux utilisateurs et retourne un résumé."""
    from ..services.plex_rss import fetch_watchlist_rss
    from ..scheduler import sync_users_from_feed
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
            {"plex_user_id": u.plex_user_id, "display_name": u.display_name, "enabled": u.enabled}
            for u in all_users
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
        {"id": "rss",      "label": "Flux RSS Plex configuré",              "done": bool(s and s.plex_rss_url)},
        {"id": "sonarr",   "label": "Sonarr configuré",                     "done": bool(s and s.sonarr_url and s.sonarr_api_key)},
        {"id": "radarr",   "label": "Radarr configuré",                     "done": bool(s and s.radarr_url and s.radarr_api_key)},
        {"id": "smtp",     "label": "Email (SMTP) configuré",               "done": bool(s and s.smtp_host)},
        {"id": "users",    "label": "Au moins un utilisateur détecté",      "done": users_count > 0},
        {"id": "webhooks", "label": "Webhooks Sonarr/Radarr configurés",    "done": bool(s and s.sonarr_url), "optional": True},
    ]
    return {"steps": steps, "complete": all(s["done"] for s in steps if not s.get("optional"))}


@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Vérifie la connectivité de tous les services (Sonarr, Radarr, SMTP, RSS)."""
    s = db.query(Settings).first()
    results = {}

    if s and s.sonarr_url and s.sonarr_api_key:
        ok, msg = await sonarr.test_connection(s.sonarr_url, s.sonarr_api_key)
        results["sonarr"] = {"ok": ok, "message": msg}
    else:
        results["sonarr"] = {"ok": None, "message": "Non configuré"}

    if s and s.radarr_url and s.radarr_api_key:
        ok, msg = await radarr.test_connection(s.radarr_url, s.radarr_api_key)
        results["radarr"] = {"ok": ok, "message": msg}
    else:
        results["radarr"] = {"ok": None, "message": "Non configuré"}

    results["smtp"] = {"ok": bool(s and s.smtp_host), "message": "Configuré" if s and s.smtp_host else "Non configuré"}
    results["rss"] = {"ok": bool(s and s.plex_rss_url), "message": "Configuré" if s and s.plex_rss_url else "Non configuré"}

    return results


# ---------------------------------------------------------------------------
# Statistiques
# ---------------------------------------------------------------------------

@router.get("/stats/timeline")
def stats_timeline(db: Session = Depends(get_db)):
    """Retourne le nombre de demandes par jour sur les 30 derniers jours."""
    from datetime import datetime, timedelta
    from sqlalchemy import func
    days = 30
    start = datetime.utcnow() - timedelta(days=days)
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


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

@router.get("/next-poll")
def next_poll_info():
    """Retourne le nombre de secondes avant le prochain polling (pour le countdown UI)."""
    from ..scheduler import scheduler
    from datetime import datetime, timezone
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
    req = db.query(MediaRequest).filter(MediaRequest.id == request_id).first()
    if not req:
        raise HTTPException(404, "Request not found")
    return {c.name: getattr(req, c.name) for c in req.__table__.columns}


@router.post("/requests/{request_id}/retry")
async def retry_request(request_id: int, db: Session = Depends(get_db)):
    """Repasse une demande en `pending` et déclenche un polling immédiat."""
    req = db.query(MediaRequest).filter(MediaRequest.id == request_id).first()
    if not req:
        raise HTTPException(404, "Request not found")
    if req.status not in ("failed", "pending"):
        raise HTTPException(400, "Only failed or pending requests can be retried")
    req.status = "pending"
    db.commit()
    await poll_watchlists()
    return {"status": "retrying"}


@router.post("/requests/poll")
async def trigger_poll():
    """Déclenche manuellement le polling des watchlists ET la vérification des statuts *arr."""
    await poll_watchlists()
    await check_arr_statuses()
    return {"status": "poll triggered"}


@router.delete("/requests/{request_id}")
def delete_request(request_id: int, db: Session = Depends(get_db)):
    req = db.query(MediaRequest).filter(MediaRequest.id == request_id).first()
    if not req:
        raise HTTPException(404, "Request not found")
    db.delete(req)
    db.commit()
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Activité et notifications
# ---------------------------------------------------------------------------

@router.get("/activity")
def activity_log(db: Session = Depends(get_db)):
    """Retourne les 25 événements les plus récents (7 derniers jours) pour le journal."""
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(days=7)
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
            events.append({
                "type": r.status if r.status in ("failed",) else "request",
                "title": r.title,
                "user": r.plex_user or r.plex_user_id or "?",
                "media_type": r.media_type,
                "time": r.requested_at.isoformat(),
            })
        if r.available_at and r.available_at >= cutoff:
            events.append({
                "type": "available",
                "title": r.title,
                "user": r.plex_user or r.plex_user_id or "?",
                "media_type": r.media_type,
                "time": r.available_at.isoformat(),
            })
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
    return [
        {"id": r.id, "title": r.title, "available_at": r.available_at.isoformat() if r.available_at else None}
        for r in items
    ]
