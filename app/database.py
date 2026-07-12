"""
Database access layer for SQLAlchemy.

SQLite is used by default. On Windows/Docker bind mounts, multiple concurrent
SQLite WAL shared-memory files can trigger "unable to open database file" on
some Windows/Docker bind mounts, so WAL is deliberately disabled while keeping
a longer busy timeout for normal SQLite lock contention.
"""

import logging
import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .models import Settings

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./data/plex_rss.db"

connect_args = {}
engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    connect_args["timeout"] = 30
    engine_kwargs.update(
        {
            "pool_pre_ping": True,
        }
    )

engine = create_engine(DATABASE_URL, connect_args=connect_args, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


if DATABASE_URL.startswith("sqlite"):

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

    subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=False,
        check=True,
    )


def seed_defaults():
    """Create default Settings and local admin user rows when needed."""
    import secrets

    from .models import PlexUser

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
