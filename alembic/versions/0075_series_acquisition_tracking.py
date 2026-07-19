"""Ajoute le suivi durable des vagues d'acquisition et de la queue Sonarr."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0075_acquisition_tracking"
down_revision: Union[str, None] = "0074_notification_hold"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "series_acquisition_batches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("media_requests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("arr_instance_id", sa.Integer(), sa.ForeignKey("arr_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("arr_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("expected_scope", sa.String(), nullable=False, server_default="monitored_seasons"),
        sa.Column("expected_seasons", sa.Text(), nullable=True, server_default="[]"),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("last_sonarr_activity_at", sa.DateTime(), nullable=True),
        sa.Column("last_plex_change_at", sa.DateTime(), nullable=True),
        sa.Column("stabilization_started_at", sa.DateTime(), nullable=True),
        sa.Column("pending_events", sa.Text(), nullable=True, server_default="[]"),
        sa.Column("summary_queued_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_series_acquisition_batches_request_id", "series_acquisition_batches", ["request_id"])
    op.create_index("ix_series_acquisition_batches_arr_instance_id", "series_acquisition_batches", ["arr_instance_id"])
    op.create_index("ix_series_acquisition_batches_arr_id", "series_acquisition_batches", ["arr_id"])
    op.create_index("ix_series_acquisition_batches_status", "series_acquisition_batches", ["status"])
    op.create_index(
        "ix_series_acquisition_batch_lookup",
        "series_acquisition_batches",
        ["arr_instance_id", "arr_id", "status"],
    )

    op.create_table(
        "sonarr_queue_observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("series_acquisition_batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("media_requests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("arr_instance_id", sa.Integer(), sa.ForeignKey("arr_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("queue_id", sa.Integer(), nullable=False),
        sa.Column("download_id", sa.String(), nullable=True),
        sa.Column("arr_media_id", sa.Integer(), nullable=True),
        sa.Column("season_number", sa.Integer(), nullable=True),
        sa.Column("episode_number", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tracked_state", sa.String(), nullable=True),
        sa.Column("tracked_status", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("status_messages", sa.Text(), nullable=True),
        sa.Column("consecutive_blocked_checks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("blocked_at", sa.DateTime(), nullable=True),
        sa.Column("admin_alert_queued_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("arr_instance_id", "queue_id", name="uq_sonarr_queue_observation"),
    )
    for column in ("batch_id", "request_id", "arr_instance_id", "download_id", "arr_media_id", "state"):
        op.create_index(f"ix_sonarr_queue_observations_{column}", "sonarr_queue_observations", [column])
    op.create_index(
        "ix_sonarr_queue_observation_state",
        "sonarr_queue_observations",
        ["state", "last_seen_at"],
    )


def downgrade() -> None:
    op.drop_table("sonarr_queue_observations")
    op.drop_table("series_acquisition_batches")
