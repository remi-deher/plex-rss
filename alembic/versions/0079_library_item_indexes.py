"""Ajoute les index manquants sur library_items (rapprochement demande/media Plex).

Sans ces index, chaque rapprochement (plex_sync._find_library_item_by_ids, reutilise
par vff_scanner.py et library_api.py) scannait la table library_items en entier pour
chaque media synchronise -- potentiellement des milliers de scans sequentiels a
chaque sync Plex sur une grosse bibliotheque.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0079_library_item_indexes"
down_revision: Union[str, None] = "0078_radarr_queue_observations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXED_COLUMNS = ("media_type", "tmdb_id", "tvdb_id", "imdb_id", "plex_guid", "arr_instance_id")


def upgrade() -> None:
    for column in _INDEXED_COLUMNS:
        op.create_index(f"ix_library_items_{column}", "library_items", [column])


def downgrade() -> None:
    for column in reversed(_INDEXED_COLUMNS):
        op.drop_index(f"ix_library_items_{column}", table_name="library_items")
