"""Rename overseerr_* columns to seer_* and jellyseerr_active to seer_active

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-15

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.alter_column("overseerr_url", new_column_name="seer_url")
        batch_op.alter_column("overseerr_api_key", new_column_name="seer_api_key")
        batch_op.alter_column("overseerr_enabled", new_column_name="seer_enabled")

    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.alter_column("jellyseerr_active", new_column_name="seer_active")


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.alter_column("seer_url", new_column_name="overseerr_url")
        batch_op.alter_column("seer_api_key", new_column_name="overseerr_api_key")
        batch_op.alter_column("seer_enabled", new_column_name="overseerr_enabled")

    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.alter_column("seer_active", new_column_name="jellyseerr_active")
