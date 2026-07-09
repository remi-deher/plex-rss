"""security i18n media issues

Revision ID: 0047_security_i18n_media_issues
Revises: 0046_approval_workflow
Create Date: 2026-07-09
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0047_security_i18n_media_issues"
down_revision: Union[str, None] = "0046_approval_workflow"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("api_token_scopes", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("totp_secret", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("default_locale", sa.String(), nullable=False, server_default="fr"))

    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.add_column(sa.Column("locale", sa.String(), nullable=True))

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ip_address", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.String(), nullable=True),
    )
    op.create_index("ix_login_attempts_ip_time", "login_attempts", ["ip_address", "attempted_at"])

    op.create_table(
        "media_issues",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("issue_type", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("reporter_plex_user_id", sa.String(), nullable=True),
        sa.Column("reporter_name", sa.String(), nullable=True),
        sa.Column("library_item_id", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("tmdb_id", sa.String(), nullable=True),
        sa.Column("tvdb_id", sa.String(), nullable=True),
        sa.Column("imdb_id", sa.String(), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
    )
    op.create_index("ix_media_issues_status_created", "media_issues", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_media_issues_status_created", table_name="media_issues")
    op.drop_table("media_issues")
    op.drop_index("ix_login_attempts_ip_time", table_name="login_attempts")
    op.drop_table("login_attempts")

    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.drop_column("locale")

    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("default_locale")
        batch_op.drop_column("totp_enabled")
        batch_op.drop_column("totp_secret")
        batch_op.drop_column("api_token_scopes")
