import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def provisioning_uri(secret: str, account_name: str, issuer: str = "Plexarr") -> str:
    label = f"{issuer}:{account_name}"
    return (
        f"otpauth://totp/{quote(label)}"
        f"?secret={quote(secret)}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"
    )


def _totp_at(secret: str, counter: int, digits: int = 6) -> str:
    padded = secret.upper() + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**digits)).zfill(digits)


def verify_code(secret: str | None, code: str | None, *, at: int | None = None, window: int = 1) -> bool:
    if not secret or not code:
        return False
    normalized = "".join(ch for ch in str(code) if ch.isdigit())
    if len(normalized) != 6:
        return False
    timestamp = int(time.time() if at is None else at)
    counter = timestamp // 30
    for delta in range(-window, window + 1):
        if hmac.compare_digest(_totp_at(secret, counter + delta), normalized):
            return True
    return False
