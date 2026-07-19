"""Ajoute media_requests.arr_processed_at : horodatage de la premiere transition
vers "sent_to_arr" (validation par Radarr/Sonarr), affiche dans la fiche detail
a cote de requested_at et available_at.

Revision ID: 27bd85d199ce
Revises: 7538ff72b5e6
Create Date: 2026-07-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "27bd85d199ce"
down_revision: Union[str, None] = "7538ff72b5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("media_requests", sa.Column("arr_processed_at", sa.DateTime(), nullable=True))
    # Backfill best-effort pour les demandes déjà transmises : requested_at est la
    # meilleure approximation disponible rétroactivement (pas d'historique de transition).
    op.execute(
        "UPDATE media_requests SET arr_processed_at = requested_at "
        "WHERE status IN ('sent_to_arr', 'available') AND arr_processed_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("media_requests", "arr_processed_at")
