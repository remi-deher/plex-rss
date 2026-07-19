"""webhook_secret + plex_verify_ssl: security hardening

Ajoute un secret partagé pour authentifier les webhooks entrants
(Sonarr/Radarr/Plex) et un flag pour activer/désactiver la vérification
TLS des appels sortants vers Plex (au lieu d'un verify=False codé en dur).

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-06 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("webhook_secret", sa.String(), nullable=True))
    op.add_column(
        "settings",
        sa.Column("plex_verify_ssl", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("settings", "plex_verify_ssl")
    op.drop_column("settings", "webhook_secret")
