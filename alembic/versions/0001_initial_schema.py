"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-14

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True, default=1),
        sa.Column("plex_url", sa.String(), nullable=True),
        sa.Column("plex_token", sa.String(), nullable=True),
        sa.Column("plex_rss_url", sa.String(), nullable=True),
        sa.Column("watchlist_source_priority", sa.String(), default="api"),
        sa.Column("watchlist_fallback_enabled", sa.Boolean(), default=True),
        sa.Column("poll_interval_minutes", sa.Integer(), default=5),
        sa.Column("sonarr_url", sa.String(), nullable=True),
        sa.Column("sonarr_api_key", sa.String(), nullable=True),
        sa.Column("sonarr_quality_profile_id", sa.Integer(), nullable=True),
        sa.Column("sonarr_root_folder", sa.String(), nullable=True),
        sa.Column("sonarr_enabled", sa.Boolean(), default=True),
        sa.Column("radarr_url", sa.String(), nullable=True),
        sa.Column("radarr_api_key", sa.String(), nullable=True),
        sa.Column("radarr_quality_profile_id", sa.Integer(), nullable=True),
        sa.Column("radarr_root_folder", sa.String(), nullable=True),
        sa.Column("radarr_enabled", sa.Boolean(), default=True),
        sa.Column("smtp_host", sa.String(), nullable=True),
        sa.Column("smtp_port", sa.Integer(), default=587),
        sa.Column("smtp_user", sa.String(), nullable=True),
        sa.Column("smtp_password", sa.String(), nullable=True),
        sa.Column("smtp_from", sa.String(), nullable=True),
        sa.Column("smtp_tls", sa.Boolean(), default=True),
        sa.Column("email_on_request", sa.Boolean(), default=True),
        sa.Column("email_on_available", sa.Boolean(), default=True),
    )

    op.create_table(
        "plex_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("plex_user_id", sa.String(), unique=True, nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("plex_email", sa.String(), nullable=True),
        sa.Column("notification_email", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "media_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("plex_user_id", sa.String(), nullable=False),
        sa.Column("plex_user", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("tmdb_id", sa.String(), nullable=True),
        sa.Column("tvdb_id", sa.String(), nullable=True),
        sa.Column("imdb_id", sa.String(), nullable=True),
        sa.Column("plex_guid", sa.String(), nullable=True),
        sa.Column("status", sa.String(), default="pending"),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("arr_id", sa.Integer(), nullable=True),
        sa.Column("request_mail_sent", sa.Boolean(), default=False),
        sa.Column("available_mail_sent", sa.Boolean(), default=False),
        sa.Column("requested_at", sa.DateTime(), nullable=True),
        sa.Column("available_at", sa.DateTime(), nullable=True),
        sa.Column("poster_url", sa.String(), nullable=True),
        sa.Column("overview", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("media_requests")
    op.drop_table("plex_users")
    op.drop_table("settings")
