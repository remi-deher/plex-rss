import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_auth
from ..models import MediaRequest, PlexUser, Settings
from ..serializers import format_datetime, request_status_value, serialize_plex_user
from ..services.email_service import _send as smtp_send
from ..services.seer import get_user_requests as seer_get_user_requests
from ..services.seer import get_users as seer_get_users
from ..utils import get_or_404

# Réutilise la validation du mode de notification définie dans settings_api
from .settings_api import _validate_series_notify_modes

router = APIRouter(prefix="/api", tags=["users"], dependencies=[Depends(require_auth)])


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
    notify_vf_movie: Optional[bool] = True
    notify_vo_movie: Optional[bool] = True
    notify_vf_series: Optional[bool] = True
    notify_vo_series: Optional[bool] = True
    discord_webhook_url: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    seer_active: Optional[bool] = None
    sonarr_instance_id: Optional[int] = None
    radarr_instance_id: Optional[int] = None


class UserEnabledUpdate(BaseModel):
    enabled: bool


def _user_source_label(user: PlexUser) -> str:
    if user.source == "seer":
        return "Seer only"
    if user.source == "api" and user.seer_user_id:
        return "Plex API + Seer"
    if user.source == "api":
        return "Plex API"
    if user.seer_user_id:
        return "RSS + Seer"
    return "RSS"


def _build_user_diagnostic(user: PlexUser, stats: dict, db: Session) -> dict:
    settings = db.query(Settings).first()
    seer_configured = bool(settings and settings.seer_url and settings.seer_api_key)
    seer_requests_enabled = bool(
        settings and settings.seer_send_requests and settings.seer_url and settings.seer_api_key
    )
    rss_configured = bool(settings and settings.plex_rss_url)
    plex_api_configured = bool(settings and settings.plex_token)

    co_request_count = 0
    for (extra_requesters,) in db.query(MediaRequest.extra_requesters).filter(
        MediaRequest.extra_requesters.isnot(None), MediaRequest.extra_requesters != "[]"
    ):
        try:
            extras = json.loads(extra_requesters or "[]")
        except Exception:
            extras = []
        if any(e.get("plex_user_id") == user.plex_user_id for e in extras):
            co_request_count += 1

    effects = [
        {
            "key": "discover",
            "label": "Visible dans Discover",
            "ok": bool(user.enabled),
            "detail": "Propose dans le selecteur de demandeur"
            if user.enabled
            else "Masque tant que l'utilisateur est desactive",
        },
        {
            "key": "automation",
            "label": "Watchlist traitee",
            "ok": bool(user.enabled),
            "detail": "Les nouvelles demandes peuvent etre traitees"
            if user.enabled
            else "Les automatisations ignorent cet utilisateur",
        },
        {
            "key": "seer_link",
            "label": "Liaison Seer",
            "ok": bool(user.seer_user_id),
            "detail": f"Compte Seer #{user.seer_user_id}" if user.seer_user_id else "Aucune liaison Seer",
        },
        {
            "key": "notifications",
            "label": "Notifications",
            "ok": bool(user.notification_email or user.plex_email or user.notify_admin),
            "detail": "Email ou notification admin disponible"
            if (user.notification_email or user.plex_email or user.notify_admin)
            else "Aucun destinataire connu",
        },
    ]

    warnings = []
    actions = []
    if not user.enabled:
        warnings.append("Utilisateur desactive : absent de Discover et ignore par les automatisations.")
        actions.append({"key": "enable", "label": "Activer", "style": "success"})
    else:
        actions.append({"key": "disable", "label": "Desactiver", "style": "outline-secondary"})
    if seer_configured and not user.seer_user_id and user.source != "seer":
        warnings.append("Seer est configure mais cet utilisateur n'est pas lie.")
        actions.append({"key": "automatch_seer", "label": "Lier Seer automatiquement", "style": "outline-info"})
    if user.seer_user_id and (not user.notification_email or not user.custom_name):
        actions.append({"key": "complete_seer", "label": "Completer depuis Seer", "style": "outline-warning"})
    if user.source == "seer":
        warnings.append("Utilisateur Seer-only : pas encore associe a un utilisateur Plex/RSS/API.")
    if not rss_configured and not plex_api_configured:
        warnings.append("Aucune source Plex watchlist configuree : seules les donnees Seer/manual peuvent apparaitre.")

    return {
        "source_label": _user_source_label(user),
        "discover_visible": bool(user.enabled),
        "automation_enabled": bool(user.enabled),
        "seer_configured": seer_configured,
        "seer_requests_enabled": seer_requests_enabled,
        "rss_configured": rss_configured,
        "plex_api_configured": plex_api_configured,
        "primary_request_count": stats.get("total", 0),
        "co_request_count": co_request_count,
        "effects": effects,
        "warnings": warnings,
        "actions": actions,
    }


def _activity_row(req: MediaRequest, role: str) -> dict:
    return {
        "id": req.id,
        "title": req.title,
        "year": req.year,
        "media_type": req.media_type,
        "status": request_status_value(req.status),
        "source": req.source,
        "role": role,
        "requested_at": format_datetime(req.requested_at),
        "available_at": format_datetime(req.available_at),
        "poster_url": req.poster_url,
        "details": {
            "request_id": req.id,
            "plex_user_id": req.plex_user_id,
            "plex_user": req.plex_user,
            "tmdb_id": req.tmdb_id,
            "tvdb_id": req.tvdb_id,
            "imdb_id": req.imdb_id,
            "plex_guid": req.plex_guid,
            "arr_id": req.arr_id,
            "arr_slug": req.arr_slug,
            "arr_instance_id": req.arr_instance_id,
            "download_client_id": req.download_client_id,
            "torrent_hash": req.torrent_hash,
            "extra_requesters": req.extra_requesters,
            "next_release_at": format_datetime(req.next_release_at),
            "next_release_label": req.next_release_label,
            "overview": req.overview,
        },
    }


def _build_user_activity(user: PlexUser, db: Session, limit: int = 12) -> dict:
    rows: dict[int, dict] = {}
    primary = (
        db.query(MediaRequest)
        .filter(MediaRequest.plex_user_id == user.plex_user_id)
        .order_by(MediaRequest.requested_at.desc())
        .limit(limit * 2)
        .all()
    )
    for req in primary:
        rows[req.id] = _activity_row(req, "primary")

    co_candidates = (
        db.query(MediaRequest)
        .filter(MediaRequest.extra_requesters.isnot(None), MediaRequest.extra_requesters != "[]")
        .all()
    )
    for req in co_candidates:
        try:
            extras = json.loads(req.extra_requesters or "[]")
        except Exception:
            extras = []
        if any(e.get("plex_user_id") == user.plex_user_id for e in extras):
            rows.setdefault(req.id, _activity_row(req, "co_requester"))

    recent = sorted(rows.values(), key=lambda r: r.get("requested_at") or "", reverse=True)[:limit]
    return {"recent": recent, "limit": limit}


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    return db.query(PlexUser).all()


@router.get("/users/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db)):
    """Détail complet d'un utilisateur + ses stats de demandes (pour la modale hub)."""
    user = get_or_404(db, PlexUser, user_id, "User not found")
    rows = (
        db.query(MediaRequest.status, MediaRequest.requested_at)
        .filter(MediaRequest.plex_user_id == user.plex_user_id)
        .all()
    )
    stats = {"total": 0, "available": 0, "failed": 0, "sent": 0, "pending": 0, "last_requested_at": None}
    for status, req_at in rows:
        stats["total"] += 1
        s = status.value if hasattr(status, "value") else str(status)
        if s == "sent_to_arr":
            stats["sent"] += 1
        elif s in stats:
            stats[s] += 1
        if req_at and (stats["last_requested_at"] is None or req_at > stats["last_requested_at"]):
            stats["last_requested_at"] = req_at

    # Utilise le sérialiseur centralisé
    diagnostic = _build_user_diagnostic(user, stats.copy(), db)
    activity = _build_user_activity(user, db)
    data = serialize_plex_user(user, stats)
    data["diagnostic"] = diagnostic
    data["activity"] = activity
    return data


@router.post("/users")
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    payload = data.model_dump()
    _validate_series_notify_modes(payload)
    existing = db.query(PlexUser).filter(PlexUser.plex_user_id == data.plex_user_id).first()
    if existing:
        raise HTTPException(409, "User already exists")
    user = PlexUser(**payload)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/users/{user_id}")
def update_user(user_id: int, data: UserCreate, db: Session = Depends(get_db)):
    user = get_or_404(db, PlexUser, user_id, "User not found")
    payload = data.model_dump()
    _validate_series_notify_modes(payload)
    for k, v in payload.items():
        setattr(user, k, v)
    # Propager le nouveau display_name sur les demandes existantes
    resolved = data.display_name or user.plex_user_id
    db.query(MediaRequest).filter(MediaRequest.plex_user_id == user.plex_user_id).update({"plex_user": resolved})
    db.commit()
    return user


@router.put("/users/{user_id}/enabled")
def update_user_enabled(user_id: int, data: UserEnabledUpdate, db: Session = Depends(get_db)):
    user = get_or_404(db, PlexUser, user_id, "User not found")
    user.enabled = data.enabled
    db.commit()
    db.refresh(user)
    return {"status": "ok", "enabled": user.enabled}


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
    s = db.query(Settings).first()
    if not s or not s.seer_url or not s.seer_api_key:
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
        rows = (
            db.query(MediaRequest.tmdb_id)
            .filter(MediaRequest.plex_user_id == user.plex_user_id, MediaRequest.tmdb_id.isnot(None))
            .all()
        )
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
    """Fusionne un utilisateur Seer-only vers un utilisateur RSS existant."""
    seer_user = get_or_404(db, PlexUser, seer_only_id, "Utilisateur Seer-only introuvable")
    if seer_user.source != "seer":
        raise HTTPException(400, "Cet utilisateur n'est pas un utilisateur Seer-only")

    target = get_or_404(db, PlexUser, target_id, "Utilisateur cible introuvable")
    if target.source == "seer":
        raise HTTPException(400, "La cible ne peut pas être un utilisateur Seer-only")

    target.seer_user_id = seer_user.seer_user_id
    target.seer_active = seer_user.seer_active

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
    """Complète les infos d'un PlexUser depuis son compte Seer lié."""
    user = get_or_404(db, PlexUser, user_id, "User not found")
    if not user.seer_user_id:
        raise HTTPException(400, "Utilisateur non lié à Seer")
    s = db.query(Settings).first()
    if not s or not s.seer_url or not s.seer_api_key:
        raise HTTPException(400, "Seer non configuré")

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

    changes = {}
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
  <p style="color:#ccc">Cet email confirme que les notifications fonctionnent correctement pour ton compte Plexarr.</p>
  <p style="color:#888;font-size:12px;margin-top:24px">Plexarr — email de test</p>
</div>
</body></html>"""
    try:
        await smtp_send(settings, recipient, "[Plexarr] Test de notification", html)
    except Exception as e:
        raise HTTPException(500, f"Échec SMTP : {e}")
    return {"status": "sent", "recipient": recipient}
