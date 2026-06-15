"""add source column to plex_users

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-15
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plex_users", sa.Column("source", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("plex_users", "source")
