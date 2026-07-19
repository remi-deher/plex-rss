"""Safety checks for legacy SQLite discovery and inspection."""

import sqlite3

import pytest
from sqlalchemy import create_engine, text

from app.legacy_migration import LegacyMigrationError, _merge_legacy_users, inspect_legacy_sqlite


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


def test_merge_legacy_users_enriches_placeholders_without_changing_ids(tmp_path):
    source_engine = create_engine(f"sqlite:///{tmp_path / 'source.db'}")
    target_engine = create_engine(f"sqlite:///{tmp_path / 'target.db'}")
    schema = """
        CREATE TABLE plex_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plex_user_id TEXT UNIQUE NOT NULL,
            display_name TEXT,
            notification_email TEXT,
            enabled BOOLEAN,
            role TEXT,
            source TEXT
        )
    """
    with source_engine.begin() as connection:
        connection.execute(text(schema))
        connection.execute(
            text(
                """INSERT INTO plex_users
                (id, plex_user_id, display_name, notification_email, enabled, role, source)
                VALUES
                (1, 'alice', 'Alice', 'alice@example.com', 0, 'admin', NULL),
                (2, 'bob', 'Bob', 'bob@example.com', 1, 'user', 'seer')"""
            )
        )
    with target_engine.begin() as connection:
        connection.execute(text(schema))
        connection.execute(
            text(
                """INSERT INTO plex_users
                (id, plex_user_id, display_name, notification_email, enabled, role, source)
                VALUES (20, 'alice', NULL, NULL, 1, 'user', 'rss')"""
            )
        )

    report = _merge_legacy_users(source_engine, target_engine)

    with target_engine.connect() as connection:
        rows = {
            row._mapping["plex_user_id"]: dict(row._mapping)
            for row in connection.execute(text("SELECT * FROM plex_users ORDER BY id"))
        }
    assert report == {
        "status": "users_merged",
        "users_inserted": 1,
        "users_updated": 1,
        "user_fields_updated": 4,
        "copied_rows": 2,
        "copied_tables": {"plex_users": 2},
    }
    assert rows["alice"] == {
        "id": 20,
        "plex_user_id": "alice",
        "display_name": "Alice",
        "notification_email": "alice@example.com",
        "enabled": 0,
        "role": "admin",
        "source": "rss",
    }
    assert rows["bob"]["display_name"] == "Bob"
    assert rows["bob"]["notification_email"] == "bob@example.com"
