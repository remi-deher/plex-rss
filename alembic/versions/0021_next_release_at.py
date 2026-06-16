"""add next_release_at to media_requests (cache pour le widget prochaines sorties)

Revision ID: 0021
Revises: 69815ec92e82
Create Date: 2026-06-16
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0021"
down_revision: str = "69815ec92e82"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("media_requests") as batch_op:
        batch_op.add_column(sa.Column("next_release_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("next_release_label", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("media_requests") as batch_op:
        batch_op.drop_column("next_release_label")
        batch_op.drop_column("next_release_at")
