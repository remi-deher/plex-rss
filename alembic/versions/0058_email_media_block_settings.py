"""add shared toggles for the poster/genres/requester block in the email shell

Le bloc affiche+titre+tags+"Demandé par" est de la mise en page (pas du contenu
qui varie par évènement) : contrairement au bandeau (couleur/badge/titre), ces
réglages sont partagés entre tous les templates, comme le header/footer.

Revision ID: 0058_email_media_block_settings
Revises: 0057_email_shell_settings
Create Date: 2026-07-11
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0058_email_media_block_settings"
down_revision: Union[str, None] = "0057_email_shell_settings"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("email_show_poster", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("email_show_genres", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("email_show_requester", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("email_requester_label", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("email_show_poster")
        batch_op.drop_column("email_show_genres")
        batch_op.drop_column("email_show_requester")
        batch_op.drop_column("email_requester_label")
