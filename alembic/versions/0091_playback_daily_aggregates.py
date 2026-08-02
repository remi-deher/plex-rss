"""Ajoute les agrégats quotidiens de l'activité Plex.

Revision ID: 0091_playback_daily_aggregates
Revises: 0090_playback_session_key
"""

import sqlalchemy as sa

from alembic import op

revision = "0091_playback_daily_aggregates"
down_revision = "0090_playback_session_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playback_daily_aggregates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("user_name", sa.String(), nullable=False, server_default=""),
        sa.Column("media_type", sa.String(), nullable=False, server_default=""),
        sa.Column("media_label", sa.String(), nullable=False, server_default=""),
        sa.Column("playback_method", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("sessions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("watch_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("transcodes", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "day", "user_name", "media_type", "media_label", "playback_method",
            name="uq_playback_daily_dimensions",
        ),
    )
    op.create_index("ix_playback_daily_day", "playback_daily_aggregates", ["day"])
    op.create_index(
        "ix_playback_daily_user_day", "playback_daily_aggregates", ["user_name", "day"]
    )
    # Le premier déploiement dispose déjà souvent de plusieurs années d'historique.
    # Le backfill SQL évite un premier chargement applicatif très coûteux.
    op.execute(
        """
        INSERT INTO playback_daily_aggregates (
            day, user_name, media_type, media_label, playback_method,
            sessions, watch_ms, transcodes
        )
        SELECT
            DATE(started_at), COALESCE(user_name, ''), COALESCE(media_type, ''),
            COALESCE(grandparent_title, title, ''), COALESCE(playback_method, 'unknown'),
            COUNT(id), COALESCE(SUM(watched_ms), 0),
            SUM(CASE WHEN playback_method = 'transcode' THEN 1 ELSE 0 END)
        FROM playback_sessions
        GROUP BY DATE(started_at), COALESCE(user_name, ''), COALESCE(media_type, ''),
                 COALESCE(grandparent_title, title, ''), COALESCE(playback_method, 'unknown')
        """
    )


def downgrade() -> None:
    op.drop_table("playback_daily_aggregates")
