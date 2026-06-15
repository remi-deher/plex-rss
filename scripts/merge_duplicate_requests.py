"""
Fusion des demandes en double dans media_requests.

Problème : avant la dédup globale, plusieurs utilisateurs demandant le même
média créaient plusieurs lignes distinctes. Ce script les fusionne :
- Garde la ligne la plus ancienne comme "primaire"
- Ajoute les autres utilisateurs dans extra_requesters (JSON)
- Supprime les lignes en double

Utilisation (depuis le conteneur Docker) :
    docker exec plex-rss python scripts/merge_duplicate_requests.py

Utilisation (locale, avec l'env Python du projet) :
    python scripts/merge_duplicate_requests.py

Options :
    --dry-run   Affiche ce qui serait fait sans modifier la base
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Ajoute la racine du projet au path pour importer l'app
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models import MediaRequest


def merge_duplicates(dry_run: bool = False):
    db = SessionLocal()
    try:
        all_requests = db.query(MediaRequest).order_by(MediaRequest.requested_at).all()

        # Grouper par (media_type, tmdb_id) — ignorer les entrées sans tmdb_id
        groups: dict[tuple, list[MediaRequest]] = defaultdict(list)
        no_tmdb: list[MediaRequest] = []

        for req in all_requests:
            if req.tmdb_id:
                groups[(req.media_type, req.tmdb_id)].append(req)
            else:
                no_tmdb.append(req)

        # Fusionner les groupes qui ont le même tvdb_id (cas : Plex donne un mauvais tmdb,
        # Seer donne le bon ; les deux entrées ont le même tvdb_id mais des tmdb différents).
        # On garde le groupe dont la source est Seer (tmdb Seer = référence).
        tvdb_to_key: dict[tuple, tuple] = {}
        groups_to_merge: dict[tuple, tuple] = {}  # clé source → clé cible (à absorber)
        for (media_type, tmdb_id), rows in groups.items():
            for r in rows:
                if r.tvdb_id:
                    vkey = (media_type, r.tvdb_id)
                    if vkey in tvdb_to_key:
                        existing_key = tvdb_to_key[vkey]
                        # Choisir la clé Seer comme cible principale
                        seer_key = next(
                            (k for k in [existing_key, (media_type, tmdb_id)]
                             if any(x.source == "seer" for x in groups[k])),
                            existing_key,
                        )
                        other_key = (media_type, tmdb_id) if seer_key == existing_key else existing_key
                        groups_to_merge[other_key] = seer_key
                    else:
                        tvdb_to_key[vkey] = (media_type, tmdb_id)

        for src_key, tgt_key in groups_to_merge.items():
            if src_key in groups:
                groups[tgt_key].extend(groups.pop(src_key))

        # Rattacher les entrées sans tmdb_id à un groupe existant par titre ou tvdb_id
        # (cas : ancienne demande RSS sans tmdb_id + nouvelle entrée Seer avec tmdb_id)
        title_to_key: dict[tuple, tuple] = {}
        tvdb_to_key2: dict[tuple, tuple] = {}
        for (media_type, tmdb_id), rows in groups.items():
            for r in rows:
                if r.title:
                    title_to_key[(media_type, r.title)] = (media_type, tmdb_id)
                if r.tvdb_id:
                    tvdb_to_key2[(media_type, r.tvdb_id)] = (media_type, tmdb_id)

        remaining_no_tmdb: list[MediaRequest] = []
        for req in no_tmdb:
            key = (
                tvdb_to_key2.get((req.media_type, req.tvdb_id)) if req.tvdb_id else None
            ) or title_to_key.get((req.media_type, req.title))
            if key:
                groups[key].append(req)
            else:
                remaining_no_tmdb.append(req)

        duplicates = {k: v for k, v in groups.items() if len(v) > 1}

        if not duplicates:
            print("Aucun doublon trouvé.")
            if remaining_no_tmdb:
                print(f"⚠  {len(remaining_no_tmdb)} demande(s) sans tmdb_id sans correspondance (ignorées).")
            return

        print(f"{len(duplicates)} groupe(s) de doublons trouvé(s).\n")

        total_merged = 0
        total_deleted = 0

        for (media_type, tmdb_id), rows in sorted(duplicates.items(), key=lambda x: x[0]):
            # La plus ancienne devient la ligne primaire
            primary = rows[0]
            others = rows[1:]

            # Charger les co-demandeurs existants du primaire
            existing_extras: list[dict] = json.loads(primary.extra_requesters or "[]")
            existing_ids = {primary.plex_user_id} | {e["plex_user_id"] for e in existing_extras}

            new_extras = list(existing_extras)
            to_delete: list[MediaRequest] = []

            for dup in others:
                if dup.plex_user_id not in existing_ids:
                    new_extras.append({
                        "plex_user_id": dup.plex_user_id,
                        "display_name": dup.plex_user or dup.plex_user_id,
                    })
                    existing_ids.add(dup.plex_user_id)

                # Si le doublon est Seer, son tmdb_id fait référence (Plex RSS peut donner un mauvais tmdb)
                if dup.source == "seer" and dup.tmdb_id and dup.tmdb_id != primary.tmdb_id:
                    if not dry_run:
                        primary.tmdb_id = dup.tmdb_id
                # Enrichir les identifiants manquants
                if dup.tvdb_id and not primary.tvdb_id:
                    if not dry_run:
                        primary.tvdb_id = dup.tvdb_id
                # Enrichir les champs manquants du primaire depuis le doublon
                if not primary.poster_url and dup.poster_url:
                    if not dry_run:
                        primary.poster_url = dup.poster_url
                if not primary.overview and dup.overview:
                    if not dry_run:
                        primary.overview = dup.overview
                if primary.title.startswith("[Seer #") and dup.title and not dup.title.startswith("[Seer #"):
                    if not dry_run:
                        primary.title = dup.title

                # Conserver le meilleur statut (available > sent_to_arr > pending > failed)
                status_rank = {"available": 4, "sent_to_arr": 3, "pending": 2, "failed": 1}
                if status_rank.get(dup.status, 0) > status_rank.get(primary.status, 0):
                    if not dry_run:
                        primary.status = dup.status
                        if dup.arr_id and not primary.arr_id:
                            primary.arr_id = dup.arr_id

                to_delete.append(dup)

            # Affichage
            co_names = [e["display_name"] for e in new_extras]
            action = "[DRY-RUN] " if dry_run else ""
            print(
                f"{action}'{primary.title}' ({media_type}, tmdb={tmdb_id})\n"
                f"  Primaire : {primary.plex_user or primary.plex_user_id} (id={primary.id})\n"
                f"  Co-demandeurs : {', '.join(co_names) if co_names else '—'}\n"
                f"  Suppressions : {[r.id for r in to_delete]}\n"
            )

            if not dry_run:
                primary.extra_requesters = json.dumps(new_extras, ensure_ascii=False)
                for dup in to_delete:
                    db.delete(dup)

            total_merged += 1
            total_deleted += len(to_delete)

        if remaining_no_tmdb:
            print(f"⚠  {len(remaining_no_tmdb)} demande(s) sans tmdb_id sans correspondance (ignorées).")

        print(f"\n{'[DRY-RUN] ' if dry_run else ''}Résultat : {total_merged} groupe(s) fusionné(s), {total_deleted} ligne(s) supprimée(s).")

        if not dry_run:
            db.commit()
            print("Base de données mise à jour.")
        else:
            print("Mode dry-run : aucune modification effectuée.")

    except Exception as e:
        print(f"Erreur : {e}", file=sys.stderr)
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fusionne les demandes en double dans media_requests.")
    parser.add_argument("--dry-run", action="store_true", help="Affiche les changements sans modifier la base")
    args = parser.parse_args()
    merge_duplicates(dry_run=args.dry_run)
