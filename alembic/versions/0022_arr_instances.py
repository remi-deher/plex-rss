"""create arr_instances table and update media_requests

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-17
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0022"
down_revision: str = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create arr_instances table
    op.create_table(
        "arr_instances",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("arr_type", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("api_key", sa.String(), nullable=False),
        sa.Column("quality_profile_id", sa.Integer(), nullable=True),
        sa.Column("root_folder", sa.String(), nullable=True),
        sa.Column("minimum_availability", sa.String(), nullable=False, server_default="released"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("indexer_ids", sa.String(), nullable=True),
    )

    # 2. Add arr_instance_id to media_requests
    with op.batch_alter_table("media_requests") as batch_op:
        batch_op.add_column(sa.Column("arr_instance_id", sa.Integer(), nullable=True))

    # 3. Migrate existing settings (Sonarr/Radarr) to arr_instances
    # Query settings
    connection = op.get_bind()
    settings_rows = connection.execute(
        sa.text(
            "SELECT id, sonarr_url, sonarr_api_key, sonarr_quality_profile_id, sonarr_root_folder, sonarr_enabled, "
            "radarr_url, radarr_api_key, radarr_quality_profile_id, radarr_root_folder, radarr_enabled, radarr_minimum_availability "
            "FROM settings"
        )
    ).fetchall()

    for row in settings_rows:
        # Sonarr instance
        if row[1] and row[2]: # sonarr_url and sonarr_api_key
            connection.execute(
                sa.text(
                    "INSERT INTO arr_instances (name, arr_type, url, api_key, quality_profile_id, root_folder, enabled, is_default, minimum_availability) "
                    "VALUES (:name, :arr_type, :url, :api_key, :quality_profile_id, :root_folder, :enabled, :is_default, :minimum_availability)"
                ),
                {
                    "name": "Sonarr Default",
                    "arr_type": "sonarr",
                    "url": row[1],
                    "api_key": row[2],
                    "quality_profile_id": row[3],
                    "root_folder": row[4],
                    "enabled": bool(row[5]) if row[5] is not None else True,
                    "is_default": True,
                    "minimum_availability": "released"
                }
            )
        # Radarr instance
        if row[6] and row[7]: # radarr_url and radarr_api_key
            connection.execute(
                sa.text(
                    "INSERT INTO arr_instances (name, arr_type, url, api_key, quality_profile_id, root_folder, enabled, is_default, minimum_availability) "
                    "VALUES (:name, :arr_type, :url, :api_key, :quality_profile_id, :root_folder, :enabled, :is_default, :minimum_availability)"
                ),
                {
                    "name": "Radarr Default",
                    "arr_type": "radarr",
                    "url": row[6],
                    "api_key": row[7],
                    "quality_profile_id": row[8],
                    "root_folder": row[9],
                    "enabled": bool(row[10]) if row[10] is not None else True,
                    "is_default": True,
                    "minimum_availability": row[11] or "released"
                }
            )


def downgrade() -> None:
    # Drop column arr_instance_id from media_requests
    with op.batch_alter_table("media_requests") as batch_op:
        batch_op.drop_column("arr_instance_id")

    # Drop table arr_instances
    op.drop_table("arr_instances")
