"""Copy a Plex-RSS SQLite database into an empty migrated PostgreSQL database."""

import argparse
import os
from pathlib import Path

from sqlalchemy import MetaData, create_engine, func, inspect, select, text


def _sqlite_url(path: str) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise SystemExit(f"SQLite source not found: {resolved}")
    return f"sqlite:///{resolved.as_posix()}"


def _postgres_url(url: str) -> str:
    if not url:
        raise SystemExit("PostgreSQL URL missing; pass --target or set DATABASE_URL")
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url
    raise SystemExit("Target must be a PostgreSQL URL")


def _table_counts(connection, metadata: MetaData) -> dict[str, int]:
    return {
        table.name: connection.execute(select(func.count()).select_from(table)).scalar_one()
        for table in metadata.sorted_tables
        if table.name != "alembic_version"
    }


def _reset_sequences(connection, metadata: MetaData) -> None:
    preparer = connection.dialect.identifier_preparer
    for table in metadata.sorted_tables:
        if "id" not in table.c:
            continue
        sequence = connection.execute(
            text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
            {"table_name": table.name, "column_name": "id"},
        ).scalar_one_or_none()
        if not sequence:
            continue
        table_name = preparer.quote(table.name)
        column_name = preparer.quote("id")
        maximum = connection.execute(text(f"SELECT MAX({column_name}) FROM {table_name}")).scalar_one()
        if maximum is None:
            connection.execute(text("SELECT setval(:sequence, 1, FALSE)"), {"sequence": sequence})
        else:
            connection.execute(
                text("SELECT setval(:sequence, :value, TRUE)"),
                {"sequence": sequence, "value": int(maximum)},
            )


def migrate(source_path: str, target_url: str, *, replace_seed: bool = False, dry_run: bool = False) -> None:
    source_engine = create_engine(_sqlite_url(source_path))
    target_engine = create_engine(_postgres_url(target_url), pool_pre_ping=True)
    source_meta = MetaData()
    target_meta = MetaData()
    source_meta.reflect(source_engine)
    target_meta.reflect(target_engine)

    missing = sorted(set(source_meta.tables) - set(target_meta.tables))
    if missing:
        raise SystemExit(f"Target is not fully migrated; missing tables: {', '.join(missing)}")

    with source_engine.connect() as source, target_engine.begin() as target:
        source_counts = _table_counts(source, source_meta)
        target_counts = _table_counts(target, target_meta)
        occupied = {name: count for name, count in target_counts.items() if count}
        allowed_seed = occupied and set(occupied) == {"settings"} and occupied["settings"] == 1
        if occupied and not (replace_seed and allowed_seed):
            details = ", ".join(f"{name}={count}" for name, count in occupied.items())
            raise SystemExit(f"Target is not empty ({details}); migration aborted")

        total = sum(source_counts.values())
        print(f"Source rows: {total} across {sum(bool(v) for v in source_counts.values())} populated tables")
        if dry_run:
            print("Dry run complete; target was not modified")
            target.rollback()
            return

        if allowed_seed:
            target.execute(target_meta.tables["settings"].delete())

        for target_table in target_meta.sorted_tables:
            name = target_table.name
            source_table = source_meta.tables.get(name)
            if source_table is None or source_counts.get(name, 0) == 0:
                continue
            common_columns = [column.name for column in target_table.columns if column.name in source_table.c]
            rows = [dict(row._mapping) for row in source.execute(select(*(source_table.c[c] for c in common_columns)))]
            if rows:
                target.execute(target_table.insert(), rows)
                print(f"  {name}: {len(rows)}")

        _reset_sequences(target, target_meta)
        imported_counts = _table_counts(target, target_meta)
        mismatches = {
            name: (count, imported_counts.get(name, 0))
            for name, count in source_counts.items()
            if name in target_meta.tables and count != imported_counts.get(name, 0)
        }
        if mismatches:
            raise RuntimeError(f"Count verification failed: {mismatches}")
        print(f"Migration complete: {total} rows copied and verified")

    source_engine.dispose()
    target_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="data/plex_rss.db", help="Path to the SQLite database")
    parser.add_argument("--target", default=os.getenv("DATABASE_URL"), help="PostgreSQL SQLAlchemy URL")
    parser.add_argument(
        "--replace-seed",
        action="store_true",
        help="Replace the single default settings row created on a fresh target",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate both databases without copying rows")
    args = parser.parse_args()
    migrate(args.source, args.target, replace_seed=args.replace_seed, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
