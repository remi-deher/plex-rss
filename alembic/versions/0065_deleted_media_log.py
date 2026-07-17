"""add deleted media log

Revision ID: 0065_deleted_media_log
Revises: d4e5f6a7b8c9
Create Date: 2026-07-17
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0065_deleted_media_log"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "deleted_media_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("tmdb_id", sa.String(), nullable=True),
        sa.Column("tvdb_id", sa.String(), nullable=True),
        sa.Column("imdb_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_by", sa.String(), nullable=True),
    )
    op.create_index("ix_deleted_media_log_tmdb_id", "deleted_media_log", ["tmdb_id"])
    op.create_index("ix_deleted_media_log_tvdb_id", "deleted_media_log", ["tvdb_id"])
    op.create_index("ix_deleted_media_log_imdb_id", "deleted_media_log", ["imdb_id"])


def downgrade() -> None:
    op.drop_index("ix_deleted_media_log_imdb_id", table_name="deleted_media_log")
    op.drop_index("ix_deleted_media_log_tvdb_id", table_name="deleted_media_log")
    op.drop_index("ix_deleted_media_log_tmdb_id", table_name="deleted_media_log")
    op.drop_table("deleted_media_log")
