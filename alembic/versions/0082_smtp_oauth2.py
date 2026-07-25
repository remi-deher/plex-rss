"""Ajoute le support OAuth2 (Microsoft) pour l'envoi SMTP.

Microsoft a desactive l'authentification basique (user/password) sur les boites
outlook.com/hotmail.fr : l'envoi via ces adresses necessite desormais OAuth2
(XOAUTH2). Ajoute les champs necessaires au flux "authorization code + PKCE"
(client_id/secret, tenant, boite, refresh/access token) en parallele du SMTP
classique existant (smtp_auth_method choisit lequel utiliser).
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0082_smtp_oauth2"
down_revision: Union[str, None] = "0081_retention_privacy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(
            sa.Column("smtp_auth_method", sa.String(), nullable=False, server_default="password")
        )
        batch_op.add_column(
            sa.Column("smtp_oauth_tenant", sa.String(), nullable=False, server_default="consumers")
        )
        batch_op.add_column(sa.Column("smtp_oauth_client_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("smtp_oauth_client_secret", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("smtp_oauth_mailbox", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("smtp_oauth_refresh_token", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("smtp_oauth_access_token", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("smtp_oauth_token_expires_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("smtp_oauth_token_expires_at")
        batch_op.drop_column("smtp_oauth_access_token")
        batch_op.drop_column("smtp_oauth_refresh_token")
        batch_op.drop_column("smtp_oauth_mailbox")
        batch_op.drop_column("smtp_oauth_client_secret")
        batch_op.drop_column("smtp_oauth_client_id")
        batch_op.drop_column("smtp_oauth_tenant")
        batch_op.drop_column("smtp_auth_method")
