"""Add custom_name to plex_users

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-15

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("plex_users", sa.Column("custom_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("plex_users", "custom_name")
