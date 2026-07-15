"""Renomme settings.arr_poll_interval_minutes -> arr_poll_interval_seconds pour
permettre un reglage en heures/minutes/secondes depuis l'onglet Taches planifiees
(au lieu d'etre fige a la granularite minute).

Revision ID: 7538ff72b5e6
Revises: a330c02449f1
Create Date: 2026-07-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7538ff72b5e6"
down_revision: Union[str, None] = "a330c02449f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("settings", "arr_poll_interval_minutes", new_column_name="arr_poll_interval_seconds")
    op.execute("UPDATE settings SET arr_poll_interval_seconds = arr_poll_interval_seconds * 60")
    op.alter_column("settings", "arr_poll_interval_seconds", server_default="900")


def downgrade() -> None:
    op.execute("UPDATE settings SET arr_poll_interval_seconds = arr_poll_interval_seconds / 60")
    op.alter_column("settings", "arr_poll_interval_seconds", new_column_name="arr_poll_interval_minutes")
    op.alter_column("settings", "arr_poll_interval_minutes", server_default="15")
