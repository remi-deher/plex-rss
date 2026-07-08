"""
Notifications push : Discord (webhook) et Telegram (Bot API).

Chaque canal est optionnel — si le token/URL n'est pas configuré, la fonction retourne
silencieusement. Les erreurs réseau sont loggées mais ne font pas planter le scheduler.

Événements supportés :
- "request"   : nouveau média demandé
- "available" : média désormais disponible dans Sonarr/Radarr
- "failed"    : échec de transmission à Sonarr/Radarr
"""

import logging

import httpx

from ..models import MediaRequest, Settings

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
    elif event == "available_vf":
        title = f"Disponible en VF â€” {request.title}{year}"
        body = f"{type_label} disponible sur Plex avec une piste audio franÃ§aise."
    elif event == "available_vo_tracking":
        title = f"Disponible en VO â€” {request.title}{year}"
        body = f"{type_label} disponible sur Plex en VO. Le suivi VF reste actif."
    elif event == "vo_only":
        title = f"Disponible en VO — {request.title}{year}"
        body = f"{type_label} disponible en VO uniquement. Vous serez prévenu dès que la VF arrive."
    elif event == "vf_available":
        title = f"VF disponible — {request.title}{year}"
        body = f"{type_label} est maintenant disponible en version française sur Plex !"
    elif event == "episode_track":
        title = f"Nouveau contenu — {request.title}{year}"
        body = f"{type_label} : nouvel épisode/saison disponible sur Plex."
    else:
        title = f"Echec — {request.title}{year}"
        body = f"Impossible de transmettre à {'Sonarr' if request.media_type == 'show' else 'Radarr'}"

    return title, body


def _build_discord_embed(event: str, request: MediaRequest, include_synopsis: bool = False) -> dict:
    """Construit un embed Discord pour un événement donné."""
    title, body = _build_message(event, request)
    color = {
        "request": 0xE5A00D,
        "available": 0x1DB954,
        "available_vf": 0x1DB954,
        "available_vo_tracking": 0x0D6EFD,
        "vo_only": 0x0D6EFD,
        "vf_available": 0x1DB954,
        "episode_track": 0x0D6EFD,
        "failed": 0xDC3545,
    }.get(event, 0x888888)
    embed: dict = {"title": title, "description": body, "color": color}
    if request.poster_url:
        embed["thumbnail"] = {"url": request.poster_url}
    if include_synopsis and request.overview:
        embed["fields"] = [{"name": "Synopsis", "value": request.overview[:500], "inline": False}]
    return embed


async def _post_discord_embed(webhook_url: str, embed: dict):
    """Envoie un embed Discord vers un webhook URL. Lève une exception en cas d'erreur."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(webhook_url, json={"embeds": [embed]})
        resp.raise_for_status()


async def _post_telegram_message(bot_token: str, chat_id: str, text: str):
    """Envoie un message Telegram. Lève une exception en cas d'erreur."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        )
        resp.raise_for_status()


async def send_discord(settings: Settings, request: MediaRequest, event: str):
    """Envoie une notification Discord via webhook global (embed coloré avec synopsis)."""
    if not settings.discord_webhook_url:
        return
    embed = _build_discord_embed(event, request, include_synopsis=True)
    try:
        await _post_discord_embed(settings.discord_webhook_url, embed)
        logger.info(f"Discord notif sent for '{request.title}' ({event})")
    except Exception as e:
        logger.error(f"Discord notification failed: {e}")


async def send_discord_to_webhook(webhook_url: str, request: MediaRequest, event: str):
    """Envoie une notification Discord vers un webhook spécifique (par utilisateur)."""
    if not webhook_url:
        return
    embed = _build_discord_embed(event, request)
    try:
        await _post_discord_embed(webhook_url, embed)
    except Exception as e:
        logger.error(f"Discord per-user notif failed ({webhook_url[:40]}…): {e}")


async def send_telegram(settings: Settings, request: MediaRequest, event: str):
    """Envoie une notification Telegram via Bot API global (sendMessage en Markdown)."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return
    title, body = _build_message(event, request)
    text = f"*{title}*\n{body}"
    if request.overview:
        text += f"\n\n_{request.overview[:300]}_"
    try:
        await _post_telegram_message(settings.telegram_bot_token, settings.telegram_chat_id, text)
        logger.info(f"Telegram notif sent for '{request.title}' ({event})")
    except Exception as e:
        logger.error(f"Telegram notification failed: {e}")


async def send_telegram_to_chat(bot_token: str, chat_id: str, request: MediaRequest, event: str):
    """Envoie une notification Telegram vers un chat spécifique (par utilisateur)."""
    if not bot_token or not chat_id:
        return
    title, body = _build_message(event, request)
    text = f"*{title}*\n{body}"
    if request.overview:
        text += f"\n\n_{request.overview[:300]}_"
    try:
        await _post_telegram_message(bot_token, chat_id, text)
    except Exception as e:
        logger.error(f"Telegram per-user notif failed (chat {chat_id}): {e}")


async def send_ntfy(url: str, token: str | None, title: str, body: str):
    """Envoie une notification push via ntfy."""
    headers = {"Title": title}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, headers=headers, content=body.encode("utf-8"))
        resp.raise_for_status()


async def send_gotify(url: str, token: str, title: str, body: str, priority: int = 5):
    """Envoie une notification push via Gotify."""
    async with httpx.AsyncClient(timeout=10) as client:
        target_url = f"{url.rstrip('/')}/message"
        resp = await client.post(
            target_url,
            params={"token": token},
            json={"title": title, "message": body, "priority": priority},
        )
        resp.raise_for_status()


async def send_ntfy_notif(settings: Settings, request: MediaRequest, event: str):
    """Notification globale ntfy wrapper."""
    if not settings.ntfy_url:
        return
    title, body = _build_message(event, request)
    if request.overview:
        body += f"\n\n{request.overview[:300]}"
    try:
        await send_ntfy(settings.ntfy_url, settings.ntfy_token, title, body)
        logger.info(f"ntfy notif sent for '{request.title}' ({event})")
    except Exception as e:
        logger.error(f"ntfy notification failed: {e}")


async def send_gotify_notif(settings: Settings, request: MediaRequest, event: str):
    """Notification globale Gotify wrapper."""
    if not settings.gotify_url or not settings.gotify_token:
        return
    title, body = _build_message(event, request)
    if request.overview:
        body += f"\n\n{request.overview[:300]}"
    try:
        await send_gotify(settings.gotify_url, settings.gotify_token, title, body)
        logger.info(f"Gotify notif sent for '{request.title}' ({event})")
    except Exception as e:
        logger.error(f"Gotify notification failed: {e}")


async def send_all(settings: Settings, request: MediaRequest, event: str):
    """Déclenche Discord, Telegram, ntfy et Gotify en séquence pour un événement donné."""
    await send_discord(settings, request, event)
    await send_telegram(settings, request, event)
    await send_ntfy_notif(settings, request, event)
    await send_gotify_notif(settings, request, event)
