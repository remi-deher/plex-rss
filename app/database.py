"""
Database access layer for SQLAlchemy.

SQLite is used by default. On Windows/Docker bind mounts, multiple concurrent
SQLite WAL shared-memory files can trigger "unable to open database file" on
some Windows/Docker bind mounts, so WAL is deliberately disabled while keeping
a longer busy timeout for normal SQLite lock contention.
"""

import os
import asyncio

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.future import select
from sqlalchemy.orm import declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/plex_rss.db")
# Ajustement pour aiosqlite / asyncpg
is_sqlite = DATABASE_URL.startswith("sqlite")
if is_sqlite:
    ASYNC_DATABASE_URL = (
        DATABASE_URL
        if DATABASE_URL.startswith("sqlite+aiosqlite://")
        else DATABASE_URL.replace("sqlite://", "sqlite+aiosqlite://", 1)
    )
    connect_args = {"check_same_thread": False, "timeout": 30}
    engine_kwargs = {"pool_pre_ping": True}
else:
    # Accept PostgreSQL URLs with or without an explicit synchronous driver.
    ASYNC_DATABASE_URL = DATABASE_URL
    if not DATABASE_URL.startswith("postgresql+asyncpg://"):
        ASYNC_DATABASE_URL = DATABASE_URL.split("://", 1)[-1]
        ASYNC_DATABASE_URL = f"postgresql+asyncpg://{ASYNC_DATABASE_URL}"
    connect_args = {}
    engine_kwargs = {"pool_pre_ping": True}

async_engine = create_async_engine(ASYNC_DATABASE_URL, connect_args=connect_args, **engine_kwargs)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

Base = declarative_base()

async def get_db_async():
    async with AsyncSessionLocal() as db:
        yield db

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(async_engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        """Use SQLite settings that behave well on Windows/Docker bind mounts."""
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA journal_mode=DELETE")
        cur.close()


def run_migrations():
    """Run Alembic migrations in a subprocess with retries."""
    import subprocess
    import sys
    import time
    import logging

    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                capture_output=False,
                check=True,
            )
            return
        except subprocess.CalledProcessError as e:
            if attempt == max_retries:
                logging.error(f"Failed to run migrations after {max_retries} attempts.")
                raise e
            logging.warning(f"Database not ready or migration failed, retrying in 5 seconds (attempt {attempt}/{max_retries})...")
            time.sleep(5)


async def seed_defaults():
    """Create default Settings and local admin user rows when needed."""
    import secrets

    from .models import PlexUser, Settings

    async with AsyncSessionLocal() as db:
        s = (await db.execute(select(Settings))).scalars().first()
        if not s:
            s = Settings(id=1)
            db.add(s)
            await db.flush()
        if not s.webhook_secret:
            s.webhook_secret = secrets.token_urlsafe(32)

        if s.auth_username:
            admin_user = (
                await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == s.auth_username))
            ).scalars().first()
            if not admin_user:
                admin_user = PlexUser(
                    plex_user_id=s.auth_username,
                    display_name="Administrateur",
                    role="admin",
                    can_login=True,
                    enabled=True,
                    source="local",
                    password_hash=s.auth_password_hash,
                    totp_secret=s.totp_secret,
                    totp_enabled=s.totp_enabled,
                )
                db.add(admin_user)
            else:
                if admin_user.password_hash != s.auth_password_hash:
                    admin_user.password_hash = s.auth_password_hash
                if admin_user.totp_secret != s.totp_secret:
                    admin_user.totp_secret = s.totp_secret
                if admin_user.totp_enabled != s.totp_enabled:
                    admin_user.totp_enabled = s.totp_enabled

        await db.commit()


async def init_db():
    """Initialize the DB: schema, optional legacy import, then defaults."""
    from .legacy_migration import auto_migrate_legacy_sqlite

    await asyncio.to_thread(run_migrations)
    await asyncio.to_thread(auto_migrate_legacy_sqlite, DATABASE_URL)
    await seed_defaults()
