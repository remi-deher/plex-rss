"""
Couche d'accès à la base de données SQLite via SQLAlchemy.

- Le moteur est configuré avec check_same_thread=False car FastAPI utilise
  plusieurs threads pour les requêtes synchrones, alors que SQLite interdit
  par défaut l'accès multi-thread sur un même connexion.
- Les migrations sont exécutées dans un sous-processus pour éviter un conflit
  de verrou entre le moteur SQLAlchemy de l'app et le moteur interne d'Alembic.
"""

import os

from sqlalchemy import create_engine
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
    """Insère la ligne Settings par défaut (id=1) si la table est vide."""
    db = SessionLocal()
    try:
        if not db.query(Settings).first():
            db.add(Settings(id=1))
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
