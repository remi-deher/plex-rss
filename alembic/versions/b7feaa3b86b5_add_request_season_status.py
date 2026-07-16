"""Ajoute la table request_season_status : disponibilite brute (fichier present cote
Sonarr, hors VFF/Plex) par saison d'une demande de serie. Alimentee par le tableau
seasons[] de la reponse Sonarr, deja recuperee par check_arr_statuses (aucun appel
reseau supplementaire) mais jusqu'ici jetee (seule l'agregat serie entiere etait garde).

Revision ID: b7feaa3b86b5
Revises: 5e2a9c7f1b3d
Create Date: 2026-07-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7feaa3b86b5"
down_revision: Union[str, None] = "5e2a9c7f1b3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "request_season_status",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("media_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("season_number", sa.Integer(), nullable=False),
        sa.Column("episodes_available_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("episodes_total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("request_id", "season_number", name="uq_request_season"),
    )
    op.create_index(
        "ix_request_season_status_request_id", "request_season_status", ["request_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_request_season_status_request_id", table_name="request_season_status")
    op.drop_table("request_season_status")
