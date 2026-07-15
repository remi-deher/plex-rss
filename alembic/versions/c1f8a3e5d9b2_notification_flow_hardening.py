"""Ajout de media_requests.failure_mail_sent et notification_logs.channel.

- failure_mail_sent : flag persisté (comme request_mail_sent/available_mail_sent)
  au lieu de dépendre uniquement du calcul volatile `was_failed` dans
  watchlist_poller.py — celui-ci pouvait racer entre deux process (voir le
  correctif du verrou distribué).
- channel : les notifications push (Discord/Telegram/ntfy/Gotify) sont
  désormais journalisées dans notification_logs comme l'email, au lieu de
  n'avoir aucune trace en cas d'échec.

Revision ID: c1f8a3e5d9b2
Revises: b7e41c9d2f10
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1f8a3e5d9b2"
down_revision: Union[str, None] = "b7e41c9d2f10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "media_requests",
        sa.Column("failure_mail_sent", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "notification_logs",
        sa.Column("channel", sa.String(), nullable=False, server_default="email"),
    )


def downgrade() -> None:
    op.drop_column("notification_logs", "channel")
    op.drop_column("media_requests", "failure_mail_sent")
