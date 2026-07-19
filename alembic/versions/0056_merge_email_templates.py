"""merge email templates into a single parametrized "available" template

Les 10 anciens templates de disponibilité (available_vf, available_vo_tracking,
vf_upgrade, language_episode/season_start/season_complete/series_complete) sont
fusionnés dans email_available_template/email_available_subject (déjà existants),
paramétrés par un contexte structuré (scope/language/is_upgrade/season/episode)
au lieu d'un template par variante.

Revision ID: 0056_merge_email_templates
Revises: 0055_simplify_notify_settings
Create Date: 2026-07-11
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0056_merge_email_templates"
down_revision: Union[str, None] = "0055_simplify_notify_settings"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

_REMOVED_TEMPLATE_COLUMNS = [
    "email_available_vf_template",
    "email_available_vo_tracking_template",
    "email_vf_upgrade_template",
    "email_language_episode_template",
    "email_language_season_start_template",
    "email_language_season_complete_template",
    "email_language_series_complete_template",
]
_REMOVED_SUBJECT_COLUMNS = [
    "email_available_vf_subject",
    "email_available_vo_tracking_subject",
    "email_vf_upgrade_subject",
    "email_language_episode_subject",
    "email_language_season_start_subject",
    "email_language_season_complete_subject",
    "email_language_series_complete_subject",
]


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        for col in _REMOVED_TEMPLATE_COLUMNS + _REMOVED_SUBJECT_COLUMNS:
            batch_op.drop_column(col)


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        for col in _REMOVED_TEMPLATE_COLUMNS:
            batch_op.add_column(sa.Column(col, sa.Text(), nullable=True))
        for col in _REMOVED_SUBJECT_COLUMNS:
            batch_op.add_column(sa.Column(col, sa.String(), nullable=True))
