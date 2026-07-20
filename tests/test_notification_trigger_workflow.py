"""Contrat complet des déclencheurs de notification de disponibilité.

Ces tests couvrent le parcours métier : jalon détecté -> contexte persisté dans la
file -> variante fonctionnelle -> template email. La matrice est volontairement
explicite pour qu'un nouveau déclencheur ne soit pas ajouté sans scénario associé.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base, MediaRequest, PendingNotification, PlexUser, RequestStatus, Settings
from app.services.acquisition_batches import classify_batch_availability
from app.services.email_service import SERIES_AVAILABILITY_DEFAULTS, send_available_notification
from app.services.notification_orchestrator import AvailabilityCandidate, _notify, resolve_and_notify_availability


IMMEDIATE_TRIGGER_CASES = (
    pytest.param("movie", "movie", None, False, None, None, id="film-generique"),
    pytest.param("movie", "movie", "vo", False, None, None, id="film-vo"),
    pytest.param("movie", "movie", "vf", False, None, None, id="film-vf"),
    pytest.param("movie", "movie", "vf", True, None, None, id="film-amelioration-vf"),
    pytest.param("show", "episode", None, False, 2, 4, id="episode-unique"),
    pytest.param("show", "season_start", None, False, 2, 1, id="debut-saison"),
    pytest.param("show", "season_complete", None, False, 2, None, id="saison-complete"),
    pytest.param("show", "series_complete", None, False, None, None, id="serie-complete"),
)


BATCH_TRIGGER_CASES = (
    pytest.param(
        [{"scope": "episode", "season_number": 1, "episode_number": 1}],
        [1, 2], "episode_available", id="lot-episode-unique",
    ),
    pytest.param(
        [
            {"scope": "episode", "season_number": 1, "episode_number": 1},
            {"scope": "episode", "season_number": 1, "episode_number": 2},
        ],
        [1, 2], "season_partial", id="lot-saison-partielle",
    ),
    pytest.param(
        [{"scope": "season_start", "season_number": 1, "episode_number": 1}],
        [1, 2], "season_started", id="lot-saison-demarree",
    ),
    pytest.param(
        [{"scope": "season_complete", "season_number": 1}],
        [1, 2], "season_complete", id="lot-une-saison-complete",
    ),
    pytest.param(
        [
            {"scope": "season_complete", "season_number": 1},
            {"scope": "season_complete", "season_number": 2},
        ],
        [1, 2, 3], "series_partial", id="lot-plusieurs-saisons-completes",
    ),
    pytest.param(
        [
            {"scope": "season_complete", "season_number": 1},
            {"scope": "season_complete", "season_number": 2},
        ],
        [1, 2], "series_complete", id="lot-serie-complete",
    ),
)


TEMPLATE_CASES = (
    pytest.param("episode_available", "episode", id="template-episode"),
    pytest.param("season_started", "season_start", id="template-debut-saison"),
    pytest.param("season_partial", "series_batch", id="template-saison-partielle"),
    pytest.param("season_complete", "season_complete", id="template-saison-complete"),
    pytest.param("series_partial", "series_batch", id="template-serie-partielle"),
    pytest.param("series_complete", "series_complete", id="template-serie-complete"),
)


GENERIC_TRIGGER_CASES = (
    pytest.param("request", "request", None, id="nouvelle-demande"),
    pytest.param("failed", "failed", {"reason": "Sonarr indisponible"}, id="echec-transmission"),
)


async def _make_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "media_type,scope,language,is_upgrade,season_number,episode_number",
    IMMEDIATE_TRIGGER_CASES,
)
async def test_immediate_trigger_is_persisted_through_notification_queue(
    media_type, scope, language, is_upgrade, season_number, episode_number
):
    """Chaque déclencheur immédiat conserve tout son contexte jusqu'à la file."""
    engine, db = await _make_db()
    settings = Settings(
        id=1,
        email_on_available=True,
        email_on_vf_available=True,
        movie_notify_language=True,
        series_notify_language=True,
    )
    user = PlexUser(
        plex_user_id="alice",
        enabled=True,
        notification_email="alice@example.com",
        notify_vf_movie=True,
        notify_vf_series=True,
    )
    req = MediaRequest(
        plex_user_id="alice",
        plex_user="Alice",
        title="Média de test",
        media_type=media_type,
        status=RequestStatus.available,
        has_vf=True if language == "vf" else False if language == "vo" else None,
    )
    db.add_all([settings, user, req])
    await db.commit()

    candidate = AvailabilityCandidate(
        scope=scope,
        language=language,
        is_upgrade=is_upgrade,
        season_number=season_number,
        episode_number=episode_number,
    )
    with patch("app.notification_queue.schedule_pending_notification", new_callable=AsyncMock) as schedule:
        queued = await resolve_and_notify_availability(settings, req, db, candidates=[candidate])

    assert queued is True
    pending = (await db.execute(select(PendingNotification))).scalars().one()
    assert pending.event == "available"
    assert json.loads(pending.recipients) == ["alice@example.com"]
    assert json.loads(pending.reason) == {
        "scope": scope,
        "language": language,
        "is_upgrade": is_upgrade,
        "season_number": season_number,
        "episode_number": episode_number,
    }
    schedule.assert_awaited_once_with(
        pending.id,
        "available",
        req.id,
        ["alice@example.com"],
        {
            "scope": scope,
            "language": language,
            "is_upgrade": is_upgrade,
            "season_number": season_number,
            "episode_number": episode_number,
        },
    )
    await db.close()
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger,queued_event,expected_context", GENERIC_TRIGGER_CASES)
async def test_generic_trigger_enters_notification_workflow(trigger, queued_event, expected_context):
    """Demande et échec rejoignent la même file avec le bon événement métier."""
    engine, db = await _make_db()
    settings = Settings(id=1, email_on_request=True, email_on_failure=True)
    user = PlexUser(plex_user_id="alice", enabled=True, notification_email="alice@example.com")
    req = MediaRequest(
        plex_user_id="alice",
        plex_user="Alice",
        title="Média de test",
        media_type="movie",
        status=RequestStatus.failed if trigger == "failed" else RequestStatus.pending,
    )
    db.add_all([settings, user, req])
    await db.commit()

    reason = "Sonarr indisponible" if trigger == "failed" else ""
    with patch("app.services.notification_orchestrator.enqueue", new_callable=AsyncMock) as enqueue:
        await _notify(trigger, settings, req, db, reason=reason)

    enqueue.assert_awaited_once_with(
        queued_event,
        req.id,
        ["alice@example.com"],
        expected_context,
        triggered_by="auto",
    )
    await db.close()
    await engine.dispose()


@pytest.mark.parametrize("events,expected_seasons,expected_variant", BATCH_TRIGGER_CASES)
def test_sonarr_batch_trigger_classification(events, expected_seasons, expected_variant):
    """Une vague Sonarr produit le bon niveau de notification récapitulative."""
    result = classify_batch_availability(events, expected_seasons)
    assert result["availability_variant"] == expected_variant


@pytest.mark.asyncio
@pytest.mark.parametrize("variant,scope", TEMPLATE_CASES)
async def test_availability_variant_reaches_its_email_template(variant, scope):
    """Le contexte issu du déclencheur sélectionne le template fonctionnel attendu."""
    settings = Settings(id=1)
    req = MediaRequest(
        id=1,
        plex_user_id="alice",
        plex_user="Alice",
        title="Série de test",
        media_type="show",
        status=RequestStatus.available,
    )
    with (
        patch("app.services.email_service._send_templated", new_callable=AsyncMock) as send,
        patch("app.services.email_service.resolve_plex_deep_link", new_callable=AsyncMock, return_value=None),
    ):
        await send_available_notification(
            settings,
            req,
            "alice@example.com",
            scope=scope,
            season_number=2,
            episode_number=4,
            availability_variant=variant,
            availability_details={"availability_variant": variant},
        )

    assert send.await_args.kwargs["template_field"] == f"email_{variant}_template"
    assert send.await_args.kwargs["subject_field"] == f"email_{variant}_subject"


def test_template_matrix_covers_every_series_availability_variant():
    """Garde-fou : toute nouvelle variante doit obtenir un scénario dans ce fichier."""
    assert {case.values[0] for case in TEMPLATE_CASES} == set(SERIES_AVAILABILITY_DEFAULTS)
