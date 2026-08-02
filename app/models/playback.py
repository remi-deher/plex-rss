"""Sessions de lecture Plex et instantanes analytiques de la mediatheque."""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..utils import now_utc_naive
from .base import Base


class PlaybackSession(Base):
    """Session de lecture normalisée, collectée depuis Plex ou importée de Tautulli."""

    __tablename__ = "playback_sessions"
    __table_args__ = (
        UniqueConstraint("source", "source_session_id", name="uq_playback_session_source"),
        Index("ix_playback_sessions_started_at", "started_at"),
        Index("ix_playback_sessions_active", "ended_at", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(default="plex")
    source_session_id: Mapped[str]
    session_key: Mapped[Optional[int]] = mapped_column(index=True)
    user_name: Mapped[Optional[str]] = mapped_column(index=True)
    plex_user_id: Mapped[Optional[str]]
    media_type: Mapped[Optional[str]]
    title: Mapped[str]
    grandparent_title: Mapped[Optional[str]]
    parent_title: Mapped[Optional[str]]
    year: Mapped[Optional[int]]
    rating_key: Mapped[Optional[str]]
    library_section_title: Mapped[Optional[str]]
    thumb_url: Mapped[Optional[str]]
    player_title: Mapped[Optional[str]]
    platform: Mapped[Optional[str]]
    product: Mapped[Optional[str]]
    player_address: Mapped[Optional[str]]
    state: Mapped[Optional[str]]
    playback_method: Mapped[Optional[str]]
    video_decision: Mapped[Optional[str]]
    audio_decision: Mapped[Optional[str]]
    quality: Mapped[Optional[str]]
    video_codec: Mapped[Optional[str]]
    audio_codec: Mapped[Optional[str]]
    container: Mapped[Optional[str]]
    subtitle_decision: Mapped[Optional[str]]
    stream_location: Mapped[Optional[str]]
    bandwidth_kbps: Mapped[Optional[int]]
    media_size_bytes: Mapped[Optional[int]]
    progress_ms: Mapped[Optional[int]]
    duration_ms: Mapped[Optional[int]]
    progress_percent: Mapped[Optional[float]]
    watched_status: Mapped[Optional[float]]
    group_count: Mapped[int] = mapped_column(default=1)
    source_group_ids: Mapped[Optional[str]]
    watched_ms: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime] = mapped_column(default=now_utc_naive)
    last_seen_at: Mapped[datetime] = mapped_column(default=now_utc_naive)
    ended_at: Mapped[Optional[datetime]]
    media_request_id: Mapped[Optional[int]] = mapped_column(index=True)


class PlaybackDailyAggregate(Base):
    """Agrégat journalier compact utilisé par les vues d'activité longue durée."""

    __tablename__ = "playback_daily_aggregates"
    __table_args__ = (
        UniqueConstraint(
            "day", "user_name", "media_type", "media_label", "playback_method",
            name="uq_playback_daily_dimensions",
        ),
        Index("ix_playback_daily_day", "day"),
        Index("ix_playback_daily_user_day", "user_name", "day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    day: Mapped[date]
    user_name: Mapped[str] = mapped_column(default="")
    media_type: Mapped[str] = mapped_column(default="")
    media_label: Mapped[str] = mapped_column(default="")
    playback_method: Mapped[str] = mapped_column(default="unknown")
    sessions: Mapped[int] = mapped_column(default=0)
    watch_ms: Mapped[int] = mapped_column(default=0)
    transcodes: Mapped[int] = mapped_column(default=0)

class LibraryAnalyticsSnapshot(Base):
    """Dernier calcul complet des insights médiathèque, prêt à être servi."""

    __tablename__ = "library_analytics_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    payload_json: Mapped[str] = mapped_column(Text)
    item_count: Mapped[int] = mapped_column(default=0)
    generated_at: Mapped[datetime] = mapped_column(default=now_utc_naive)
    updated_at: Mapped[datetime] = mapped_column(default=now_utc_naive)
