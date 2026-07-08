"""Add a one-level undo backup column for email templates

Revision ID: 0039_email_templates_backup
Revises: 0038_language_milestone_templates
Create Date: 2026-07-07
"""

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0039_email_templates_backup"
down_revision: Union[str, None] = "0038_language_milestone_templates"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("email_templates_backup", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("email_templates_backup")
