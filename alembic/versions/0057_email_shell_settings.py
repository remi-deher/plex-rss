"""add editable email shell settings (shared header/footer + per-event banner)

Ajoute les réglages permettant d'éditer la coquille email depuis /templates :
- email_header_brand / email_header_subtitle / email_footer_template : partagés
  entre tous les modèles (édités une seule fois).
- email_<type>_accent_color / _badge_text / _headline_text / _show_synopsis pour
  request/available/upgrade/failure : bandeau spécifique par type d'évènement.

Toutes les colonnes sont nullable ; None = valeur par défaut codée en dur côté
app.services.email_service (get_shared_email_parts/get_event_visuals).

Revision ID: 0057_email_shell_settings
Revises: a2d5f655592c
Create Date: 2026-07-11
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0057_email_shell_settings"
down_revision: Union[str, None] = "a2d5f655592c"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

_EVENT_TYPES = ["request", "available", "upgrade", "failure"]


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("email_header_brand", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("email_header_subtitle", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("email_footer_template", sa.Text(), nullable=True))
        for t in _EVENT_TYPES:
            batch_op.add_column(sa.Column(f"email_{t}_accent_color", sa.String(), nullable=True))
            batch_op.add_column(sa.Column(f"email_{t}_badge_text", sa.String(), nullable=True))
            batch_op.add_column(sa.Column(f"email_{t}_headline_text", sa.String(), nullable=True))
            batch_op.add_column(sa.Column(f"email_{t}_show_synopsis", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("email_header_brand")
        batch_op.drop_column("email_header_subtitle")
        batch_op.drop_column("email_footer_template")
        for t in _EVENT_TYPES:
            batch_op.drop_column(f"email_{t}_accent_color")
            batch_op.drop_column(f"email_{t}_badge_text")
            batch_op.drop_column(f"email_{t}_headline_text")
            batch_op.drop_column(f"email_{t}_show_synopsis")
