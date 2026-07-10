"""media request downloading flag

Revision ID: 0049_media_request_downloading
Revises: 0048_user_security_passkeys
Create Date: 2026-07-10
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0049_media_request_downloading"
down_revision: Union[str, None] = "0048_user_security_passkeys"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("media_requests") as batch_op:
        batch_op.add_column(sa.Column("is_downloading", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("media_requests") as batch_op:
        batch_op.drop_column("is_downloading")
