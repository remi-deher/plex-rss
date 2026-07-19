"""remove_email_fragments

Revision ID: a2d5f655592c
Revises: a5c324f3ae2d
Create Date: 2026-07-11 05:05:55.031029

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a2d5f655592c"
down_revision: Union[str, None] = "a5c324f3ae2d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("email_fragment_subject_movie")
        batch_op.drop_column("email_fragment_subject_episode")
        batch_op.drop_column("email_fragment_subject_season_start")
        batch_op.drop_column("email_fragment_subject_season_complete")
        batch_op.drop_column("email_fragment_subject_series_complete")
        batch_op.drop_column("email_fragment_status_available")
        batch_op.drop_column("email_fragment_status_available_vo")
        batch_op.drop_column("email_fragment_status_available_vf")
        batch_op.drop_column("email_fragment_status_upgrade_vf")
        batch_op.drop_column("email_fragment_note_empty")
        batch_op.drop_column("email_fragment_note_vo_tracking")
        batch_op.drop_column("email_fragment_note_upgrade")


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("email_fragment_subject_movie", sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column("email_fragment_subject_episode", sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column("email_fragment_subject_season_start", sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column("email_fragment_subject_season_complete", sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column("email_fragment_subject_series_complete", sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column("email_fragment_status_available", sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column("email_fragment_status_available_vo", sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column("email_fragment_status_available_vf", sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column("email_fragment_status_upgrade_vf", sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column("email_fragment_note_empty", sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column("email_fragment_note_vo_tracking", sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column("email_fragment_note_upgrade", sa.VARCHAR(), nullable=True))
