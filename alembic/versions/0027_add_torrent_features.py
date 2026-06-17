"""add torrent features

Revision ID: 0027
Revises: 745cd4ca3bab
Create Date: 2026-06-17 09:42:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "745cd4ca3bab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Settings table changes
    op.add_column("settings", sa.Column("torrent_required_keywords", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("torrent_forbidden_keywords", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("torrent_min_size_gb", sa.Float(), nullable=True))
    op.add_column("settings", sa.Column("torrent_max_size_gb", sa.Float(), nullable=True))
    op.add_column("settings", sa.Column("torrent_ratio_limit", sa.Float(), nullable=True))
    op.add_column("settings", sa.Column("torrent_seed_time_limit_hours", sa.Integer(), nullable=True))
    op.add_column("settings", sa.Column("torrent_auto_delete_files", sa.Boolean(), nullable=False, server_default="1"))

    # MediaRequest table changes
    op.add_column("media_requests", sa.Column("download_client_id", sa.Integer(), nullable=True))
    op.add_column("media_requests", sa.Column("torrent_hash", sa.String(), nullable=True))


def downgrade() -> None:
    # MediaRequest table changes
    op.drop_column("media_requests", "torrent_hash")
    op.drop_column("media_requests", "download_client_id")

    # Settings table changes
    op.drop_column("settings", "torrent_auto_delete_files")
    op.drop_column("settings", "torrent_seed_time_limit_hours")
    op.drop_column("settings", "torrent_ratio_limit")
    op.drop_column("settings", "torrent_max_size_gb")
    op.drop_column("settings", "torrent_min_size_gb")
    op.drop_column("settings", "torrent_forbidden_keywords")
    op.drop_column("settings", "torrent_required_keywords")
