"""add ntfy and gotify notification settings

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-17
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0024"
down_revision: str = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("ntfy_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("ntfy_token", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("gotify_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("gotify_token", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("gotify_token")
        batch_op.drop_column("gotify_url")
        batch_op.drop_column("ntfy_token")
        batch_op.drop_column("ntfy_url")
