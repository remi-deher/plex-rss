"""movie tracking mode + vff enabled default true

Revision ID: 0051_movie_tracking_vff_default
Revises: 0050_download_history
Create Date: 2026-07-10
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0051_movie_tracking_vff_default"
down_revision: Union[str, None] = "0050_download_history"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.add_column(sa.Column("movie_tracking_mode", sa.String(), nullable=True))

    # Le suivi VO/VF devient la priorité par défaut : bascule la ligne settings existante
    # (le changement de défaut côté modèle Python ne touche pas les lignes déjà en base).
    op.execute("UPDATE settings SET vff_enabled = TRUE")


def downgrade() -> None:
    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.drop_column("movie_tracking_mode")
