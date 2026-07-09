"""user security and passkeys

Revision ID: 0048_user_security_passkeys
Revises: 0047_security_i18n_media_issues
Create Date: 2026-07-09
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0048_user_security_passkeys"
down_revision: Union[str, None] = "0047_security_i18n_media_issues"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.add_column(sa.Column("password_hash", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("totp_secret", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "passkey_credentials",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("plex_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("credential_id", sa.String(), unique=True, nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("name", sa.String(), nullable=False, server_default="Passkey"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("passkey_credentials")

    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.drop_column("totp_enabled")
        batch_op.drop_column("totp_secret")
        batch_op.drop_column("password_hash")
