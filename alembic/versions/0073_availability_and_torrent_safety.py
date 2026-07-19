"""Rend la confirmation de disponibilite explicite et securise les torrents directs."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0073_availability_torrent"
down_revision: Union[str, None] = "0072_request_fulfillment_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("availability_confirmation_mode", sa.String(), nullable=False, server_default="hybrid"),
    )
    op.add_column(
        "settings",
        sa.Column("availability_confirmation_timeout_minutes", sa.Integer(), nullable=False, server_default="30"),
    )
    op.execute("UPDATE settings SET torrent_auto_delete_files = false")
    with op.batch_alter_table("settings") as batch_op:
        batch_op.alter_column("torrent_auto_delete_files", server_default=sa.false())
    op.add_column("media_requests", sa.Column("torrent_name", sa.String(), nullable=True))
    op.add_column("media_requests", sa.Column("torrent_content_path", sa.Text(), nullable=True))
    op.add_column("media_requests", sa.Column("torrent_completed_at", sa.DateTime(), nullable=True))
    op.add_column("media_requests", sa.Column("torrent_import_verified_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("media_requests", "torrent_import_verified_at")
    op.drop_column("media_requests", "torrent_completed_at")
    op.drop_column("media_requests", "torrent_content_path")
    op.drop_column("media_requests", "torrent_name")
    op.drop_column("settings", "availability_confirmation_timeout_minutes")
    op.drop_column("settings", "availability_confirmation_mode")
    with op.batch_alter_table("settings") as batch_op:
        batch_op.alter_column("torrent_auto_delete_files", server_default=sa.true())
