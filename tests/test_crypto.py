import pytest

from app.crypto import decrypt_secret, encrypt_secret


def test_encrypt_secret_plain_without_key(monkeypatch):
    monkeypatch.delenv("PLEXARR_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("PLEXARR_SECRET_KEY", raising=False)

    assert encrypt_secret("secret") == "secret"
    assert decrypt_secret("secret") == "secret"


def test_encrypt_secret_roundtrip_with_key(monkeypatch):
    pytest.importorskip("cryptography")
    monkeypatch.setenv("PLEXARR_ENCRYPTION_KEY", "test-key")

    encrypted = encrypt_secret("secret")

    assert encrypted != "secret"
    assert encrypted.startswith("enc:v1:")
    assert decrypt_secret(encrypted) == "secret"
