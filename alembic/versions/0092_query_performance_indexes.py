"""Ajoute les index composites des listes et rapprochements fréquents.

Revision ID: 0092_query_performance_indexes
Revises: 0091_playback_daily_aggregates
"""

from alembic import op

revision = "0092_query_performance_indexes"
down_revision = "0091_playback_daily_aggregates"
branch_labels = None
depends_on = None

_INDEXES = (
    ("ix_media_requests_requested_id", "media_requests", "requested_at DESC, id DESC", None),
    ("ix_media_requests_status_requested", "media_requests", "status, requested_at DESC", None),
    ("ix_media_requests_type_status", "media_requests", "media_type, status", None),
    ("ix_media_requests_arr_identity", "media_requests", "arr_instance_id, arr_id", None),
    (
        "ix_media_requests_next_release_at",
        "media_requests",
        "next_release_at",
        "next_release_at IS NOT NULL",
    ),
    ("ix_library_items_added_id", "library_items", "added_at DESC, title, id", None),
    ("ix_library_items_arr_identity", "library_items", "arr_instance_id, arr_id", None),
    ("ix_poll_history_started_at", "poll_history", "started_at DESC", None),
    ("ix_poll_history_job_started_at", "poll_history", "job, started_at DESC", None),
)


def upgrade() -> None:
    concurrently = "CONCURRENTLY " if op.get_bind().dialect.name == "postgresql" else ""
    if concurrently:
        with op.get_context().autocommit_block():
            for name, table, columns, predicate in _INDEXES:
                where = f" WHERE {predicate}" if predicate else ""
                op.execute(
                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "
                    f"ON {table} ({columns}){where}"
                )
    else:
        for name, table, columns, predicate in _INDEXES:
            where = f" WHERE {predicate}" if predicate else ""
            op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns}){where}")


def downgrade() -> None:
    concurrently = "CONCURRENTLY " if op.get_bind().dialect.name == "postgresql" else ""
    if concurrently:
        with op.get_context().autocommit_block():
            for name, _, _, _ in reversed(_INDEXES):
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    else:
        for name, _, _, _ in reversed(_INDEXES):
            op.execute(f"DROP INDEX IF EXISTS {name}")
