"""Tests unitaires pour app/services/email_service.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import MediaRequest, Settings
from app.services.email_service import (
    _build_context,
    add_email_footer,
    render_template,
    send_available_notification,
    send_failure_notification,
    send_request_notification,
)


def _settings(**kwargs) -> Settings:
    defaults = dict(


def _settings(**kwargs) -> Settings:
    defaults = dict(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="user@example.com",
        smtp_password="secret",
        smtp_from="plex@example.com",
        smtp_tls=True,
        email_request_template=None,
        email_available_template=None,
        email_upgrade_template=None,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _req(**kwargs) -> MediaRequest:
    defaults = dict(
        plex_user_id="alice",
        plex_user="Alice",
        title="Inception",
        year=2010,
        media_type="movie",
        overview="A thief who steals corporate secrets.",
        poster_url="https://image.tmdb.org/t/p/w300/poster.jpg",
    )
    defaults.update(kwargs)
    return MediaRequest(**defaults)


# ---------------------------------------------------------------------------
# _build_context
# ---------------------------------------------------------------------------


def test_build_context_movie_labels():
    """media_type movie → labels français corrects."""
    ctx = _build_context(_req(media_type="movie"))
    assert ctx["media_type_label"] == "Film"
    assert ctx["media_type_label_cap"] == "Le film"


def test_build_context_show_labels():
    """media_type show → labels français corrects."""
    ctx = _build_context(_req(media_type="show"))
    assert ctx["media_type_label"].startswith("S")
    assert ctx["media_type_label_cap"].startswith("La s")


def test_build_context_fallback_to_plex_user_id():
    """Si plex_user est None, plex_user_id utilisé comme fallback."""
    req = _req(plex_user=None, plex_user_id="user_abc")
    ctx = _build_context(req)
    assert ctx["plex_user"] == "user_abc"


def test_build_context_display_name_overrides_plex_user():
    """display_name (custom_name) prime sur request.plex_user."""
    req = _req(plex_user="username_brut")
    ctx = _build_context(req, display_name="Papa")
    assert ctx["plex_user"] == "Papa"


def test_build_context_includes_all_keys():
    """Le contexte contient toutes les clés attendues par les templates."""
    ctx = _build_context(_req())
    for key in ("title", "year", "poster_url", "plex_user", "media_type", "media_type_label", "overview"):
        assert key in ctx


# ---------------------------------------------------------------------------
# render_template
# ---------------------------------------------------------------------------


def test_render_template_substitutes_variables():
    """Les variables Jinja2 sont correctement remplacées."""
    tpl = "Hello {{ title }} ({{ year }})"
    result = render_template(tpl, {"title": "Inception", "year": 2010})
    assert result == "Hello Inception (2010)"


def test_render_template_invalid_returns_error_html():
    """Un template invalide retourne un message HTML d'erreur (pas d'exception)."""
    result = render_template("{% for %}", {})
    assert "Erreur de template" in result


def test_render_template_conditional_block():
    """Les blocs conditionnels Jinja2 fonctionnent."""
    tpl = "{% if poster_url %}<img src='{{ poster_url }}'>{% endif %}"
    assert "<img" in render_template(tpl, {"poster_url": "http://x.com/img.jpg"})
    assert "<img" not in render_template(tpl, {"poster_url": ""})


def test_add_email_footer_injects_credit_once():
    html = "<html><body><p>Hello</p></body></html>"
    result = add_email_footer(html)
    assert "Logiciel" in result
    assert "DEHER" in result
    assert result.count("DEHER") == 1
    assert add_email_footer(result).count("DEHER") == 1


# ---------------------------------------------------------------------------
# send_request_notification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_request_uses_default_template_when_none():
    """Template custom None → DEFAULT_REQUEST_TEMPLATE utilisé."""
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_request_notification(_settings(), _req(), "dest@example.com")

    mock_send.assert_called_once()
    msg = mock_send.call_args[0][0]
    assert "Inception" in msg.as_string()
    assert msg["Subject"] == "[Plexarr] Nouvelle demande : Inception"


@pytest.mark.asyncio
async def test_send_request_uses_custom_template():
    """Template custom défini → rendu avec les variables du média."""
    custom = "Film: {{ title }}"
    s = _settings(email_request_template=custom)
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_request_notification(s, _req(), "dest@example.com")

    body = mock_send.call_args[0][0].get_payload(0).get_payload(decode=True).decode()
    assert "Film: Inception" in body


@pytest.mark.asyncio
async def test_send_custom_template_gets_global_footer():
    """Même un template custom reçoit le footer Plexarr/crédit à l'envoi."""
    s = _settings(email_request_template="<html><body>CUSTOM {{ title }}</body></html>")
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_request_notification(s, _req(), "dest@example.com")

    msg = mock_send.call_args[0][0]
    body = msg.get_payload(0).get_payload(decode=True).decode()
    assert "CUSTOM Inception" in body
    assert "Logiciel" in body
    assert "DEHER" in body


@pytest.mark.asyncio
async def test_send_skipped_when_smtp_not_configured():
    """SMTP non configuré → aucun envoi, pas d'exception."""
    s = _settings(smtp_host=None)
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_request_notification(s, _req(), "dest@example.com")

    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_send_raises_on_smtp_error():
    """Erreur SMTP → exception propagée (pour que notification_queue la capture)."""
    with patch(
        "app.services.email_service.aiosmtplib.send", new=AsyncMock(side_effect=Exception("connection refused"))
    ):
        with pytest.raises(Exception, match="connection refused"):
            await send_request_notification(_settings(), _req(), "dest@example.com")


# ---------------------------------------------------------------------------
# send_available_notification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_available_subject_and_body():
    """Email disponibilité : sujet générique (subject_phrase status_phrase) et corps."""
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_available_notification(_settings(), _req(), "dest@example.com")

    msg = mock_send.call_args[0][0]
    assert msg["Subject"] == "[Plexarr] Le film Inception est maintenant disponible !"
    assert "Le film Inception" in msg.as_string()


@pytest.mark.asyncio
async def test_send_available_uses_custom_template():
    """Template available custom pris en compte."""
    custom = "Disponible: {{ title }}"
    s = _settings(email_available_template=custom)
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_available_notification(s, _req(), "dest@example.com")

    body = mock_send.call_args[0][0].get_payload(0).get_payload(decode=True).decode()
    assert "Disponible: Inception" in body


@pytest.mark.asyncio
async def test_send_available_vf_uses_merged_template():
    """Disponibilité initiale VF : le status phrase est 'est maintenant disponible en VF !'."""
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_available_notification(_settings(), _req(), "dest@example.com", language="vf")

    msg = mock_send.call_args[0][0]
    assert msg["Subject"] == "[Plexarr] Le film Inception est maintenant disponible en VF !"
    body = msg.get_payload(0).get_payload(decode=True).decode()
    assert "est maintenant disponible en VF !" in body


@pytest.mark.asyncio
async def test_send_available_vo_tracking_uses_merged_template():
    """Disponibilité initiale VO : annonce la dispo VO avec le tracking dans la note_phrase."""
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_available_notification(_settings(), _req(), "dest@example.com", language="vo")

    msg = mock_send.call_args[0][0]
    assert "est maintenant disponible en VO !" in msg["Subject"]
    body = msg.get_payload(0).get_payload(decode=True).decode()
    assert "est maintenant disponible en VO !" in body
    assert "serez notifi" in body


@pytest.mark.asyncio
async def test_send_vf_available_uses_episode_milestone_template():
    """Un jalon VF par épisode : subject episode et status upgrade."""
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_available_notification(
            _settings(), _req(media_type="show", season_number=1, episode_number=2), "dest@example.com", scope="episode", language="vf", is_upgrade=True
        )

    msg = mock_send.call_args[0][0]
    assert "L'épisode S01E02 de Inception est maintenant disponible en VF ! (Mise à jour)" in msg["Subject"]
    body = msg.get_payload(0).get_payload(decode=True).decode()
    assert "est maintenant disponible en VF ! (Mise à jour)" in body


@pytest.mark.asyncio
async def test_send_vf_available_upgrade_uses_update_badge():
    """Upgrade VF générique : note upgrade présente dans l'email."""
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_available_notification(_settings(), _req(), "dest@example.com", language="vf", is_upgrade=True)

    msg = mock_send.call_args[0][0]
    assert "Le film Inception est maintenant disponible en VF ! (Mise à jour)" in msg["Subject"]
    body = msg.get_payload(0).get_payload(decode=True).decode()
    assert "est maintenant disponible en VF ! (Mise à jour)" in body
    assert "remplacé la version originale" in body


@pytest.mark.asyncio
async def test_send_vo_only_uses_season_start_milestone_template():
    """Un jalon VO début de saison utilise le subject season_start."""
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_available_notification(
            _settings(), _req(media_type="show", season_number=1), "dest@example.com", scope="season_start", language="vo"
        )

    msg = mock_send.call_args[0][0]
    assert "Le premier épisode de la saison 1 de Inception est maintenant disponible en VO !" in msg["Subject"]
    body = msg.get_payload(0).get_payload(decode=True).decode()
    assert "Le premier épisode de la saison 1 de Inception" in body


# ---------------------------------------------------------------------------
# availability milestone rendering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_partially_available_includes_episode_counts():
    """Email de disponibilité partielle (legacy test adapted) : episode scope subject."""
    req = _req(
        media_type="show",
        title="Breaking Bad",
        season_number=1,
        episode_number=3,
        episodes_available_count=3,
        episodes_aired_count=5,
        episodes_total_count=10,
    )
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_available_notification(_settings(), req, "dest@example.com", scope="episode")

@pytest.mark.asyncio
async def test_send_failure_includes_reason():
    """Email d'Ã©chec contient la raison fournie."""
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_failure_notification(_settings(), _req(), "dest@example.com", reason="Sonarr injoignable")

    msg = mock_send.call_args[0][0]
    body = msg.get_payload(0).get_payload(decode=True).decode()
    assert "Sonarr injoignable" in body


@pytest.mark.asyncio
async def test_send_failure_subject():
    """Sujet de l'email d'Ã©chec contient le titre du mÃ©dia."""
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_failure_notification(_settings(), _req(), "dest@example.com")

    assert "Inception" in mock_send.call_args[0][0]["Subject"]


@pytest.mark.asyncio
async def test_send_failure_uses_custom_template_and_subject():
    """Template d'Ã©chec customisÃ© et sujet personnalisÃ©."""
    s = _settings(
        email_failure_template="Ã‰chec: {{ title }} - {{ reason }}", email_failure_subject="Alerte: {{ title }}"
    )
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_failure_notification(s, _req(), "dest@example.com", reason="Erreur API")

    msg = mock_send.call_args[0][0]
    assert msg["Subject"] == "Alerte: Inception"
    body = msg.get_payload(0).get_payload(decode=True).decode()
    assert "Ã‰chec: Inception - Erreur API" in body


# ---------------------------------------------------------------------------
# _send â€” configuration SMTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_uses_starttls_when_smtp_tls_true():
    """smtp_tls=True â†’ start_tls=True, use_tls=False passÃ© Ã  aiosmtplib."""
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_request_notification(_settings(smtp_tls=True), _req(), "dest@example.com")

    kwargs = mock_send.call_args[1]
    assert kwargs["start_tls"] is True
    assert kwargs["use_tls"] is False


@pytest.mark.asyncio
async def test_send_uses_ssl_when_smtp_tls_false():
    """smtp_tls=False â†’ use_tls=True, start_tls=False (SSL direct, port 465)."""
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_request_notification(_settings(smtp_tls=False), _req(), "dest@example.com")

    kwargs = mock_send.call_args[1]
    assert kwargs["use_tls"] is True
    assert kwargs["start_tls"] is False
