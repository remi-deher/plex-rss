"""Exploration analytique du catalogue Plex et croisement avec l'historique."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..cache import cache
from ..models import PlaybackSession, Settings

CACHE_KEY = "plexarr:library-analytics:v1"


def _int(value, default=0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _stream_language(stream: dict) -> str:
    return stream.get("language") or stream.get("languageCode") or "Inconnu"


def parse_plex_item(item: dict, library: str, section_type: str) -> dict[str, Any]:
    media = (_list(item.get("Media")) or [{}])[0]
    part = (_list(media.get("Part")) or [{}])[0]
    streams = _list(part.get("Stream"))
    audio = [s for s in streams if _int(s.get("streamType")) == 2]
    subtitles = [s for s in streams if _int(s.get("streamType")) == 3]
    raw_type = item.get("type") or section_type
    media_type = {"movie": "movie", "episode": "episode", "track": "track"}.get(raw_type, raw_type)
    return {
        "rating_key": str(item.get("ratingKey") or ""),
        "title": item.get("title") or "Sans titre",
        "parent_title": item.get("parentTitle"),
        "grandparent_title": item.get("grandparentTitle"),
        "media_type": media_type,
        "library": library,
        "studio": item.get("studio") or "Inconnu",
        "year": _int(item.get("year")) or None,
        "added_at": datetime.fromtimestamp(_int(item.get("addedAt"))).isoformat() if _int(item.get("addedAt")) else None,
        "duration_ms": _int(item.get("duration") or media.get("duration")),
        "size_bytes": _int(part.get("size")),
        "container": part.get("container") or media.get("container") or "Inconnu",
        "video_codec": (media.get("videoCodec") or "Inconnu").upper(),
        "audio_codec": (media.get("audioCodec") or (audio[0].get("codec") if audio else None) or "Inconnu").upper(),
        "video_resolution": media.get("videoResolution") or "Inconnue",
        "audio_channels": media.get("audioChannels") or (audio[0].get("channels") if audio else None),
        "audio_languages": sorted({_stream_language(s) for s in audio}),
        "subtitle_languages": sorted({_stream_language(s) for s in subtitles}),
        "subtitle_count": len(subtitles),
        "audio_track_count": len(audio),
    }


async def fetch_plex_catalog(settings: Settings) -> dict[str, Any]:
    if not settings.plex_url or not settings.plex_token:
        return {"items": [], "generated_at": datetime.utcnow().isoformat(), "libraries": []}
    headers = {"X-Plex-Token": settings.plex_token, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=60, verify=settings.plex_verify_ssl) as client:
        sections_response = await client.get(f"{settings.plex_url.rstrip('/')}/library/sections", headers=headers)
        sections_response.raise_for_status()
        sections = _list(sections_response.json().get("MediaContainer", {}).get("Directory"))
        rows: list[dict[str, Any]] = []
        libraries = []
        for section in sections:
            section_type = section.get("type")
            plex_type = {"movie": 1, "show": 4, "artist": 10}.get(section_type)
            if not plex_type:
                continue
            name, key = section.get("title") or "Bibliothèque", section.get("key")
            libraries.append({"key": str(key), "name": name, "type": section_type})
            response = await client.get(
                f"{settings.plex_url.rstrip('/')}/library/sections/{key}/all",
                headers=headers,
                params={"type": plex_type, "includeMeta": 1},
            )
            response.raise_for_status()
            container = response.json().get("MediaContainer", {})
            items = _list(container.get("Metadata") or container.get("Video") or container.get("Track"))
            rows.extend(parse_plex_item(item, name, section_type) for item in items)
    return {"items": rows, "generated_at": datetime.utcnow().isoformat(), "libraries": libraries}


async def cached_catalog(settings: Settings, refresh: bool = False) -> dict[str, Any]:
    if refresh:
        await cache.delete(CACHE_KEY)
    return await cache.get_or_refresh(
        CACHE_KEY,
        soft_ttl_seconds=1800,
        hard_ttl_seconds=86400,
        compute_sync=lambda: fetch_plex_catalog(settings),
    )


def _distribution(rows: list[dict], key: str, limit=12) -> list[dict]:
    counts = Counter(str(row.get(key) or "Inconnu") for row in rows)
    total = sum(counts.values()) or 1
    return [
        {"label": label, "count": count, "percent": round(count / total * 100, 1)}
        for label, count in counts.most_common(limit)
    ]


def apply_filters(rows: list[dict], filters: dict[str, Any]) -> list[dict]:
    search = str(filters.get("search") or "").strip().lower()
    result = []
    for row in rows:
        if filters.get("media_type") and row["media_type"] != filters["media_type"]:
            continue
        for key in ("library", "studio", "video_codec", "audio_codec", "container"):
            if filters.get(key) and str(row.get(key)) != str(filters[key]):
                break
        else:
            if search and search not in " ".join(
                str(row.get(k) or "").lower() for k in ("title", "parent_title", "grandparent_title", "studio")
            ):
                continue
            subtitle = filters.get("subtitle")
            if subtitle == "with" and not row["subtitle_count"]:
                continue
            if subtitle == "without" and row["subtitle_count"]:
                continue
            watched = filters.get("watched")
            if watched == "yes" and not row.get("play_count"):
                continue
            if watched == "no" and row.get("play_count"):
                continue
            size_gb = row["size_bytes"] / 1024**3
            if filters.get("min_size_gb") is not None and size_gb < filters["min_size_gb"]:
                continue
            if filters.get("max_size_gb") is not None and size_gb > filters["max_size_gb"]:
                continue
            result.append(row)
    return result


async def analytics_payload(settings: Settings, db: AsyncSession, filters: dict[str, Any], refresh=False) -> dict:
    catalog = await cached_catalog(settings, refresh)
    rows = [dict(item) for item in catalog["items"]]
    history = (await db.execute(select(PlaybackSession))).scalars().all()
    by_key: dict[str, list[PlaybackSession]] = defaultdict(list)
    by_title: dict[str, list[PlaybackSession]] = defaultdict(list)
    for session in history:
        if session.rating_key:
            by_key[str(session.rating_key)].append(session)
        for title in (session.title, session.grandparent_title):
            if title:
                by_title[title.casefold()].append(session)
    for row in rows:
        sessions = by_key.get(row["rating_key"]) or by_title.get(
            str(row.get("grandparent_title") or row["title"]).casefold(), []
        )
        row["play_count"] = len(sessions)
        row["watch_time_ms"] = sum(s.watched_ms or s.progress_ms or 0 for s in sessions)
        row["viewers"] = sorted({s.user_name for s in sessions if s.user_name})

    filtered = apply_filters(rows, filters)
    total_size = sum(row["size_bytes"] for row in filtered)
    total_duration = sum(row["duration_ms"] for row in filtered)
    unwatched = sum(1 for row in filtered if not row["play_count"])
    oversized = sorted(filtered, key=lambda row: row["size_bytes"], reverse=True)[:5]
    insights = [
        {"kind": "storage", "title": "Poids du catalogue filtré", "value": total_size, "unit": "bytes"},
        {"kind": "unwatched", "title": "Jamais visionnés", "value": unwatched, "unit": "items"},
        {"kind": "subtitles", "title": "Sans sous-titres", "value": sum(not r["subtitle_count"] for r in filtered), "unit": "items"},
    ]
    options = {
        key: sorted({str(row.get(key)) for row in rows if row.get(key)})
        for key in ("library", "studio", "video_codec", "audio_codec", "container")
    }
    return {
        "generated_at": catalog["generated_at"],
        "summary": {
            "items": len(filtered),
            "size_bytes": total_size,
            "duration_ms": total_duration,
            "plays": sum(row["play_count"] for row in filtered),
            "viewers": len({viewer for row in filtered for viewer in row["viewers"]}),
        },
        "insights": insights,
        "distributions": {
            "types": _distribution(filtered, "media_type"),
            "studios": _distribution(filtered, "studio"),
            "video_codecs": _distribution(filtered, "video_codec"),
            "audio_codecs": _distribution(filtered, "audio_codec"),
            "resolutions": _distribution(filtered, "video_resolution"),
            "containers": _distribution(filtered, "container"),
        },
        "largest": oversized,
        "options": options,
        "items": filtered,
    }
