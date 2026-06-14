"""add authentication credentials to settings

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-14
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("auth_username", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("auth_password_hash", sa.String(), nullable=True))


def downgrade():
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("auth_username")
        batch_op.drop_column("auth_password_hash")
