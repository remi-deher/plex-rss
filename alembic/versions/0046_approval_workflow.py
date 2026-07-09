"""approval workflow

Revision ID: 0046_approval_workflow
Revises: 0045_user_roles
Create Date: 2026-07-09
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0046_approval_workflow"
down_revision: Union[str, None] = "0045_user_roles"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("require_approval", sa.Boolean(), nullable=False, server_default=sa.false()))

    with op.batch_alter_table("media_requests") as batch_op:
        batch_op.add_column(sa.Column("approved_by", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("approved_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("rejected_reason", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("media_requests") as batch_op:
        batch_op.drop_column("rejected_reason")
        batch_op.drop_column("approved_at")
        batch_op.drop_column("approved_by")

    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("require_approval")
