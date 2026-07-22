"""Tests des helpers de securite partages (app/utils.py).

Verrouille les correctifs CodeQL recents (py/url-redirection, py/stack-trace-exposure) :
sans ces tests, une regression sur ces fonctions ne serait detectee par rien -- voir
la revue de code du 2026-07-22 (safe_redirect_path / safe_error_message a 0% de
couverture sur leurs branches de rejet).
"""

import httpx
import pytest

from app.utils import safe_error_message, safe_redirect_path


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "/"),
        ("", "/"),
        ("   ", "/"),
        # Chemins relatifs internes valides : conserves tels quels.
        ("/dashboard", "/dashboard"),
        ("/library?status=pending_approval", "/library?status=pending_approval"),
        ("/media/show/123", "/media/show/123"),
        # Bypass "protocol-relative" : commence par "/" mais navigue vers un autre hote.
        ("//evil.com", "/"),
        ("//evil.com/path", "/"),
        (r"/\evil.com", "/"),
        (r"/\/evil.com", "/"),
        # URL absolue deguisee (scheme/netloc detectes par urlsplit malgre un prefixe "/").
        ("https://evil.com", "/"),
        ("http://evil.com/x", "/"),
        ("javascript:alert(1)", "/"),
        # Pas de prefixe "/" du tout.
        ("evil.com", "/"),
        ("dashboard", "/"),
    ],
)
def test_safe_redirect_path_rejects_external_targets(value, expected):
    assert safe_redirect_path(value) == expected


def test_safe_redirect_path_custom_default():
    assert safe_redirect_path("", default="/dashboard") == "/dashboard"
    assert safe_redirect_path("//evil.com", default="/dashboard") == "/dashboard"
    assert safe_redirect_path("/settings", default="/dashboard") == "/settings"


def test_safe_error_message_never_leaks_raw_exception_text():
    secret_detail = "Traceback: /etc/passwd leaked at line 42, host internal-db.local"
    message = safe_error_message(Exception(secret_detail))
    assert secret_detail not in message
    assert message == "Exception"


def test_safe_error_message_maps_httpx_status_error_to_status_code_only():
    request = httpx.Request("GET", "http://internal-service.local/secret-path")
    response = httpx.Response(500, request=request, text="internal stack trace details")
    exc = httpx.HTTPStatusError("boom", request=request, response=response)

    message = safe_error_message(exc)

    assert message == "Erreur HTTP 500"
    assert "internal-service.local" not in message
    assert "secret-path" not in message


def test_safe_error_message_maps_timeout_and_connect_errors():
    assert safe_error_message(httpx.TimeoutException("timed out")) == "Délai d'attente dépassé"
    assert safe_error_message(httpx.ConnectError("refused")) == "Connexion impossible (hôte injoignable)"
