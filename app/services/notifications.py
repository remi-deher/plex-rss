"""
Notifications push : Discord (webhook), Telegram (Bot API), ntfy et Gotify.

Toutes les fonctions send_* lèvent désormais une exception en cas d'échec réel (réseau,
HTTP non-2xx) au lieu de l'avaler silencieusement : c'est notification_queue.py (l'appelant)
qui centralise retry + journalisation dans NotificationLog, comme pour l'email — auparavant
une simple erreur réseau perdait la notification push sans aucune trace ni nouvelle tentative.
Quand le canal n'est simplement pas configuré (URL/token absent), elles lèvent
`ChannelNotConfigured` : l'appelant sait alors qu'il n'y a rien à journaliser ni retenter.

Événements supportés :
- "request"   : nouveau média demandé
- "available" : média désormais disponible dans Sonarr/Radarr
- "failed"    : échec de transmission à Sonarr/Radarr/Seer/Prowlarr
"""

import logging

import httpx

from ..models import MediaRequest, Settings
from .notification_catalog import event_color

logger = logging.getLogger(__name__)


class ChannelNotConfigured(Exception):
    """Le canal (URL/token) n'est pas configuré : rien à envoyer, rien à journaliser."""


def _build_message(event: str, request: MediaRequest, context: dict | None = None) -> tuple[str, str]:
    """Construit le titre et le corps d'une notification selon l'événement.

    `context` : reprend le contexte structuré déjà utilisé par l'email (voir
    notification_orchestrator._notify) — pour "failed", `context["reason"]` porte le
    message déjà résolu par l'appelant (cible réelle : Seer/Sonarr/Radarr/Prowlarr/torrent),
    au lieu de re-deviner "Sonarr ou Radarr" ici sans savoir ce qui a vraiment été tenté.

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
        reason = (context or {}).get("reason")
        body = reason or f"Impossible de transmettre à {'Sonarr' if request.media_type == 'show' else 'Radarr'}"

    return title, body


def _build_discord_embed(event: str, request: MediaRequest, context: dict | None = None, include_synopsis: bool = False) -> dict:
    """Construit un embed Discord pour un événement donné."""
    title, body = _build_message(event, request, context)
    embed: dict = {"title": title, "description": body, "color": event_color(event)}
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


async def send_discord(settings: Settings, request: MediaRequest, event: str, context: dict | None = None):
    """Envoie une notification Discord via webhook global (embed coloré avec synopsis)."""
    if not settings.discord_webhook_url:
        raise ChannelNotConfigured("discord_webhook_url absent")
    embed = _build_discord_embed(event, request, context, include_synopsis=True)
    await _post_discord_embed(settings.discord_webhook_url, embed)
    logger.info(f"Discord notif sent for '{request.title}' ({event})")


async def send_discord_to_webhook(webhook_url: str, request: MediaRequest, event: str, context: dict | None = None):
    """Envoie une notification Discord vers un webhook spécifique (par utilisateur)."""
    if not webhook_url:
        raise ChannelNotConfigured("webhook Discord utilisateur absent")
    embed = _build_discord_embed(event, request, context)
    await _post_discord_embed(webhook_url, embed)


async def send_telegram(settings: Settings, request: MediaRequest, event: str, context: dict | None = None):
    """Envoie une notification Telegram via Bot API global (sendMessage en Markdown)."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        raise ChannelNotConfigured("telegram_bot_token/chat_id absent")
    title, body = _build_message(event, request, context)
    text = f"*{title}*\n{body}"
    if request.overview:
        text += f"\n\n_{request.overview[:300]}_"
    await _post_telegram_message(settings.telegram_bot_token, settings.telegram_chat_id, text)
    logger.info(f"Telegram notif sent for '{request.title}' ({event})")


async def send_telegram_to_chat(bot_token: str, chat_id: str, request: MediaRequest, event: str, context: dict | None = None):
    """Envoie une notification Telegram vers un chat spécifique (par utilisateur)."""
    if not bot_token or not chat_id:
        raise ChannelNotConfigured("bot_token/chat_id utilisateur absent")
    title, body = _build_message(event, request, context)
    text = f"*{title}*\n{body}"
    if request.overview:
        text += f"\n\n_{request.overview[:300]}_"
    await _post_telegram_message(bot_token, chat_id, text)


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


async def send_ntfy_notif(settings: Settings, request: MediaRequest, event: str, context: dict | None = None):
    """Notification globale ntfy wrapper."""
    if not settings.ntfy_url:
        raise ChannelNotConfigured("ntfy_url absent")
    title, body = _build_message(event, request, context)
    if request.overview:
        body += f"\n\n{request.overview[:300]}"
    await send_ntfy(settings.ntfy_url, settings.ntfy_token, title, body)
    logger.info(f"ntfy notif sent for '{request.title}' ({event})")


async def send_gotify_notif(settings: Settings, request: MediaRequest, event: str, context: dict | None = None):
    """Notification globale Gotify wrapper."""
    if not settings.gotify_url or not settings.gotify_token:
        raise ChannelNotConfigured("gotify_url/token absent")
    title, body = _build_message(event, request, context)
    if request.overview:
        body += f"\n\n{request.overview[:300]}"
    await send_gotify(settings.gotify_url, settings.gotify_token, title, body)
    logger.info(f"Gotify notif sent for '{request.title}' ({event})")
