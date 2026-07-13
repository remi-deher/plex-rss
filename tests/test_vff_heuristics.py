from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import ArrInstance, Base, LibraryItem, MediaRequest, Settings
from app.services.vff import (
    compute_vf_granularity,
    get_audio_info,
    show_has_full_french_audio,
    sync_plex_library_blocking,
)
from tests.async_support import TestSession


def test_get_audio_info_filename_fallback():
    # Mock a Plex movie with no audio streams tagged as French, but file path containing VFF
    mock_stream = MagicMock()
    mock_stream.languageCode = "en"
    mock_stream.language = "english"
    mock_stream.title = "Stereo"
    mock_stream.displayTitle = "English Stereo"

    mock_part = MagicMock()
    mock_part.file = "/data/downloads/Inception.2010.MULTI.VFF.1080p.mkv"
    mock_part.audioStreams.return_value = [mock_stream]

    mock_media = MagicMock()
    mock_media.parts = [mock_part]

    mock_movie = MagicMock()
    mock_movie.media = [mock_media]

    has_fr, tracks = get_audio_info(mock_movie)
    assert has_fr is True
    assert any(t["is_fr"] for t in tracks)
    assert any("nom de fichier" in t["label"].lower() for t in tracks)


def test_show_has_full_french_audio_rules():
    # Mock Plex episodes and seasons
    # Season 1: 2 episodes, all VF
    # Season 2: 2 episodes, all VO

    mock_ep_s1_e1 = MagicMock()
    mock_ep_s1_e1.title = "S01E01"

    mock_ep_s1_e2 = MagicMock()
    mock_ep_s1_e2.title = "S01E02"

    mock_ep_s2_e1 = MagicMock()
    mock_ep_s2_e1.title = "S02E01"

    mock_ep_s2_e2 = MagicMock()
    mock_ep_s2_e2.title = "S02E02"

    with patch("app.services.vff._reload"):
        # Case 1: 1 Season (VF) and 1 Season (VO)
        # Season 1 has VF, Season 2 has VO (0 VF)
        # N_vf_seasons = 1.
        # Season 2 has VO episodes, but since N_vf_seasons == 1, we do NOT track Season 2.
        # So should_track should be False!

        with patch("app.services.vff.get_french_audio_state") as mock_audio_state:

            def side_effect(ep):
                has_fr = ep == mock_ep_s1_e1 or ep == mock_ep_s1_e2
                return {"has_fr": has_fr, "fr_is_default": has_fr, "tracks": []}

            mock_audio_state.side_effect = side_effect

            mock_s1 = MagicMock()
            mock_s1.seasonNumber = 1
            mock_s1.episodes.return_value = [mock_ep_s1_e1, mock_ep_s1_e2]

            mock_s2 = MagicMock()
            mock_s2.seasonNumber = 2
            mock_s2.episodes.return_value = [mock_ep_s2_e1, mock_ep_s2_e2]

            mock_show = MagicMock()
            mock_show.seasons.return_value = [mock_s1, mock_s2]

            complete, should_track, with_vf, total, _episode_status, _french_default = show_has_full_french_audio(
                mock_show
            )
            assert complete is False
            assert should_track is False  # Rule 3: Only 1 season has VF, so we don't track other seasons
            assert with_vf == 2
            assert total == 4

        # Case 2: 2 Seasons with VF, and 1 Season with VO (0 VF)
        # Season 1 has VF, Season 2 has VF, Season 3 has VO.
        # N_vf_seasons = 2.
        # Season 3 has VO episodes. Since N_vf_seasons >= 2, we track Season 3!
        # So should_track should be True!

        mock_ep_s3_e1 = MagicMock()

        with patch("app.services.vff.get_french_audio_state") as mock_audio_state:

            def side_effect(ep):
                has_fr = ep in (mock_ep_s1_e1, mock_ep_s1_e2, mock_ep_s2_e1)
                return {"has_fr": has_fr, "fr_is_default": has_fr, "tracks": []}

            mock_audio_state.side_effect = side_effect

            mock_s1 = MagicMock()
            mock_s1.seasonNumber = 1
            mock_s1.episodes.return_value = [mock_ep_s1_e1, mock_ep_s1_e2]

            mock_s2 = MagicMock()
            mock_s2.seasonNumber = 2
            mock_s2.episodes.return_value = [mock_ep_s2_e1, mock_ep_s2_e2]

            mock_s3 = MagicMock()
            mock_s3.seasonNumber = 3
            mock_s3.episodes.return_value = [mock_ep_s3_e1]

            mock_show = MagicMock()
            mock_show.seasons.return_value = [mock_s1, mock_s2, mock_s3]

            complete, should_track, with_vf, total, _episode_status, _french_default = show_has_full_french_audio(
                mock_show
            )
            assert complete is False
            assert should_track is True  # Rule 2: At least 2 seasons have VF, so we track Season 3
            assert with_vf == 3
            assert total == 5

        # Case 3: Season 1 has 1 episode in VF, and 1 episode in VO
        # N_vf_seasons = 1.
        # Season 1 has VO episodes, and info["vf"] > 0.
        # So should_track should be True (Rule 1).

        with patch("app.services.vff.get_french_audio_state") as mock_audio_state:

            def side_effect(ep):
                has_fr = ep == mock_ep_s1_e1
                return {"has_fr": has_fr, "fr_is_default": has_fr, "tracks": []}

            mock_audio_state.side_effect = side_effect

            mock_s1 = MagicMock()
            mock_s1.seasonNumber = 1
            mock_s1.episodes.return_value = [mock_ep_s1_e1, mock_ep_s1_e2]

            mock_show = MagicMock()
            mock_show.seasons.return_value = [mock_s1]

            complete, should_track, with_vf, total, _episode_status, _french_default = show_has_full_french_audio(
                mock_show
            )
            assert complete is False
            assert should_track is True  # Rule 1: Season partially in VF, so we track it
            assert with_vf == 1
            assert total == 2


def test_sync_plex_library_blocking():
    # Mocking Plex library sections and items
    mock_item = MagicMock()
    mock_item.title = "Inception"
    mock_item.year = 2010
    mock_item.guid = "plex://movie/12345"
    mock_item.thumb = "/photo/123"
    mock_item.summary = "A dream within a dream"
    mock_item.addedAt = None

    mock_guid = MagicMock()
    mock_guid.id = "tmdb://27205"
    mock_item.guids = [mock_guid]

    mock_section = MagicMock()
    mock_section.all.return_value = [mock_item]

    mock_plex = MagicMock()
    mock_plex.library.section.return_value = mock_section

    with patch("app.services.vff.connect", return_value=mock_plex):
        results = sync_plex_library_blocking("http://localhost:32400", "token", [{"name": "Films", "kind": "movie"}])

        assert len(results) == 1
        assert results[0]["title"] == "Inception"
        assert results[0]["tmdb_id"] == "27205"
        assert results[0]["plex_guid"] == "plex://movie/12345"
        assert "X-Plex-Token=token" in results[0]["poster_url"]


@pytest.mark.asyncio
async def test_sync_plex_media():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = TestSession(Session())

    # Initialisation de settings
    settings = Settings(
        plex_url="http://localhost",
        plex_token="token",
        vff_enabled=True,
        vff_libraries='[{"name": "Films", "kind": "movie"}]',
    )
    db.add(settings)

    # Ajouter une instance Arr de test
    arr_inst = ArrInstance(
        id=1, name="Radarr Test", arr_type="radarr", url="http://radarr", api_key="key", enabled=True
    )
    db.add(arr_inst)
    db.commit()

    mock_item = {
        "title": "New Movie From Plex",
        "year": 2024,
        "media_type": "movie",
        "plex_guid": "plex://movie/999",
        "tmdb_id": "9999",
        "tvdb_id": None,
        "imdb_id": None,
        "poster_url": "http://poster",
        "overview": "Overview",
        "added_at": None,
    }

    mock_arr_movie = {"id": 42, "tmdbId": 9999, "imdbId": "tt9999", "titleSlug": "new-movie-from-plex"}

    from app.scheduler import plex_sync_state, sync_plex_media

    with (
        patch("app.services.vff.sync_plex_library_blocking", return_value=[mock_item]),
        patch("app.services.plex_sync.AsyncSessionLocal", return_value=db),
        patch("app.services.plex_sync.get_all_movies", return_value=[mock_arr_movie]),
        patch("app.services.plex_sync.get_all_series", return_value=[]),
        patch("app.services.vff_scanner.check_vf_statuses"),
    ):
        plex_sync_state["status"] = "idle"

        await sync_plex_media()

        # Verify the movie was added to the unified library table and associated with Radarr.
        item = db.query(LibraryItem).filter(LibraryItem.plex_guid == "plex://movie/999").first()
        assert item is not None
        assert item.title == "New Movie From Plex"
        assert item.arr_instance_id == 1
        assert item.arr_id == 42
        assert item.arr_slug == "new-movie-from-plex"


# ---------------------------------------------------------------------------
# compute_vf_granularity
# ---------------------------------------------------------------------------


def test_granularity_none_episode_status():
    assert compute_vf_granularity(None) == "none"
    assert compute_vf_granularity({}) == "none"


def test_granularity_none_all_vo():
    episode_status = {1: {1: False, 2: False}, 2: {1: False}}
    assert compute_vf_granularity(episode_status) == "none"


def test_granularity_episode_partial_scattered_episodes():
    """Quelques episodes VF epars, aucune saison entiere -> episode_partial."""
    episode_status = {1: {1: True, 2: False}, 2: {1: False, 2: False}}
    assert compute_vf_granularity(episode_status) == "episode_partial"


def test_granularity_season_partial_one_full_season():
    """Une saison entiere en VF (saison 1), le reste en VO -> season_partial."""
    episode_status = {1: {1: True, 2: True}, 2: {1: False, 2: False}}
    assert compute_vf_granularity(episode_status) == "season_partial"


def test_granularity_season_partial_takes_priority_over_episode_partial():
    """Une saison complete en VF + des episodes epars ailleurs -> season_partial prime."""
    episode_status = {1: {1: True, 2: True}, 2: {1: True, 2: False}}
    assert compute_vf_granularity(episode_status) == "season_partial"
