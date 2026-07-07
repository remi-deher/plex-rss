"""Editable language email templates

Revision ID: 0037_language_email_templates
Revises: 0036_notification_milestones
Create Date: 2026-07-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0037_language_email_templates"
down_revision: Union[str, None] = "0036_notification_milestones"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("email_available_vf_template", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("email_available_vo_tracking_template", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("email_vf_upgrade_template", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("email_available_vf_subject", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("email_available_vo_tracking_subject", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("email_vf_upgrade_subject", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("email_vf_upgrade_subject")
        batch_op.drop_column("email_available_vo_tracking_subject")
        batch_op.drop_column("email_available_vf_subject")
        batch_op.drop_column("email_vf_upgrade_template")
        batch_op.drop_column("email_available_vo_tracking_template")
        batch_op.drop_column("email_available_vf_template")
