"""Exploration analytique du catalogue Plex et snapshots persistants."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import AsyncSessionLocal
from ..models import LibraryAnalyticsSnapshot, PlaybackSession, Settings
from ..utils import now_utc_naive


def _int(value, default=0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _stream_language(stream: dict) -> str:
    return stream.get("language") or stream.get("languageCode") or "Inconnu"


def _subtitle_type(stream: dict) -> str:
    language = _stream_language(stream)
    codec = str(stream.get("codec") or stream.get("format") or "Inconnu").upper()
    forced = " · Forcé" if stream.get("forced") in (True, 1, "1", "true") else ""
    return f"{language} · {codec}{forced}"


def parse_plex_item(item: dict, library: str, section_type: str) -> dict[str, Any]:
    media = (_list(item.get("Media")) or [{}])[0]
    part = (_list(media.get("Part")) or [{}])[0]
    streams = _list(part.get("Stream"))
    audio = [stream for stream in streams if _int(stream.get("streamType")) == 2]
    subtitles = [stream for stream in streams if _int(stream.get("streamType")) == 3]
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
        "audio_languages": sorted({_stream_language(stream) for stream in audio}),
        "subtitle_languages": sorted({_stream_language(stream) for stream in subtitles}),
        "subtitle_types": sorted({_subtitle_type(stream) for stream in subtitles}),
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
                str(row.get(key) or "").lower()
                for key in ("title", "parent_title", "grandparent_title", "studio")
            ):
                continue
            subtitle = filters.get("subtitle")
            if subtitle == "with" and not row["subtitle_count"]:
                continue
            if subtitle == "without" and row["subtitle_count"]:
                continue
            if filters.get("subtitle_type") and filters["subtitle_type"] not in row.get("subtitle_types", []):
                continue
            if filters.get("subtitle_language") and filters["subtitle_language"] not in row.get("subtitle_languages", []):
                continue
            if filters.get("audio_language") and filters["audio_language"] not in row.get("audio_languages", []):
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


def _build_payload(rows: list[dict], generated_at: str, filters: dict[str, Any]) -> dict:
    all_rows = [dict(item) for item in rows]
    filtered = apply_filters(all_rows, filters)
    total_size = sum(row["size_bytes"] for row in filtered)
    total_duration = sum(row["duration_ms"] for row in filtered)
    oversized = sorted(filtered, key=lambda row: row["size_bytes"], reverse=True)[:5]
    return {
        "generated_at": generated_at,
        "summary": {
            "items": len(filtered),
            "size_bytes": total_size,
            "duration_ms": total_duration,
            "plays": sum(row["play_count"] for row in filtered),
            "viewers": len({viewer for row in filtered for viewer in row["viewers"]}),
        },
        "insights": [
            {"kind": "storage", "title": "Poids du catalogue filtré", "value": total_size, "unit": "bytes"},
            {"kind": "unwatched", "title": "Jamais visionnés", "value": sum(not row["play_count"] for row in filtered), "unit": "items"},
            {"kind": "subtitles", "title": "Sans sous-titres", "value": sum(not row["subtitle_count"] for row in filtered), "unit": "items"},
        ],
        "distributions": {
            "types": _distribution(filtered, "media_type"),
            "studios": _distribution(filtered, "studio"),
            "video_codecs": _distribution(filtered, "video_codec"),
            "audio_codecs": _distribution(filtered, "audio_codec"),
            "resolutions": _distribution(filtered, "video_resolution"),
            "containers": _distribution(filtered, "container"),
        },
        "largest": oversized,
        "options": {
            key: sorted({str(row.get(key)) for row in all_rows if row.get(key)})
            for key in ("library", "studio", "video_codec", "audio_codec", "container")
        } | {
            "audio_language": sorted({
                language for row in all_rows for language in row.get("audio_languages", []) if language
            }),
            "subtitle_language": sorted({
                language for row in all_rows for language in row.get("subtitle_languages", []) if language
            }),
            "subtitle_type": sorted({
                subtitle_type
                for row in all_rows
                for subtitle_type in row.get("subtitle_types", [])
                if subtitle_type
            })
        },
        "items": filtered,
    }


async def refresh_library_analytics_snapshot(settings: Settings, db: AsyncSession) -> dict:
    """Recalcule puis remplace le snapshot; l'ancien reste intact si le calcul échoue."""

    catalog = await fetch_plex_catalog(settings)
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
        row["watch_time_ms"] = sum(session.watched_ms or session.progress_ms or 0 for session in sessions)
        row["viewers"] = sorted({session.user_name for session in sessions if session.user_name})

    payload = _build_payload(rows, catalog["generated_at"], {})
    now = now_utc_naive()
    snapshot = await db.get(LibraryAnalyticsSnapshot, 1)
    if snapshot is None:
        snapshot = LibraryAnalyticsSnapshot(id=1, payload_json="{}", generated_at=now, updated_at=now)
        db.add(snapshot)
    snapshot.payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    snapshot.item_count = len(rows)
    snapshot.generated_at = datetime.fromisoformat(catalog["generated_at"])
    snapshot.updated_at = now
    await db.commit()
    return payload


async def refresh_library_analytics() -> dict:
    """Point d'entrée autonome utilisé par le worker ARQ."""

    async with AsyncSessionLocal() as db:
        settings = (await db.execute(select(Settings))).scalars().first()
        if settings is None:
            return {"items": 0, "status": "not_configured"}
        payload = await refresh_library_analytics_snapshot(settings, db)
        return {"items": payload["summary"]["items"], "generated_at": payload["generated_at"]}


async def analytics_payload(settings: Settings, db: AsyncSession, filters: dict[str, Any], refresh=False) -> dict:
    snapshot = None if refresh else await db.get(LibraryAnalyticsSnapshot, 1)
    if snapshot is None:
        payload = await refresh_library_analytics_snapshot(settings, db)
    else:
        try:
            payload = json.loads(snapshot.payload_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = await refresh_library_analytics_snapshot(settings, db)

    if not any(value is not None and value != "" for value in filters.values()):
        return payload
    return _build_payload(payload.get("items", []), payload["generated_at"], filters)


async def analytics_summary_payload(
    settings: Settings, db: AsyncSession, filters: dict[str, Any], refresh: bool = False
) -> dict:
    """Resume complet sans renvoyer les milliers de lignes du catalogue."""
    payload = await analytics_payload(settings, db, filters, refresh)
    return {key: value for key, value in payload.items() if key != "items"}


async def analytics_items_payload(
    settings: Settings,
    db: AsyncSession,
    filters: dict[str, Any],
    *,
    offset: int = 0,
    limit: int = 100,
    insight_kind: str | None = None,
    insight_field: str | None = None,
    insight_value: str | None = None,
) -> dict:
    snapshot = await db.get(LibraryAnalyticsSnapshot, 1)
    if snapshot is None:
        payload = await refresh_library_analytics_snapshot(settings, db)
    else:
        try:
            payload = json.loads(snapshot.payload_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = await refresh_library_analytics_snapshot(settings, db)
    rows = apply_filters(payload.get("items", []), filters)
    if insight_kind == "unwatched":
        rows = [row for row in rows if not row.get("play_count")]
    elif insight_kind == "subtitles":
        rows = [row for row in rows if not row.get("subtitle_count")]
    elif insight_kind == "distribution" and insight_field and insight_value is not None:
        allowed = {"media_type", "studio", "video_codec", "audio_codec", "video_resolution", "container"}
        if insight_field in allowed:
            rows = [row for row in rows if str(row.get(insight_field) or "Inconnu") == insight_value]
    if insight_kind in (None, "storage"):
        rows.sort(key=lambda row: row.get("size_bytes") or 0, reverse=True)
    total = len(rows)
    page = rows[offset:offset + limit]
    return {
        "items": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(page) < total,
        "generated_at": payload.get("generated_at"),
    }
