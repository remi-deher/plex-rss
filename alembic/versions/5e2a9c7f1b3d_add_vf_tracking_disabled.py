"""Ajoute media_requests.vf_tracking_disabled : arrete definitivement le scan VF
periodique pour une demande, pose explicitement en cloturant une demande VO
(voir requests_api.mark_request_processed / stop_vf_tracking).

Revision ID: 5e2a9c7f1b3d
Revises: 9f3c1a7e2b4d
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5e2a9c7f1b3d"
down_revision: Union[str, None] = "9f3c1a7e2b4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "media_requests",
        sa.Column("vf_tracking_disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("media_requests", "vf_tracking_disabled")
