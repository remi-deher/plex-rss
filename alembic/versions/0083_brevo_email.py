"""Ajoute le support de l'API Brevo comme transport d'envoi d'email.

Alternative HTTP (pas de serveur SMTP) au SMTP classique/OAuth2 deja en place :
utile pour les fournisseurs sans SMTP exploitable ou pour eviter la gestion d'un
compte SMTP dedie. Reutilise smtp_from comme adresse expeditrice -- seule une
cle API est necessaire en plus.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0083_brevo_email"
down_revision: Union[str, None] = "0082_smtp_oauth2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("brevo_api_key", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("brevo_api_key")
