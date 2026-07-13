"""Inspection and complete migration of legacy Plex-RSS SQLite databases."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, create_engine, func, select, text

logger = logging.getLogger(__name__)

SQLITE_HEADER = b"SQLite format 3\x00"
CORE_TABLES = {"settings", "plex_users", "media_requests"}
MARKER_PATH = Path("data/.legacy_sqlite_migration.json")


class LegacyMigrationError(RuntimeError):
    """Raised when a legacy database cannot be safely inspected or migrated."""


def sqlite_url(path: str | Path) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise LegacyMigrationError(f"Base SQLite introuvable : {resolved}")
    return f"sqlite:///{resolved.as_posix()}"


def postgres_sync_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url
    raise LegacyMigrationError("La base cible doit etre PostgreSQL")


def postgres_client_url(url: str) -> str:
    """Return a libpq URL accepted by pg_dump/pg_restore."""
    return postgres_sync_url(url).replace("postgresql+psycopg2://", "postgresql://", 1)


def _counts(connection, metadata: MetaData) -> dict[str, int]:
    return {
        table.name: connection.execute(select(func.count()).select_from(table)).scalar_one()
        for table in metadata.sorted_tables
        if table.name != "alembic_version"
    }


def inspect_legacy_sqlite(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise LegacyMigrationError(f"Base SQLite introuvable : {resolved}")
    with resolved.open("rb") as handle:
        if handle.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
            raise LegacyMigrationError("Le fichier n'est pas une base SQLite valide")

    uri = f"file:{resolved.as_posix()}?mode=ro"
    connection = None
    try:
        connection = sqlite3.connect(uri, uri=True)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise LegacyMigrationError(f"Controle d'integrite SQLite en echec : {integrity}")
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        missing = sorted(CORE_TABLES - table_names)
        if missing:
            raise LegacyMigrationError(
                "Cette base ne correspond pas a Plex-RSS (tables absentes : " + ", ".join(missing) + ")"
            )
        counts = {
            name: int(connection.execute(f'SELECT COUNT(*) FROM "{name.replace(chr(34), chr(34) * 2)}"').fetchone()[0])
            for name in sorted(table_names)
            if name != "alembic_version"
        }
        revision = None
        if "alembic_version" in table_names:
            row = connection.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
            revision = row[0] if row else None
    except sqlite3.Error as exc:
        raise LegacyMigrationError(f"Lecture SQLite impossible : {exc}") from exc
    finally:
        if connection is not None:
            connection.close()

    return {
        "valid": True,
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "integrity": "ok",
        "alembic_revision": revision,
        "tables": counts,
        "populated_tables": sum(1 for value in counts.values() if value),
        "total_rows": sum(counts.values()),
    }


def _reset_sequences(connection, metadata: MetaData) -> None:
    preparer = connection.dialect.identifier_preparer
    for table in metadata.sorted_tables:
        if table.name == "alembic_version" or "id" not in table.c:
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


def migrate_sqlite_to_postgres(
    source_path: str | Path,
    target_url: str,
    *,
    replace_seed: bool = False,
    replace_target: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Copy every compatible table in one PostgreSQL transaction and verify row counts."""
    inspection = inspect_legacy_sqlite(source_path)
    source_engine = create_engine(sqlite_url(source_path))
    target_engine = create_engine(postgres_sync_url(target_url), pool_pre_ping=True)
    source_meta = MetaData()
    target_meta = MetaData()
    try:
        source_meta.reflect(source_engine)
        target_meta.reflect(target_engine)
        missing_target = sorted(CORE_TABLES - set(target_meta.tables))
        if missing_target:
            raise LegacyMigrationError(
                "La cible PostgreSQL n'est pas migree (tables absentes : " + ", ".join(missing_target) + ")"
            )

        copied: dict[str, int] = {}
        ignored = sorted(set(source_meta.tables) - set(target_meta.tables) - {"alembic_version"})
        with source_engine.connect() as source, target_engine.begin() as target:
            source_counts = _counts(source, source_meta)
            target_counts = _counts(target, target_meta)
            occupied = {name: count for name, count in target_counts.items() if count}
            seed_only = occupied == {"settings": 1}
            if occupied and not replace_target and not (replace_seed and seed_only):
                details = ", ".join(f"{name}={count}" for name, count in occupied.items())
                raise LegacyMigrationError(f"La cible n'est pas vide ({details})")

            if dry_run:
                return {
                    **inspection,
                    "status": "validated",
                    "target_rows": sum(target_counts.values()),
                    "ignored_tables": ignored,
                }

            if replace_target:
                for table in reversed(target_meta.sorted_tables):
                    if table.name != "alembic_version":
                        target.execute(table.delete())
            elif seed_only:
                target.execute(target_meta.tables["settings"].delete())

            for target_table in target_meta.sorted_tables:
                name = target_table.name
                if name == "alembic_version":
                    continue
                source_table = source_meta.tables.get(name)
                if source_table is None or not source_counts.get(name):
                    continue
                columns = [column.name for column in target_table.columns if column.name in source_table.c]
                rows = [
                    dict(row._mapping)
                    for row in source.execute(select(*(source_table.c[column] for column in columns)))
                ]
                if rows:
                    target.execute(target_table.insert(), rows)
                    copied[name] = len(rows)

            _reset_sequences(target, target_meta)
            imported_counts = _counts(target, target_meta)
            mismatches = {
                name: {"source": count, "target": imported_counts.get(name, 0)}
                for name, count in source_counts.items()
                if name in target_meta.tables and name != "alembic_version" and count != imported_counts.get(name, 0)
            }
            if mismatches:
                raise LegacyMigrationError(f"Verification des lignes en echec : {mismatches}")

        return {
            **inspection,
            "status": "migrated",
            "copied_tables": copied,
            "copied_rows": sum(copied.values()),
            "ignored_tables": ignored,
        }
    finally:
        source_engine.dispose()
        target_engine.dispose()


def create_postgres_backup(target_url: str, directory: str | Path = "data/backups") -> Path:
    pg_dump = shutil.which("pg_dump")
    pg_restore = shutil.which("pg_restore")
    if not pg_dump or not pg_restore:
        raise LegacyMigrationError("pg_dump/pg_restore indisponibles dans le conteneur")
    backup_dir = Path(directory)
    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / f"pre-legacy-import-{datetime.now(timezone.utc):%Y%m%d-%H%M%S-%f}.dump"
    try:
        subprocess.run(
            [pg_dump, "--format=custom", "--file", str(path), postgres_client_url(target_url)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run([pg_restore, "--list", str(path)], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        path.unlink(missing_ok=True)
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise LegacyMigrationError(f"Sauvegarde PostgreSQL impossible : {detail}") from exc
    return path


def _enabled(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.lower() not in {"0", "false", "no", "off"}


def auto_migrate_legacy_sqlite(target_url: str) -> dict[str, Any] | None:
    """Migrate a mounted legacy DB only when PostgreSQL contains no application rows."""
    if not target_url.startswith("postgresql") or not _enabled(os.getenv("AUTO_MIGRATE_LEGACY_SQLITE")):
        return None
    marker = Path(os.getenv("LEGACY_MIGRATION_MARKER", str(MARKER_PATH)))
    if marker.exists():
        return None
    explicit = os.getenv("LEGACY_SQLITE_PATH")
    candidates = [Path(explicit)] if explicit else [Path("data/plex_rss.db"), Path("data/plex-rss.db")]
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        return None

    try:
        report = migrate_sqlite_to_postgres(source, target_url, replace_seed=True)
    except LegacyMigrationError as exc:
        if "cible n'est pas vide" in str(exc):
            logger.info("Legacy SQLite database found at %s; PostgreSQL already contains data, skipping", source)
            return None
        logger.warning("Automatic legacy SQLite migration skipped: %s", exc)
        return None

    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "migrated_at": datetime.now(timezone.utc).isoformat(),
                "source": str(source.resolve()),
                "source_sha256": digest,
                "copied_rows": report["copied_rows"],
                "copied_tables": report["copied_tables"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("Automatically migrated %s rows from %s", report["copied_rows"], source)
    return report
