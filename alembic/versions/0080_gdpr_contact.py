"""Ajoute l'identite du responsable de traitement pour la page /privacy (RGPD)."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0080_gdpr_contact"
down_revision: Union[str, None] = "0079_library_item_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("gdpr_contact_name", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("gdpr_contact_email", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("gdpr_contact_email")
        batch_op.drop_column("gdpr_contact_name")
