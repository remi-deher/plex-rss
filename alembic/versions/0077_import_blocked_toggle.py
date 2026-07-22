"""Ajoute la bascule notify_import_blocked (alerte admin distincte d'un echec de transmission)."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0077_import_blocked_toggle"
down_revision: Union[str, None] = "0076_series_email_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(
            sa.Column("notify_import_blocked", sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("notify_import_blocked")
