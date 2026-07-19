"""vff integration: settings, per-user notify flags and media_request vf tracking

Revision ID: 0029
Revises: 0028
Create Date: 2026-07-06 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Settings : configuration VFF ---
    op.add_column("settings", sa.Column("vff_enabled", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("settings", sa.Column("vff_libraries", sa.Text(), nullable=True))
    op.add_column(
        "settings",
        sa.Column("vff_recheck_interval_minutes", sa.Integer(), nullable=False, server_default="360"),
    )
    op.add_column("settings", sa.Column("vff_auto_search", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("settings", sa.Column("email_on_vf_available", sa.Boolean(), nullable=False, server_default="1"))

    # --- PlexUser : flags de notification VF par type de média ---
    op.add_column("plex_users", sa.Column("notify_vf_movie", sa.Boolean(), nullable=True, server_default="1"))
    op.add_column("plex_users", sa.Column("notify_vf_series", sa.Boolean(), nullable=True, server_default="1"))
    op.add_column("plex_users", sa.Column("notify_vf_anime", sa.Boolean(), nullable=True, server_default="0"))

    # --- MediaRequest : suivi de la piste française ---
    op.add_column("media_requests", sa.Column("has_vf", sa.Boolean(), nullable=True))
    op.add_column("media_requests", sa.Column("vf_category", sa.String(), nullable=True))
    op.add_column("media_requests", sa.Column("vf_checked_at", sa.DateTime(), nullable=True))
    op.add_column("media_requests", sa.Column("vf_available_at", sa.DateTime(), nullable=True))
    op.add_column(
        "media_requests",
        sa.Column("vf_available_mail_sent", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "media_requests",
        sa.Column("vo_only_mail_sent", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("media_requests", "vo_only_mail_sent")
    op.drop_column("media_requests", "vf_available_mail_sent")
    op.drop_column("media_requests", "vf_available_at")
    op.drop_column("media_requests", "vf_checked_at")
    op.drop_column("media_requests", "vf_category")
    op.drop_column("media_requests", "has_vf")

    op.drop_column("plex_users", "notify_vf_anime")
    op.drop_column("plex_users", "notify_vf_series")
    op.drop_column("plex_users", "notify_vf_movie")

    op.drop_column("settings", "email_on_vf_available")
    op.drop_column("settings", "vff_auto_search")
    op.drop_column("settings", "vff_recheck_interval_minutes")
    op.drop_column("settings", "vff_libraries")
    op.drop_column("settings", "vff_enabled")
