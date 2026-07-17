"""Ajoute le journal persistant de diagnostic des demandes."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[tuple[str, str], None] = ("b7feaa3b86b5", "9f3c1a7e2b4d")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("media_requests", sa.Column("diagnostic_context", sa.Text(), nullable=True))
    op.create_table(
        "diagnostic_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=True),
        sa.Column("correlation_id", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="success"),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("media_type", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("details", sa.Text(), nullable=True),
    )
    op.create_index("ix_diagnostic_events_request_created", "diagnostic_events", ["request_id", "created_at"])
    op.create_index("ix_diagnostic_events_category_created", "diagnostic_events", ["category", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_diagnostic_events_category_created", table_name="diagnostic_events")
    op.drop_index("ix_diagnostic_events_request_created", table_name="diagnostic_events")
    op.drop_table("diagnostic_events")
    op.drop_column("media_requests", "diagnostic_context")
