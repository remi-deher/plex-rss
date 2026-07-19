"""movie tracking mode global default

Revision ID: 0052_movie_tracking_mode_global
Revises: 0051_movie_tracking_vff_default
Create Date: 2026-07-10
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0052_movie_tracking_mode_global"
down_revision: Union[str, None] = "0051_movie_tracking_vff_default"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("movie_tracking_mode", sa.String(), nullable=True))

    op.execute("UPDATE settings SET movie_tracking_mode = 'language' WHERE movie_tracking_mode IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("movie_tracking_mode")
