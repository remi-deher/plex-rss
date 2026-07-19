"""media_requests.library_item_id: lien vers library_items

Une demande (MediaRequest) et un élément de bibliothèque (LibraryItem) peuvent
représenter le même média physique (l'utilisateur l'a demandé ET Plex l'a
synchronisé). Jusqu'ici, chacun avait son propre has_vf scanné indépendamment,
ce qui pouvait diverger (ex: Bibliothèque affiche VF, Demandes affiche encore
VO en attente pour le même titre).

Ce lien fait du LibraryItem la source de vérité unique une fois établi : le
backfill ci-dessous relie immédiatement les paires déjà en désync par
identité (GUID Plex > IDs externes > titre+année+type), la même logique que
`_find_library_item` côté scheduler.

Revision ID: 0033
Revises: 0032
Create Date: 2026-07-06 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("media_requests", sa.Column("library_item_id", sa.Integer(), nullable=True))
    op.create_index("ix_media_requests_library_item_id", "media_requests", ["library_item_id"])

    # --- Backfill : relie les demandes existantes à leur LibraryItem par identité ---
    conn = op.get_bind()
    requests = conn.execute(
        sa.text(
            "SELECT id, plex_guid, tmdb_id, tvdb_id, imdb_id, title, year, media_type "
            "FROM media_requests WHERE library_item_id IS NULL"
        )
    ).fetchall()

    for r in requests:
        li_id = None
        if r.plex_guid:
            row = conn.execute(
                sa.text("SELECT id FROM library_items WHERE plex_guid = :v"), {"v": r.plex_guid}
            ).fetchone()
            li_id = row[0] if row else None
        if li_id is None and r.tmdb_id:
            row = conn.execute(sa.text("SELECT id FROM library_items WHERE tmdb_id = :v"), {"v": r.tmdb_id}).fetchone()
            li_id = row[0] if row else None
        if li_id is None and r.tvdb_id:
            row = conn.execute(sa.text("SELECT id FROM library_items WHERE tvdb_id = :v"), {"v": r.tvdb_id}).fetchone()
            li_id = row[0] if row else None
        if li_id is None and r.imdb_id:
            row = conn.execute(sa.text("SELECT id FROM library_items WHERE imdb_id = :v"), {"v": r.imdb_id}).fetchone()
            li_id = row[0] if row else None
        if li_id is None and r.title:
            row = conn.execute(
                sa.text(
                    "SELECT id FROM library_items "
                    "WHERE lower(title) = lower(:title) AND year IS :year AND media_type = :media_type"
                ),
                {"title": r.title, "year": r.year, "media_type": r.media_type},
            ).fetchone()
            li_id = row[0] if row else None

        if li_id is not None:
            conn.execute(
                sa.text("UPDATE media_requests SET library_item_id = :li_id WHERE id = :req_id"),
                {"li_id": li_id, "req_id": r.id},
            )


def downgrade() -> None:
    op.drop_index("ix_media_requests_library_item_id", table_name="media_requests")
    op.drop_column("media_requests", "library_item_id")
