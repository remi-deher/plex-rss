"""vf_granularity: distingue épisode(s) VF isolé(s) d'une saison entière en VF

Une série non-complète en VF (has_vf=False) peut avoir 0 épisode VF, quelques
épisodes VF épars, ou une saison entière en VF sans que la série le soit. Ajoute
un champ dérivé du cache par épisode (vf_episode_status) pour distinguer ces cas
au niveau badge, sans requête supplémentaire à l'affichage.

Revision ID: 0035
Revises: 0034
Create Date: 2026-07-07 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("media_requests", sa.Column("vf_granularity", sa.String(), nullable=True))
    op.add_column("library_items", sa.Column("vf_granularity", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("library_items", "vf_granularity")
    op.drop_column("media_requests", "vf_granularity")
