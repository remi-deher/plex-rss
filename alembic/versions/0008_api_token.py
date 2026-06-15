"""Add api_token to settings

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-15

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("api_token", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("settings", "api_token")
