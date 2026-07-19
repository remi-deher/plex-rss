"""performance indexes on media_requests and notification tables

Revision ID: 0053_notification_perf_indexes
Revises: 0052_movie_tracking_mode_global
Create Date: 2026-07-11
"""

from typing import Union

from alembic import op

revision: str = "0053_notification_perf_indexes"
down_revision: Union[str, None] = "0052_movie_tracking_mode_global"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

_MEDIA_REQUEST_INDEXES = [
    ("ix_media_requests_plex_user_id", "plex_user_id"),
    ("ix_media_requests_tmdb_id", "tmdb_id"),
    ("ix_media_requests_tvdb_id", "tvdb_id"),
    ("ix_media_requests_status", "status"),
    ("ix_media_requests_arr_instance_id", "arr_instance_id"),
    ("ix_media_requests_torrent_hash", "torrent_hash"),
    ("ix_media_requests_has_vf", "has_vf"),
    ("ix_media_requests_library_item_id", "library_item_id"),
]


def upgrade() -> None:
    # IF NOT EXISTS : ces index peuvent avoir été partiellement créés par une tentative
    # précédente interrompue (DDL SQLite non transactionnelle, commit statement par statement).
    for index_name, column in _MEDIA_REQUEST_INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON media_requests ({column})")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notification_logs_event ON notification_logs (event)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notification_logs_sent_at ON notification_logs (sent_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pending_notifications_req_id ON pending_notifications (req_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pending_notifications_req_id")
    op.execute("DROP INDEX IF EXISTS ix_notification_logs_sent_at")
    op.execute("DROP INDEX IF EXISTS ix_notification_logs_event")
    for index_name, _ in reversed(_MEDIA_REQUEST_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
