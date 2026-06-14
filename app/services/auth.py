"""
Service d'authentification.

- Hachage et vérification des mots de passe avec bcrypt (passlib).
- Gestion de la clé secrète pour SessionMiddleware :
  générée aléatoirement au premier démarrage, persistée dans data/.secret_key.
  Cela garantit que les sessions restent valides après un redémarrage du conteneur
  tant que le volume data/ est monté.
"""

import os
import secrets

import bcrypt

_SECRET_KEY_FILE = "data/.secret_key"


def get_secret_key() -> str:
    """Lit ou génère la clé secrète de session (persistée dans data/.secret_key)."""
    os.makedirs("data", exist_ok=True)
    if os.path.exists(_SECRET_KEY_FILE):
        with open(_SECRET_KEY_FILE) as f:
            key = f.read().strip()
            if key:
                return key
    key = secrets.token_hex(32)
    with open(_SECRET_KEY_FILE, "w") as f:
        f.write(key)
    return key


def hash_password(password: str) -> str:
    """Retourne le hash bcrypt du mot de passe."""
    # Encodage en bytes nécessaire pour bcrypt
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Vérifie qu'un mot de passe en clair correspond au hash stocké."""
    try:
        plain_bytes = plain.encode("utf-8")
        hashed_bytes = hashed.encode("utf-8")
        return bcrypt.checkpw(plain_bytes, hashed_bytes)
    except Exception:
        return False
