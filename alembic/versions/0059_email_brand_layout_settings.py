"""add brand color, header subtitle toggle, poster size and media layout settings

Complète les réglages communs de la coquille email : une couleur de marque
(en-tête, liens du pied de page, libellé "Demandé par"), un bouton pour masquer
le sous-titre du bandeau, la largeur de l'affiche, et la disposition du bloc
affiche/texte (affiche à gauche/droite ou empilée au-dessus du texte).

Revision ID: 0059_email_brand_layout_settings
Revises: 0058_email_media_block_settings
Create Date: 2026-07-11
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0059_email_brand_layout_settings"
down_revision: Union[str, None] = "0058_email_media_block_settings"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("email_brand_color", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("email_show_header_subtitle", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("email_poster_width", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("email_media_layout", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("email_brand_color")
        batch_op.drop_column("email_show_header_subtitle")
        batch_op.drop_column("email_poster_width")
        batch_op.drop_column("email_media_layout")
