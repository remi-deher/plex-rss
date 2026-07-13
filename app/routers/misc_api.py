import json as _json
import os as _os
from collections import defaultdict
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import sqlalchemy

from ..database import get_db_async
from ..dependencies import get_current_plex_user, require_admin, require_auth
from ..i18n import SUPPORTED_LOCALES, catalog, normalize_locale
from ..models import ArrInstance, MediaRequest, PlexUser, Settings, VfEpisodeStatus
from ..serializers import format_datetime
from ..utils import now_utc_naive, wrap_image_proxy

router = APIRouter(prefix="/api", tags=["misc"])


@router.get("/image-proxy", dependencies=[Depends(require_auth)])
async def image_proxy(url: str):
    """Proxy authenticated UI images to avoid HTTPS pages loading HTTP posters directly."""
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, "URL image invalide")
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, verify=False) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as e:
        raise HTTPException(502, f"Image inaccessible: {e}") from e

    content_type = resp.headers.get("content-type", "application/octet-stream").split(";")[0].strip().lower()
    if not content_type.startswith("image/"):
        raise HTTPException(415, "La ressource n'est pas une image")
    return Response(
        content=resp.content,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/i18n/catalog", dependencies=[Depends(require_auth)])
async def i18n_catalog(
    request: Request, db: AsyncSession = Depends(get_db_async), user: PlexUser | None = Depends(get_current_plex_user)
):
    settings = (await db.execute(select(Settings))).scalars().first()
    requested = request.query_params.get("locale")
    locale = normalize_locale(
        requested or (user.locale if user else None) or (settings.default_locale if settings else None)
    )
    return {"locale": locale, "supported": sorted(SUPPORTED_LOCALES), "messages": catalog(locale)}


async def _delete_vf_episode_cache(db: AsyncSession, request_id: int) -> None:
    """Purge le cache VF par épisode d'une demande supprimée (évite les lignes orphelines)."""
    await db.execute(sqlalchemy.delete(VfEpisodeStatus).where(VfEpisodeStatus.source_type == "request", VfEpisodeStatus.source_id == request_id))


@router.get("/onboarding")
async def onboarding_status(db: AsyncSession = Depends(get_db_async), _: None = Depends(require_admin)):
    """Retourne l'état d'avancement de la configuration initiale (checklist)."""
    s = (await db.execute(select(Settings))).scalars().first()
    users_count = (await db.execute(select(sqlalchemy.func.count()).select_from(PlexUser))).scalar()
    has_sonarr = (await db.execute(select(ArrInstance).filter(ArrInstance.arr_type == "sonarr", ArrInstance.enabled))).scalars().first() is not None
    has_radarr = (await db.execute(select(ArrInstance).filter(ArrInstance.arr_type == "radarr", ArrInstance.enabled))).scalars().first() is not None
    steps = [
        {"id": "rss", "label": "Flux RSS Plex configuré", "done": bool(s and s.plex_rss_url)},
        {"id": "sonarr", "label": "Sonarr configuré", "done": has_sonarr},
        {"id": "radarr", "label": "Radarr configuré", "done": has_radarr},
        {"id": "smtp", "label": "Email (SMTP) configuré", "done": bool(s and s.smtp_host)},
        {"id": "users", "label": "Au moins un utilisateur détecté", "done": users_count > 0},
        {
            "id": "webhooks",
            "label": "Webhooks Sonarr/Radarr configurés",
            "done": has_sonarr or has_radarr,
            "optional": True,
        },
    ]
    return {"steps": steps, "complete": all(s["done"] for s in steps if not s.get("optional"))}


@router.get("/onboarding/context")
async def onboarding_context(db: AsyncSession = Depends(get_db_async), _: None = Depends(require_admin)):
    """Snapshot de la configuration actuelle pour pré-remplir l'assistant.

    Les secrets ne sont jamais renvoyés en clair : on expose seulement un booléen
    `*_set` indiquant qu'une valeur est déjà enregistrée. Le wizard s'appuie dessus
    pour ne réécrire un secret que si l'utilisateur en saisit un nouveau (sinon le
    champ reste vide côté client → non transmis → non écrasé côté serveur).
    """
    s = (await db.execute(select(Settings))).scalars().first()

    def val(attr):
        return getattr(s, attr, None) if s else None

    def is_set(attr):
        return bool(getattr(s, attr, None)) if s else False

    instances = (await db.execute(select(ArrInstance))).scalars().all()
    return {
        "has_account": bool(s and s.auth_username),
        "plex": {
            "url": val("plex_url"),
            "rss_url": val("plex_rss_url"),
            "verify_ssl": val("plex_verify_ssl"),
            "token_set": is_set("plex_token"),
        },
        "arr_instances": [
            {
                "id": i.id,
                "name": i.name,
                "arr_type": i.arr_type,
                "url": i.url,
                "quality_profile_id": i.quality_profile_id,
                "root_folder": i.root_folder,
                "minimum_availability": i.minimum_availability,
                "enabled": i.enabled,
                "is_default": i.is_default,
            }
            for i in instances
        ],
        "seer": {
            "enabled": bool(val("seer_send_requests") or val("seer_enabled")),
            "url": val("seer_url"),
            "send_requests": val("seer_send_requests"),
            "fallback_arr": val("seer_fallback_arr"),
            "api_key_set": is_set("seer_api_key"),
        },
        "vff": {
            "enabled": val("vff_enabled"),
            "libraries": val("vff_libraries"),
            "recheck_interval_minutes": val("vff_recheck_interval_minutes"),
            "auto_search": val("vff_auto_search"),
        },
        "smtp": {
            "host": val("smtp_host"),
            "port": val("smtp_port"),
            "user": val("smtp_user"),
            "from": val("smtp_from"),
            "tls": val("smtp_tls"),
            "admin_email": val("admin_notification_email"),
            "password_set": is_set("smtp_password"),
        },
        "discord": {"enabled": val("discord_enabled"), "webhook_set": is_set("discord_webhook_url")},
        "telegram": {
            "enabled": val("telegram_enabled"),
            "chat_id": val("telegram_chat_id"),
            "bot_token_set": is_set("telegram_bot_token"),
        },
        "ntfy": {
            "enabled": val("ntfy_enabled"),
            "url": val("ntfy_url"),
            "topic": val("ntfy_topic"),
            "token_set": is_set("ntfy_token"),
        },
        "gotify": {"enabled": val("gotify_enabled"), "url": val("gotify_url"), "token_set": is_set("gotify_token")},
        "tmdb": {"api_key_set": is_set("tmdb_api_key")},
    }


@router.post("/plex/sso/pin")
async def plex_sso_pin(request: Request, _: None = Depends(require_admin)):
    """Crée une demande de PIN Plex SSO et retourne l'URL d'authentification."""
    from ..services.plex_api import get_auth_pin

    try:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.url.netloc)
        forward_url = f"{scheme}://{host}/settings"
        return await get_auth_pin(forward_url=forward_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur d'initialisation SSO Plex : {str(e)}")


@router.get("/plex/sso/check/{pin_id}")
async def plex_sso_check(pin_id: int, _: None = Depends(require_admin)):
    """Vérifie si le PIN Plex a été validé et retourne le token."""
    from ..services.plex_api import check_auth_pin

    try:
        token = await check_auth_pin(pin_id)
        return {"authenticated": bool(token), "token": token}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Conflits et Nettoyage de base de données
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
        "poster_url": wrap_image_proxy(r.poster_url),
        "requested_at": format_datetime(r.requested_at),
        "available_at": format_datetime(r.available_at),
    }


async def _merge_entries(keeper: MediaRequest, dup: MediaRequest, db: AsyncSession):
    """Fusionne dup dans keeper : co-demandeurs + champs manquants."""
    extras: list[dict] = _json.loads(keeper.extra_requesters or "[]")
    existing_ids = {keeper.plex_user_id} | {e["plex_user_id"] for e in extras}
    for e in _json.loads(dup.extra_requesters or "[]"):
        if e["plex_user_id"] not in existing_ids:
            extras.append(e)
            existing_ids.add(e["plex_user_id"])
    if dup.plex_user_id not in existing_ids:
        extras.append({"plex_user_id": dup.plex_user_id, "display_name": dup.plex_user or dup.plex_user_id})

    if dup.source == "seer" and dup.tmdb_id:
        keeper.tmdb_id = dup.tmdb_id
    elif not keeper.tmdb_id and dup.tmdb_id:
        keeper.tmdb_id = dup.tmdb_id
    if not keeper.tvdb_id and dup.tvdb_id:
        keeper.tvdb_id = dup.tvdb_id
    if not keeper.poster_url and dup.poster_url:
        keeper.poster_url = dup.poster_url
    keeper.extra_requesters = _json.dumps(extras, ensure_ascii=False)
    await db.delete(dup)


@router.get("/conflicts")
async def list_conflicts(db: AsyncSession = Depends(get_db_async), _: None = Depends(require_admin)):
    """Retourne tous les conflits détectés, filtrés des ignorés."""
    ignored = _load_ignored()
    all_reqs = (await db.execute(select(MediaRequest))).scalars().all()
    known_user_ids = {u.plex_user_id for u in (await db.execute(select(PlexUser))).scalars().all()}
    now = now_utc_naive()

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

    orphaned = []
    for r in all_reqs:
        if r.plex_user_id not in known_user_ids:
            key = f"orphan:{r.id}"
            if key in ignored:
                continue
            orphaned.append({"key": key, **_req_dict(r)})

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
async def resolve_conflict(body: dict, db: AsyncSession = Depends(get_db_async), _: None = Depends(require_admin)):
    keep_id: int = body.get("keep_id")
    delete_ids: list[int] = body.get("delete_ids", [])
    if not keep_id or not delete_ids:
        raise HTTPException(400, "keep_id et delete_ids requis")
    keeper = await db.get(MediaRequest, keep_id)
    if not keeper:
        raise HTTPException(404, f"Entrée {keep_id} introuvable")
    for del_id in delete_ids:
        dup = await db.get(MediaRequest, del_id)
        if dup:
            await _merge_entries(keeper, dup, db)
    await db.commit()
    return {"ok": True, "kept": keep_id, "deleted": delete_ids}


@router.post("/conflicts/auto-resolve")
async def auto_resolve_conflicts(db: AsyncSession = Depends(get_db_async), _: None = Depends(require_admin)):
    """Résout automatiquement tous les conflits tmdb : garde l'entrée Seer."""
    all_reqs = (await db.execute(select(MediaRequest))).scalars().all()
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
                await _merge_entries(keeper, dup, db)
        resolved += 1

    await db.commit()
    return {"ok": True, "resolved": resolved}


@router.post("/conflicts/ignore")
def ignore_conflict(body: dict, _: None = Depends(require_admin)):
    """Marque un conflit comme ignoré (ne réapparaîtra plus)."""
    key: str = body.get("key")
    if not key:
        raise HTTPException(400, "key requis")
    ignored = _load_ignored()
    ignored.add(key)
    _save_ignored(ignored)
    return {"ok": True}


@router.delete("/conflicts/ignore/{key:path}")
def unignore_conflict(key: str, _: None = Depends(require_admin)):
    """Retire un conflit de la liste des ignorés."""
    ignored = _load_ignored()
    ignored.discard(key)
    _save_ignored(ignored)
    return {"ok": True}


@router.delete("/conflicts/no-tmdb/{request_id}")
async def delete_no_tmdb(request_id: int, db: AsyncSession = Depends(get_db_async), _: None = Depends(require_admin)):
    req = await db.get(MediaRequest, request_id)
    if not req:
        raise HTTPException(404, "Entrée introuvable")
    if req.tmdb_id:
        raise HTTPException(400, "Cette entrée a un tmdb_id — utilisez /conflicts/resolve")
    await _delete_vf_episode_cache(db, req.id)
    await db.delete(req)
    await db.commit()
    return {"ok": True}


@router.delete("/conflicts/orphan/{request_id}")
async def delete_orphan(request_id: int, db: AsyncSession = Depends(get_db_async), _: None = Depends(require_admin)):
    req = await db.get(MediaRequest, request_id)
    if not req:
        raise HTTPException(404, "Entrée introuvable")
    await _delete_vf_episode_cache(db, req.id)
    await db.delete(req)
    await db.commit()
    return {"ok": True}
