"""add arr_slug to media_requests

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("media_requests") as batch_op:
        batch_op.add_column(sa.Column("arr_slug", sa.String(), nullable=True))


def downgrade():
    with op.batch_alter_table("media_requests") as batch_op:
        batch_op.drop_column("arr_slug")
