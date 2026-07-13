"""add_seer_suppress_notifications

Revision ID: 6a097c5e5b27
Revises: cc52de65eef4
Create Date: 2026-07-14 01:32:49.627893

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '6a097c5e5b27'
down_revision: Union[str, None] = 'cc52de65eef4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('settings', sa.Column('seer_suppress_notifications', sa.Boolean(), server_default='true', nullable=False))

def downgrade() -> None:
    op.drop_column('settings', 'seer_suppress_notifications')
