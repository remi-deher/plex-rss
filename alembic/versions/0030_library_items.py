"""library_items: separate library media from requests

Sépare les médias réellement présents dans Plex (auparavant stockés dans
media_requests avec source='plex_sync' et un faux demandeur) dans une table
dédiée library_items. Migration de données incluse (et réversible).

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-06 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "library_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("tmdb_id", sa.String(), nullable=True),
        sa.Column("tvdb_id", sa.String(), nullable=True),
        sa.Column("imdb_id", sa.String(), nullable=True),
        sa.Column("plex_guid", sa.String(), nullable=True),
        sa.Column("poster_url", sa.String(), nullable=True),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=True),
        sa.Column("arr_instance_id", sa.Integer(), nullable=True),
        sa.Column("arr_id", sa.Integer(), nullable=True),
        sa.Column("arr_slug", sa.String(), nullable=True),
        sa.Column("has_vf", sa.Boolean(), nullable=True),
        sa.Column("vf_category", sa.String(), nullable=True),
        sa.Column("vf_checked_at", sa.DateTime(), nullable=True),
        sa.Column("vf_available_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_library_items_plex_guid", "library_items", ["plex_guid"])

    # --- Migration de données : plex_sync -> library_items ---
    op.execute(
        """
        INSERT INTO library_items (
            title, year, media_type, tmdb_id, tvdb_id, imdb_id, plex_guid,
            poster_url, overview, added_at, arr_instance_id, arr_id, arr_slug,
            has_vf, vf_category, vf_checked_at, vf_available_at, created_at, updated_at
        )
        SELECT
            title, year, media_type, tmdb_id, tvdb_id, imdb_id, plex_guid,
            poster_url, overview, available_at, arr_instance_id, arr_id, arr_slug,
            has_vf, vf_category, vf_checked_at, vf_available_at,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM media_requests
        WHERE source = 'plex_sync'
        """
    )
    op.execute("DELETE FROM media_requests WHERE source = 'plex_sync'")


def downgrade() -> None:
    # Recrée les lignes plex_sync dans media_requests à partir de library_items.
    op.execute(
        """
        INSERT INTO media_requests (
            plex_user_id, plex_user, title, year, media_type,
            tmdb_id, tvdb_id, imdb_id, plex_guid,
            status, source, arr_id, arr_slug, arr_instance_id,
            request_mail_sent, available_mail_sent, requested_at, available_at,
            poster_url, overview, has_vf, vf_category, vf_checked_at, vf_available_at,
            vf_available_mail_sent, vo_only_mail_sent
        )
        SELECT
            'admin', 'Plex Library', title, year, media_type,
            tmdb_id, tvdb_id, imdb_id, plex_guid,
            'available', 'plex_sync', arr_id, arr_slug, arr_instance_id,
            1, 1, added_at, added_at,
            poster_url, overview, has_vf, vf_category, vf_checked_at, vf_available_at,
            0, 0
        FROM library_items
        """
    )
    op.drop_index("ix_library_items_plex_guid", table_name="library_items")
    op.drop_table("library_items")
