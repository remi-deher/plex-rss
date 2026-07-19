"""Ajoute media_requests.notify_suppressed : desactive les mails auto (demande/
disponible/echec) pour un item de watchlist deja vieux de plus de 24h au moment
de sa detection (vieil item qui ressort dans une fenetre RSS limitee a 50
entrees). Decide une seule fois a la creation, jamais recalcule ensuite.

Revision ID: 9f3c1a7e2b4d
Revises: 27bd85d199ce
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9f3c1a7e2b4d"
down_revision: Union[str, None] = "27bd85d199ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "media_requests",
        sa.Column("notify_suppressed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("media_requests", "notify_suppressed")
