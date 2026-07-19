"""add french default flag to vf episode cache

Revision ID: 0062_vf_episode_french_default
Revises: 0061_email_correction_template
Create Date: 2026-07-11
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0062_vf_episode_french_default"
down_revision: Union[str, None] = "0061_email_correction_template"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("vf_episode_status") as batch_op:
        batch_op.add_column(sa.Column("fr_is_default", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("vf_episode_status") as batch_op:
        batch_op.drop_column("fr_is_default")
