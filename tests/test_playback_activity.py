from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db_async
from app.dependencies import require_admin
from app.main import app
from app.models import PlaybackSession, Settings
from app.services.playback_activity import _masked_ip, _playback_method, _serialize, parse_plex_sessions


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
           videoDecision="transcode" videoResolution="4k" />
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


def test_parse_plex_sessions_can_keep_full_ip():
    session = parse_plex_sessions(PLEX_SESSIONS_XML, anonymize_ips=False)[0]
    assert session["player_address"] == "192.168.1.25"


def test_playback_method_prioritizes_transcoding():
    assert _playback_method("transcode", "copy") == "transcode"
    assert _playback_method("copy", "copy") == "direct_stream"
    assert _playback_method("directplay", "directplay") == "direct_play"


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


def test_playback_thumb_rejects_external_url(client):
    response = client.get("/api/playback/thumb?path=https://example.com/poster.jpg")
    assert response.status_code == 400


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
