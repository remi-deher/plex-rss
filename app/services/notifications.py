"""
Notifications push : Discord (webhook) et Telegram (Bot API).

Chaque canal est optionnel — si le token/URL n'est pas configuré, la fonction retourne
silencieusement. Les erreurs réseau sont loggées mais ne font pas planter le scheduler.

Événements supportés :
- "request"   : nouveau média demandé
- "available" : média désormais disponible dans Sonarr/Radarr
- "failed"    : échec de transmission à Sonarr/Radarr
"""

import httpx
import logging
from ..models import Settings, MediaRequest

logger = logging.getLogger(__name__)


def _build_message(event: str, request: MediaRequest) -> tuple[str, str]:
    """Construit le titre et le corps d'une notification selon l'événement.

    Returns:
        (title, body)
    """
    type_label = "Série" if request.media_type == "show" else "Film"
    user = request.plex_user or request.plex_user_id or "?"
    year = f" ({request.year})" if request.year else ""

    if event == "request":
        title = f"Nouvelle demande — {request.title}{year}"
        body = f"{type_label} demandé par {user}"
    elif event == "available":
        title = f"Disponible — {request.title}{year}"
        body = f"{type_label} maintenant disponible sur Plex !"
    else:
        title = f"Echec — {request.title}{year}"
        body = f"Impossible de transmettre à {'Sonarr' if request.media_type == 'show' else 'Radarr'}"

    return title, body


async def send_discord(settings: Settings, request: MediaRequest, event: str):
    """Envoie une notification Discord via webhook (embed coloré).

    Les couleurs correspondent aux statuts : orange (demande), vert (dispo), rouge (échec).
    """
    if not settings.discord_webhook_url:
        return

    title, body = _build_message(event, request)
    color = {"request": 0xE5A00D, "available": 0x1DB954, "failed": 0xDC3545}.get(event, 0x888888)

    embed = {
        "title": title,
        "description": body,
        "color": color,
    }
    if request.poster_url:
        embed["thumbnail"] = {"url": request.poster_url}
    if request.overview:
        # Tronquer pour rester dans les limites Discord (4096 chars par embed)
        embed["fields"] = [{"name": "Synopsis", "value": request.overview[:500], "inline": False}]

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(settings.discord_webhook_url, json={"embeds": [embed]})
            resp.raise_for_status()
            logger.info(f"Discord notif sent for '{request.title}' ({event})")
    except Exception as e:
        logger.error(f"Discord notification failed: {e}")


async def send_telegram(settings: Settings, request: MediaRequest, event: str):
    """Envoie une notification Telegram via Bot API (sendMessage en Markdown).

    Le synopsis est tronqué à 300 caractères pour garder les messages lisibles.
    """
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return

    title, body = _build_message(event, request)
    text = f"*{title}*\n{body}"
    if request.overview:
        text += f"\n\n_{request.overview[:300]}_"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                },
            )
            resp.raise_for_status()
            logger.info(f"Telegram notif sent for '{request.title}' ({event})")
    except Exception as e:
        logger.error(f"Telegram notification failed: {e}")


async def send_all(settings: Settings, request: MediaRequest, event: str):
    """Déclenche Discord et Telegram en séquence pour un événement donné."""
    await send_discord(settings, request, event)
    await send_telegram(settings, request, event)
