"""Ajoute settings.public_base_url : URL publique de l'instance, utilisee pour
construire des liens absolus dans les emails (ex: lien vers la politique de
confidentialite), envoyes depuis des jobs planifies sans contexte de requete HTTP.

Revision ID: 0071_public_base_url
Revises: 0070_plex_sync_intervals
Create Date: 2026-07-20

"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0071_public_base_url"
down_revision: Union[str, None] = "0070_plex_sync_intervals"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("public_base_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("settings", "public_base_url")
