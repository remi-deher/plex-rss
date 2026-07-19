"""Copy a legacy Plex-RSS SQLite database to migrated PostgreSQL."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.legacy_migration import LegacyMigrationError, migrate_sqlite_to_postgres


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="data/plex_rss.db", help="Path to the SQLite database")
    parser.add_argument("--target", default=os.getenv("DATABASE_URL"), help="PostgreSQL SQLAlchemy URL")
    parser.add_argument(
        "--replace-seed",
        action="store_true",
        help="Replace the single default settings row on a fresh target",
    )
    parser.add_argument(
        "--replace-target",
        action="store_true",
        help="Replace every application row already present in PostgreSQL",
    )
    parser.add_argument(
        "--confirm-replace",
        help="Required value REPLACE when --replace-target is used",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate both databases without copying rows")
    args = parser.parse_args()
    if args.replace_target and args.confirm_replace != "REPLACE":
        parser.error("--replace-target requires --confirm-replace REPLACE")
    try:
        report = migrate_sqlite_to_postgres(
            args.source,
            args.target,
            replace_seed=args.replace_seed,
            replace_target=args.replace_target,
            dry_run=args.dry_run,
        )
    except LegacyMigrationError as exc:
        parser.exit(1, f"Migration aborted: {exc}\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
