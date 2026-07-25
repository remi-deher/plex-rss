"""Remplace la config SMTP/OAuth2/Brevo unique de Settings par une liste de fournisseurs
d'email (table email_providers), avec ordre de repli en cas d'echec.

Miroir du modele deja en place pour les instances Sonarr/Radarr/Prowlarr (arr_instances) :
plusieurs fournisseurs peuvent etre configures, actives independamment, et essayes par
ordre de priorite jusqu'a un envoi reussi. Settings ne garde que l'interrupteur global
(email_enabled) et l'adresse d'expedition commune (smtp_from), utilisee par tous les
fournisseurs et par ailleurs dans l'app (apercus d'email, destinataire de repli...).

La configuration existante (SMTP classique, SMTP OAuth2 Microsoft ou Brevo, une seule
etait possible avant cette migration) est reprise dans un unique EmailProvider "Email
principal" pour ne pas interrompre l'envoi des notifications existantes.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0084_email_providers"
down_revision: Union[str, None] = "0083_brevo_email"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_providers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("provider_type", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("smtp_host", sa.String(), nullable=True),
        sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="587"),
        sa.Column("smtp_tls", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("smtp_user", sa.String(), nullable=True),
        sa.Column("smtp_password", sa.Text(), nullable=True),
        sa.Column("oauth_tenant", sa.String(), nullable=False, server_default="consumers"),
        sa.Column("oauth_client_id", sa.String(), nullable=True),
        sa.Column("oauth_client_secret", sa.Text(), nullable=True),
        sa.Column("oauth_mailbox", sa.String(), nullable=True),
        sa.Column("oauth_refresh_token", sa.Text(), nullable=True),
        sa.Column("oauth_access_token", sa.Text(), nullable=True),
        sa.Column("oauth_token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("brevo_api_key", sa.Text(), nullable=True),
    )

    # Reprend la config SMTP/OAuth2/Brevo existante (une seule possible avant cette
    # migration, portee par settings.smtp_auth_method) dans un unique EmailProvider,
    # pour que les notifications continuent de partir sans reconfiguration manuelle.
    # Les colonnes deja chiffrees (smtp_password, oauth_*, brevo_api_key) contiennent
    # du texte chiffre au repos (voir app/crypto.py) : une copie SQL brute prealable au
    # DROP COLUMN prime la valeur telle quelle, sans passer par le chiffrement Python
    # (inutile ici, la valeur est deja chiffree avec la meme cle applicative).
    op.execute(
        """
        INSERT INTO email_providers
            (name, provider_type, enabled, priority, smtp_host, smtp_port, smtp_tls,
             smtp_user, smtp_password, oauth_tenant, oauth_client_id, oauth_client_secret,
             oauth_mailbox, oauth_refresh_token, oauth_access_token, oauth_token_expires_at,
             brevo_api_key)
        SELECT
            'Email principal',
            CASE WHEN smtp_auth_method IN ('oauth2', 'brevo') THEN smtp_auth_method ELSE 'smtp' END,
            true,
            0,
            smtp_host, COALESCE(smtp_port, 587), COALESCE(smtp_tls, true),
            smtp_user, smtp_password, COALESCE(smtp_oauth_tenant, 'consumers'), smtp_oauth_client_id,
            smtp_oauth_client_secret, smtp_oauth_mailbox, smtp_oauth_refresh_token,
            smtp_oauth_access_token, smtp_oauth_token_expires_at, brevo_api_key
        FROM settings
        WHERE smtp_host IS NOT NULL OR smtp_oauth_client_id IS NOT NULL OR brevo_api_key IS NOT NULL
        """
    )

    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("smtp_host")
        batch_op.drop_column("smtp_port")
        batch_op.drop_column("smtp_user")
        batch_op.drop_column("smtp_password")
        batch_op.drop_column("smtp_tls")
        batch_op.drop_column("smtp_auth_method")
        batch_op.drop_column("smtp_oauth_tenant")
        batch_op.drop_column("smtp_oauth_client_id")
        batch_op.drop_column("smtp_oauth_client_secret")
        batch_op.drop_column("smtp_oauth_mailbox")
        batch_op.drop_column("smtp_oauth_refresh_token")
        batch_op.drop_column("smtp_oauth_access_token")
        batch_op.drop_column("smtp_oauth_token_expires_at")
        batch_op.drop_column("brevo_api_key")


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("smtp_host", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="587"))
        batch_op.add_column(sa.Column("smtp_user", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("smtp_password", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("smtp_tls", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("smtp_auth_method", sa.String(), nullable=False, server_default="password"))
        batch_op.add_column(sa.Column("smtp_oauth_tenant", sa.String(), nullable=False, server_default="consumers"))
        batch_op.add_column(sa.Column("smtp_oauth_client_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("smtp_oauth_client_secret", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("smtp_oauth_mailbox", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("smtp_oauth_refresh_token", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("smtp_oauth_access_token", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("smtp_oauth_token_expires_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("brevo_api_key", sa.Text(), nullable=True))

    op.execute(
        """
        UPDATE settings SET
            smtp_host = p.smtp_host, smtp_port = p.smtp_port, smtp_user = p.smtp_user,
            smtp_password = p.smtp_password, smtp_tls = p.smtp_tls, smtp_auth_method =
            CASE WHEN p.provider_type = 'smtp' THEN 'password' ELSE p.provider_type END,
            smtp_oauth_tenant = p.oauth_tenant, smtp_oauth_client_id = p.oauth_client_id,
            smtp_oauth_client_secret = p.oauth_client_secret, smtp_oauth_mailbox = p.oauth_mailbox,
            smtp_oauth_refresh_token = p.oauth_refresh_token, smtp_oauth_access_token = p.oauth_access_token,
            smtp_oauth_token_expires_at = p.oauth_token_expires_at, brevo_api_key = p.brevo_api_key
        FROM (
            SELECT * FROM email_providers ORDER BY priority ASC, id ASC LIMIT 1
        ) AS p
        WHERE settings.id = (SELECT id FROM settings LIMIT 1)
        """
    )
    op.drop_table("email_providers")
