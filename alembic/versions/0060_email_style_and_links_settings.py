"""add email shell style settings + tmdb/plex link toggles

Complète les réglages communs de la coquille email : couleur de fond de page,
couleur de fond de carte, police (preset), largeur de carte, rayon des coins,
taille du texte du synopsis, et deux bascules pour afficher un lien TMDB et un
bouton "Lire sur Plex" (résolu au moment de l'envoi, jamais en aperçu).

Revision ID: 0060_email_style_and_links_settings
Revises: 0059_email_brand_layout_settings
Create Date: 2026-07-11
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0060_email_style_and_links_settings"
down_revision: Union[str, None] = "0059_email_brand_layout_settings"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("email_bg_color", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("email_card_bg_color", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("email_font_family", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("email_card_width", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("email_card_border_radius", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("email_synopsis_font_size", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("email_show_tmdb_link", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("email_show_plex_button", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("email_bg_color")
        batch_op.drop_column("email_card_bg_color")
        batch_op.drop_column("email_font_family")
        batch_op.drop_column("email_card_width")
        batch_op.drop_column("email_card_border_radius")
        batch_op.drop_column("email_synopsis_font_size")
        batch_op.drop_column("email_show_tmdb_link")
        batch_op.drop_column("email_show_plex_button")
