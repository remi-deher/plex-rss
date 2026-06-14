"""Radarr v5 minimumAvailability + Overseerr integration

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-14

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Radarr v5
    op.add_column(
        "settings", sa.Column("radarr_minimum_availability", sa.String(), server_default="released", nullable=False)
    )
    # Overseerr
    op.add_column("settings", sa.Column("overseerr_url", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("overseerr_api_key", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("overseerr_enabled", sa.Boolean(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("settings", "radarr_minimum_availability")
    op.drop_column("settings", "overseerr_url")
    op.drop_column("settings", "overseerr_api_key")
    op.drop_column("settings", "overseerr_enabled")
