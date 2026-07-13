"""Safety checks for legacy SQLite discovery and inspection."""

import sqlite3

import pytest

from app.legacy_migration import LegacyMigrationError, inspect_legacy_sqlite


def _legacy_database(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE settings (id INTEGER PRIMARY KEY);
            CREATE TABLE plex_users (id INTEGER PRIMARY KEY, plex_user_id TEXT);
            CREATE TABLE media_requests (id INTEGER PRIMARY KEY, title TEXT);
            CREATE TABLE alembic_version (version_num TEXT NOT NULL);
            INSERT INTO settings (id) VALUES (1);
            INSERT INTO plex_users (id, plex_user_id) VALUES (1, 'alice');
            INSERT INTO media_requests (id, title) VALUES (1, 'Dune'), (2, 'Arrival');
            INSERT INTO alembic_version (version_num) VALUES ('0064');
            """
        )


def test_inspect_legacy_sqlite_reports_counts(tmp_path):
    path = tmp_path / "legacy.db"
    _legacy_database(path)

    report = inspect_legacy_sqlite(path)

    assert report["valid"] is True
    assert report["integrity"] == "ok"
    assert report["alembic_revision"] == "0064"
    assert report["tables"]["media_requests"] == 2
    assert report["total_rows"] == 4


def test_inspect_rejects_non_sqlite_file(tmp_path):
    path = tmp_path / "fake.db"
    path.write_bytes(b"not a database")

    with pytest.raises(LegacyMigrationError, match="SQLite valide"):
        inspect_legacy_sqlite(path)


def test_inspect_rejects_unrelated_sqlite_database(tmp_path):
    path = tmp_path / "unrelated.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE something_else (id INTEGER PRIMARY KEY)")

    with pytest.raises(LegacyMigrationError, match="Plex-RSS"):
        inspect_legacy_sqlite(path)
