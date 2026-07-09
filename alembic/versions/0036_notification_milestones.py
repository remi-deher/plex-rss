"""Notification milestones and VO/VF modes

Revision ID: 0036_notification_milestones
Revises: 0035
Create Date: 2026-07-07
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0036_notification_milestones"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("movie_vo_notify", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("movie_vf_notify", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(
            sa.Column(
                "series_vo_notify_mode",
                sa.String(),
                nullable=False,
                server_default="season_start_and_complete",
            )
        )
        batch_op.add_column(
            sa.Column(
                "series_vf_notify_mode",
                sa.String(),
                nullable=False,
                server_default="season_start_and_complete",
            )
        )

    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.add_column(sa.Column("movie_vo_notify", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("movie_vf_notify", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("series_vo_notify_mode", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("series_vf_notify_mode", sa.String(), nullable=True))

    op.create_table(
        "notification_milestones",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("req_id", sa.Integer(), nullable=False),
        sa.Column("plex_user_id", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("milestone_type", sa.String(), nullable=False),
        sa.Column("season_number", sa.Integer(), nullable=True),
        sa.Column("episode_number", sa.Integer(), nullable=True),
        sa.UniqueConstraint(
            "req_id",
            "plex_user_id",
            "direction",
            "milestone_type",
            "season_number",
            "episode_number",
            name="uq_notification_milestone",
        ),
    )


def downgrade() -> None:
    op.drop_table("notification_milestones")
    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.drop_column("series_vf_notify_mode")
        batch_op.drop_column("series_vo_notify_mode")
        batch_op.drop_column("movie_vf_notify")
        batch_op.drop_column("movie_vo_notify")
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("series_vf_notify_mode")
        batch_op.drop_column("series_vo_notify_mode")
        batch_op.drop_column("movie_vf_notify")
        batch_op.drop_column("movie_vo_notify")
