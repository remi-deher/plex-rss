"""Helpers for optional at-rest encryption of sensitive database fields."""

import base64
import hashlib
import logging
import os
from typing import Optional

from sqlalchemy.types import Text, TypeDecorator

logger = logging.getLogger(__name__)

_PREFIX = "enc:v1:"


def _fernet():
    secret = os.getenv("PLEXARR_ENCRYPTION_KEY") or os.getenv("PLEXARR_SECRET_KEY")
    if not secret:
        return None
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
