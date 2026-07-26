"""Etat d'avancement de la configuration initiale (checklist du tableau de bord) et appariement SSO Plex."""

import logging

import sqlalchemy
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db_async
from ..dependencies import require_admin
from ..models import ArrInstance, PlexUser, Settings
from ..services import email_providers

router = APIRouter(prefix="/api", tags=["misc"])
logger = logging.getLogger(__name__)

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
        {"id": "smtp", "label": "Email (SMTP) configuré", "done": await email_providers.has_enabled_provider(db)},
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
