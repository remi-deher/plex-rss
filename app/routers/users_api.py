from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_auth
from ..models import MediaRequest, PlexUser, Settings
from ..services.email_service import _send as smtp_send
from ..services.seer import get_users as seer_get_users, get_user_requests as seer_get_user_requests
from ..utils import get_or_404

router = APIRouter(prefix="/api", tags=["users"], dependencies=[Depends(require_auth)])

# Réutilise la validation du mode de notification définie dans settings_api
from .settings_api import _validate_series_notify_modes


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


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    return db.query(PlexUser).all()


@router.get("/users/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db)):
    """Détail complet d'un utilisateur + ses stats de demandes (pour la modale hub)."""
    user = get_or_404(db, PlexUser, user_id, "User not found")
    rows = db.query(MediaRequest.status, MediaRequest.requested_at).filter(
        MediaRequest.plex_user_id == user.plex_user_id
    ).all()
    stats = {"total": 0, "available": 0, "failed": 0, "sent": 0, "pending": 0, "last_requested_at": None}
    for status, req_at in rows:
        stats["total"] += 1
        s = status.value if hasattr(status, "value") else str(status)
        if s in stats:
            stats[s] += 1
        if req_at and (stats["last_requested_at"] is None or req_at > stats["last_requested_at"]):
            stats["last_requested_at"] = req_at

    # Utilise le sérialiseur centralisé
    from ..serializers import serialize_plex_user
    return serialize_plex_user(user, stats)


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
        rows = db.query(MediaRequest.tmdb_id).filter(
            MediaRequest.plex_user_id == user.plex_user_id, MediaRequest.tmdb_id.isnot(None)
        ).all()
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
