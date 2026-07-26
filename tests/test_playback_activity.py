from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db_async
from app.dependencies import require_admin
from app.main import app
from app.models import PlaybackSession, Settings
from app.services.playback_activity import (
    _analytics,
    _masked_ip,
    _playback_method,
    _serialize,
    _tautulli_values,
    parse_plex_sessions,
)


@pytest.fixture()
def client(async_db):
    async_db.add(Settings(id=1))
    async_db.commit()
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[get_db_async] = lambda: async_db
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides.pop(get_db_async, None)


PLEX_SESSIONS_XML = """
<MediaContainer size="1">
  <Video addedAt="1" duration="3600000" grandparentTitle="Foundation"
         librarySectionTitle="Séries" ratingKey="123" title="Création et destruction"
         type="episode" viewOffset="900000" year="2025">
    <Media audioCodec="eac3" audioDecision="copy" videoCodec="hevc"
           videoDecision="transcode" videoResolution="4k" container="mkv">
      <Part size="12884901888" container="mkv">
        <Stream streamType="3" selected="1" decision="burn" />
      </Part>
    </Media>
    <User id="42" title="Rémi" />
    <Player address="192.168.1.25" machineIdentifier="player-1" platform="webOS"
            product="Plex for LG" state="playing" title="Télévision" />
    <Session bandwidth="18400" id="session-abc" location="lan" />
    <TranscodeSession audioDecision="copy" key="/transcode/session/session-abc"
                      videoDecision="transcode" />
  </Video>
</MediaContainer>
"""


def test_parse_plex_sessions_normalizes_live_session():
    result = parse_plex_sessions(PLEX_SESSIONS_XML)

    assert len(result) == 1
    session = result[0]
    assert session["source_session_id"] == "session-abc"
    assert session["user_name"] == "Rémi"
    assert session["grandparent_title"] == "Foundation"
    assert session["player_title"] == "Télévision"
    assert session["player_address"] == "192.168.1.0"
    assert session["playback_method"] == "transcode"
    assert session["quality"] == "4k"
    assert session["bandwidth_kbps"] == 18400
    assert session["progress_ms"] == 900000
    assert session["container"] == "mkv"
    assert session["subtitle_decision"] == "burn"
    assert session["stream_location"] == "lan"
    assert session["media_size_bytes"] == 12884901888


def test_parse_plex_sessions_can_keep_full_ip():
    session = parse_plex_sessions(PLEX_SESSIONS_XML, anonymize_ips=False)[0]
    assert session["player_address"] == "192.168.1.25"


def test_playback_method_prioritizes_transcoding():
    assert _playback_method("transcode", "copy") == "transcode"
    assert _playback_method("copy", "copy") == "direct_stream"
    assert _playback_method("directplay", "directplay") == "direct_play"
    assert _playback_method(None, None, "direct play") == "direct_play"
    assert _playback_method(None, None, "copy") == "direct_stream"
    assert _playback_method(None, None, "transcode") == "transcode"
    assert _playback_method(None, None) == "unknown"


def test_tautulli_values_use_history_decision_and_real_progress():
    values = _tautulli_values(
        {
            "transcode_decision": "copy",
            "play_duration": 263,
            "percent_complete": 84,
        }
    )

    assert values["playback_method"] == "direct_stream"
    assert values["watched_ms"] == 263_000
    assert values["duration_ms"] == 313_095
    assert values["progress_ms"] == 263_000


def test_tautulli_values_do_not_turn_missing_play_duration_into_full_watch():
    values = _tautulli_values({"duration": 3600, "percent_complete": 0})

    assert values["watched_ms"] == 0
    assert values["progress_ms"] == 0
    assert values["playback_method"] == "unknown"


def test_masked_ip_supports_ipv6():
    assert _masked_ip("2001:db8:1234:5678:abcd::1", True) == "2001:db8:1234:5678::"


def test_serialize_routes_relative_plex_thumb_through_authenticated_endpoint():
    row = PlaybackSession(
        source_session_id="session",
        title="Film",
        thumb_url="/library/metadata/123/thumb/456",
    )
    assert _serialize(row)["thumb_url"] == (
        "/api/playback/thumb?path=%2Flibrary%2Fmetadata%2F123%2Fthumb%2F456"
    )


def test_serialize_rebuilds_missing_imported_thumb_from_rating_key():
    row = PlaybackSession(
        source="tautulli",
        source_session_id="imported",
        title="Film importé",
        rating_key="987",
    )
    assert _serialize(row)["thumb_url"] == (
        "/api/playback/thumb?path=%2Flibrary%2Fmetadata%2F987%2Fthumb"
    )


def test_serialize_extracts_plex_path_from_tautulli_image_proxy():
    row = PlaybackSession(
        source="tautulli",
        source_session_id="imported",
        title="Épisode importé",
        thumb_url="/pms_image_proxy?img=%2Flibrary%2Fmetadata%2F456%2Fthumb%2F789",
    )
    assert _serialize(row)["thumb_url"] == (
        "/api/playback/thumb?path=%2Flibrary%2Fmetadata%2F456%2Fthumb%2F789"
    )


def test_playback_thumb_rejects_external_url(client):
    response = client.get("/api/playback/thumb?path=https://example.com/poster.jpg")
    assert response.status_code == 400


def test_analytics_computes_completion_quality_and_user_trends():
    from datetime import datetime, timedelta

    started = datetime(2026, 7, 20, 20, 0)
    rows = [
        PlaybackSession(
            source_session_id=f"session-{index}",
            title=f"Épisode {index}",
            grandparent_title="Foundation",
            media_type="episode",
            user_name="Rémi",
            player_title="Apple TV",
            playback_method="transcode" if index == 0 else "direct_play",
            video_decision="transcode" if index == 0 else "directplay",
            subtitle_decision="burn" if index == 0 else None,
            video_codec="hevc",
            quality="4k",
            bandwidth_kbps=12000 + index * 1000,
            duration_ms=3_600_000,
            watched_ms=3_500_000,
            started_at=started + timedelta(hours=index),
            ended_at=started + timedelta(hours=index + 1),
            last_seen_at=started + timedelta(hours=index + 1),
        )
        for index in range(3)
    ]

    analytics = _analytics(rows, [])

    assert analytics["completion"][0]["completion_rate"] == 100
    assert analytics["concurrency"]["peak"] == 2
    assert analytics["quality"]["transcode_reasons"] == [{"label": "Sous-titres", "count": 1}]
    assert analytics["quality"]["devices"][0]["compatibility_score"] == 67
    assert analytics["binges"][0]["episodes"] == 3
    assert analytics["users"][0]["favorite_title"] == "Foundation"


def test_activity_endpoint_returns_snapshot(client):
    payload = {"active": [], "history": [], "summary": {"sessions": 0}, "daily": [], "users": []}
    with patch("app.routers.activity_api.activity_snapshot", new=AsyncMock(return_value=payload)):
        response = client.get("/api/playback?days=7")
    assert response.status_code == 200
    assert response.json() == payload


def test_activity_refresh_reports_plex_failure(client):
    with patch(
        "app.routers.activity_api.collect_plex_activity",
        new=AsyncMock(side_effect=RuntimeError("Plex hors ligne")),
    ):
        response = client.post("/api/playback/refresh")
    assert response.status_code == 502
    assert "Plex hors ligne" in response.json()["detail"]


def test_tautulli_normalize_endpoint_returns_report(client):
    payload = {"normalized": 12, "matched": 15, "received": 20, "unmatched": 5}
    with patch(
        "app.routers.activity_api.normalize_tautulli_history",
        new=AsyncMock(return_value=payload),
    ):
        response = client.post("/api/playback/tautulli/normalize", json={"length": 10000})
    assert response.status_code == 200
    assert response.json() == payload
