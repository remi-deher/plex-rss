"""add user routing columns to plex_users

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-17
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: str = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.add_column(sa.Column("sonarr_instance_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("radarr_instance_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.drop_column("radarr_instance_id")
        batch_op.drop_column("sonarr_instance_id")
