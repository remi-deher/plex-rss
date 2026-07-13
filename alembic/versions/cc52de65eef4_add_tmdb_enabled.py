"""add tmdb_enabled

Revision ID: cc52de65eef4
Revises: 0064_admin_action_logs
Create Date: 2026-07-13 15:05:16.509505

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'cc52de65eef4'
down_revision: Union[str, None] = '0064_admin_action_logs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('settings', sa.Column('tmdb_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')))


def downgrade() -> None:
    op.drop_column('settings', 'tmdb_enabled')
