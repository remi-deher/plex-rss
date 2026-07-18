"""Tests unitaires pour app/services/email_service.py."""

from unittest.mock import AsyncMock, patch

import pytest

from app.models import MediaRequest, Settings
from app.services.email_service import (
    _build_tags,
    build_correction_email,
    build_tmdb_url,
    get_event_visuals,
    get_shared_email_parts,
    render_subject,
    render_template,
    resolve_plex_deep_link,
    send_available_notification,
    send_correction_notification,
    send_failure_notification,
    send_request_notification,
)
from app.services.email_service import test_smtp as smtp_test_connection


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
        email_failure_template=None,
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
# render_template / render_subject
# ---------------------------------------------------------------------------


def test_render_template_substitutes_tags():
    """Les tags {tag} sont remplacés par leur valeur avant conversion Markdown."""
    result = render_template("Hello {titre} ({annee})", {"{titre}": "Inception", "{annee}": "2010"}, {})
    assert "Inception" in result
    assert "2010" in result


def test_render_template_invalid_jinja_returns_error_html():
    """Un template dont le rendu Jinja (coquille) échoue retourne un message d'erreur (pas d'exception)."""
    # jinja_ctx incomplet : {{ _brand_color }} référencé par la coquille n'est pas fourni,
    # Jinja2 le traite comme une variable indéfinie (chaîne vide), donc pas d'erreur ici.
    # Pour provoquer une véritable erreur de syntaxe, on injecte un tag corrompant le Jinja.
    result = render_template("{{{invalid", {}, {})
    assert "Erreur de template" in result


def test_render_subject_substitutes_tags():
    subject = render_subject("Nouveau : {titre}", {"{titre}": "Inception"}, fallback="fallback")
    assert subject == "Nouveau : Inception"


def test_render_subject_falls_back_when_empty():
    subject = render_subject("   ", {}, fallback="[Plexarr] Fallback")
    assert subject == "[Plexarr] Fallback"


# ---------------------------------------------------------------------------
# get_shared_email_parts / get_event_visuals
# ---------------------------------------------------------------------------


def test_get_shared_email_parts_defaults_without_settings():
    parts = get_shared_email_parts(None)
    assert parts["_show_poster"] is True
    assert "_footer_html" in parts


def test_get_shared_email_parts_respects_overrides():
    s = _settings(email_show_poster=False, email_brand_color="#123456")
    parts = get_shared_email_parts(s)
    assert parts["_show_poster"] is False
    assert parts["_brand_color"] == "#123456"


def test_get_shared_email_parts_omits_privacy_link_when_no_base_url():
    """Sans public_base_url configuree, pas de lien vers /privacy dans le pied de page --
    un lien absent vaut mieux qu'un lien casse ou pointant vers le mauvais domaine."""
    parts = get_shared_email_parts(_settings())
    assert "/privacy" not in parts["_footer_html"]


def test_get_shared_email_parts_includes_privacy_link_when_base_url_set():
    s = _settings(public_base_url="https://plexarr.example.com/")
    parts = get_shared_email_parts(s)
    assert 'href="https://plexarr.example.com/privacy"' in parts["_footer_html"]


def test_get_event_visuals_defaults_per_event():
    visuals = get_event_visuals(None, "request")
    assert visuals["_badge_text"] == "Nouvelle demande"
    visuals = get_event_visuals(None, "failure")
    assert visuals["_badge_text"] == "Action requise"


def test_get_event_visuals_respects_override():
    s = _settings(email_available_badge_text="Custom Badge")
    visuals = get_event_visuals(s, "available")
    assert visuals["_badge_text"] == "Custom Badge"


# ---------------------------------------------------------------------------
# build_tmdb_url
# ---------------------------------------------------------------------------


def test_build_tmdb_url_movie():
    url = build_tmdb_url(_req(tmdb_id="27205", media_type="movie"))
    assert url == "https://www.themoviedb.org/movie/27205"


def test_build_tmdb_url_show():
    url = build_tmdb_url(_req(tmdb_id="1396", media_type="show"))
    assert url == "https://www.themoviedb.org/tv/1396"


def test_build_tmdb_url_none_without_tmdb_id():
    assert build_tmdb_url(_req(tmdb_id=None)) is None


def test_build_tags_exposes_diagnostic_context():
    request = _req(
        title="Berceuse Mortelle",
        diagnostic_context='{"availability_source":"Radarr","arr_event":"Import",'
        '"plex_match_status":"confirmed","plex_match_method":"tmdb",'
        '"plex_match_title":"Berceuse Mortelle"}',
    )
    tags = _build_tags(request)
    assert tags["{source_disponibilite}"] == "Radarr"
    assert tags["{evenement_arr}"] == "Import"
    assert tags["{statut_plex}"] == "confirmed"
    assert tags["{methode_correspondance_plex}"] == "tmdb"


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
    assert msg["Subject"] == "[Plexarr] Nouvelle demande : Inception"


@pytest.mark.asyncio
async def test_send_request_uses_custom_template():
    """Template custom défini (tag {titre}) → rendu avec les variables du média."""
    custom = "Film demandé : {titre}"
    s = _settings(email_request_template=custom)
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_request_notification(s, _req(), "dest@example.com")

    body = mock_send.call_args[0][0].get_payload(0).get_payload(decode=True).decode()
    assert "Film demandé : Inception" in body


@pytest.mark.asyncio
async def test_send_request_includes_footer_credit():
    """Le pied de page Plexarr/DEHER est injecté dans la coquille email pour tout envoi."""
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_request_notification(_settings(), _req(), "dest@example.com")

    body = mock_send.call_args[0][0].get_payload(0).get_payload(decode=True).decode()
    assert "DEHER" in body


@pytest.mark.asyncio
async def test_send_raises_when_smtp_not_configured():
    """SMTP non configuré → exception levée (pas de succès silencieux sans envoi réel).

    Un retour silencieux remonterait comme un succès jusqu'à _send_with_retry (aucune
    exception = tentative réussie) : request_mail_sent serait posé à True et un
    NotificationLog success=True créé alors qu'aucun email n'a été envoyé.
    """
    s = _settings(smtp_host=None)
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        with pytest.raises(RuntimeError, match="incomplète"):
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
async def test_send_available_default_subject():
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_available_notification(_settings(), _req(), "dest@example.com")

    msg = mock_send.call_args[0][0]
    assert "Inception" in msg["Subject"]


@pytest.mark.asyncio
async def test_send_available_uses_custom_template():
    custom = "Disponible : {titre}"
    s = _settings(email_available_template=custom)
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_available_notification(s, _req(), "dest@example.com")

    body = mock_send.call_args[0][0].get_payload(0).get_payload(decode=True).decode()
    assert "Disponible : Inception" in body


@pytest.mark.asyncio
async def test_send_available_vf_language_tag():
    """language='vf' → le tag {langue} vaut 'en VF' dans le corps."""
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_available_notification(_settings(), _req(), "dest@example.com", language="vf")

    body = mock_send.call_args[0][0].get_payload(0).get_payload(decode=True).decode()
    assert "en VF" in body


@pytest.mark.asyncio
async def test_send_available_vo_language_tag():
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_available_notification(_settings(), _req(), "dest@example.com", language="vo")

    body = mock_send.call_args[0][0].get_payload(0).get_payload(decode=True).decode()
    assert "en VO" in body


@pytest.mark.asyncio
async def test_send_available_upgrade_uses_upgrade_template_and_subject():
    """is_upgrade=True → email_upgrade_template/subject utilisés (pas email_available_*)."""
    s = _settings(email_upgrade_template="Mise à jour : {titre}", email_upgrade_subject="Upgrade: {titre}")
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_available_notification(s, _req(), "dest@example.com", language="vf", is_upgrade=True)

    msg = mock_send.call_args[0][0]
    assert msg["Subject"] == "Upgrade: Inception"
    body = msg.get_payload(0).get_payload(decode=True).decode()
    assert "Mise à jour : Inception" in body


@pytest.mark.asyncio
async def test_send_available_episode_scope_details_tag():
    """scope='episode' avec saison/épisode → {details_saison_episode} renseigné dans le corps."""
    s = _settings(email_available_template="{titre} {details_saison_episode}")
    req = _req(media_type="show", title="Breaking Bad")
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_available_notification(
            s, req, "dest@example.com", scope="episode", season_number=1, episode_number=3
        )

    body = mock_send.call_args[0][0].get_payload(0).get_payload(decode=True).decode()
    assert "Saison 1, Épisode 3" in body


# ---------------------------------------------------------------------------
# send_failure_notification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_failure_includes_reason():
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_failure_notification(_settings(), _req(), "dest@example.com", reason="Sonarr injoignable")

    body = mock_send.call_args[0][0].get_payload(0).get_payload(decode=True).decode()
    assert "Sonarr injoignable" in body


@pytest.mark.asyncio
async def test_send_failure_subject_contains_title():
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_failure_notification(_settings(), _req(), "dest@example.com")

    assert "Inception" in mock_send.call_args[0][0]["Subject"]


@pytest.mark.asyncio
async def test_send_failure_uses_custom_template_and_subject():
    s = _settings(email_failure_template="Échec : {titre} - {raison}", email_failure_subject="Alerte : {titre}")
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_failure_notification(s, _req(), "dest@example.com", reason="Erreur API")

    msg = mock_send.call_args[0][0]
    assert msg["Subject"] == "Alerte : Inception"
    body = msg.get_payload(0).get_payload(decode=True).decode()
    assert "Échec : Inception - Erreur API" in body


# ---------------------------------------------------------------------------
# _send — configuration SMTP (TLS/SSL)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_uses_starttls_when_smtp_tls_true():
    """smtp_tls=True → start_tls=True, use_tls=False passé à aiosmtplib."""
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_request_notification(_settings(smtp_tls=True), _req(), "dest@example.com")

    kwargs = mock_send.call_args[1]
    assert kwargs["start_tls"] is True
    assert kwargs["use_tls"] is False


@pytest.mark.asyncio
async def test_send_uses_ssl_when_smtp_tls_false():
    """smtp_tls=False → use_tls=True, start_tls=False (SSL direct, port 465)."""
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_request_notification(_settings(smtp_tls=False), _req(), "dest@example.com")

    kwargs = mock_send.call_args[1]
    assert kwargs["use_tls"] is True
    assert kwargs["start_tls"] is False


# ---------------------------------------------------------------------------
# resolve_plex_deep_link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_plex_deep_link_none_without_plex_config():
    """Sans plex_url/plex_token configurés → None (best-effort, jamais d'exception)."""
    link = await resolve_plex_deep_link(_settings(), _req())
    assert link is None


# ---------------------------------------------------------------------------
# build_correction_email / send_correction_notification
# ---------------------------------------------------------------------------


def test_build_correction_email_includes_corrections_and_subject():
    subject, html = build_correction_email(
        _settings(),
        _req(),
        "Alice",
        ["Son corrigé", "Sous-titres resynchronisés"],
        plex_deep_link="https://app.plex.tv/desktop/#!/details",
    )
    assert "Inception" in subject
    assert "Son corrigé" in html
    assert "Sous-titres resynchronisés" in html


@pytest.mark.asyncio
async def test_send_correction_notification_sends_email():
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_correction_notification(
            _settings(), _req(), "dest@example.com", "Alice", ["Son corrigé"], correction_note="Fichier remplacé"
        )

    mock_send.assert_called_once()
    body = mock_send.call_args[0][0].get_payload(0).get_payload(decode=True).decode()
    assert "Son corrigé" in body
    assert "Fichier remplacé" in body


# ---------------------------------------------------------------------------
# test_smtp
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smtp_connection_check_success():
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()):
        ok, message = await smtp_test_connection(_settings(), "dest@example.com")

    assert ok is True
    assert "dest@example.com" in message


@pytest.mark.asyncio
async def test_smtp_connection_check_failure_returns_error_message():
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock(side_effect=Exception("auth failed"))):
        ok, message = await smtp_test_connection(_settings(), "dest@example.com")

    assert ok is False
    assert "auth failed" in message
