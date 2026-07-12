"""
Database access layer for SQLAlchemy.

SQLite is used by default. On Windows/Docker bind mounts, multiple concurrent
SQLite WAL shared-memory files can trigger "unable to open database file" on
some Windows/Docker bind mounts, so WAL is deliberately disabled while keeping
a longer busy timeout for normal SQLite lock contention.
"""

import logging
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/plex_rss.db")
SYNC_DATABASE_URL = (
    DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if DATABASE_URL.startswith("postgresql+asyncpg://")
    else DATABASE_URL
)

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

# Moteurs synchrones (pour les threads APScheduler)
engine = create_engine(SYNC_DATABASE_URL, connect_args=connect_args, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Moteurs asynchrones (pour FastAPI)
async_engine = create_async_engine(ASYNC_DATABASE_URL, connect_args=connect_args, **engine_kwargs)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)
# Alias used by migrated services/routers
SessionLocalAsync = AsyncSessionLocal

Base = declarative_base()

async def get_db_async():
    async with AsyncSessionLocal() as db:
        yield db

if DATABASE_URL.startswith("sqlite"):
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        """Use SQLite settings that behave well on Windows/Docker bind mounts."""
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA journal_mode=DELETE")
        cur.close()


def run_migrations():
    """Run Alembic migrations in a subprocess."""
    import subprocess
    import sys

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=False,
        check=True,
    )


def seed_defaults():
    """Create default Settings and local admin user rows when needed."""
    import secrets

    from .models import PlexUser, Settings

    db = SessionLocal()
    try:
        s = db.query(Settings).first()
        if not s:
            s = Settings(id=1)
            db.add(s)
            db.flush()
        if not s.webhook_secret:
            s.webhook_secret = secrets.token_urlsafe(32)

        if s.auth_username:
            admin_user = db.query(PlexUser).filter(PlexUser.plex_user_id == s.auth_username).first()
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

        db.commit()
    finally:
        db.close()


def init_db():
    """Initialize the DB: migrations, then defaults."""
    run_migrations()
    seed_defaults()


def get_db():
    """FastAPI dependency providing a short-lived SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
