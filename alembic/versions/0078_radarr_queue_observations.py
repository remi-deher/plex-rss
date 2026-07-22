"""Ajoute le suivi de la file Radarr (detection des imports bloques, symetrique de Sonarr)."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0078_radarr_queue_observations"
down_revision: Union[str, None] = "0077_import_blocked_toggle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "radarr_queue_observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("media_requests.id", ondelete="SET NULL"), index=True),
        sa.Column("arr_instance_id", sa.Integer(), sa.ForeignKey("arr_instances.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("queue_id", sa.Integer(), nullable=False),
        sa.Column("arr_media_id", sa.Integer(), index=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tracked_state", sa.String(), nullable=True),
        sa.Column("tracked_status", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("consecutive_blocked_checks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("blocked_at", sa.DateTime(), nullable=True),
        sa.Column("admin_alert_queued_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("arr_instance_id", "queue_id", name="uq_radarr_queue_observation"),
    )
    op.create_index(
        "ix_radarr_queue_observation_state", "radarr_queue_observations", ["state", "last_seen_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_radarr_queue_observation_state", table_name="radarr_queue_observations")
    op.drop_table("radarr_queue_observations")
