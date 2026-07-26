"""Collecte et normalisation de l'activité Plex, avec import historique Tautulli."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from xml.etree import ElementTree

import httpx
from sqlalchemy import case, delete, func
from sqlalchemy.future import select

from ..database import AsyncSessionLocal
from ..models import PlaybackSession, Settings
from ..realtime import publish
from ..utils import now_utc_naive, wrap_image_proxy

logger = logging.getLogger(__name__)


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


def _playback_method(video_decision: str | None, audio_decision: str | None) -> str:
    decisions = {str(video_decision or "").lower(), str(audio_decision or "").lower()}
    if "transcode" in decisions:
        return "transcode"
    if "copy" in decisions:
        return "direct_stream"
    return "direct_play"


def _serialize(row: PlaybackSession) -> dict:
    thumb_url = row.thumb_url
    if thumb_url and thumb_url.startswith("/"):
        thumb_url = f"/api/playback/thumb?path={quote(thumb_url, safe='')}"
    else:
        thumb_url = wrap_image_proxy(thumb_url)
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
        "bandwidth_kbps": row.bandwidth_kbps,
        "progress_ms": row.progress_ms,
        "duration_ms": row.duration_ms,
        "watched_ms": row.watched_ms,
        "progress": round((row.progress_ms or 0) / row.duration_ms * 100, 1) if row.duration_ms else 0,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "media_request_id": row.media_request_id,
    }


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
        user_attrs = user.attrib if user is not None else {}
        player_attrs = player.attrib if player is not None else {}
        session_attrs = session.attrib if session is not None else {}
        transcode_attrs = transcode.attrib if transcode is not None else {}
        media_attrs = media_info.attrib if media_info is not None else {}
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
                "bandwidth_kbps": _int(session_attrs.get("bandwidth") or transcode_attrs.get("bandwidth")),
                "progress_ms": _int(media.get("viewOffset"), 0),
                "duration_ms": _int(media.get("duration")),
            }
        )
    return sessions


async def collect_plex_activity() -> dict:
    async with AsyncSessionLocal() as db:
        settings = (await db.execute(select(Settings))).scalars().first()
        if not settings or not settings.live_activity_enabled or not settings.plex_url or not settings.plex_token:
            return {"status": "disabled", "active": 0}
        headers = {"X-Plex-Token": settings.plex_token, "Accept": "application/xml"}
        async with httpx.AsyncClient(timeout=10, verify=settings.plex_verify_ssl) as client:
            response = await client.get(f"{settings.plex_url.rstrip('/')}/status/sessions", headers=headers)
            response.raise_for_status()
        snapshots = parse_plex_sessions(response.text, anonymize_ips=settings.activity_anonymize_ips)
        now = now_utc_naive()
        active_ids = {item["source_session_id"] for item in snapshots}
        existing = {
            row.source_session_id: row
            for row in (
                await db.execute(
                    select(PlaybackSession).filter(
                        PlaybackSession.source == "plex",
                        PlaybackSession.ended_at.is_(None),
                    )
                )
            ).scalars()
        }
        for snapshot in snapshots:
            row = existing.get(snapshot["source_session_id"])
            if row is None:
                row = PlaybackSession(
                    source="plex",
                    started_at=now,
                    last_seen_at=now,
                    title=snapshot["title"],
                    source_session_id=snapshot["source_session_id"],
                )
                db.add(row)
            previous_progress = row.progress_ms or snapshot["progress_ms"] or 0
            for key, value in snapshot.items():
                setattr(row, key, value)
            row.last_seen_at = now
            row.ended_at = None
            row.watched_ms = max(row.watched_ms or 0, snapshot["progress_ms"] or 0, previous_progress)
        for session_id, row in existing.items():
            if session_id not in active_ids:
                row.ended_at = now
                row.state = "stopped"
                row.watched_ms = max(row.watched_ms or 0, row.progress_ms or 0)
        if settings.activity_retention_days:
            cutoff = now - timedelta(days=settings.activity_retention_days)
            await db.execute(delete(PlaybackSession).where(PlaybackSession.ended_at < cutoff))
        await db.commit()
    await publish("activity.updated", {"active": len(snapshots)}, admin_only=True)
    return {"status": "complete", "active": len(snapshots)}


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
                },
            )
            response.raise_for_status()
            payload = response.json().get("response", {})
        if payload.get("result") != "success":
            raise ValueError(payload.get("message") or "Import Tautulli refusé.")
        rows = payload.get("data", {}).get("data") or []
        imported = 0
        for item in rows:
            reference = str(item.get("reference_id") or item.get("row_id") or item.get("id") or "")
            if not reference:
                continue
            exists = (
                await db.execute(
                    select(PlaybackSession.id).filter(
                        PlaybackSession.source == "tautulli",
                        PlaybackSession.source_session_id == reference,
                    )
                )
            ).scalar()
            if exists:
                continue
            started = _dt_from_epoch(item.get("started")) or now_utc_naive()
            stopped = _dt_from_epoch(item.get("stopped"))
            duration_ms = _int(item.get("duration"), 0) * 1000
            watched_ms = _int(item.get("play_duration") or item.get("duration"), 0) * 1000
            video_decision = item.get("video_decision")
            audio_decision = item.get("audio_decision")
            db.add(
                PlaybackSession(
                    source="tautulli",
                    source_session_id=reference,
                    user_name=item.get("friendly_name") or item.get("user"),
                    media_type=item.get("media_type"),
                    title=item.get("title") or "Lecture Plex",
                    grandparent_title=item.get("grandparent_title"),
                    parent_title=item.get("parent_title"),
                    year=_int(item.get("year")),
                    rating_key=str(item.get("rating_key") or "") or None,
                    library_section_title=item.get("section_name"),
                    thumb_url=item.get("thumb"),
                    player_title=item.get("player"),
                    platform=item.get("platform"),
                    product=item.get("product"),
                    player_address=_masked_ip(item.get("ip_address"), settings.activity_anonymize_ips),
                    state="stopped",
                    video_decision=video_decision,
                    audio_decision=audio_decision,
                    playback_method=_playback_method(video_decision, audio_decision),
                    quality=item.get("quality_profile") or item.get("video_resolution"),
                    video_codec=item.get("video_codec"),
                    audio_codec=item.get("audio_codec"),
                    bandwidth_kbps=_int(item.get("bandwidth")),
                    duration_ms=duration_ms,
                    watched_ms=watched_ms,
                    progress_ms=watched_ms,
                    started_at=started,
                    last_seen_at=stopped or started,
                    ended_at=stopped or started + timedelta(milliseconds=watched_ms),
                )
            )
            imported += 1
        await db.commit()
    await publish("activity.updated", {"imported": imported, "source": "tautulli"}, admin_only=True)
    return {"imported": imported, "received": len(rows)}


async def activity_snapshot(days: int = 30, db=None) -> dict:
    days = min(max(days, 1), 3650)
    cutoff = now_utc_naive() - timedelta(days=days)
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
    totals = (
        await db.execute(
            select(
                func.count(PlaybackSession.id),
                func.coalesce(func.sum(PlaybackSession.watched_ms), 0),
                func.count(func.distinct(PlaybackSession.user_name)),
                func.sum(case((PlaybackSession.playback_method == "transcode", 1), else_=0)),
            ).filter(PlaybackSession.started_at >= cutoff)
        )
    ).one()
    daily_rows = (
        await db.execute(
            select(
                func.date(PlaybackSession.started_at).label("day"),
                func.count(PlaybackSession.id),
                func.coalesce(func.sum(PlaybackSession.watched_ms), 0),
            )
            .filter(PlaybackSession.started_at >= cutoff)
            .group_by(func.date(PlaybackSession.started_at))
            .order_by(func.date(PlaybackSession.started_at))
        )
    ).all()
    user_rows = (
        await db.execute(
            select(
                PlaybackSession.user_name,
                func.count(PlaybackSession.id),
                func.coalesce(func.sum(PlaybackSession.watched_ms), 0),
            )
            .filter(PlaybackSession.started_at >= cutoff, PlaybackSession.user_name.is_not(None))
            .group_by(PlaybackSession.user_name)
            .order_by(func.sum(PlaybackSession.watched_ms).desc())
            .limit(10)
        )
    ).all()
    total = int(totals[0] or 0)
    transcodes = int(totals[3] or 0)
    return {
        "active": [_serialize(row) for row in active],
        "history": [_serialize(row) for row in history],
        "summary": {
            "sessions": total,
            "watch_ms": int(totals[1] or 0),
            "users": int(totals[2] or 0),
            "transcodes": transcodes,
            "transcode_rate": round(transcodes / total * 100, 1) if total else 0,
        },
        "daily": [
            {"date": str(row[0]), "sessions": int(row[1] or 0), "watch_ms": int(row[2] or 0)}
            for row in daily_rows
        ],
        "users": [
            {"name": row[0], "sessions": int(row[1] or 0), "watch_ms": int(row[2] or 0)}
            for row in user_rows
        ],
    }
