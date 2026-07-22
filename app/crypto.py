"""Helpers for at-rest encryption of sensitive database fields."""

import base64
import hashlib
import logging
import os
import secrets
from typing import Optional

from sqlalchemy.types import Text, TypeDecorator

logger = logging.getLogger(__name__)

_PREFIX = "enc:v1:"
_ENCRYPTION_KEY_FILE = "data/.encryption_key"


def _get_or_create_encryption_key() -> str:
    """Lit ou génère la clé de chiffrement au repos (persistée dans data/.encryption_key).

    PLEXARR_ENCRYPTION_KEY / PLEXARR_SECRET_KEY restent prioritaires si définies (utile
    pour fixer la clé explicitement, ex. pour la partager entre plusieurs instances).
    Sans elles, une clé est générée au premier démarrage et persistée sur le volume
    data/ : le chiffrement des secrets (tokens Plex/*arr, mots de passe SMTP, etc.) est
    ainsi toujours actif, jamais silencieusement désactivé faute de variable d'env.
    """
    env_secret = os.getenv("PLEXARR_ENCRYPTION_KEY") or os.getenv("PLEXARR_SECRET_KEY")
    if env_secret:
        return env_secret
    os.makedirs("data", exist_ok=True)
    if os.path.exists(_ENCRYPTION_KEY_FILE):
        with open(_ENCRYPTION_KEY_FILE) as f:
            key = f.read().strip()
            if key:
                return key
    key = secrets.token_hex(32)
    with open(_ENCRYPTION_KEY_FILE, "w") as f:
        f.write(key)
    try:
        os.chmod(_ENCRYPTION_KEY_FILE, 0o600)
    except OSError:
        # Système de fichiers ne supportant pas les permissions Unix (ex: certains volumes Windows).
        pass
    return key


def _fernet():
    secret = _get_or_create_encryption_key()
    try:
        from cryptography.fernet import Fernet
    except Exception:
        logger.warning("cryptography is not installed; sensitive fields remain readable as plaintext")
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: Optional[str]) -> Optional[str]:
    if value is None or value == "" or value.startswith(_PREFIX):
        return value
    fernet = _fernet()
    if not fernet:
        return value
    return _PREFIX + fernet.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: Optional[str]) -> Optional[str]:
    if value is None or value == "" or not value.startswith(_PREFIX):
        return value
    fernet = _fernet()
    if not fernet:
        return value
    try:
        return fernet.decrypt(value[len(_PREFIX) :].encode("ascii")).decode("utf-8")
    except Exception:
        logger.exception("Could not decrypt an encrypted database field")
        return value


class EncryptedText(TypeDecorator):
    """Text column that encrypts new writes when PLEXARR_ENCRYPTION_KEY is configured.

    Existing plaintext values remain readable, so current installations can opt in
    without a one-shot migration. The next write to a protected field stores it encrypted.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_secret(value)

    def process_result_value(self, value, dialect):
        return decrypt_secret(value)
