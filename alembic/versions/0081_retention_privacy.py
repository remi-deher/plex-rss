"""Ajoute les retentions RGPD : tentatives de connexion (IP) et journaux d'audit.

Sans ces reglages, LoginAttempt (adresses IP) et les journaux d'audit/diagnostic
n'etaient jamais purges -- conservation indefinie contraire au principe de
minimisation (Art. 5-1-e RGPD). La retention IP a une valeur par defaut bornee (90 j),
appliquee aussi a la ligne settings existante.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0081_retention_privacy"
down_revision: Union[str, None] = "0080_gdpr_contact"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(
            sa.Column("login_attempt_retention_days", sa.Integer(), nullable=True, server_default="90")
        )
        batch_op.add_column(sa.Column("audit_log_retention_days", sa.Integer(), nullable=True))
    # server_default ne couvre que les futures insertions ; on borne aussi la ligne
    # settings deja presente (une seule, id=1) pour ne pas laisser d'IP en conservation
    # indefinie apres migration.
    op.execute("UPDATE settings SET login_attempt_retention_days = 90 WHERE login_attempt_retention_days IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("audit_log_retention_days")
        batch_op.drop_column("login_attempt_retention_days")
