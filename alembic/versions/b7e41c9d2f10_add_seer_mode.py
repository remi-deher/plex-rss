"""Ajout de settings.seer_mode (observer/actor) et redéfinition de seer_enabled en switch général.

- seer_mode = "actor" si l'install envoyait déjà ses demandes via Seer, sinon "observer".
- seer_enabled devient le switch général : activé si Seer était déjà utilisé
  (envoi de demandes actif, ou URL + clé API configurées).

Revision ID: b7e41c9d2f10
Revises: 6a097c5e5b27
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7e41c9d2f10"
down_revision: Union[str, None] = "6a097c5e5b27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("seer_mode", sa.String(), nullable=False, server_default="observer"),
    )
    op.execute("UPDATE settings SET seer_mode = 'actor' WHERE seer_send_requests IS TRUE")
    op.execute(
        "UPDATE settings SET seer_enabled = TRUE "
        "WHERE seer_send_requests IS TRUE OR (seer_url IS NOT NULL AND seer_url != '' AND seer_api_key IS NOT NULL AND seer_api_key != '')"
    )


def downgrade() -> None:
    op.execute("UPDATE settings SET seer_send_requests = TRUE WHERE seer_mode = 'actor' AND seer_enabled IS TRUE")
    op.drop_column("settings", "seer_mode")
