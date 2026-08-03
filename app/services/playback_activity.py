"""Collecte et normalisation de l'activité Plex, avec import historique Tautulli."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from datetime import time as datetime_time
from urllib.parse import parse_qs, quote, unquote, urlparse
from xml.etree import ElementTree

import httpx
from sqlalchemy import case, delete, func, or_
from sqlalchemy.future import select
from sqlalchemy.orm import load_only

from ..cache import cache
from ..database import AsyncSessionLocal
from ..models import PlaybackDailyAggregate, PlaybackSession, Settings
from ..realtime import publish
from ..utils import now_utc_naive, wrap_image_proxy
from .distributed_lock import acquire_distributed_lock, release_distributed_lock
from .ip_geolocation import lookup_ip_location, lookup_ip_locations

logger = logging.getLogger(__name__)
_plex_collection_lock = asyncio.Lock()
_PLEX_COLLECTION_LOCK_KEY = "plexarr:locks:playback-activity"

# Tolérance aux ratés de polling avant de clôturer une session encore ouverte (hoquet
# réseau/PMS, session momentanément absente de /status/sessions). Le websocket Plex
# (plex_activity_ws.py) reste le signal faisant autorité et ferme immédiatement une
# session sur un évènement "stopped" explicite -- ce compteur ne couvre que le filet de
# sécurité du polling. Volontairement en mémoire de process (pas de colonne dédiée) :
# une remise à zéro au redémarrage du worker n'a qu'un impact mineur (un cycle de
# tolérance perdu au pire).
_MISS_THRESHOLD = 2
_miss_counts: dict[int, int] = {}
_GEO_FIELDS = (
    "geo_status",
    "geo_city",
    "geo_region",
    "geo_country",
    "geo_country_code",
    "geo_lat",
    "geo_lon",
)


def _has_preserved_location(row: PlaybackSession) -> bool:
    return row.geo_status in {"resolved", "local", "anonymized"} or any(
        getattr(row, field) is not None for field in _GEO_FIELDS[1:]
    )


def _row_location(row: PlaybackSession) -> dict:
    return {field: getattr(row, field) for field in _GEO_FIELDS}


def _percent(value: int | float, total: int | float) -> float:
    return round(value / total * 100, 1) if total else 0


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return int(ordered[index])


def _media_label(row: PlaybackSession) -> str:
    return row.grandparent_title or row.title


def _transcode_reason(row: PlaybackSession) -> str:
    if str(row.subtitle_decision or "").lower() in {"burn", "transcode"}:
        return "Sous-titres"
    if str(row.video_decision or "").lower() == "transcode":
        return "Vidéo / résolution"
    if str(row.audio_decision or "").lower() == "transcode":
        return "Audio"
    if row.container:
        return "Conteneur"
    return "Non déterminée"


def _analytics(rows: list[PlaybackSession], previous_rows: list[PlaybackSession]) -> dict:
    total = len(rows)
    watch_ms = sum(row.watched_ms or 0 for row in rows)
    previous_total = len(previous_rows)
    previous_watch_ms = sum(row.watched_ms or 0 for row in previous_rows)

    heatmap = defaultdict(lambda: {"sessions": 0, "watch_ms": 0})
    for row in rows:
        if row.started_at:
            key = (row.started_at.weekday(), row.started_at.hour)
            heatmap[key]["sessions"] += 1
            heatmap[key]["watch_ms"] += row.watched_ms or 0

    events: list[tuple[datetime, int]] = []
    concurrent_daily: dict[str, int] = defaultdict(int)
    for row in rows:
        if not row.started_at:
            continue
        end = row.ended_at or row.last_seen_at or row.started_at
        if end < row.started_at:
            end = row.started_at
        events.extend(((row.started_at, 1), (end, -1)))
    current = peak = 0
    peak_at = None
    for moment, delta in sorted(events, key=lambda value: (value[0], -value[1])):
        current += delta
        if current > peak:
            peak, peak_at = current, moment
        day = moment.date().isoformat()
        concurrent_daily[day] = max(concurrent_daily[day], current)

    completion_groups: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for row in rows:
        progress = row.progress_percent
        if progress is None and row.duration_ms:
            progress = min(100, (row.progress_ms or row.watched_ms or 0) / row.duration_ms * 100)
        if progress is not None:
            completed = row.watched_status == 1 if row.watched_status is not None else progress >= 85
            completion_groups[row.media_type or "other"].append((progress, completed))
    completion = []
    for media_type, values in completion_groups.items():
        completed = sum(is_completed for _, is_completed in values)
        completion.append(
            {
                "media_type": media_type,
                "sessions": len(values),
                "completed": completed,
                "completion_rate": _percent(completed, len(values)),
                "average_progress": round(sum(value for value, _ in values) / len(values), 1),
            }
        )

    media_groups: dict[tuple[str, str], dict] = {}
    for row in rows:
        label = _media_label(row)
        key = (row.media_type or "other", label)
        item = media_groups.setdefault(
            key,
            {
                "title": label,
                "media_type": "show" if row.grandparent_title else row.media_type,
                "sessions": 0,
                "watch_ms": 0,
                "users": set(),
                "thumb_url": _thumb_url(row),
                "rating_key": row.rating_key,
                "size_bytes": 0,
                "completed": 0,
                "abandoned": 0,
                "resumed": 0,
                "rewatches": 0,
            },
        )
        item["sessions"] += 1
        item["watch_ms"] += row.watched_ms or 0
        if row.user_name:
            item["users"].add(row.user_name)
        item["size_bytes"] = max(item["size_bytes"], row.media_size_bytes or 0)
        progress = row.progress_percent
        if progress is None and row.duration_ms:
            progress = min(100, (row.progress_ms or row.watched_ms or 0) / row.duration_ms * 100)
        completed = row.watched_status == 1 if row.watched_status is not None else (progress or 0) >= 85
        item["completed"] += int(completed)
        item["abandoned"] += int(not completed and (progress or 0) < 21.25)
        item["resumed"] += int((row.group_count or 1) > 1)

    repeat_counts = Counter(
        (row.user_name, row.rating_key)
        for row in rows
        if row.user_name and row.rating_key
    )
    for row in rows:
        key = (row.media_type or "other", _media_label(row))
        if row.user_name and row.rating_key and repeat_counts[(row.user_name, row.rating_key)] > 1:
            media_groups[key]["rewatches"] += 1
            repeat_counts[(row.user_name, row.rating_key)] -= 1

    ranked_media = list(media_groups.values())
    for item in ranked_media:
        item["users"] = len(item["users"])
        item["completion_rate"] = _percent(item["completed"], item["sessions"])
        size_gb = item["size_bytes"] / (1024**3)
        item["watch_hours_per_gb"] = round(item["watch_ms"] / 3_600_000 / size_gb, 2) if size_gb else None
    popular = sorted(ranked_media, key=lambda item: item["watch_ms"], reverse=True)[:10]
    popular_by_audience = sorted(
        ranked_media, key=lambda item: (item["users"], item["sessions"], item["watch_ms"]), reverse=True
    )[:10]

    method_counts = Counter(row.playback_method or "unknown" for row in rows)
    codec_counts = Counter((row.video_codec or "Inconnu").upper() for row in rows)
    resolution_counts = Counter(row.quality or "Inconnue" for row in rows)
    device_groups: dict[str, dict] = {}
    for row in rows:
        device = row.player_title or row.product or row.platform or "Inconnu"
        item = device_groups.setdefault(device, {"device": device, "sessions": 0, "direct": 0, "transcodes": 0})
        item["sessions"] += 1
        if row.playback_method == "transcode":
            item["transcodes"] += 1
        elif row.playback_method in {"direct_play", "direct_stream"}:
            item["direct"] += 1
    devices = sorted(device_groups.values(), key=lambda item: item["sessions"], reverse=True)[:10]
    for item in devices:
        item["compatibility_score"] = round(item["direct"] / item["sessions"] * 100) if item["sessions"] else 0

    bandwidth_values = [row.bandwidth_kbps for row in rows if row.bandwidth_kbps]
    bandwidth_by_user: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        if row.bandwidth_kbps:
            bandwidth_by_user[row.user_name or "Inconnu"].append(row.bandwidth_kbps)

    transcode_reasons = Counter(_transcode_reason(row) for row in rows if row.playback_method == "transcode")

    episode_rows = sorted(
        (row for row in rows if row.media_type == "episode" and row.user_name and row.grandparent_title),
        key=lambda row: (row.user_name or "", row.grandparent_title or "", row.started_at or datetime.min),
    )
    binges = []
    chain: list[PlaybackSession] = []
    for row in episode_rows:
        previous = chain[-1] if chain else None
        same_chain = (
            previous
            and previous.user_name == row.user_name
            and previous.grandparent_title == row.grandparent_title
            and row.started_at
            and (previous.ended_at or previous.last_seen_at or previous.started_at)
            and row.started_at - (previous.ended_at or previous.last_seen_at or previous.started_at) <= timedelta(hours=2)
        )
        if not same_chain:
            if len(chain) >= 3:
                binges.append(chain)
            chain = [row]
        else:
            chain.append(row)
    if len(chain) >= 3:
        binges.append(chain)
    binge_items = [
        {
            "user_name": chain[0].user_name,
            "title": chain[0].grandparent_title,
            "episodes": len(chain),
            "watch_ms": sum(row.watched_ms or 0 for row in chain),
            "started_at": chain[0].started_at.isoformat() if chain[0].started_at else None,
        }
        for chain in sorted(binges, key=lambda value: sum(row.watched_ms or 0 for row in value), reverse=True)[:10]
    ]

    previous_users = defaultdict(lambda: {"sessions": 0, "watch_ms": 0})
    for row in previous_rows:
        if row.user_name:
            previous_users[row.user_name]["sessions"] += 1
            previous_users[row.user_name]["watch_ms"] += row.watched_ms or 0
    user_groups: dict[str, dict] = {}
    for row in rows:
        if not row.user_name:
            continue
        item = user_groups.setdefault(
            row.user_name,
            {"name": row.user_name, "sessions": 0, "watch_ms": 0, "titles": Counter(), "devices": Counter(), "last_seen_at": None},
        )
        item["sessions"] += 1
        item["watch_ms"] += row.watched_ms or 0
        item["titles"][_media_label(row)] += 1
        item["devices"][row.player_title or row.product or row.platform or "Inconnu"] += 1
        seen = row.last_seen_at or row.ended_at or row.started_at
        if seen and (item["last_seen_at"] is None or seen > item["last_seen_at"]):
            item["last_seen_at"] = seen
    user_trends = []
    for item in user_groups.values():
        previous = previous_users[item["name"]]
        user_trends.append(
            {
                "name": item["name"],
                "sessions": item["sessions"],
                "watch_ms": item["watch_ms"],
                "watch_change": _percent(item["watch_ms"] - previous["watch_ms"], previous["watch_ms"]) if previous["watch_ms"] else (100 if item["watch_ms"] else 0),
                "favorite_title": item["titles"].most_common(1)[0][0] if item["titles"] else None,
                "favorite_device": item["devices"].most_common(1)[0][0] if item["devices"] else None,
                "last_seen_at": item["last_seen_at"].isoformat() if item["last_seen_at"] else None,
            }
        )
    user_trends.sort(key=lambda item: item["watch_ms"], reverse=True)

    known_storage = {}
    for row in rows:
        if row.rating_key and row.media_size_bytes:
            known_storage[row.rating_key] = max(known_storage.get(row.rating_key, 0), row.media_size_bytes)
    storage_bytes = sum(known_storage.values())

    return {
        "comparison": {
            "sessions_change": _percent(total - previous_total, previous_total) if previous_total else (100 if total else 0),
            "watch_change": _percent(watch_ms - previous_watch_ms, previous_watch_ms) if previous_watch_ms else (100 if watch_ms else 0),
        },
        "heatmap": [
            {"weekday": weekday, "hour": hour, **heatmap[(weekday, hour)]}
            for weekday in range(7)
            for hour in range(24)
        ],
        "concurrency": {
            "peak": peak,
            "peak_at": peak_at.isoformat() if peak_at else None,
            "daily": [{"date": day, "peak": value} for day, value in sorted(concurrent_daily.items())],
        },
        "completion": completion,
        "popular": popular,
        "popular_by_audience": popular_by_audience,
        "engagement": {
            "completed": sum(item["completed"] for item in ranked_media),
            "abandoned": sum(item["abandoned"] for item in ranked_media),
            "resumed": sum(item["resumed"] for item in ranked_media),
            "rewatches": sum(item["rewatches"] for item in ranked_media),
        },
        "quality": {
            "methods": [{"key": key, "count": count, "rate": _percent(count, total)} for key, count in method_counts.most_common()],
            "codecs": [{"label": key, "count": count} for key, count in codec_counts.most_common(8)],
            "resolutions": [{"label": key, "count": count} for key, count in resolution_counts.most_common(8)],
            "devices": devices,
            "transcode_reasons": [{"label": key, "count": count} for key, count in transcode_reasons.most_common()],
        },
        "bandwidth": {
            "average_kbps": round(sum(bandwidth_values) / len(bandwidth_values)) if bandwidth_values else 0,
            "peak_kbps": max(bandwidth_values, default=0),
            "p95_kbps": _percentile(bandwidth_values, 0.95),
            "by_user": [
                {"name": name, "average_kbps": round(sum(values) / len(values)), "peak_kbps": max(values)}
                for name, values in sorted(bandwidth_by_user.items(), key=lambda item: sum(item[1]), reverse=True)[:10]
            ],
        },
        "binges": binge_items,
        "users": user_trends[:20],
        "storage": {
            "known_items": len(known_storage),
            "known_bytes": storage_bytes,
            "watch_hours_per_gb": round(watch_ms / 3_600_000 / (storage_bytes / (1024**3)), 2) if storage_bytes else None,
        },
    }


def _int(value, default=None):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _dt_from_epoch(value) -> datetime | None:
    timestamp = _int(value)
    if not timestamp:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)


def _masked_ip(value: str | None, anonymize: bool) -> str | None:
    if not value or not anonymize:
        return value
    if ":" in value:
        return ":".join(value.split(":")[:4]) + "::"
    parts = value.split(".")
    return ".".join(parts[:3] + ["0"]) if len(parts) == 4 else None


def _decision(value: str | None) -> str:
    return str(value or "").strip().lower().replace("-", " ").replace("_", " ")


def _playback_method(
    video_decision: str | None,
    audio_decision: str | None,
    transcode_decision: str | None = None,
) -> str:
    aggregate = _decision(transcode_decision)
    if aggregate in {"transcode", "transcoded"}:
        return "transcode"
    if aggregate in {"copy", "direct stream", "directstream"}:
        return "direct_stream"
    if aggregate in {"direct play", "directplay"}:
        return "direct_play"

    decisions = {_decision(video_decision), _decision(audio_decision)}
    if "transcode" in decisions:
        return "transcode"
    if decisions & {"copy", "direct stream", "directstream"}:
        return "direct_stream"
    if decisions & {"direct play", "directplay"}:
        return "direct_play"
    return "unknown"


def _tautulli_values(item: dict) -> dict:
    """Normalise les champs réellement renvoyés par get_history."""
    play_seconds = max(0, _int(item.get("play_duration"), 0))
    percent_complete = max(0.0, min(100.0, float(item.get("percent_complete") or 0)))
    watched_status = max(0.0, min(1.0, float(item.get("watched_status") or 0)))
    video_decision = item.get("video_decision")
    audio_decision = item.get("audio_decision")
    return {
        "video_decision": video_decision,
        "audio_decision": audio_decision,
        "playback_method": _playback_method(
            video_decision,
            audio_decision,
            item.get("transcode_decision"),
        ),
        # get_history expose `duration` comme alias historique de play_duration :
        # ce n'est jamais la durée du média.
        "duration_ms": None,
        "watched_ms": play_seconds * 1000,
        "progress_ms": None,
        "progress_percent": percent_complete,
        "watched_status": watched_status,
        "group_count": max(1, _int(item.get("group_count"), 1)),
        "source_group_ids": str(item.get("group_ids") or "") or None,
    }


def _plex_thumb_path(row: PlaybackSession) -> str | None:
    """Retrouve un chemin Plex exploitable, y compris pour les anciens imports Tautulli."""
    thumb_url = row.thumb_url or ""
    if thumb_url.startswith("/library/metadata/"):
        return thumb_url
    if thumb_url.startswith("/pms_image_proxy"):
        proxied = unquote((parse_qs(urlparse(thumb_url).query).get("img") or [""])[0])
        proxied_path = urlparse(proxied).path
        if proxied_path.startswith("/library/metadata/"):
            return proxied_path
    if row.rating_key:
        return f"/library/metadata/{quote(str(row.rating_key), safe='')}/thumb"
    return None


def _serialize(row: PlaybackSession) -> dict:
    thumb_url = _thumb_url(row)
    return {
        "id": row.id,
        "source": row.source,
        "session_id": row.source_session_id,
        "user_name": row.user_name,
        "media_type": row.media_type,
        "title": row.title,
        "grandparent_title": row.grandparent_title,
        "parent_title": row.parent_title,
        "year": row.year,
        "rating_key": row.rating_key,
        "library": row.library_section_title,
        "thumb_url": thumb_url,
        "player": row.player_title,
        "platform": row.platform,
        "product": row.product,
        "address": row.player_address,
        "state": row.state,
        "playback_method": row.playback_method,
        "video_decision": row.video_decision,
        "audio_decision": row.audio_decision,
        "quality": row.quality,
        "video_codec": row.video_codec,
        "audio_codec": row.audio_codec,
        "container": row.container,
        "subtitle_decision": row.subtitle_decision,
        "location": row.stream_location,
        "geo_status": row.geo_status,
        "geo_city": row.geo_city,
        "geo_region": row.geo_region,
        "geo_country": row.geo_country,
        "geo_country_code": row.geo_country_code,
        "geo_lat": row.geo_lat,
        "geo_lon": row.geo_lon,
        "bandwidth_kbps": row.bandwidth_kbps,
        "media_size_bytes": row.media_size_bytes,
        "progress_ms": row.progress_ms,
        "duration_ms": row.duration_ms,
        "watched_ms": row.watched_ms,
        "progress": (
            round(row.progress_percent, 1)
            if row.progress_percent is not None
            else round((row.progress_ms or 0) / row.duration_ms * 100, 1)
            if row.duration_ms
            else 0
        ),
        "progress_percent": row.progress_percent,
        "watched_status": row.watched_status,
        "group_count": row.group_count or 1,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "media_request_id": row.media_request_id,
    }


def _tautulli_row_id(item: dict) -> str:
    """Return the identifier of one history row, not its grouped reference."""
    return str(item.get("row_id") or item.get("id") or item.get("reference_id") or "")


def _tautulli_session_values(item: dict, settings: Settings, location: dict) -> dict:
    values = _tautulli_values(item)
    started = _dt_from_epoch(item.get("started")) or now_utc_naive()
    stopped = _dt_from_epoch(item.get("stopped"))
    return {
        "user_name": item.get("friendly_name") or item.get("user"),
        "media_type": item.get("media_type"),
        "title": item.get("title") or "Lecture Plex",
        "grandparent_title": item.get("grandparent_title"),
        "parent_title": item.get("parent_title"),
        "year": _int(item.get("year")),
        "rating_key": str(item.get("rating_key") or "") or None,
        "library_section_title": item.get("section_name"),
        "thumb_url": item.get("thumb"),
        "player_title": item.get("player"),
        "platform": item.get("platform"),
        "product": item.get("product"),
        "player_address": _masked_ip(
            item.get("ip_address"), settings.activity_anonymize_ips
        ),
        "state": "stopped",
        "quality": item.get("quality_profile") or item.get("video_resolution"),
        "video_codec": item.get("video_codec"),
        "audio_codec": item.get("audio_codec"),
        "container": item.get("container"),
        "subtitle_decision": item.get("subtitle_decision"),
        "stream_location": item.get("location"),
        "bandwidth_kbps": _int(item.get("bandwidth")),
        "media_size_bytes": _int(item.get("file_size") or item.get("media_size")),
        "started_at": started,
        "last_seen_at": stopped or started,
        "ended_at": stopped or started + timedelta(milliseconds=values["watched_ms"]),
        **values,
        **location,
    }


def _thumb_url(row: PlaybackSession) -> str | None:
    plex_thumb_path = _plex_thumb_path(row)
    if plex_thumb_path:
        return f"/api/playback/thumb?path={quote(plex_thumb_path, safe='')}"
    return wrap_image_proxy(row.thumb_url)


def parse_plex_sessions(xml: str, *, anonymize_ips: bool = True) -> list[dict]:
    root = ElementTree.fromstring(xml)
    sessions: list[dict] = []
    for media in root:
        if media.tag not in {"Video", "Track", "Photo"}:
            continue
        user = media.find("User")
        player = media.find("Player")
        session = media.find("Session")
        transcode = media.find("TranscodeSession")
        media_info = media.find("Media")
        part = media_info.find("Part") if media_info is not None else None
        user_attrs = user.attrib if user is not None else {}
        player_attrs = player.attrib if player is not None else {}
        session_attrs = session.attrib if session is not None else {}
        transcode_attrs = transcode.attrib if transcode is not None else {}
        media_attrs = media_info.attrib if media_info is not None else {}
        part_attrs = part.attrib if part is not None else {}
        subtitle_stream = next(
            (
                stream
                for stream in (part.findall("Stream") if part is not None else [])
                if stream.get("streamType") == "3" and stream.get("selected") == "1"
            ),
            None,
        )
        session_id = (
            session_attrs.get("id")
            or transcode_attrs.get("key")
            or player_attrs.get("machineIdentifier")
        )
        if not session_id:
            seed = "|".join(
                [media.get("ratingKey", ""), user_attrs.get("title", ""), player_attrs.get("title", "")]
            )
            session_id = hashlib.sha1(seed.encode()).hexdigest()
        decision_attrs = transcode_attrs or media_attrs
        video_decision = decision_attrs.get("videoDecision")
        audio_decision = decision_attrs.get("audioDecision")
        sessions.append(
            {
                "source_session_id": session_id,
                # Identifiant entier Plex (distinct du Session/@id ci-dessus), utilisé
                # pour corréler avec les évènements du websocket Plex, qui n'exposent
                # que ce sessionKey -- voir plex_activity_ws.py.
                "session_key": _int(media.get("sessionKey")),
                "user_name": user_attrs.get("title"),
                "plex_user_id": user_attrs.get("id"),
                "media_type": media.get("type"),
                "title": media.get("title") or "Lecture Plex",
                "grandparent_title": media.get("grandparentTitle"),
                "parent_title": media.get("parentTitle"),
                "year": _int(media.get("year")),
                "rating_key": media.get("ratingKey"),
                "library_section_title": media.get("librarySectionTitle"),
                "thumb_url": media.get("thumb") or media.get("grandparentThumb"),
                "player_title": player_attrs.get("title"),
                "platform": player_attrs.get("platform"),
                "product": player_attrs.get("product"),
                "player_address": _masked_ip(player_attrs.get("address"), anonymize_ips),
                "state": player_attrs.get("state") or "playing",
                "video_decision": video_decision,
                "audio_decision": audio_decision,
                "playback_method": _playback_method(video_decision, audio_decision),
                "quality": media_attrs.get("videoResolution") or media.get("videoResolution"),
                "video_codec": media_attrs.get("videoCodec") or media.get("videoCodec"),
                "audio_codec": media_attrs.get("audioCodec") or media.get("audioCodec"),
                "container": media_attrs.get("container") or part_attrs.get("container"),
                "subtitle_decision": (
                    subtitle_stream.get("decision") if subtitle_stream is not None else None
                ),
                "stream_location": session_attrs.get("location"),
                "bandwidth_kbps": _int(session_attrs.get("bandwidth") or transcode_attrs.get("bandwidth")),
                "media_size_bytes": _int(part_attrs.get("size")),
                "progress_ms": _int(media.get("viewOffset"), 0),
                "duration_ms": _int(media.get("duration")),
                "progress_percent": (
                    round(_int(media.get("viewOffset"), 0) / _int(media.get("duration")) * 100, 1)
                    if _int(media.get("duration"))
                    else None
                ),
            }
        )
    return sessions


def _deduplicate_plex_sessions(snapshots: list[dict]) -> list[dict]:
    """Une seule photographie par identifiant Plex, la plus récente gagnant."""
    return list({
        item["source_session_id"]: item
        for item in snapshots
    }.values())


async def _collect_plex_activity_unlocked() -> dict:
    async with AsyncSessionLocal() as db:
        settings = (await db.execute(select(Settings))).scalars().first()
        if not settings or not settings.live_activity_enabled or not settings.plex_url or not settings.plex_token:
            return {"status": "disabled", "active": 0}
        headers = {"X-Plex-Token": settings.plex_token, "Accept": "application/xml"}
        async with httpx.AsyncClient(timeout=10, verify=settings.plex_verify_ssl) as client:
            response = await client.get(f"{settings.plex_url.rstrip('/')}/status/sessions", headers=headers)
            response.raise_for_status()
        snapshots = parse_plex_sessions(response.text, anonymize_ips=settings.activity_anonymize_ips)
        # Plex peut exposer deux nœuds pour une même lecture (notamment pendant une
        # transition de lecteur/transcodage). Sans déduplication, la boucle ajoutait
        # deux objets ORM portant la même clé unique avant le premier flush.
        snapshots = _deduplicate_plex_sessions(snapshots)
        locations = await lookup_ip_locations(
            {snapshot.get("player_address") for snapshot in snapshots},
            db=db,
            anonymized=settings.activity_anonymize_ips,
        )
        for snapshot in snapshots:
            address = str(snapshot.get("player_address") or "").strip()
            snapshot.update(
                locations.get(address)
                or await lookup_ip_location(None, anonymized=settings.activity_anonymize_ips)
            )
        now = now_utc_naive()
        active_ids = {item["source_session_id"] for item in snapshots}
        rows = (
            await db.execute(
                select(PlaybackSession).filter(
                    PlaybackSession.source == "plex",
                    or_(
                        PlaybackSession.ended_at.is_(None),
                        PlaybackSession.source_session_id.in_(active_ids),
                    ),
                )
            )
        ).scalars().all()
        existing = {row.source_session_id: row for row in rows}
        # Repli de corrélation : le Session/@id ou TranscodeSession/@key qui compose
        # source_session_id peut changer en cours de lecture (relance de transcodage,
        # changement de bitrate). session_key + rating_key identifient la même lecture
        # de façon plus stable et permettent d'"adopter" la ligne existante au lieu de
        # la fragmenter en plusieurs sessions.
        existing_by_key = {
            (row.session_key, row.rating_key): row
            for row in rows
            if row.session_key is not None and row.rating_key is not None
        }
        previously_active = [row for row in rows if row.ended_at is None]
        started_rows: list[PlaybackSession] = []
        for snapshot in snapshots:
            row = existing.get(snapshot["source_session_id"])
            if row is None and snapshot.get("session_key") is not None and snapshot.get("rating_key"):
                row = existing_by_key.get((snapshot["session_key"], snapshot["rating_key"]))
            if row is None:
                row = PlaybackSession(
                    source="plex",
                    started_at=now,
                    last_seen_at=now,
                    title=snapshot["title"],
                    source_session_id=snapshot["source_session_id"],
                )
                db.add(row)
                started_rows.append(row)
                existing[row.source_session_id] = row
            if _has_preserved_location(row):
                # Le lieu appartient à la session historique : une résolution plus
                # récente de la même IP ne doit jamais réécrire cette valeur.
                for key in _GEO_FIELDS:
                    snapshot.pop(key, None)
            previous_progress = row.progress_ms or snapshot["progress_ms"] or 0
            for key, value in snapshot.items():
                setattr(row, key, value)
            row.last_seen_at = now
            row.ended_at = None
            row.watched_ms = max(row.watched_ms or 0, snapshot["progress_ms"] or 0, previous_progress)
            row.watched_status = 1 if (row.progress_percent or 0) >= 85 else 0
        for row in previously_active:
            if row.last_seen_at == now:
                # Mise à jour ce cycle (correspondance directe ou adoptée via
                # session_key+rating_key) : plus manquante, on oublie ses ratés passés.
                _miss_counts.pop(row.id, None)
                continue
            misses = _miss_counts.get(row.id, 0) + 1
            if misses < _MISS_THRESHOLD:
                _miss_counts[row.id] = misses
                continue
            _miss_counts.pop(row.id, None)
            row.ended_at = now
            row.state = "stopped"
            row.watched_ms = max(row.watched_ms or 0, row.progress_ms or 0)
        if settings.activity_retention_days:
            cutoff = now - timedelta(days=settings.activity_retention_days)
            await db.execute(delete(PlaybackSession).where(PlaybackSession.ended_at < cutoff))
        await db.commit()
        affected_days = {
            row.started_at.date() for row in [*rows, *started_rows] if row.started_at
        }
        await _rebuild_daily_aggregates(db, affected_days)
        if settings.activity_retention_days:
            await db.execute(
                delete(PlaybackDailyAggregate).where(PlaybackDailyAggregate.day < cutoff.date())
            )
            await db.commit()
        started = [_serialize(row) for row in started_rows]
    await publish(
        "activity.updated",
        {"active": len(snapshots), "started": started},
        admin_only=True,
    )
    return {"status": "complete", "active": len(snapshots)}


async def collect_plex_activity() -> dict:
    """Collecte sérialisée entre le worker ARQ et le rafraîchissement HTTP manuel."""
    async with _plex_collection_lock:
        token = await acquire_distributed_lock(_PLEX_COLLECTION_LOCK_KEY, ttl=30)
        if token is None:
            return {"status": "skipped", "reason": "already_running"}
        try:
            return await _collect_plex_activity_unlocked()
        finally:
            await release_distributed_lock(_PLEX_COLLECTION_LOCK_KEY, token)


async def handle_websocket_state(session_key: int, rating_key: str | None, state: str) -> dict:
    """Traite un évènement d'état poussé par le websocket Plex (plex_activity_ws.py).

    Signal faisant autorité : un "stopped" ferme la session immédiatement, sans
    attendre qu'elle disparaisse du polling. Une session inconnue (jamais vue par le
    polling) est ignorée ici -- c'est à l'appelant de déclencher un `collect_plex_activity`
    pour l'enrichir avec les métadonnées complètes (codec, bande passante...) absentes
    du message websocket.
    """
    now = now_utc_naive()
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(PlaybackSession).filter(
                    PlaybackSession.source == "plex",
                    PlaybackSession.ended_at.is_(None),
                    PlaybackSession.session_key == session_key,
                )
            )
        ).scalars().first()
        if row is None and rating_key:
            row = (
                await db.execute(
                    select(PlaybackSession).filter(
                        PlaybackSession.source == "plex",
                        PlaybackSession.ended_at.is_(None),
                        PlaybackSession.rating_key == rating_key,
                    )
                )
            ).scalars().first()
        if row is None:
            return {"status": "unknown"}
        if state == "stopped":
            row.ended_at = now
            row.state = "stopped"
            row.watched_ms = max(row.watched_ms or 0, row.progress_ms or 0)
            _miss_counts.pop(row.id, None)
        else:
            row.last_seen_at = now
            row.state = state
        await db.commit()
        if row.started_at:
            await _rebuild_daily_aggregates(db, {row.started_at.date()})
    await publish(
        "activity.updated",
        {"source": "websocket", "state": state, "session_key": session_key},
        admin_only=True,
    )
    return {"status": "handled", "state": state}


async def test_tautulli(url: str, api_key: str) -> tuple[bool, str]:
    if not url or not api_key:
        return False, "URL et clé API Tautulli requises."
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{url.rstrip('/')}/api/v2",
                params={"apikey": api_key, "cmd": "get_server_info"},
            )
            response.raise_for_status()
            payload = response.json().get("response", {})
            if payload.get("result") != "success":
                return False, payload.get("message") or "Réponse Tautulli invalide."
        return True, "Connexion Tautulli réussie."
    except Exception as exc:
        logger.warning("Test Tautulli impossible: %s", exc)
        return False, f"Connexion Tautulli impossible: {exc}"


async def _tautulli_locations(rows: list[dict], *, db, anonymized: bool) -> dict[str, dict]:
    """Resout une seule fois chaque IP distincte d'un lot Tautulli.

    Un historique de 10 000 lectures contient generalement peu d'adresses distinctes.
    La deduplication et la limite de concurrence evitent toutefois de lancer des milliers
    d'appels simultanes lors d'un gros import.
    """
    addresses = {
        str(item.get("ip_address") or "").strip()
        for item in rows
    }
    addresses.discard("")
    return await lookup_ip_locations(addresses, db=db, anonymized=anonymized)


async def import_tautulli_history(*, length: int = 1000) -> dict:
    async with AsyncSessionLocal() as db:
        settings = (await db.execute(select(Settings))).scalars().first()
        if not settings or not settings.tautulli_url or not settings.tautulli_api_key:
            raise ValueError("Tautulli n'est pas configuré.")
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(
                f"{settings.tautulli_url.rstrip('/')}/api/v2",
                params={
                    "apikey": settings.tautulli_api_key,
                    "cmd": "get_history",
                    "length": min(max(length, 1), 10000),
                    "order_column": "date",
                    "order_dir": "desc",
                    "grouping": 0,
                },
            )
            response.raise_for_status()
            payload = response.json().get("response", {})
        if payload.get("result") != "success":
            raise ValueError(payload.get("message") or "Import Tautulli refusé.")
        rows = payload.get("data", {}).get("data") or []
        locations = await _tautulli_locations(
            rows,
            db=db,
            anonymized=settings.activity_anonymize_ips,
        )
        imported = 0
        updated = 0
        imported_days: set[date] = set()
        existing_rows = (
            await db.execute(
                select(PlaybackSession).filter(PlaybackSession.source == "tautulli")
            )
        ).scalars().all()
        existing_by_reference = {row.source_session_id: row for row in existing_rows}
        for item in rows:
            reference = _tautulli_row_id(item)
            if not reference:
                continue
            raw_address = str(item.get("ip_address") or "").strip()
            location = locations.get(raw_address) or await lookup_ip_location(
                None,
                anonymized=settings.activity_anonymize_ips,
            )
            session_values = _tautulli_session_values(item, settings, location)
            session = existing_by_reference.get(reference)
            if session is not None and _has_preserved_location(session):
                for field in _GEO_FIELDS:
                    session_values.pop(field, None)
            if session is None:
                session = PlaybackSession(
                    source="tautulli",
                    source_session_id=reference,
                    **session_values,
                )
                db.add(session)
                existing_by_reference[reference] = session
                imported += 1
                imported_days.add(session_values["started_at"].date())
            elif any(getattr(session, key) != value for key, value in session_values.items()):
                for key, value in session_values.items():
                    setattr(session, key, value)
                updated += 1
                imported_days.add(session_values["started_at"].date())
        await db.commit()
        await _rebuild_daily_aggregates(db, imported_days)
    await publish(
        "activity.updated",
        {"imported": imported, "updated": updated, "source": "tautulli"},
        admin_only=True,
    )
    return {"imported": imported, "updated": updated, "received": len(rows)}


async def normalize_tautulli_history(*, length: int = 10000) -> dict:
    """Récupère à nouveau l'historique Tautulli et répare les lignes déjà importées."""
    async with AsyncSessionLocal() as db:
        settings = (await db.execute(select(Settings))).scalars().first()
        if not settings or not settings.tautulli_url or not settings.tautulli_api_key:
            raise ValueError("Tautulli n'est pas configuré.")
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(
                f"{settings.tautulli_url.rstrip('/')}/api/v2",
                params={
                    "apikey": settings.tautulli_api_key,
                    "cmd": "get_history",
                    "length": min(max(length, 1), 10000),
                    "order_column": "date",
                    "order_dir": "desc",
                    "grouping": 0,
                },
            )
            response.raise_for_status()
            payload = response.json().get("response", {})
        if payload.get("result") != "success":
            raise ValueError(payload.get("message") or "Normalisation Tautulli refusée.")

        rows = payload.get("data", {}).get("data") or []
        locations = await _tautulli_locations(
            rows,
            db=db,
            anonymized=settings.activity_anonymize_ips,
        )
        references = {
            _tautulli_row_id(item): item
            for item in rows
        }
        references.pop("", None)
        existing = (
            await db.execute(
                select(PlaybackSession).filter(
                    PlaybackSession.source == "tautulli",
                    PlaybackSession.source_session_id.in_(references),
                )
            )
        ).scalars().all() if references else []
        changed = 0
        changed_days: set[date] = set()
        for session in existing:
            item = references[session.source_session_id]
            values = _tautulli_values(item)
            updates = {
                **values,
                "quality": item.get("quality_profile") or item.get("video_resolution") or session.quality,
                "video_codec": item.get("video_codec") or session.video_codec,
                "audio_codec": item.get("audio_codec") or session.audio_codec,
                "container": item.get("container") or session.container,
                "subtitle_decision": item.get("subtitle_decision") or session.subtitle_decision,
                "bandwidth_kbps": _int(item.get("bandwidth")) or session.bandwidth_kbps,
            }
            raw_address = str(item.get("ip_address") or "").strip()
            if raw_address:
                updates["player_address"] = _masked_ip(
                    raw_address,
                    settings.activity_anonymize_ips,
                )
                if not _has_preserved_location(session):
                    updates.update(locations[raw_address])
            if any(getattr(session, key) != value for key, value in updates.items()):
                for key, value in updates.items():
                    setattr(session, key, value)
                if session.started_at:
                    changed_days.add(session.started_at.date())
                changed += 1
        await db.commit()
        await _rebuild_daily_aggregates(db, changed_days)
    await publish("activity.updated", {"normalized": changed, "source": "tautulli"}, admin_only=True)
    return {
        "normalized": changed,
        "matched": len(existing),
        "received": len(rows),
        "unmatched": max(0, len(references) - len(existing)),
    }


async def recalculate_playback_locations() -> dict:
    """Complète les lieux manquants sans modifier ceux déjà attachés aux sessions."""
    async with AsyncSessionLocal() as db:
        settings = (await db.execute(select(Settings))).scalars().first()
        rows = (
            await db.execute(
                select(PlaybackSession).filter(PlaybackSession.player_address.is_not(None))
            )
        ).scalars().all()
        addresses = {
            str(row.player_address).strip()
            for row in rows
            if str(row.player_address or "").strip()
        }
        seeds = {}
        for row in rows:
            address = str(row.player_address or "").strip()
            if address and row.geo_status in {"resolved", "local"}:
                seeds.setdefault(address, _row_location(row))

        anonymized = bool(settings and settings.activity_anonymize_ips)
        locations = await lookup_ip_locations(
            addresses,
            db=db,
            anonymized=anonymized,
            seed_locations=seeds,
        )
        updated = 0
        preserved = 0
        unresolved = 0
        for row in rows:
            if _has_preserved_location(row):
                preserved += 1
                continue
            location = locations.get(str(row.player_address or "").strip())
            if not location or location.get("geo_status") not in {"resolved", "local"}:
                unresolved += 1
                continue
            for field, value in location.items():
                setattr(row, field, value)
            updated += 1
        await db.commit()

    await publish(
        "activity.updated",
        {"locations_updated": updated, "source": "geoip"},
        admin_only=True,
    )
    return {
        "sessions": len(rows),
        "addresses": len(addresses),
        "updated": updated,
        "preserved": preserved,
        "unresolved": unresolved,
        "anonymized": anonymized,
    }


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


async def _rebuild_daily_aggregates(db, days: set[date]) -> None:
    """Reconstruit uniquement les jours affectés par une collecte ou un import."""
    if not days:
        return
    await db.execute(delete(PlaybackDailyAggregate).where(PlaybackDailyAggregate.day.in_(days)))
    rows = (
        await db.execute(_daily_aggregate_query(days))
    ).all()
    db.add_all([
        PlaybackDailyAggregate(
            day=_as_date(row[0]), user_name=row[1], media_type=row[2], media_label=row[3],
            playback_method=row[4], sessions=int(row[5] or 0), watch_ms=int(row[6] or 0),
            transcodes=int(row[7] or 0),
        )
        for row in rows
    ])
    await db.commit()


def _daily_aggregate_query(days: set[date]):
    """Construit l'agrégation avec les mêmes expressions dans SELECT et GROUP BY.

    PostgreSQL compare aussi les paramètres liés des expressions de regroupement. Si
    chaque ``coalesce`` est recréé dans ``group_by()``, SQLAlchemy génère deux séries de
    paramètres (par exemple ``$1`` et ``$9``) et PostgreSQL refuse la requête, même si
    leurs valeurs sont identiques.
    """
    day_expr = func.date(PlaybackSession.started_at)
    user_expr = func.coalesce(PlaybackSession.user_name, "")
    media_type_expr = func.coalesce(PlaybackSession.media_type, "")
    media_label_expr = func.coalesce(
        PlaybackSession.grandparent_title, PlaybackSession.title, ""
    )
    playback_method_expr = func.coalesce(PlaybackSession.playback_method, "unknown")
    dimensions = (
        day_expr,
        user_expr,
        media_type_expr,
        media_label_expr,
        playback_method_expr,
    )
    return (
        select(
            *dimensions,
            func.count(PlaybackSession.id),
            func.coalesce(func.sum(PlaybackSession.watched_ms), 0),
            func.sum(case((PlaybackSession.playback_method == "transcode", 1), else_=0)),
        )
        .filter(day_expr.in_(days))
        .group_by(*dimensions)
    )


async def _ensure_daily_aggregates(db, start_day: date, end_day: date) -> None:
    aggregate_count = (
        await db.execute(
            select(func.count(PlaybackDailyAggregate.id)).filter(
                PlaybackDailyAggregate.day >= start_day,
                PlaybackDailyAggregate.day <= end_day,
            )
        )
    ).scalar() or 0
    if aggregate_count:
        return
    session_days = (
        await db.execute(
            select(func.date(PlaybackSession.started_at))
            .filter(
                PlaybackSession.started_at >= datetime.combine(start_day, datetime_time.min),
                PlaybackSession.started_at < datetime.combine(end_day + timedelta(days=1), datetime_time.min),
            )
            .distinct()
        )
    ).scalars().all()
    await _rebuild_daily_aggregates(db, {_as_date(day) for day in session_days if day})


async def _aggregate_overview(db, cutoff: datetime, previous_cutoff: datetime) -> dict:
    start_day, cutoff_day = previous_cutoff.date(), cutoff.date()
    end_day = now_utc_naive().date()
    await _ensure_daily_aggregates(db, start_day, end_day)
    current_filter = (
        PlaybackDailyAggregate.day >= cutoff_day,
        PlaybackDailyAggregate.day <= end_day,
    )
    user_count = (
        await db.execute(
            select(func.count(func.distinct(PlaybackDailyAggregate.user_name))).filter(
                *current_filter, PlaybackDailyAggregate.user_name != ""
            )
        )
    ).scalar() or 0
    # Les totaux sessions/watch/transcodes doivent inclure les lectures dont le nom
    # utilisateur est absent ; seul COUNT(DISTINCT user_name) ignore la chaîne vide.
    global_totals = (
        await db.execute(
            select(
                func.coalesce(func.sum(PlaybackDailyAggregate.sessions), 0),
                func.coalesce(func.sum(PlaybackDailyAggregate.watch_ms), 0),
                func.coalesce(func.sum(PlaybackDailyAggregate.transcodes), 0),
            ).filter(*current_filter)
        )
    ).one()
    daily_rows = (
        await db.execute(
            select(
                PlaybackDailyAggregate.day,
                func.sum(PlaybackDailyAggregate.sessions),
                func.sum(PlaybackDailyAggregate.watch_ms),
            )
            .filter(*current_filter)
            .group_by(PlaybackDailyAggregate.day)
            .order_by(PlaybackDailyAggregate.day)
        )
    ).all()
    user_rows = (
        await db.execute(
            select(
                PlaybackDailyAggregate.user_name,
                func.sum(PlaybackDailyAggregate.sessions),
                func.sum(PlaybackDailyAggregate.watch_ms),
            )
            .filter(*current_filter, PlaybackDailyAggregate.user_name != "")
            .group_by(PlaybackDailyAggregate.user_name)
            .order_by(func.sum(PlaybackDailyAggregate.watch_ms).desc())
            .limit(10)
        )
    ).all()
    previous = (
        await db.execute(
            select(
                func.coalesce(func.sum(PlaybackDailyAggregate.sessions), 0),
                func.coalesce(func.sum(PlaybackDailyAggregate.watch_ms), 0),
            ).filter(
                PlaybackDailyAggregate.day >= start_day,
                PlaybackDailyAggregate.day < cutoff_day,
            )
        )
    ).one()
    total = int(global_totals[0] or 0)
    watch_ms = int(global_totals[1] or 0)
    transcodes = int(global_totals[2] or 0)
    return {
        "summary": {
            "sessions": total,
            "watch_ms": watch_ms,
            "users": int(user_count),
            "transcodes": transcodes,
            "transcode_rate": round(transcodes / total * 100, 1) if total else 0,
        },
        "daily": [
            {"date": row[0].isoformat(), "sessions": int(row[1] or 0), "watch_ms": int(row[2] or 0)}
            for row in daily_rows
        ],
        "users": [
            {"name": row[0], "sessions": int(row[1] or 0), "watch_ms": int(row[2] or 0)}
            for row in user_rows
        ],
        "comparison": {
            "sessions": int(previous[0] or 0),
            "watch_ms": int(previous[1] or 0),
        },
    }


async def activity_snapshot(days: int = 30, db=None) -> dict:
    days = min(max(days, 1), 3650)
    cutoff = datetime.combine((now_utc_naive() - timedelta(days=days)).date(), datetime_time.min)
    previous_cutoff = cutoff - timedelta(days=days)
    if db is None:
        async with AsyncSessionLocal() as owned_db:
            return await activity_snapshot(days, db=owned_db)
    active = (
        await db.execute(
            select(PlaybackSession)
            .filter(PlaybackSession.ended_at.is_(None))
            .order_by(PlaybackSession.started_at.desc())
        )
    ).scalars().all()
    history = (
        await db.execute(
            select(PlaybackSession)
            .filter(PlaybackSession.started_at >= cutoff)
            .order_by(PlaybackSession.started_at.desc())
            .limit(100)
        )
    ).scalars().all()
    analytics_rows = (
        await db.execute(
            select(PlaybackSession)
            .options(
                load_only(
                    PlaybackSession.id,
                    PlaybackSession.source,
                    PlaybackSession.user_name,
                    PlaybackSession.media_type,
                    PlaybackSession.title,
                    PlaybackSession.grandparent_title,
                    PlaybackSession.rating_key,
                    PlaybackSession.thumb_url,
                    PlaybackSession.player_title,
                    PlaybackSession.platform,
                    PlaybackSession.product,
                    PlaybackSession.playback_method,
                    PlaybackSession.video_decision,
                    PlaybackSession.audio_decision,
                    PlaybackSession.quality,
                    PlaybackSession.video_codec,
                    PlaybackSession.container,
                    PlaybackSession.subtitle_decision,
                    PlaybackSession.bandwidth_kbps,
                    PlaybackSession.media_size_bytes,
                    PlaybackSession.progress_ms,
                    PlaybackSession.duration_ms,
                    PlaybackSession.progress_percent,
                    PlaybackSession.watched_status,
                    PlaybackSession.group_count,
                    PlaybackSession.watched_ms,
                    PlaybackSession.started_at,
                    PlaybackSession.last_seen_at,
                    PlaybackSession.ended_at,
                )
            )
            .filter(PlaybackSession.started_at >= cutoff)
            .order_by(PlaybackSession.started_at)
        )
    ).scalars().all()
    previous_rows = (
        await db.execute(
            select(PlaybackSession)
            .options(
                load_only(
                    PlaybackSession.id,
                    PlaybackSession.user_name,
                    PlaybackSession.watched_ms,
                )
            )
            .filter(
                PlaybackSession.started_at >= previous_cutoff,
                PlaybackSession.started_at < cutoff,
            )
        )
    ).scalars().all()
    overview = await _aggregate_overview(db, cutoff, previous_cutoff)
    analytics = _analytics(list(analytics_rows), list(previous_rows))
    previous = overview.pop("comparison")
    current = overview["summary"]
    analytics["comparison"] = {
        "sessions_change": _percent(current["sessions"] - previous["sessions"], previous["sessions"])
        if previous["sessions"] else (100 if current["sessions"] else 0),
        "watch_change": _percent(current["watch_ms"] - previous["watch_ms"], previous["watch_ms"])
        if previous["watch_ms"] else (100 if current["watch_ms"] else 0),
    }
    return {
        "active": [_serialize(row) for row in active],
        "history": [_serialize(row) for row in history],
        **overview,
        "analytics": analytics,
    }


async def live_activity_snapshot(db=None) -> dict:
    """Retourne uniquement les sessions actives, pour le polling fréquent."""
    if db is None:
        async with AsyncSessionLocal() as owned_db:
            return await live_activity_snapshot(db=owned_db)
    settings = (await db.execute(select(Settings))).scalars().first()
    active = (
        await db.execute(
            select(PlaybackSession)
            .filter(PlaybackSession.ended_at.is_(None))
            .order_by(PlaybackSession.started_at.desc())
        )
    ).scalars().all()
    configured = bool(settings and settings.plex_url and settings.plex_token)
    return {
        "active": [_serialize(row) for row in active],
        "enabled": bool(settings and settings.live_activity_enabled and configured),
        "configured": configured,
    }


async def activity_statistics(days: int = 30, db=None, refresh: bool = False) -> dict:
    """Retourne l'historique et les agrégats, mis en cache séparément du direct."""
    days = min(max(days, 1), 3650)
    cache_key = f"plexarr:playback:statistics:{days}"
    async def _compute(session):
        snapshot = await activity_snapshot(days, db=session)
        snapshot.pop("active", None)
        return snapshot

    if refresh:
        if db is None:
            async with AsyncSessionLocal() as owned_db:
                snapshot = await _compute(owned_db)
        else:
            snapshot = await _compute(db)
        await cache.set_json(
            cache_key, {"value": snapshot, "cached_at": time.time()}, ttl_seconds=600
        )
        return snapshot

    async def _background():
        async with AsyncSessionLocal() as fresh_db:
            return await _compute(fresh_db)

    if db is None:
        async with AsyncSessionLocal() as owned_db:
            return await cache.get_or_refresh(
                cache_key, 60, 600, lambda: _compute(owned_db), _background
            )
    return await cache.get_or_refresh(cache_key, 60, 600, lambda: _compute(db), _background)
