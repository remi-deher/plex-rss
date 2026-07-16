"""Tests unitaires pour app/scheduler.py — poll_watchlists et check_arr_statuses."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, LibraryItem, MediaRequest, PlexUser, RequestStatus, Settings
from app.scheduler import check_arr_statuses, poll_watchlists, sync_users_from_feed
from tests.async_support import TestSession

# ---------------------------------------------------------------------------
# Fixtures DB in-memory
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = TestSession(Session())
    yield session
    session.close()


def _settings(**kwargs) -> Settings:
    defaults = dict(
        sonarr_url="http://sonarr.local",
        sonarr_api_key="key",
        sonarr_enabled=True,
        sonarr_quality_profile_id=1,
        sonarr_root_folder="/tv",
        radarr_url="http://radarr.local",
        radarr_api_key="key",
        radarr_enabled=True,
        radarr_quality_profile_id=1,
        radarr_root_folder="/movies",
        radarr_minimum_availability="released",
        seer_enabled=False,
        # plex_url/plex_token configurés par défaut : has_plex_proof() bypass en True
        # (proof toujours considérée acquise) dès que l'un des deux est absent, ce qui
        # rendrait ces tests de disponibilité muets. Un LibraryItem non-matchant
        # (_unmatched_library_item ci-dessous) est nécessaire en complément pour forcer
        # un vrai contrôle de correspondance (has_plex_proof bypasse aussi si la table
        # LibraryItem est vide).
        plex_url="http://plex.local",
        plex_token="plex-token",
        email_on_request=True,
        email_on_available=True,
        smtp_from="admin@example.com",
        admin_notification_email=None,
        vff_enabled=False,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _unmatched_library_item(**kwargs) -> LibraryItem:
    """LibraryItem qui ne correspond à aucune des demandes de test ci-dessous.

    Force has_plex_proof() à effectuer une vraie recherche de correspondance
    (count(LibraryItem) > 0) sans jamais matcher — la demande reste donc sans
    preuve Plex, comme avant l'introduction du bypass "bibliothèque vide".
    """
    defaults = dict(
        title="Some Other Movie",
        year=1999,
        media_type="movie",
        tmdb_id="999999",
        tvdb_id=None,
        imdb_id=None,
        plex_guid="plex://movie/unrelated",
        poster_url=None,
        overview="",
        added_at=None,
        arr_instance_id=None,
        arr_id=None,
        arr_slug=None,
    )
    defaults.update(kwargs)
    return LibraryItem(**defaults)


def _movie_item(**kwargs) -> dict:
    defaults = dict(
        title="Inception",
        year=2010,
        media_type="movie",
        plex_user="alice",
        plex_user_id="alice",
        tmdb_id="27205",
        tvdb_id=None,
        imdb_id="tt1375666",
        plex_guid="plex://movie/abc",
        poster_url=None,
        overview="",
        source="api",
    )
    defaults.update(kwargs)
    return defaults


def _show_item(**kwargs) -> dict:
    defaults = dict(
        title="Breaking Bad",
        year=2008,
        media_type="show",
        plex_user="alice",
        plex_user_id="alice",
        tmdb_id=None,
        tvdb_id="81189",
        imdb_id=None,
        plex_guid="plex://show/xyz",
        poster_url=None,
        overview="",
        source="api",
    )
    defaults.update(kwargs)
    return defaults


# ---------------------------------------------------------------------------
# Helpers de patch
# ---------------------------------------------------------------------------


def _patch_session_poller(db):
    """Remplace SessionLocal pour watchlist_poller."""
    return patch("app.services.watchlist_poller.AsyncSessionLocal", return_value=db)


@contextmanager
def _patch_session_arr(db):
    """Remplace SessionLocal pour arr_tracker."""
    with (
        patch("app.services.arr_tracker.AsyncSessionLocal", return_value=db),
        patch("app.services.arr_tracker.get_all_movies", new=AsyncMock(return_value=[])),
        patch("app.services.arr_tracker.get_all_series", new=AsyncMock(return_value=[])),
        patch("app.services.arr_tracker.get_queue_movie_ids", new=AsyncMock(return_value=set())),
        patch("app.services.arr_tracker.get_queue_series_ids", new=AsyncMock(return_value=set())),
        patch("app.services.arr_tracker.movie_exists", new=AsyncMock(return_value=True)),
        patch("app.services.arr_tracker.series_exists", new=AsyncMock(return_value=True)),
        patch("app.services.arr_tracker._refresh_next_release", new=AsyncMock()),
    ):
        yield


def _patch_session(db):
    """Remplace SessionLocal par une factory retournant la session de test (poller par défaut)."""
    return patch("app.services.watchlist_poller.AsyncSessionLocal", return_value=db)


def _patch_watchlist(items):
    return patch("app.services.watchlist_poller.fetch_watchlist", new=AsyncMock(return_value=items))


def _patch_submit(arr_id=42, already_existed=False, arr_slug="inception"):
    return patch(
        "app.services.watchlist_poller._submit_to_arr",
        new=AsyncMock(return_value=(arr_id, already_existed, arr_slug)),
    )


def _patch_enqueue():
    return patch("app.services.notification_orchestrator.enqueue", new_callable=AsyncMock)


# ---------------------------------------------------------------------------
# poll_watchlists — cas nominaux
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_new_item_creates_request_and_notifies(db):
    """Nouvel item → MediaRequest créé avec status sent_to_arr, notification enqueued."""
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.commit()

    with _patch_session(db), _patch_watchlist([_movie_item()]), _patch_submit(), _patch_enqueue() as mock_enqueue:
        await poll_watchlists()

    req = db.query(MediaRequest).first()
    assert req is not None
    assert req.title == "Inception"
    assert req.status == RequestStatus.sent_to_arr
    assert req.arr_id == 42
    mock_enqueue.assert_called_once()
    event = mock_enqueue.call_args[0][0]
    assert event == "request"


@pytest.mark.asyncio
async def test_poll_old_watchlist_item_suppresses_notification(db):
    """Item watchlist dont la date reelle d'ajout (pubDate RSS) depasse deja 24h a la
    detection (resurgit dans le flux RSS limite a 50 entrees, voir plex_rss.py) :
    la demande est bien creee/transmise a *arr, mais aucune notification n'est enqueuee,
    et notify_suppressed est pose une fois pour toutes.
    """
    from datetime import timedelta
    from app.utils import now_utc_naive

    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.commit()

    old_date = now_utc_naive() - timedelta(days=10)
    with (
        _patch_session(db),
        _patch_watchlist([_movie_item(requested_at=old_date)]),
        _patch_submit(),
        _patch_enqueue() as mock_enqueue,
    ):
        await poll_watchlists()

    req = db.query(MediaRequest).first()
    assert req is not None
    assert req.status == RequestStatus.sent_to_arr
    assert req.arr_id == 42
    assert req.notify_suppressed is True
    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_poll_recent_watchlist_item_does_not_suppress(db):
    """Item watchlist ajoute il y a moins de 24h : comportement normal, notifie."""
    from datetime import timedelta
    from app.utils import now_utc_naive

    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.commit()

    recent_date = now_utc_naive() - timedelta(hours=2)
    with (
        _patch_session(db),
        _patch_watchlist([_movie_item(requested_at=recent_date)]),
        _patch_submit(),
        _patch_enqueue() as mock_enqueue,
    ):
        await poll_watchlists()

    req = db.query(MediaRequest).first()
    assert req.notify_suppressed is False
    mock_enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_poll_skipped_when_distributed_lock_held_elsewhere(db):
    """Verrou Redis déjà détenu (autre process/conteneur) → cycle ignoré, aucun traitement.

    Couvre l'incident : deux MediaRequest identiques créées à 369ms d'écart (source
    'api') suite à un poll manuel via /api/requests/poll qui a couru en même temps que
    le cron ARQ dans le conteneur worker — le verrou asyncio local ne protège que dans
    un seul process, pas entre deux conteneurs distincts.
    """
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.commit()

    with (
        _patch_session(db),
        _patch_watchlist([_movie_item()]),
        _patch_submit() as mock_submit,
        patch("app.services.watchlist_poller._acquire_distributed_poll_lock", new=AsyncMock(return_value=None)),
    ):
        await poll_watchlists()

    mock_submit.assert_not_called()
    assert db.query(MediaRequest).count() == 0


@pytest.mark.asyncio
async def test_poll_releases_distributed_lock_after_run(db):
    """Le verrou Redis est relâché après un cycle, même en cas d'erreur, pour ne pas bloquer le suivant."""
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.commit()

    with (
        _patch_session(db),
        _patch_watchlist([_movie_item()]),
        _patch_submit(),
        _patch_enqueue(),
        patch(
            "app.services.watchlist_poller._acquire_distributed_poll_lock", new=AsyncMock(return_value="tok")
        ),
        patch("app.services.watchlist_poller._release_distributed_poll_lock", new=AsyncMock()) as mock_release,
    ):
        await poll_watchlists()

    mock_release.assert_called_once_with("tok")


@pytest.mark.asyncio
async def test_poll_requires_approval_for_standard_user(db):
    """Validation globale active -> demande creee mais pas transmise a Arr."""
    db.add(_settings(require_approval=True))
    db.add(PlexUser(plex_user_id="alice", enabled=True, role="user", auto_approve=False))
    db.commit()

    with (
        _patch_session(db),
        _patch_watchlist([_movie_item()]),
        _patch_submit() as mock_submit,
        _patch_enqueue() as mock_enqueue,
    ):
        await poll_watchlists()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.pending_approval
    mock_submit.assert_not_called()
    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_poll_auto_approved_user_bypasses_approval(db):
    """Un utilisateur auto_approve continue a partir directement vers Arr."""
    db.add(_settings(require_approval=True))
    db.add(PlexUser(plex_user_id="alice", enabled=True, role="user", auto_approve=True))
    db.commit()

    with _patch_session(db), _patch_watchlist([_movie_item()]), _patch_submit() as mock_submit, _patch_enqueue():
        await poll_watchlists()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.sent_to_arr
    mock_submit.assert_called_once()


@pytest.mark.asyncio
async def test_poll_existing_sent_to_arr_is_skipped(db):
    """Item déjà sent_to_arr → pas de doublon, pas de notification."""
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    existing = MediaRequest(
        plex_user_id="alice",
        plex_user="alice",
        title="Inception",
        media_type="movie",
        status=RequestStatus.sent_to_arr,
    )
    db.add(existing)
    db.commit()

    with (
        _patch_session(db),
        _patch_watchlist([_movie_item()]),
        _patch_submit() as mock_submit,
        _patch_enqueue() as mock_enqueue,
    ):
        await poll_watchlists()

    mock_submit.assert_not_called()
    mock_enqueue.assert_not_called()
    assert db.query(MediaRequest).count() == 1


@pytest.mark.asyncio
async def test_poll_failed_request_is_retried(db):
    """Item en statut failed → retenté et passé à sent_to_arr."""
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.add(
        MediaRequest(
            plex_user_id="alice",
            plex_user="alice",
            title="Inception",
            media_type="movie",
            status=RequestStatus.failed,
        )
    )
    db.commit()

    with _patch_session(db), _patch_watchlist([_movie_item()]), _patch_submit(), _patch_enqueue():
        await poll_watchlists()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.sent_to_arr
    assert db.query(MediaRequest).count() == 1  # pas de doublon


@pytest.mark.asyncio
async def test_poll_arr_error_sets_failed_and_notifies_failure(db):
    """Échec de _submit_to_arr → status failed, notification d'échec."""
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.commit()

    with (
        _patch_session(db),
        _patch_watchlist([_movie_item()]),
        # Patcher watchlist_poller._submit_to_arr (pas app.scheduler._submit_to_arr,
        # simple ré-export non résolu par _process_watchlist_item, qui referme sur le
        # nom module-local) : sans ça, le vrai appel réseau part et le test ne passe
        # que par accident (timeout DNS coïncidant avec le statut "failed" attendu).
        patch("app.services.watchlist_poller._submit_to_arr", new=AsyncMock(side_effect=Exception("timeout"))),
        _patch_enqueue() as mock_enqueue,
    ):
        await poll_watchlists()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.failed
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args[0][0] == "failed"


@pytest.mark.asyncio
async def test_poll_repeated_failure_does_not_renotify_once_flag_persisted(db):
    """Une demande déjà 'failed' + failure_mail_sent=True (le worker a fini de traiter le
    1er échec) qui échoue à nouveau au cycle suivant NE renvoie PAS de notification.

    Couvre l'incident de production : jusqu'à 12 mails d'échec consécutifs pour la même
    demande, un cycle de poll toutes les 60-90s relançant _submit_to_arr et renvoyant la
    notification malgré le garde-fou `was_failed` (qui pouvait racer entre deux process —
    voir le verrou distribué). `failure_mail_sent` est désormais un flag persisté vérifié
    par _notify() lui-même — le scénario réaliste est que le worker a déjà traité et posé
    le flag avant le cycle de poll suivant (la queue traite en ~1-3s, largement avant les
    60-90s d'intervalle).
    """
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.add(_sent_request(status=RequestStatus.failed, failure_mail_sent=True))
    db.commit()

    with (
        _patch_session(db),
        _patch_watchlist([_movie_item()]),
        patch("app.services.watchlist_poller._submit_to_arr", new=AsyncMock(side_effect=Exception("timeout"))),
        _patch_enqueue() as mock_enqueue,
    ):
        await poll_watchlists()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.failed
    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_retry_endpoint_resets_failure_mail_sent(db):
    """Un retry manuel remet failure_mail_sent à False : un nouvel échec doit renotifier."""
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    req = _sent_request(status=RequestStatus.failed, failure_mail_sent=True)
    db.add(req)
    db.commit()

    from app.routers.requests_api import retry_request

    # poll_watchlists() ferme sa propre session (partagée avec `db` via _patch_session) dans
    # son `finally` — la mocker évite de rendre `db` inutilisable pour l'assertion qui suit.
    with patch("app.routers.requests_api.poll_watchlists", new=AsyncMock()):
        await retry_request(req.id, db=db)

    reloaded = db.query(MediaRequest).filter(MediaRequest.id == req.id).first()
    assert reloaded.failure_mail_sent is False


@pytest.mark.asyncio
async def test_poll_failure_message_names_actual_attempted_target(db):
    """Le mail d'échec nomme la cible réellement tentée (ex: Prowlarr), pas toujours Sonarr/Radarr.

    _submit_to_arr pose item["_attempted_target"] avant de tenter chaque cible ; le
    message d'échec doit le refléter plutôt que le générique "Sonarr/Radarr" d'avant.
    """
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.commit()

    async def _fail_via_prowlarr(settings, item, user_obj=None, db=None):
        item["_attempted_target"] = "prowlarr"
        raise Exception("Aucun résultat exploitable trouvé via Prowlarr")

    with (
        _patch_session(db),
        _patch_watchlist([_movie_item()]),
        patch("app.services.watchlist_poller._submit_to_arr", new=AsyncMock(side_effect=_fail_via_prowlarr)),
        _patch_enqueue() as mock_enqueue,
    ):
        await poll_watchlists()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.failed
    context = mock_enqueue.call_args[0][3]
    assert "Prowlarr" in context["reason"]


@pytest.mark.asyncio
async def test_poll_already_existed_still_notifies_new_request(db):
    """already_existed=True (le média était déjà catalogué côté Radarr/Sonarr pour une
    raison indépendante) ne doit PAS empêcher la notification "demande envoyée" pour un
    utilisateur qui la demande pour la première fois : seul `request_mail_sent` (vérifié
    par `_notify`) doit régir l'anti-spam, pas `already_existed`.
    """
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.commit()

    with (
        _patch_session(db),
        _patch_watchlist([_movie_item()]),
        _patch_submit(already_existed=True),
        _patch_enqueue() as mock_enqueue,
    ):
        await poll_watchlists()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.sent_to_arr
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args[0][0] == "request"


@pytest.mark.asyncio
async def test_poll_disabled_user_is_skipped(db):
    """Utilisateur désactivé → son item est ignoré."""
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=False))
    db.commit()

    with _patch_session(db), _patch_watchlist([_movie_item()]), _patch_submit() as mock_submit:
        await poll_watchlists()

    mock_submit.assert_not_called()
    assert db.query(MediaRequest).count() == 0


@pytest.mark.asyncio
async def test_poll_no_settings_returns_early(db):
    """Aucun Settings en DB → retour immédiat sans crash."""
    with _patch_session(db), _patch_watchlist([_movie_item()]) as mock_fetch:
        await poll_watchlists()

    mock_fetch.assert_not_called()  # fetch_watchlist appelé seulement après settings check


@pytest.mark.asyncio
async def test_poll_empty_watchlist_returns_early(db):
    """Watchlist vide → aucune demande créée."""
    db.add(_settings())
    db.commit()

    with _patch_session(db), _patch_watchlist([]), _patch_submit() as mock_submit:
        await poll_watchlists()

    mock_submit.assert_not_called()
    assert db.query(MediaRequest).count() == 0


@pytest.mark.asyncio
async def test_poll_show_item_routes_to_sonarr(db):
    """Item de type show → _submit_to_arr appelé (vérification du type)."""
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.commit()

    with _patch_session(db), _patch_watchlist([_show_item()]), _patch_submit() as mock_submit, _patch_enqueue():
        await poll_watchlists()

    mock_submit.assert_called_once()
    _, item_arg, _user = mock_submit.call_args[0]
    assert item_arg["media_type"] == "show"

    req = db.query(MediaRequest).first()
    assert req.media_type == "show"
    assert req.status == RequestStatus.sent_to_arr


# ---------------------------------------------------------------------------
# check_arr_statuses — cas nominaux
# ---------------------------------------------------------------------------


def _sent_request(**kwargs) -> MediaRequest:
    defaults = dict(
        plex_user_id="alice",
        plex_user="alice",
        title="Inception",
        media_type="movie",
        status=RequestStatus.sent_to_arr,
        arr_id=42,
        tmdb_id="27205",
        available_mail_sent=False,
    )
    defaults.update(kwargs)
    return MediaRequest(**defaults)


@pytest.mark.asyncio
async def test_check_arr_movie_becomes_available(db):
    """is_movie_available → True : statut reste sent_to_arr tant que Plex ne confirme pas."""
    db.add(_settings())
    db.add(_sent_request())
    db.add(_unmatched_library_item())
    db.commit()

    with (
        _patch_session_arr(db),
        patch("app.services.arr_tracker.is_movie_available", new=AsyncMock(return_value=(True, 42, None))),
        _patch_enqueue() as mock_enqueue,
    ):
        await check_arr_statuses()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.sent_to_arr
    assert req.available_at is None
    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_check_arr_movie_not_yet_available(db):
    """is_movie_available → False : statut reste sent_to_arr."""
    db.add(_settings())
    db.add(_sent_request())
    db.commit()

    with (
        _patch_session_arr(db),
        patch("app.services.arr_tracker.is_movie_available", new=AsyncMock(return_value=(False, None, None))),
        _patch_enqueue() as mock_enqueue,
    ):
        await check_arr_statuses()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.sent_to_arr
    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_check_arr_statuses_skipped_when_distributed_lock_held_elsewhere(db):
    """Verrou Redis déjà détenu (autre process/conteneur) → cycle ignoré, aucun traitement.

    Même schéma que poll_watchlists : check_arr_statuses est déclenché à la fois par
    APScheduler (conteneur API), le cron ARQ (conteneur worker) et /api/requests/poll
    (HTTP manuel) — le verrou asyncio local ne protège que dans un seul process.
    """
    db.add(_settings())
    db.add(_sent_request())
    db.commit()

    with (
        _patch_session_arr(db),
        patch("app.services.arr_tracker.is_movie_available", new=AsyncMock(return_value=(True, 42, None))) as mock_check,
        patch("app.services.arr_tracker.acquire_distributed_lock", new=AsyncMock(return_value=None)),
    ):
        await check_arr_statuses()

    mock_check.assert_not_called()
    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.sent_to_arr


@pytest.mark.asyncio
async def test_check_arr_statuses_releases_distributed_lock_after_run(db):
    """Le verrou Redis est relâché après un cycle, même en cas d'erreur, pour ne pas bloquer le suivant."""
    db.add(_settings())
    db.add(_sent_request())
    db.commit()

    with (
        _patch_session_arr(db),
        patch("app.services.arr_tracker.is_movie_available", new=AsyncMock(return_value=(False, None, None))),
        patch("app.services.arr_tracker.acquire_distributed_lock", new=AsyncMock(return_value="tok")),
        patch("app.services.arr_tracker.release_distributed_lock", new=AsyncMock()) as mock_release,
    ):
        await check_arr_statuses()

    mock_release.assert_called_once_with("plexarr:lock:check_arr_statuses", "tok")


@pytest.mark.asyncio
async def test_check_arr_show_becomes_available(db):
    """get_series_episode_stats → série complète, mais reste sent_to_arr sans preuve Plex."""
    db.add(_settings())
    db.add(_sent_request(title="Breaking Bad", media_type="show", tvdb_id="81189"))
    db.add(_unmatched_library_item())
    db.commit()

    series_stats = {
        "arr_id": 7,
        "title_slug": None,
        "episode_file_count": 5,
        "episode_count": 5,
        "total_episode_count": 5,
    }
    with (
        _patch_session_arr(db),
        patch("app.services.arr_tracker.get_series_episode_stats", new=AsyncMock(return_value=series_stats)),
        _patch_enqueue() as mock_enqueue,
    ):
        await check_arr_statuses()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.sent_to_arr
    assert req.episodes_available_count == 5
    assert req.episodes_total_count == 5
    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_check_arr_show_becomes_partially_available(db):
    """Régression : un seul épisode présent sur 5 ne doit plus afficher "Disponible"

    (statut RequestStatus.available, badge vert) comme si la série était complète —
    c'est le comportement corrigé (voir arr_tracker.py, is_show_partial). Pas de
    LibraryItem non-matchant ici : table LibraryItem vide -> has_plex_proof() bypass
    à True (voir commentaire de _settings), donc le statut peut réellement transiter."""
    db.add(_settings())
    db.add(_sent_request(title="Breaking Bad", media_type="show", tvdb_id="81189"))
    db.commit()

    series_stats = {
        "arr_id": 7,
        "title_slug": None,
        "episode_file_count": 1,
        "episode_count": 1,
        "total_episode_count": 5,
    }
    with (
        _patch_session_arr(db),
        patch("app.services.arr_tracker.get_series_episode_stats", new=AsyncMock(return_value=series_stats)),
        _patch_enqueue() as mock_enqueue,
    ):
        await check_arr_statuses()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.partially_available
    assert req.episodes_available_count == 1
    assert req.episodes_total_count == 5
    assert req.available_at is None
    # La notif de disponibilite partielle (pipeline existant, _handle_show_progress_notification)
    # doit toujours partir normalement -- seul le statut affiche change avec ce correctif.
    mock_enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_check_arr_show_becomes_fully_available(db):
    """Régression : quand tous les épisodes sont présents, le statut doit bien passer
    à RequestStatus.available (pas rester bloqué à partially_available)."""
    db.add(_settings())
    db.add(_sent_request(title="Breaking Bad", media_type="show", tvdb_id="81189"))
    db.commit()

    series_stats = {
        "arr_id": 7,
        "title_slug": None,
        "episode_file_count": 5,
        "episode_count": 5,
        "total_episode_count": 5,
    }
    with (
        _patch_session_arr(db),
        patch("app.services.arr_tracker.get_series_episode_stats", new=AsyncMock(return_value=series_stats)),
        _patch_enqueue(),
    ):
        await check_arr_statuses()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.available
    assert req.available_at is not None


@pytest.mark.asyncio
async def test_check_arr_no_candidates_returns_early(db):
    """Aucune demande sent_to_arr → aucun check effectué."""
    db.add(_settings())
    db.add(
        MediaRequest(
            plex_user_id="alice", plex_user="alice", title="X", media_type="movie", status=RequestStatus.available
        )
    )
    db.commit()

    with _patch_session_arr(db), patch("app.services.arr_tracker.is_movie_available", new=AsyncMock()) as mock_check:
        await check_arr_statuses()

    mock_check.assert_not_called()


@pytest.mark.asyncio
async def test_check_arr_seer_used_when_enabled(db):
    """Seer en mode acteur → seer_available utilisé à la place de is_movie_available."""
    s = _settings(seer_enabled=True, seer_mode="actor", seer_url="http://seer.local", seer_api_key="key")
    db.add(s)
    db.add(_sent_request(source="seer"))
    db.add(_unmatched_library_item())
    db.commit()

    with (
        _patch_session_arr(db),
        patch("app.services.arr_tracker.seer_available", new=AsyncMock(return_value=(True, 42, None))) as mock_seer,
        patch("app.services.arr_tracker.is_movie_available", new=AsyncMock()) as mock_radarr,
        _patch_enqueue(),
    ):
        await check_arr_statuses()

    mock_seer.assert_called_once()
    mock_radarr.assert_not_called()
    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.sent_to_arr


@pytest.mark.asyncio
async def test_check_arr_seer_available_with_plex_match_becomes_available(db):
    """Seer available + Plex match => local availability is confirmed."""
    s = _settings(seer_enabled=True, seer_mode="actor", seer_url="http://seer.local", seer_api_key="key")
    db.add(s)
    db.add(_sent_request(source="seer"))
    db.add(
        LibraryItem(
            title="Inception",
            year=None,
            media_type="movie",
            tmdb_id="27205",
            tvdb_id=None,
            imdb_id=None,
            plex_guid="plex://movie/inception",
            poster_url=None,
            overview="",
            added_at=None,
            arr_instance_id=None,
            arr_id=None,
            arr_slug=None,
        )
    )
    db.commit()

    with (
        _patch_session_arr(db),
        patch("app.services.arr_tracker.seer_available", new=AsyncMock(return_value=(True, 42, None))) as mock_seer,
        patch("app.services.arr_tracker.is_movie_available", new=AsyncMock()) as mock_radarr,
        _patch_enqueue() as mock_enqueue,
    ):
        await check_arr_statuses()

    mock_seer.assert_called_once()
    mock_radarr.assert_not_called()
    req = db.query(MediaRequest).filter(MediaRequest.title == "Inception").first()
    assert req.status == RequestStatus.available
    assert req.library_item_id is not None
    mock_enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_check_arr_seer_unavailable_falls_back_to_radarr(db):
    """Seer dit non dispo → fallback direct sur Radarr qui dit dispo (mais pas de preuve Plex)."""
    s = _settings(seer_enabled=True, seer_mode="actor", seer_url="http://seer.local", seer_api_key="key")
    db.add(s)
    db.add(_sent_request(source="seer"))
    db.add(_unmatched_library_item())
    db.commit()

    with (
        _patch_session_arr(db),
        patch("app.services.arr_tracker.seer_available", new=AsyncMock(return_value=(False, None, None))),
        patch(
            "app.services.arr_tracker.is_movie_available", new=AsyncMock(return_value=(True, 99, "inception"))
        ) as mock_radarr,
        _patch_enqueue() as mock_enqueue,
    ):
        await check_arr_statuses()

    mock_radarr.assert_called_once()
    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.sent_to_arr
    assert req.arr_slug == "inception"
    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_check_arr_seer_unavailable_falls_back_to_sonarr(db):
    """Seer dit non dispo → fallback direct sur Sonarr qui dit dispo (mais pas de preuve Plex)."""
    s = _settings(seer_enabled=True, seer_mode="actor", seer_url="http://seer.local", seer_api_key="key")
    db.add(s)
    db.add(_sent_request(title="Breaking Bad", media_type="show", tvdb_id="81189", source="seer"))
    db.add(_unmatched_library_item())
    db.commit()

    series_stats = {
        "arr_id": 7,
        "title_slug": None,
        "episode_file_count": 5,
        "episode_count": 5,
        "total_episode_count": 5,
    }
    with (
        _patch_session_arr(db),
        patch("app.services.arr_tracker.seer_available", new=AsyncMock(return_value=(False, None, None))),
        patch(
            "app.services.arr_tracker.get_series_episode_stats", new=AsyncMock(return_value=series_stats)
        ) as mock_sonarr,
        _patch_enqueue() as mock_enqueue,
    ):
        await check_arr_statuses()

    mock_sonarr.assert_called_once()
    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.sent_to_arr
    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_check_arr_seer_unavailable_radarr_also_unavailable(db):
    """Seer et Radarr disent tous les deux non dispo → reste sent_to_arr."""
    s = _settings(seer_enabled=True, seer_url="http://seer.local", seer_api_key="key")
    db.add(s)
    db.add(_sent_request(source="seer"))
    db.commit()

    with (
        _patch_session_arr(db),
        patch("app.services.arr_tracker.seer_available", new=AsyncMock(return_value=(False, None, None))),
        patch(
            "app.services.arr_tracker.is_movie_available", new=AsyncMock(return_value=(False, None, None))
        ) as mock_radarr,
        _patch_enqueue() as mock_enqueue,
    ):
        await check_arr_statuses()

    mock_radarr.assert_called_once()
    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.sent_to_arr
    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_check_arr_exception_does_not_crash_loop(db):
    """Exception sur un item → les autres items continuent d'être traités."""
    db.add(_settings())
    db.add(_sent_request(title="Movie A", arr_id=1, tmdb_id="111"))
    db.add(_sent_request(title="Movie B", arr_id=2, tmdb_id="222"))
    db.add(_unmatched_library_item())
    db.commit()

    call_count = 0

    async def flaky(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("network error")
        return (True, 2, None)

    with (
        _patch_session_arr(db),
        patch("app.services.arr_tracker.is_movie_available", new=AsyncMock(side_effect=flaky)),
        _patch_enqueue(),
    ):
        await check_arr_statuses()

    statuses = {r.title: r.status for r in db.query(MediaRequest).all()}
    # Le second item reste suivi, mais attend la preuve Plex avant availability.
    assert statuses["Movie B"] == RequestStatus.sent_to_arr


# ---------------------------------------------------------------------------
# sync_users_from_feed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_users_creates_unknown_user(db):
    """Utilisateur inconnu dans le flux → PlexUser auto-créé avec enabled=True."""
    items = [{"plex_user_id": "bob", "title": "X", "media_type": "movie"}]
    await sync_users_from_feed(items, db)

    user = db.query(PlexUser).filter(PlexUser.plex_user_id == "bob").first()
    assert user is not None
    assert user.enabled is True


@pytest.mark.asyncio
async def test_sync_users_does_not_duplicate(db):
    """Utilisateur déjà connu → pas de doublon."""
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.commit()

    items = [{"plex_user_id": "alice", "title": "X", "media_type": "movie"}]
    await sync_users_from_feed(items, db)

    assert db.query(PlexUser).count() == 1
