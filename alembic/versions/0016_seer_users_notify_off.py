"""disable email notifications by default for seer/hybrid users

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-15
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE plex_users SET notify_on_request = FALSE, notify_on_available = FALSE "
            "WHERE seer_user_id IS NOT NULL OR source = 'seer'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE plex_users SET notify_on_request = TRUE, notify_on_available = TRUE "
            "WHERE seer_user_id IS NOT NULL OR source = 'seer'"
        )
    )
