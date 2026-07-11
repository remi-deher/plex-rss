"""simplify notification settings to 2 axes (notify_language + notify_granularity)

Remplace l'ancien enchevêtrement movie_tracking_mode/series_tracking_mode (language/
simple/classic) + series_vo_notify_mode/series_vf_notify_mode/series_episode_notify_mode
(4 valeurs chacun) + partial_notify_frequency par 3 réglages clairs :
- movie_notify_language (bool)
- series_notify_language (bool)
- series_notify_granularity ("minimal" | "jalons" | "tout")

Revision ID: 0055_simplify_notify_settings
Revises: 0054_notification_log_context
Create Date: 2026-07-11
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0055_simplify_notify_settings"
down_revision: Union[str, None] = "0054_notification_log_context"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

# "every_episode" -> "tout", "season_complete"/"season_start_and_complete" -> "jalons",
# "series_complete" -> "minimal".
_GRANULARITY_CASE = """
    CASE
        WHEN {col} = 'every_episode' THEN 'tout'
        WHEN {col} = 'series_complete' THEN 'minimal'
        WHEN {col} IN ('season_complete', 'season_start_and_complete') THEN 'jalons'
        ELSE 'jalons'
    END
"""


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("movie_notify_language", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("series_notify_language", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("series_notify_granularity", sa.String(), nullable=True))

    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.add_column(sa.Column("movie_notify_language", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("series_notify_language", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("series_notify_granularity", sa.String(), nullable=True))

    # settings : ligne unique, toujours peuplée (comportement global par défaut)
    op.execute(
        f"""
        UPDATE settings SET
            movie_notify_language = CASE WHEN movie_tracking_mode = 'classic' THEN 0 ELSE 1 END,
            series_notify_language = CASE WHEN series_tracking_mode IN ('simple', 'classic') THEN 0 ELSE 1 END,
            series_notify_granularity = CASE
                WHEN series_tracking_mode = 'classic' THEN 'minimal'
                WHEN series_tracking_mode = 'simple' THEN {_GRANULARITY_CASE.format(col='series_episode_notify_mode')}
                ELSE {_GRANULARITY_CASE.format(col='series_vf_notify_mode')}
            END
        """
    )

    # plex_users : uniquement pour les utilisateurs qui avaient un override explicite —
    # les autres restent NULL ("hérite du réglage global"), comme avant.
    op.execute(
        """
        UPDATE plex_users SET movie_notify_language = CASE WHEN movie_tracking_mode = 'classic' THEN 0 ELSE 1 END
        WHERE movie_tracking_mode IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE plex_users SET series_notify_language = CASE WHEN series_tracking_mode IN ('simple', 'classic') THEN 0 ELSE 1 END
        WHERE series_tracking_mode IS NOT NULL
        """
    )
    op.execute(
        f"""
        UPDATE plex_users SET series_notify_granularity = CASE
            WHEN series_tracking_mode = 'classic' THEN 'minimal'
            WHEN series_tracking_mode = 'simple' AND series_episode_notify_mode IS NOT NULL
                THEN {_GRANULARITY_CASE.format(col='series_episode_notify_mode')}
            WHEN series_vf_notify_mode IS NOT NULL
                THEN {_GRANULARITY_CASE.format(col='series_vf_notify_mode')}
            ELSE NULL
        END
        WHERE series_tracking_mode IS NOT NULL OR series_vf_notify_mode IS NOT NULL OR series_episode_notify_mode IS NOT NULL
        """
    )

    with op.batch_alter_table("settings") as batch_op:
        batch_op.alter_column("movie_notify_language", nullable=False, server_default="1")
        batch_op.alter_column("series_notify_language", nullable=False, server_default="1")
        batch_op.alter_column("series_notify_granularity", nullable=False, server_default="jalons")
        batch_op.drop_column("movie_tracking_mode")
        batch_op.drop_column("movie_vo_notify")
        batch_op.drop_column("movie_vf_notify")
        batch_op.drop_column("series_tracking_mode")
        batch_op.drop_column("series_vo_notify_mode")
        batch_op.drop_column("series_vf_notify_mode")
        batch_op.drop_column("series_episode_notify_mode")
        batch_op.drop_column("partial_notify_frequency")

    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.drop_column("movie_tracking_mode")
        batch_op.drop_column("movie_vo_notify")
        batch_op.drop_column("movie_vf_notify")
        batch_op.drop_column("series_tracking_mode")
        batch_op.drop_column("series_vo_notify_mode")
        batch_op.drop_column("series_vf_notify_mode")
        batch_op.drop_column("series_episode_notify_mode")
        batch_op.drop_column("partial_notify_frequency")


def downgrade() -> None:
    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.add_column(sa.Column("movie_tracking_mode", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("movie_vo_notify", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("movie_vf_notify", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("series_tracking_mode", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("series_vo_notify_mode", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("series_vf_notify_mode", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("series_episode_notify_mode", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("partial_notify_frequency", sa.String(), nullable=True))
        batch_op.drop_column("movie_notify_language")
        batch_op.drop_column("series_notify_language")
        batch_op.drop_column("series_notify_granularity")

    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("movie_tracking_mode", sa.String(), nullable=False, server_default="language"))
        batch_op.add_column(sa.Column("movie_vo_notify", sa.Boolean(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("movie_vf_notify", sa.Boolean(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("series_tracking_mode", sa.String(), nullable=False, server_default="language"))
        batch_op.add_column(
            sa.Column("series_vo_notify_mode", sa.String(), nullable=False, server_default="season_start_and_complete")
        )
        batch_op.add_column(
            sa.Column("series_vf_notify_mode", sa.String(), nullable=False, server_default="season_start_and_complete")
        )
        batch_op.add_column(
            sa.Column(
                "series_episode_notify_mode", sa.String(), nullable=False, server_default="season_start_and_complete"
            )
        )
        batch_op.add_column(sa.Column("partial_notify_frequency", sa.String(), nullable=False, server_default="milestones"))
        batch_op.drop_column("movie_notify_language")
        batch_op.drop_column("series_notify_language")
        batch_op.drop_column("series_notify_granularity")
