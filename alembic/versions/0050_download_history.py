"""download history

Revision ID: 0050_download_history
Revises: 0049_media_request_downloading
Create Date: 2026-07-10
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0050_download_history"
down_revision: Union[str, None] = "0049_media_request_downloading"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "download_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("instance_name", sa.String(), nullable=True),
        sa.Column("poster_url", sa.String(), nullable=True),
        sa.Column("request_id", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_download_history_completed_at", "download_history", ["completed_at"])


def downgrade() -> None:
    op.drop_index("ix_download_history_completed_at", table_name="download_history")
    op.drop_table("download_history")
