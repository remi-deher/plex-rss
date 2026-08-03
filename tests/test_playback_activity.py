from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, select
from sqlalchemy.dialects.postgresql import asyncpg

from app.database import get_db_async
from app.dependencies import require_admin
from app.main import app
from app.models import PlaybackDailyAggregate, PlaybackIpLocation, PlaybackSession, Settings
from app.services import playback_activity
from app.services.playback_activity import (
    _analytics,
    _collect_plex_activity_unlocked,
    _daily_aggregate_query,
    _deduplicate_plex_sessions,
    _masked_ip,
    _miss_counts,
    _playback_method,
    _serialize,
    import_tautulli_history,
    recalculate_playback_locations,
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


def test_playback_session_round_trips_media_size_above_int32(async_db):
    media_size = 4_008_741_339
    row = PlaybackSession(
        source_session_id="large-media",
        title="Film 4K",
        media_size_bytes=media_size,
    )
    async_db.add(row)
    async_db.commit()
    async_db.expire_all()

    stored = async_db.query(PlaybackSession).filter_by(source_session_id="large-media").one()

    assert stored.media_size_bytes == media_size
    assert isinstance(PlaybackSession.__table__.c.media_size_bytes.type, BigInteger)


def test_parse_plex_sessions_can_keep_full_ip():
    session = parse_plex_sessions(PLEX_SESSIONS_XML, anonymize_ips=False)[0]
    assert session["player_address"] == "192.168.1.25"


def test_duplicate_plex_session_ids_are_collapsed_before_persistence():
    snapshots = [
        {"source_session_id": "same", "progress_ms": 100},
        {"source_session_id": "other", "progress_ms": 50},
        {"source_session_id": "same", "progress_ms": 200},
    ]

    result = _deduplicate_plex_sessions(snapshots)

    assert result == [
        {"source_session_id": "same", "progress_ms": 200},
        {"source_session_id": "other", "progress_ms": 50},
    ]


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
    assert values["duration_ms"] is None
    assert values["progress_ms"] is None
    assert values["progress_percent"] == 84


def test_tautulli_values_do_not_turn_missing_play_duration_into_full_watch():
    values = _tautulli_values({"duration": 3600, "percent_complete": 0})

    assert values["watched_ms"] == 0
    assert values["progress_ms"] is None
    assert values["duration_ms"] is None
    assert values["playback_method"] == "unknown"


@pytest.mark.asyncio
async def test_tautulli_import_persists_anonymized_ip_and_geo_status(async_db):
    async_db.add(
        Settings(
            id=1,
            tautulli_url="http://tautulli.local",
            tautulli_api_key="secret",
            activity_anonymize_ips=True,
        )
    )
    async_db.commit()
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "response": {
            "result": "success",
            "data": {"data": [{
                "reference_id": "tautulli-with-ip",
                "title": "Film distant",
                "media_type": "movie",
                "ip_address": "82.64.10.20",
                "location": "wan",
                "started": 1_786_000_000,
                "stopped": 1_786_003_600,
                "play_duration": 3600,
            }]},
        }
    }
    client = _mock_httpx_client(response)

    with (
        patch.object(playback_activity, "AsyncSessionLocal", return_value=async_db),
        patch.object(playback_activity.httpx, "AsyncClient", return_value=client),
        patch.object(playback_activity, "publish", new=AsyncMock()),
    ):
        result = await import_tautulli_history(length=1)

    stored = async_db.query(PlaybackSession).filter_by(source_session_id="tautulli-with-ip").one()
    assert result["imported"] == 1
    assert stored.player_address == "82.64.10.0"
    assert stored.geo_status == "anonymized"


@pytest.mark.asyncio
async def test_tautulli_import_expands_grouped_history_without_double_counting(async_db):
    async_db.add(
        Settings(id=1, tautulli_url="http://tautulli.local", tautulli_api_key="secret")
    )
    async_db.add(
        PlaybackSession(
            source="tautulli",
            source_session_id="10",
            title="Ancien groupe",
            watched_ms=3_000_000,
            group_count=2,
        )
    )
    async_db.commit()
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "response": {
            "result": "success",
            "data": {
                "data": [
                    {
                        "reference_id": "10",
                        "row_id": "11",
                        "title": "Lecture récente",
                        "started": 1_786_003_600,
                        "stopped": 1_786_005_400,
                        "play_duration": 1800,
                        "group_count": 1,
                    },
                    {
                        "reference_id": "10",
                        "row_id": "10",
                        "title": "Lecture ancienne",
                        "started": 1_786_000_000,
                        "stopped": 1_786_001_200,
                        "play_duration": 1200,
                        "group_count": 1,
                    },
                ]
            },
        }
    }
    client = _mock_httpx_client(response)

    with (
        patch.object(playback_activity, "AsyncSessionLocal", return_value=async_db),
        patch.object(playback_activity.httpx, "AsyncClient", return_value=client),
        patch.object(playback_activity, "publish", new=AsyncMock()),
        patch.object(
            playback_activity,
            "lookup_ip_location",
            new=AsyncMock(return_value={"geo_status": "missing"}),
        ),
    ):
        result = await import_tautulli_history(length=10000)

    rows = async_db.query(PlaybackSession).order_by(PlaybackSession.source_session_id).all()
    assert result == {"imported": 1, "updated": 1, "received": 2}
    assert [row.source_session_id for row in rows] == ["10", "11"]
    assert [row.watched_ms for row in rows] == [1_200_000, 1_800_000]
    assert [row.group_count for row in rows] == [1, 1]
    assert client.get.await_args.kwargs["params"]["grouping"] == 0


@pytest.mark.asyncio
async def test_location_recalculation_fills_missing_and_preserves_existing(async_db):
    async_db.add(Settings(id=1, activity_anonymize_ips=False))
    async_db.add_all([
        PlaybackSession(
            source="tautulli",
            source_session_id="located",
            title="Localisation historique",
            player_address="82.64.10.20",
            geo_status="resolved",
            geo_city="Paris historique",
            geo_country="France",
        ),
        PlaybackSession(
            source="tautulli",
            source_session_id="missing",
            title="Sans localisation",
            player_address="82.64.10.20",
        ),
        PlaybackSession(
            source="plex",
            source_session_id="local",
            title="Lecture locale",
            player_address="192.168.1.25",
        ),
    ])
    async_db.commit()

    with (
        patch.object(playback_activity, "AsyncSessionLocal", return_value=async_db),
        patch.object(playback_activity, "publish", new=AsyncMock()),
        patch(
            "app.services.ip_geolocation.lookup_ip_location",
            wraps=playback_activity.lookup_ip_location,
        ) as lookup,
    ):
        result = await recalculate_playback_locations()

    located = async_db.query(PlaybackSession).filter_by(source_session_id="located").one()
    missing = async_db.query(PlaybackSession).filter_by(source_session_id="missing").one()
    local = async_db.query(PlaybackSession).filter_by(source_session_id="local").one()
    assert located.geo_city == "Paris historique"
    assert missing.geo_city == "Paris historique"
    assert local.geo_status == "local"
    assert local.geo_country == "local"
    assert result["updated"] == 2
    assert result["preserved"] == 1
    assert async_db.query(PlaybackIpLocation).count() == 2
    assert lookup.await_count == 1


def test_analytics_uses_tautulli_watched_status_and_grouping():
    rows = [
        PlaybackSession(
            source="tautulli",
            source_session_id="grouped",
            title="Film",
            media_type="movie",
            user_name="Utilisateur",
            rating_key="42",
            progress_percent=70,
            watched_status=1,
            group_count=3,
            watched_ms=4_000_000,
        ),
        PlaybackSession(
            source="tautulli",
            source_session_id="rewatch",
            title="Film",
            media_type="movie",
            user_name="Utilisateur",
            rating_key="42",
            progress_percent=10,
            watched_status=0,
            group_count=1,
            watched_ms=300_000,
        ),
    ]

    analytics = _analytics(rows, [])

    assert analytics["completion"][0]["completed"] == 1
    assert analytics["engagement"] == {
        "completed": 1,
        "abandoned": 1,
        "resumed": 1,
        "rewatches": 1,
    }
    assert analytics["popular"][0]["users"] == 1
    assert analytics["popular"][0]["completion_rate"] == 50


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


def test_statistics_builds_and_uses_daily_aggregates(client, async_db):
    from app.utils import now_utc_naive

    async_db.add(
        PlaybackSession(
            source_session_id="daily-aggregate",
            title="Film agrégé",
            user_name="Rémi",
            media_type="movie",
            playback_method="transcode",
            watched_ms=3_600_000,
            started_at=now_utc_naive(),
            last_seen_at=now_utc_naive(),
            ended_at=now_utc_naive(),
        )
    )
    async_db.commit()

    response = client.get("/api/playback/statistics?days=7")

    assert response.status_code == 200
    assert response.json()["summary"] == {
        "sessions": 1,
        "watch_ms": 3_600_000,
        "users": 1,
        "transcodes": 1,
        "transcode_rate": 100.0,
    }
    aggregate = async_db.query(PlaybackDailyAggregate).one()
    assert aggregate.media_label == "Film agrégé"


def test_daily_aggregate_query_reuses_grouping_parameters_for_postgresql():
    from datetime import date

    statement = _daily_aggregate_query({date(2026, 8, 3)})
    sql = str(statement.compile(dialect=asyncpg.dialect()))

    select_clause, group_by_clause = sql.split(" GROUP BY ", 1)
    for parameter in ("$1::VARCHAR", "$2::VARCHAR", "$3::VARCHAR", "$4::VARCHAR"):
        assert parameter in select_clause
        assert parameter in group_by_clause
    assert "$9::VARCHAR" not in sql


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


def test_location_recalculation_endpoint_returns_report(client):
    payload = {
        "sessions": 20,
        "addresses": 4,
        "updated": 12,
        "preserved": 7,
        "unresolved": 1,
        "anonymized": False,
    }
    with patch(
        "app.routers.activity_api.recalculate_playback_locations",
        new=AsyncMock(return_value=payload),
    ):
        response = client.post("/api/playback/locations/recalculate")
    assert response.status_code == 200
    assert response.json() == payload


def _plex_response(xml: str) -> MagicMock:
    resp = MagicMock()
    resp.text = xml
    resp.raise_for_status = MagicMock()
    return resp


def _mock_httpx_client(get_return: MagicMock) -> AsyncMock:
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=get_return)
    return client


@pytest.fixture(autouse=True)
def _reset_miss_counts():
    _miss_counts.clear()
    yield
    _miss_counts.clear()


ROTATED_SESSION_XML = """
<MediaContainer size="1">
  <Video sessionKey="5" ratingKey="123" title="Film" type="movie"
         viewOffset="1000" duration="600000">
    <Session id="new-key" bandwidth="1000" location="lan" />
  </Video>
</MediaContainer>
"""

EMPTY_SESSIONS_XML = '<MediaContainer size="0"></MediaContainer>'


@pytest.mark.asyncio
async def test_session_id_rotation_adopts_existing_row_via_session_key(async_db):
    async_db.add(
        Settings(id=1, live_activity_enabled=True, plex_url="http://plex.local:32400", plex_token="tok")
    )
    async_db.add(
        PlaybackSession(
            source="plex",
            source_session_id="old-key",
            session_key=5,
            rating_key="123",
            title="Film",
        )
    )
    async_db.commit()

    client = _mock_httpx_client(_plex_response(ROTATED_SESSION_XML))
    with (
        patch.object(playback_activity, "AsyncSessionLocal", return_value=async_db),
        patch.object(playback_activity.httpx, "AsyncClient", return_value=client),
    ):
        await _collect_plex_activity_unlocked()

    rows = (
        await async_db.execute(select(PlaybackSession).filter(PlaybackSession.source == "plex"))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].source_session_id == "new-key"
    assert rows[0].session_key == 5
    assert rows[0].ended_at is None


@pytest.mark.asyncio
async def test_session_missing_from_one_poll_is_not_closed_immediately(async_db):
    async_db.add(
        Settings(id=1, live_activity_enabled=True, plex_url="http://plex.local:32400", plex_token="tok")
    )
    async_db.add(
        PlaybackSession(
            source="plex",
            source_session_id="sess-1",
            session_key=7,
            rating_key="42",
            title="Série",
        )
    )
    async_db.commit()

    client = _mock_httpx_client(_plex_response(EMPTY_SESSIONS_XML))
    with (
        patch.object(playback_activity, "AsyncSessionLocal", return_value=async_db),
        patch.object(playback_activity.httpx, "AsyncClient", return_value=client),
    ):
        await _collect_plex_activity_unlocked()
        row = (
            await async_db.execute(
                select(PlaybackSession).filter(PlaybackSession.source_session_id == "sess-1")
            )
        ).scalars().first()
        assert row.ended_at is None, "un seul poll manqué ne doit pas clôturer la session"

        await _collect_plex_activity_unlocked()
        await async_db.refresh(row)
        assert row.ended_at is not None, "deux ratés consécutifs doivent clôturer la session"
