"""Ajoute la collecte des lectures Plex et la connexion Tautulli."""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0085_playback_activity"
down_revision: Union[str, None] = "0084_email_providers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("live_activity_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("activity_retention_days", sa.Integer(), nullable=True, server_default="365"))
        batch_op.add_column(sa.Column("activity_anonymize_ips", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("tautulli_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("tautulli_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("tautulli_api_key", sa.Text(), nullable=True))

    op.create_table(
        "playback_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(), nullable=False, server_default="plex"),
        sa.Column("source_session_id", sa.String(), nullable=False),
        sa.Column("user_name", sa.String(), nullable=True),
        sa.Column("plex_user_id", sa.String(), nullable=True),
        sa.Column("media_type", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("grandparent_title", sa.String(), nullable=True),
        sa.Column("parent_title", sa.String(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("rating_key", sa.String(), nullable=True),
        sa.Column("library_section_title", sa.String(), nullable=True),
        sa.Column("thumb_url", sa.String(), nullable=True),
        sa.Column("player_title", sa.String(), nullable=True),
        sa.Column("platform", sa.String(), nullable=True),
        sa.Column("product", sa.String(), nullable=True),
        sa.Column("player_address", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=True),
        sa.Column("playback_method", sa.String(), nullable=True),
        sa.Column("video_decision", sa.String(), nullable=True),
        sa.Column("audio_decision", sa.String(), nullable=True),
        sa.Column("quality", sa.String(), nullable=True),
        sa.Column("video_codec", sa.String(), nullable=True),
        sa.Column("audio_codec", sa.String(), nullable=True),
        sa.Column("bandwidth_kbps", sa.Integer(), nullable=True),
        sa.Column("progress_ms", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("watched_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("media_request_id", sa.Integer(), nullable=True),
        sa.UniqueConstraint("source", "source_session_id", name="uq_playback_session_source"),
    )
    op.create_index("ix_playback_sessions_user_name", "playback_sessions", ["user_name"])
    op.create_index("ix_playback_sessions_started_at", "playback_sessions", ["started_at"])
    op.create_index("ix_playback_sessions_active", "playback_sessions", ["ended_at", "last_seen_at"])
    op.create_index("ix_playback_sessions_media_request_id", "playback_sessions", ["media_request_id"])


def downgrade() -> None:
    op.drop_table("playback_sessions")
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("tautulli_api_key")
        batch_op.drop_column("tautulli_url")
        batch_op.drop_column("tautulli_enabled")
        batch_op.drop_column("activity_anonymize_ips")
        batch_op.drop_column("activity_retention_days")
        batch_op.drop_column("live_activity_enabled")
