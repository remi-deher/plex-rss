"""Ajoute les modeles fonctionnels de disponibilite des series."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0076_series_email_templates"
down_revision: Union[str, None] = "0075_acquisition_tracking"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VARIANTS = (
    "episode_available",
    "season_started",
    "season_partial",
    "season_complete",
    "series_partial",
    "series_complete",
)


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        for variant in VARIANTS:
            batch_op.add_column(sa.Column(f"email_{variant}_template", sa.Text(), nullable=True))
            batch_op.add_column(sa.Column(f"email_{variant}_subject", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        for variant in reversed(VARIANTS):
            batch_op.drop_column(f"email_{variant}_subject")
            batch_op.drop_column(f"email_{variant}_template")
