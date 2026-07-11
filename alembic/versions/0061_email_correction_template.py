"""add email correction template settings

Revision ID: 0061_email_correction_template
Revises: 0060_email_style_and_links_settings
Create Date: 2026-07-11
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0061_email_correction_template"
down_revision: Union[str, None] = "0060_email_style_and_links_settings"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("email_correction_template", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("email_correction_subject", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("email_correction_accent_color", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("email_correction_badge_text", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("email_correction_headline_text", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("email_correction_show_synopsis", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("email_correction_show_synopsis")
        batch_op.drop_column("email_correction_headline_text")
        batch_op.drop_column("email_correction_badge_text")
        batch_op.drop_column("email_correction_accent_color")
        batch_op.drop_column("email_correction_subject")
        batch_op.drop_column("email_correction_template")
