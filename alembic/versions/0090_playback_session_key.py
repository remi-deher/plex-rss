"""Ajoute playback_sessions.session_key pour corréler polling et websocket Plex.

Le websocket Plex (`/:/websockets/notifications`) identifie une session par un
`sessionKey` entier, distinct du `Session/@id` (string) utilisé par le polling
`/status/sessions`. Sans colonne dédiée, impossible de rattacher un événement
websocket à la ligne créée par le polling, ni de survivre à une rotation de
`TranscodeSession/@key` en cours de lecture.

Revision ID: 0090_playback_session_key
Revises: 0089_normalize_email_configuration
"""

from alembic import op
import sqlalchemy as sa

revision = "0090_playback_session_key"
down_revision = "0089_normalize_email_configuration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("playback_sessions") as batch_op:
        batch_op.add_column(sa.Column("session_key", sa.Integer(), nullable=True))
        batch_op.create_index(
            "ix_playback_sessions_session_key", ["session_key"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("playback_sessions") as batch_op:
        batch_op.drop_index("ix_playback_sessions_session_key")
        batch_op.drop_column("session_key")
