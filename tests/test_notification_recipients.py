"""Tests unitaires pour scheduler._get_recipients — filtrage des destinataires email."""

from unittest.mock import MagicMock

import pytest

from app.scheduler import _get_recipients

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(smtp_from="noreply@app.com", admin_email=None):
    s = MagicMock()
    s.smtp_from = smtp_from
    s.admin_notification_email = admin_email
    return s


def _make_user(
    notification_email=None,
    enabled=True,
    notify_on_request=True,
    notify_on_available=True,
    notify_admin=True,
):
    u = MagicMock()
    u.notification_email = notification_email
    u.enabled = enabled
    u.notify_on_request = notify_on_request
    u.notify_on_available = notify_on_available
    u.notify_admin = notify_admin
    return u


# ---------------------------------------------------------------------------
# Utilisateur désactivé
# ---------------------------------------------------------------------------


def test_disabled_user_returns_empty():
    user = _make_user(notification_email="alice@example.com", enabled=False)
    result = _get_recipients(user, _make_settings())
    assert result == []


def test_enabled_user_returns_recipients():
    user = _make_user(notification_email="alice@example.com", enabled=True)
    result = _get_recipients(user, _make_settings())
    assert "alice@example.com" in result


# ---------------------------------------------------------------------------
# Flags notify_on_request / notify_on_available
# ---------------------------------------------------------------------------


def test_notify_on_request_false_returns_empty():
    user = _make_user(notification_email="a@b.com", notify_on_request=False)
    result = _get_recipients(user, _make_settings(), event="request")
    assert result == []


def test_notify_on_request_none_does_not_block():
    """None = non défini, ne bloque pas les envois."""
    user = _make_user(notification_email="a@b.com", notify_on_request=None)
    result = _get_recipients(user, _make_settings(), event="request")
    assert "a@b.com" in result


def test_notify_on_available_false_returns_empty():
    user = _make_user(notification_email="a@b.com", notify_on_available=False)
    result = _get_recipients(user, _make_settings(), event="available")
    assert result == []


def test_notify_on_available_none_does_not_block():
    user = _make_user(notification_email="a@b.com", notify_on_available=None)
    result = _get_recipients(user, _make_settings(), event="available")
    assert "a@b.com" in result


def test_notify_on_available_check_does_not_affect_request():
    """notify_on_available=False ne bloque pas les requests."""
    user = _make_user(notification_email="a@b.com", notify_on_available=False, notify_on_request=True)
    result = _get_recipients(user, _make_settings(), event="request")
    assert "a@b.com" in result


def test_notify_on_request_check_does_not_affect_available():
    """notify_on_request=False ne bloque pas les disponibilités."""
    user = _make_user(notification_email="a@b.com", notify_on_request=False, notify_on_available=True)
    result = _get_recipients(user, _make_settings(), event="available")
    assert "a@b.com" in result


# ---------------------------------------------------------------------------
# Fallback sur smtp_from
# ---------------------------------------------------------------------------


def test_fallback_to_smtp_from_when_no_user_email():
    user = _make_user(notification_email=None)
    result = _get_recipients(user, _make_settings(smtp_from="admin@app.com"))
    assert "admin@app.com" in result


def test_empty_whitespace_email_yields_no_recipients():
    """Une chaîne d'espaces est "truthy" donc ne déclenche pas le fallback smtp_from.

    Le code fait `(user.notification_email or smtp_from)` — "   " est truthy,
    donc raw="   " et recipients devient [] après split/strip.
    Comportement documenté : utiliser None ou "" pour déclencher le fallback.
    """
    user = _make_user(notification_email="   ")
    result = _get_recipients(user, _make_settings(smtp_from="admin@app.com"))
    # "   " est truthy → pas de fallback → liste vide
    assert result == []


def test_no_user_and_no_smtp_from_returns_empty():
    result = _get_recipients(None, _make_settings(smtp_from=""))
    assert result == []


def test_no_user_uses_smtp_from():
    result = _get_recipients(None, _make_settings(smtp_from="fallback@app.com"))
    assert result == ["fallback@app.com"]


# ---------------------------------------------------------------------------
# Email admin
# ---------------------------------------------------------------------------


def test_admin_email_appended_when_notify_admin_true():
    user = _make_user(notification_email="user@b.com", notify_admin=True)
    settings = _make_settings(admin_email="admin@b.com")
    result = _get_recipients(user, settings)
    assert "admin@b.com" in result
    assert "user@b.com" in result


def test_admin_email_not_duplicated_when_same_as_user():
    user = _make_user(notification_email="admin@b.com", notify_admin=True)
    settings = _make_settings(admin_email="admin@b.com")
    result = _get_recipients(user, settings)
    assert result.count("admin@b.com") == 1


def test_admin_email_not_appended_when_notify_admin_false():
    user = _make_user(notification_email="user@b.com", notify_admin=False)
    settings = _make_settings(admin_email="admin@b.com")
    result = _get_recipients(user, settings)
    assert "admin@b.com" not in result
    assert "user@b.com" in result


def test_multiple_admin_emails_appended():
    user = _make_user(notification_email="user@b.com", notify_admin=True)
    settings = _make_settings(admin_email="admin1@b.com, admin2@b.com")
    result = _get_recipients(user, settings)
    assert "admin1@b.com" in result
    assert "admin2@b.com" in result


def test_no_admin_email_when_setting_empty():
    user = _make_user(notification_email="user@b.com", notify_admin=True)
    settings = _make_settings(admin_email=None)
    result = _get_recipients(user, settings)
    assert result == ["user@b.com"]


# ---------------------------------------------------------------------------
# Combinaisons : disabled + flags
# ---------------------------------------------------------------------------


def test_disabled_user_with_admin_still_returns_empty():
    """Un utilisateur désactivé n'a aucun destinataire, même l'admin."""
    user = _make_user(
        notification_email="user@b.com",
        enabled=False,
        notify_admin=True,
    )
    settings = _make_settings(admin_email="admin@b.com")
    result = _get_recipients(user, settings)
    assert result == []


def test_multiple_user_emails_all_included():
    user = _make_user(notification_email="a@b.com, c@d.com")
    result = _get_recipients(user, _make_settings())
    assert "a@b.com" in result
    assert "c@d.com" in result
