"""
Couche d'accès à la base de données SQLite via SQLAlchemy.

- Le moteur est configuré avec check_same_thread=False car FastAPI utilise
  plusieurs threads pour les requêtes synchrones, alors que SQLite interdit
  par défaut l'accès multi-thread sur un même connexion.
- Les migrations sont exécutées dans un sous-processus pour éviter un conflit
  de verrou entre le moteur SQLAlchemy de l'app et le moteur interne d'Alembic.
"""

import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .models import Settings

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./data/plex_rss.db"

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        """Applique busy_timeout sur chaque connexion SQLite.

        Sous contention (ex. synchro Plex de milliers d'items en tâche de fond),
        une lecture attend jusqu'à 5 s la libération du verrou au lieu d'échouer
        immédiatement en "database is locked". On NE force PAS le mode WAL : sa
        mémoire partagée (-shm, mmap) n'est pas supportée sur les bind-mounts
        Windows/Docker et provoque "unable to open database file". La réactivité
        est assurée par l'intégration en thread + commits par lots (voir plex_sync).
        """
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()


def run_migrations():
    """Applique les migrations Alembic dans un sous-processus.

    L'exécution en subprocess évite que le moteur de l'app et celui d'Alembic
    se marchent dessus sur le fichier SQLite (erreur "database is locked").
    """
    import subprocess

    subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=False,
        check=True,
    )


def seed_defaults():
    """Insère la ligne Settings par défaut (id=1) si la table est vide.

    Génère aussi un webhook_secret au premier démarrage (ou après une mise à jour
    qui l'a laissé vide) pour que les endpoints /webhook/* soient authentifiés
    dès le départ, sans étape manuelle.
    """
    import secrets
    from .models import Settings, PlexUser

    db = SessionLocal()
    try:
        s = db.query(Settings).first()
        if not s:
            s = Settings(id=1)
            db.add(s)
            db.flush()
        if not s.webhook_secret:
            s.webhook_secret = secrets.token_urlsafe(32)

        # Seed local admin PlexUser row
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
                    totp_enabled=s.totp_enabled
                )
                db.add(admin_user)
            else:
                # Sync credentials from Settings table if updated
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
    """Initialise la DB : migrations puis seed."""
    run_migrations()
    seed_defaults()


def get_db():
    """Dépendance FastAPI : fournit une session et la ferme après la requête."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
