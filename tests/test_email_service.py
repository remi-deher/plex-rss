"""Tests unitaires pour app/services/email_service.py.

Le transport (SMTP classique/OAuth2/Brevo, choix du fournisseur, repli en cas
d'échec) vit dans app/services/email_providers.py — voir tests/test_email_providers.py.
Ici, on vérifie uniquement le rendu des templates et que `_send` délègue
correctement à `email_providers.send_with_fallback`.
"""

from contextlib import contextmanager
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


def _settings(**kwargs) -> Settings:
    defaults = dict(
        smtp_from="plex@example.com",
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


class _FakeSessionContext:
    """Evite d'ouvrir une vraie connexion DB : `_send` ne s'en sert que pour la
    transmettre telle quelle à send_with_fallback (mocké ci-dessous), jamais pour
    l'interroger elle-même."""

    async def __aenter__(self):
        return None

    async def __aexit__(self, *a):
        return False


@contextmanager
def _patch_send():
    """Mock du point d'entrée transport : `_send` délègue tout à send_with_fallback,
    lui-même chargé de choisir/basculer entre fournisseurs (voir email_providers.py)."""
    with (
        patch("app.services.email_service.AsyncSessionLocal", lambda: _FakeSessionContext()),
        patch("app.services.email_service.email_providers.send_with_fallback", new=AsyncMock()) as mock_send,
    ):
        yield mock_send


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
    assert "Erreur de rendu du template" in result


def test_render_subject_substitutes_tags():
    subject = render_subject("Nouveau : {titre}", {"{titre}": "Inception"}, fallback="fallback")
    assert subject == "Nouveau : Inception"


def test_render_subject_falls_back_when_empty():
    subject = render_subject("   ", {}, fallback="[Plexarr] Fallback")
    assert subject == "[Plexarr] Fallback"


def test_season_template_variables_support_subjects_and_grouped_seasons():
    req = _req(media_type="show")
    tags = _build_tags(
        req,
        scope="season_complete",
        season_number=1,
        availability_details={"available_seasons": [4, 1, 2]},
    )

    assert tags["{numero_saison}"] == "1"
    assert tags["{saison}"] == "Saison 1"
    assert tags["{saisons_concernees}"] == "Saison 1, 2 et 4"
    assert render_subject("{titre} - {saisons_concernees}", tags, fallback="fallback") == f"{req.title} - Saison 1, 2 et 4"


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
    with _patch_send() as mock_send:
        await send_request_notification(_settings(), _req(), "dest@example.com")

    mock_send.assert_awaited_once()
    _db, sender, recipient, subject, _html = mock_send.call_args[0]
    assert sender == "plex@example.com"
    assert recipient == "dest@example.com"
    assert subject == "[Plexarr] Nouvelle demande : Inception"


@pytest.mark.asyncio
async def test_send_request_uses_custom_template():
    """Template custom défini (tag {titre}) → rendu avec les variables du média."""
    custom = "Film demandé : {titre}"
    s = _settings(email_request_template=custom)
    with _patch_send() as mock_send:
        await send_request_notification(s, _req(), "dest@example.com")

    html = mock_send.call_args[0][4]
    assert "Film demandé : Inception" in html


@pytest.mark.asyncio
async def test_send_request_includes_footer_credit():
    """Le pied de page Plexarr/DEHER est injecté dans la coquille email pour tout envoi."""
    with _patch_send() as mock_send:
        await send_request_notification(_settings(), _req(), "dest@example.com")

    html = mock_send.call_args[0][4]
    assert "DEHER" in html


@pytest.mark.asyncio
async def test_send_propagates_failure_from_providers():
    """Aucun fournisseur actif / tous en échec → exception propagée (pas de succès silencieux).

    Un retour silencieux remonterait comme un succès jusqu'à _send_with_retry (aucune
    exception = tentative réussie) : request_mail_sent serait posé à True et un
    NotificationLog success=True créé alors qu'aucun email n'a été envoyé.
    """
    with (
        patch("app.services.email_service.AsyncSessionLocal", lambda: _FakeSessionContext()),
        patch(
            "app.services.email_service.email_providers.send_with_fallback",
            new=AsyncMock(side_effect=RuntimeError("Aucun fournisseur d'email configuré et actif")),
        ),
    ):
        with pytest.raises(RuntimeError, match="Aucun fournisseur"):
            await send_request_notification(_settings(), _req(), "dest@example.com")


# ---------------------------------------------------------------------------
# send_available_notification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_available_default_subject():
    with _patch_send() as mock_send:
        await send_available_notification(_settings(), _req(), "dest@example.com")

    subject = mock_send.call_args[0][3]
    assert "Inception" in subject


@pytest.mark.asyncio
async def test_send_available_uses_custom_template():
    custom = "Disponible : {titre}"
    s = _settings(email_available_template=custom)
    with _patch_send() as mock_send:
        await send_available_notification(s, _req(), "dest@example.com")

    html = mock_send.call_args[0][4]
    assert "Disponible : Inception" in html


@pytest.mark.asyncio
async def test_send_available_vf_language_tag():
    """language='vf' → le tag {langue} vaut 'en VF' dans le corps."""
    with _patch_send() as mock_send:
        await send_available_notification(_settings(), _req(), "dest@example.com", language="vf")

    html = mock_send.call_args[0][4]
    assert "en VF" in html


@pytest.mark.asyncio
async def test_send_available_vo_language_tag():
    with _patch_send() as mock_send:
        await send_available_notification(_settings(), _req(), "dest@example.com", language="vo")

    html = mock_send.call_args[0][4]
    assert "en VO" in html


@pytest.mark.asyncio
async def test_send_available_upgrade_uses_upgrade_template_and_subject():
    """is_upgrade=True → email_upgrade_template/subject utilisés (pas email_available_*)."""
    s = _settings(email_upgrade_template="Mise à jour : {titre}", email_upgrade_subject="Upgrade: {titre}")
    with _patch_send() as mock_send:
        await send_available_notification(s, _req(), "dest@example.com", language="vf", is_upgrade=True)

    _db, _sender, _recipient, subject, html = mock_send.call_args[0]
    assert subject == "Upgrade: Inception"
    assert "Mise à jour : Inception" in html


@pytest.mark.asyncio
async def test_send_available_episode_scope_details_tag():
    """scope='episode' avec saison/épisode → {details_saison_episode} renseigné dans le corps."""
    s = _settings(email_available_template="{titre} {details_saison_episode}")
    req = _req(media_type="show", title="Breaking Bad")
    with _patch_send() as mock_send:
        await send_available_notification(
            s, req, "dest@example.com", scope="episode", season_number=1, episode_number=3
        )

    html = mock_send.call_args[0][4]
    assert "Saison 1, Épisode 3" in html


@pytest.mark.asyncio
async def test_series_complete_uses_dedicated_template_and_variables():
    settings = _settings(
        email_series_complete_template="Serie terminee : {titre} ({nombre_saisons_completes}/{nombre_saisons_attendues})",
        email_series_complete_subject="Serie complete : {titre}",
    )
    request = _req(media_type="show", title="Breaking Bad")
    details = {
        "availability_variant": "series_complete",
        "available_seasons": [1, 2, 3, 4, 5],
        "complete_seasons": [1, 2, 3, 4, 5],
        "expected_seasons": [1, 2, 3, 4, 5],
    }
    with _patch_send() as mock_send:
        await send_available_notification(
            settings,
            request,
            "dest@example.com",
            scope="series_batch",
            availability_variant="series_complete",
            availability_details=details,
        )

    _db, _sender, _recipient, subject, html = mock_send.call_args[0]
    assert subject == "Serie complete : Breaking Bad"
    assert "Serie terminee : Breaking Bad (5/5)" in html


# ---------------------------------------------------------------------------
# send_failure_notification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_failure_includes_reason():
    with _patch_send() as mock_send:
        await send_failure_notification(_settings(), _req(), "dest@example.com", reason="Sonarr injoignable")

    html = mock_send.call_args[0][4]
    assert "Sonarr injoignable" in html


@pytest.mark.asyncio
async def test_send_failure_subject_contains_title():
    with _patch_send() as mock_send:
        await send_failure_notification(_settings(), _req(), "dest@example.com")

    assert "Inception" in mock_send.call_args[0][3]


@pytest.mark.asyncio
async def test_send_failure_uses_custom_template_and_subject():
    s = _settings(email_failure_template="Échec : {titre} - {raison}", email_failure_subject="Alerte : {titre}")
    with _patch_send() as mock_send:
        await send_failure_notification(s, _req(), "dest@example.com", reason="Erreur API")

    _db, _sender, _recipient, subject, html = mock_send.call_args[0]
    assert subject == "Alerte : Inception"
    assert "Échec : Inception - Erreur API" in html


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
    with _patch_send() as mock_send:
        await send_correction_notification(
            _settings(), _req(), "dest@example.com", "Alice", ["Son corrigé"], correction_note="Fichier remplacé"
        )

    mock_send.assert_awaited_once()
    html = mock_send.call_args[0][4]
    assert "Son corrigé" in html
    assert "Fichier remplacé" in html
