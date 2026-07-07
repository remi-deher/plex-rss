"""Editable language milestone email templates

Revision ID: 0038_language_milestone_templates
Revises: 0037_language_email_templates
Create Date: 2026-07-07
"""

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0038_language_milestone_templates"
down_revision: Union[str, None] = "0037_language_email_templates"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("email_language_episode_template", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("email_language_season_start_template", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("email_language_season_complete_template", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("email_language_series_complete_template", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("email_language_episode_subject", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("email_language_season_start_subject", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("email_language_season_complete_subject", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("email_language_series_complete_subject", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("email_language_series_complete_subject")
        batch_op.drop_column("email_language_season_complete_subject")
        batch_op.drop_column("email_language_season_start_subject")
        batch_op.drop_column("email_language_episode_subject")
        batch_op.drop_column("email_language_series_complete_template")
        batch_op.drop_column("email_language_season_complete_template")
        batch_op.drop_column("email_language_season_start_template")
        batch_op.drop_column("email_language_episode_template")
