"""Separe l'etat metier d'une demande de son etat technique d'execution."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0072_request_fulfillment_status"
down_revision: Union[str, None] = "0071_public_base_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "media_requests",
        sa.Column("fulfillment_status", sa.String(), nullable=False, server_default="not_submitted"),
    )
    op.add_column("media_requests", sa.Column("fulfillment_updated_at", sa.DateTime(), nullable=True))
    op.add_column("media_requests", sa.Column("fulfillment_error", sa.Text(), nullable=True))
    op.create_index(
        "ix_media_requests_fulfillment_status", "media_requests", ["fulfillment_status"]
    )
    op.execute(
        "UPDATE media_requests SET fulfillment_status = CASE "
        "WHEN status = 'available' THEN 'completed' "
        "WHEN status = 'partially_available' THEN 'partially_available' "
        "WHEN status = 'sent_to_arr' AND is_downloading = true THEN 'downloading' "
        "WHEN status = 'sent_to_arr' THEN 'submitted' "
        "WHEN status = 'failed' THEN 'failed' "
        "WHEN status = 'rejected' THEN 'removed' "
        "WHEN status = 'pending_approval' THEN 'not_submitted' "
        "ELSE 'awaiting_submission' END, "
        "fulfillment_updated_at = COALESCE(available_at, arr_processed_at, requested_at)"
    )


def downgrade() -> None:
    op.drop_index("ix_media_requests_fulfillment_status", table_name="media_requests")
    op.drop_column("media_requests", "fulfillment_error")
    op.drop_column("media_requests", "fulfillment_updated_at")
    op.drop_column("media_requests", "fulfillment_status")
