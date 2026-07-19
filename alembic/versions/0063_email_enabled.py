"""add master email_enabled toggle

Revision ID: 0063_email_enabled
Revises: 0062_vf_episode_french_default
Create Date: 2026-07-11
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0063_email_enabled"
down_revision: Union[str, None] = "0062_vf_episode_french_default"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("email_enabled", sa.Boolean(), nullable=True, server_default="1"))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("email_enabled")
