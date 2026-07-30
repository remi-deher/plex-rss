"""Écouteur temps réel du websocket Plex (/:/websockets/notifications).

Complète le polling de playback_activity.py : Plex y pousse les changements d'état
(playing/paused/buffering/stopped) en direct, avec un évènement "stopped" explicite qui
fait autorité pour clôturer une session -- contrairement au polling, qui ne peut que
déduire un arrêt de l'absence de la session au cycle suivant (voir _MISS_THRESHOLD dans
playback_activity.py). Le polling reste actif comme filet de sécurité : Plex a un bug
connu où certains flux n'envoient jamais l'évènement "stopped", et le websocket ne
transporte pas les métadonnées complètes (codec, bande passante...) nécessaires à
l'enrichissement d'une session inconnue.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import ssl
from urllib.parse import urlsplit, urlunsplit

import websockets
from sqlalchemy.future import select

from ..database import AsyncSessionLocal
from ..models import Settings
from .distributed_lock import acquire_distributed_lock, release_distributed_lock, renew_distributed_lock
from .playback_activity import collect_plex_activity, handle_websocket_state

logger = logging.getLogger(__name__)

_LOCK_KEY = "plexarr:locks:playback-websocket"
_LOCK_TTL = 90
_RENEW_INTERVAL = 30
_SETTINGS_RECHECK_INTERVAL = 30
_BACKOFF_MIN = 5
_BACKOFF_MAX = 60
_HEALTHY_CONNECTION_SECONDS = 30  # au-delà, la connexion est jugée stable : reset du backoff


def _websocket_url(plex_url: str, plex_token: str) -> str:
    parts = urlsplit(plex_url.rstrip("/"))
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit((scheme, parts.netloc, "/:/websockets/notifications", f"X-Plex-Token={plex_token}", ""))


async def _load_settings() -> Settings | None:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(Settings))).scalars().first()


async def _handle_message(raw: str | bytes) -> None:
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return
    container = payload.get("NotificationContainer") or {}
    if container.get("type") != "playing":
        return
    for item in container.get("PlaySessionStateNotification") or []:
        try:
            session_key = int(item.get("sessionKey"))
        except (TypeError, ValueError):
            continue
        rating_key = str(item.get("ratingKey") or "") or None
        state = str(item.get("state") or "").lower()
        if not state:
            continue
        try:
            result = await handle_websocket_state(session_key, rating_key, state)
            if state != "stopped" and result.get("status") == "unknown":
                # Session jamais vue par le polling : on déclenche une collecte complète
                # plutôt que de dupliquer le parsing/l'enrichissement XML avec les seuls
                # champs (partiels) fournis par le websocket.
                await collect_plex_activity()
        except Exception:
            logger.exception("Erreur traitement évènement websocket Plex (sessionKey=%s)", session_key)


async def _renew_loop(token: str) -> None:
    while True:
        await asyncio.sleep(_RENEW_INTERVAL)
        await renew_distributed_lock(_LOCK_KEY, token, ttl=_LOCK_TTL)


async def _listen_once(settings: Settings) -> None:
    """Une connexion websocket, jusqu'à déconnexion ou erreur."""
    url = _websocket_url(settings.plex_url, settings.plex_token)
    ssl_context = None
    if url.startswith("wss://"):
        ssl_context = ssl.create_default_context()
        if not settings.plex_verify_ssl:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

    connected_at = asyncio.get_running_loop().time()
    async with websockets.connect(
        url, ssl=ssl_context, open_timeout=15, ping_interval=20, ping_timeout=20
    ) as ws:
        logger.info("Websocket Plex connecté (%s)", settings.plex_url)
        async for message in ws:
            await _handle_message(message)
    elapsed = asyncio.get_running_loop().time() - connected_at
    if elapsed < _HEALTHY_CONNECTION_SECONDS:
        raise ConnectionError("Connexion websocket Plex trop courte, probable rejet/instabilité")


async def run_alert_listener() -> None:
    """Boucle de fond : maintient une connexion websocket Plex, avec reconnexion et
    verrou distribué pour rester le seul écouteur actif (défensif si le déploiement
    scale un jour au-delà d'un conteneur worker).
    """
    backoff = _BACKOFF_MIN
    token: str | None = None
    try:
        while True:
            settings = await _load_settings()
            if not settings or not settings.live_activity_enabled or not settings.plex_url or not settings.plex_token:
                await asyncio.sleep(_SETTINGS_RECHECK_INTERVAL)
                continue

            if token is None:
                token = await acquire_distributed_lock(_LOCK_KEY, ttl=_LOCK_TTL)
                if token is None:
                    # Un autre process détient déjà l'écoute (autre réplique/instance).
                    await asyncio.sleep(_LOCK_TTL / 2)
                    continue

            renew_task = asyncio.create_task(_renew_loop(token))
            try:
                await _listen_once(settings)
                backoff = _BACKOFF_MIN
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Websocket Plex déconnecté (%s), reconnexion dans %ss", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)
            finally:
                renew_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await renew_task
    finally:
        if token:
            await release_distributed_lock(_LOCK_KEY, token)
