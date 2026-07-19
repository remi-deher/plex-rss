"""Ajout de settings.arr_poll_interval_minutes (colonne reelle remplacant l'ancien
arr_poll_interval_hours orphelin, jamais persiste) et de la table job_run_logs
(historique generique des taches planifiees).

Revision ID: a330c02449f1
Revises: c6ed250da8d6
Create Date: 2026-07-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a330c02449f1"
down_revision: Union[str, None] = "c6ed250da8d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("arr_poll_interval_minutes", sa.Integer(), nullable=False, server_default="15"),
    )
    op.create_table(
        "job_run_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_job_run_logs_job_started", "job_run_logs", ["job", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_job_run_logs_job_started", table_name="job_run_logs")
    op.drop_table("job_run_logs")
    op.drop_column("settings", "arr_poll_interval_minutes")
