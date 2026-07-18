"""Utilitaires partagés entre les modules de l'application."""

from datetime import datetime
from typing import Any, Protocol, TypeVar

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select


class _HasId(Protocol):
    id: Any


_T = TypeVar("_T", bound=_HasId)


async def async_get_or_404(
    db: AsyncSession,
    model: type[_T],
    obj_id: Any,
    detail: str = "Not found",
) -> _T:
    obj = (await db.execute(select(model).filter(model.id == obj_id))).scalars().first()
    if not obj:
        raise HTTPException(status_code=404, detail=detail)
    return obj


def parse_email_list(raw: str | None) -> list[str]:
    """Parse une chaîne d'emails séparés par virgules en liste nettoyée.

    Retourne une liste vide si raw est None ou ne contient que des espaces.
    """
    if not raw:
        return []
    return [e.strip() for e in raw.split(",") if e.strip()]


def identity_keys(rec) -> list:
    """Clés d'identité d'un média (pour rapprocher demande ↔ élément de bibliothèque).

    Ordre de priorité au moment du rapprochement : GUID Plex, puis IDs externes
    (TMDB/TVDB/IMDB), puis titre+année+type en dernier recours. Partagé entre la vue
    Bibliothèque (rapprochement à l'affichage) et le scheduler (lien persistant
    MediaRequest.library_item_id) pour ne pas dupliquer cette logique à deux endroits.
    """
    keys: list[tuple] = []
    if getattr(rec, "plex_guid", None):
        keys.append(("guid", rec.plex_guid))
    if getattr(rec, "tmdb_id", None):
        keys.append(("tmdb", rec.tmdb_id))
    if getattr(rec, "tvdb_id", None):
        keys.append(("tvdb", rec.tvdb_id))
    if getattr(rec, "imdb_id", None):
        keys.append(("imdb", rec.imdb_id))
    keys.append(("title", (rec.title or "").lower().strip(), rec.year, rec.media_type))
    return keys


def now_utc() -> datetime:
    """Instant courant, aware UTC."""
    from datetime import timezone

    return datetime.now(timezone.utc)


def now_utc_naive() -> datetime:
    """Instant courant UTC sans tzinfo (colonnes DB stockées en naïf-UTC)."""
    from datetime import timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)


# Fuseau implicite de toute l'app : aucun réglage de fuseau n'est exposé côté Settings
# (les heures saisies dans l'UI, ex. "digest_hour", sont toujours une heure murale locale
# pour un unique utilisateur/foyer) — donc un seul fuseau assumé partout, plutôt qu'une
# fausse généralité qui comparerait ces heures locales à l'UTC brut sans jamais convertir.
APP_TIMEZONE = "Europe/Paris"


def local_hour() -> int:
    """Heure murale courante dans APP_TIMEZONE (gère automatiquement CET/CEST).

    À utiliser partout où une heure réglée par l'utilisateur (ex. digest_hour) doit être
    comparée à "maintenant" — comparer directement à now_utc().hour décale silencieusement
    l'horaire réel de 1h (CET) ou 2h (CEST) par rapport à ce que l'utilisateur a réglé.
    """
    from datetime import timezone
    from zoneinfo import ZoneInfo

    return datetime.now(timezone.utc).astimezone(ZoneInfo(APP_TIMEZONE)).hour


def local_minute() -> int:
    """Minute murale courante dans APP_TIMEZONE — pendant de local_hour() pour les
    réglages heure+minute (ex. digest_hour/digest_minute, plex_sync_hour/plex_sync_minute)."""
    from datetime import timezone
    from zoneinfo import ZoneInfo

    return datetime.now(timezone.utc).astimezone(ZoneInfo(APP_TIMEZONE)).minute


def wrap_image_proxy(url: str | None) -> str | None:
    """Wraps HTTP and/or local IP image URLs through /api/image-proxy to resolve Mixed Content issues in the browser."""
    if not url:
        return url

    # If it is an insecure HTTP url or uses a private IP subnet, route it via proxy
    has_local_ip = any(ip in url for ip in (".192.", ".168.", ".10.", ".127.", "192.168.", "10.0.", "127.0."))
    if url.startswith("http://") or (url.startswith("https://") and has_local_ip):
        import urllib.parse
        return f"/api/image-proxy?url={urllib.parse.quote_plus(url)}"

    return url
