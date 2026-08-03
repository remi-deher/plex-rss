"""Elargit les tailles, durees et identifiants de lecture en 64 bits.

Revision ID: 0093_playback_big_integers
Revises: 0092_query_performance_indexes
"""

import sqlalchemy as sa

from alembic import op

revision = "0093_playback_big_integers"
down_revision = "0092_query_performance_indexes"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("session_key", True),
    ("media_size_bytes", True),
    ("progress_ms", True),
    ("duration_ms", True),
    ("watched_ms", False),
)


def _alter_columns(
    source_type: sa.types.TypeEngine, target_type: sa.types.TypeEngine
) -> None:
    for name, nullable in _COLUMNS:
        op.alter_column(
            "playback_sessions",
            name,
            existing_type=source_type,
            type_=target_type,
            existing_nullable=nullable,
        )


def upgrade() -> None:
    # SQLite stocke deja ses INTEGER signes sur 64 bits. Une reconstruction de table
    # n'apporterait aucune protection supplementaire et serait inutilement risquee.
    if op.get_bind().dialect.name == "sqlite":
        return
    _alter_columns(sa.Integer(), sa.BigInteger())


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    _alter_columns(sa.BigInteger(), sa.Integer())
