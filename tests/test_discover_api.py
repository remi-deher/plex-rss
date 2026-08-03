"""Régressions de sécurité, validation et annotation du catalogue Découvrir."""

from unittest.mock import ANY, AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.database import get_db_async
from app.dependencies import require_auth
from app.main import app
from app.models import MediaRequest, RequestStatus
from app.routers.discover_api import _annotate, _guard
from app.utils import now_utc_naive


@pytest.fixture()
def db(async_db):
    return async_db


@pytest.fixture()
def client(db):
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_db_async] = lambda: db
    test_client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    yield test_client
    app.dependency_overrides.clear()


def _request(db, *, status, requested_at, plex_user_id):
    row = MediaRequest(
        plex_user_id=plex_user_id,
        plex_user=plex_user_id,
        title="Film",
        year=2025,
        media_type="movie",
        tmdb_id="42",
        status=status,
        requested_at=requested_at,
    )
    db.add(row)
    db.commit()
    return row


def test_guard_preserves_expected_http_errors():
    expected = HTTPException(404, "Absent")
    with pytest.raises(HTTPException) as caught:
        _guard(expected)
    assert caught.value is expected
    assert caught.value.status_code == 404


def test_invalid_catalog_parameters_are_rejected(client):
    assert client.get("/api/discover/popular?media_type=person").status_code == 422
    assert client.get("/api/discover/popular?page=0").status_code == 422
    assert client.get("/api/discover/discover?sort_by=unsupported").status_code == 422


def test_api_token_style_request_cannot_list_requesters(client):
    response = client.get("/api/discover/requesters")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_annotation_prefers_most_advanced_request_status(db):
    from datetime import timedelta

    recent = _request(
        db,
        status=RequestStatus.failed,
        requested_at=now_utc_naive(),
        plex_user_id="recent",
    )
    advanced = _request(
        db,
        status=RequestStatus.sent_to_arr,
        requested_at=now_utc_naive() - timedelta(days=1),
        plex_user_id="advanced",
    )

    result = await _annotate(db, [{"tmdb_id": 42, "media_type": "movie"}])

    assert result[0]["request_id"] == advanced.id
    assert result[0]["request_id"] != recent.id
    assert result[0]["request_status"] == "sent_to_arr"


def test_trending_returns_paginated_annotated_envelope(client):
    payload = {
        "items": [{"tmdb_id": 42, "media_type": "movie", "title": "Film"}],
        "page": 1,
        "total_pages": 3,
        "total_results": 55,
    }
    with patch("app.routers.discover_api.tmdb.trending", new=AsyncMock(return_value=payload)):
        response = client.get("/api/discover/trending?media_type=all&page=1&paginated=true")

    assert response.status_code == 200
    body = response.json()
    assert body["total_pages"] == 3
    assert body["items"][0]["requested"] is False


def test_trending_keeps_legacy_list_shape_by_default(client):
    payload = {
        "items": [{"tmdb_id": 42, "media_type": "movie", "title": "Film"}],
        "page": 1,
        "total_pages": 3,
        "total_results": 55,
    }
    with patch("app.routers.discover_api.tmdb.trending", new=AsyncMock(return_value=payload)):
        response = client.get("/api/discover/trending?media_type=all&page=1")

    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert response.json()[0]["title"] == "Film"


def test_home_reuses_trending_for_hero_and_rail(client):
    payload = {
        "items": [{"tmdb_id": 42, "media_type": "movie", "title": "Film"}],
        "page": 1,
        "total_pages": 1,
        "total_results": 1,
    }
    trending = AsyncMock(return_value=payload)
    with patch("app.routers.discover_api.tmdb.trending", new=trending):
        response = client.get("/api/discover/home?sections=hero,trending")

    assert response.status_code == 200
    sections = response.json()["sections"]
    assert sections["hero"]["item"]["title"] == "Film"
    assert sections["trending"]["items"][0]["title"] == "Film"
    assert sections["trending"]["items"][0]["requested"] is False
    trending.assert_awaited_once_with(ANY, "all", "day", 1)


def test_home_caches_external_catalog_but_refreshes_local_status(client, db):
    payload = {
        "items": [{"tmdb_id": 42, "media_type": "movie", "title": "Film"}],
        "page": 1,
        "total_pages": 1,
        "total_results": 1,
    }
    trending = AsyncMock(return_value=payload)
    with patch("app.routers.discover_api.tmdb.trending", new=trending):
        first = client.get("/api/discover/home?sections=trending")
        _request(db, status=RequestStatus.pending, requested_at=now_utc_naive(), plex_user_id="user")
        second = client.get("/api/discover/home?sections=trending")

    assert first.json()["sections"]["trending"]["items"][0]["requested"] is False
    assert second.json()["sections"]["trending"]["items"][0]["requested"] is True
    trending.assert_awaited_once()


def test_home_keeps_other_sections_when_one_fails(client):
    payload = {
        "items": [{"tmdb_id": 42, "media_type": "movie", "title": "Film"}],
        "page": 1,
        "total_pages": 1,
        "total_results": 1,
    }
    with (
        patch("app.routers.discover_api.tmdb.trending", new=AsyncMock(return_value=payload)),
        patch("app.routers.discover_api.tmdb.popular", new=AsyncMock(side_effect=RuntimeError("TMDB down"))),
    ):
        response = client.get("/api/discover/home?sections=trending,popular_movies")

    assert response.status_code == 200
    sections = response.json()["sections"]
    assert sections["trending"]["items"][0]["title"] == "Film"
    assert sections["popular_movies"]["items"] == []
    assert sections["popular_movies"]["error"] == "Section temporairement indisponible."


def test_home_rejects_unknown_sections(client):
    response = client.get("/api/discover/home?sections=trending,unknown")

    assert response.status_code == 422


def test_sources_return_configured_region_and_curated_items(client, db):
    from app.models import Settings

    db.add(Settings(tmdb_api_key="key", tmdb_region="BE"))
    db.commit()
    sources = [{"id": 8, "kind": "provider", "name": "Netflix", "logo_url": None}]
    discover_sources = AsyncMock(return_value=sources)
    with patch("app.routers.discover_api.tmdb.discovery_sources", new=discover_sources):
        response = client.get("/api/discover/sources")

    assert response.status_code == 200
    assert response.json() == {"region": "BE", "items": sources}
    discover_sources.assert_awaited_once_with(ANY, "BE")


def test_source_media_is_annotated_and_paginated(client):
    payload = {
        "items": [{"tmdb_id": 42, "media_type": "movie", "title": "Film"}],
        "page": 1,
        "total_pages": 2,
        "total_results": 21,
    }
    discover = AsyncMock(return_value=payload)
    with patch("app.routers.discover_api.tmdb.discover_by_source", new=discover):
        response = client.get("/api/discover/source/provider/8?media_type=movie&page=1")

    assert response.status_code == 200
    assert response.json()["items"][0]["requested"] is False
    assert response.json()["total_pages"] == 2
    discover.assert_awaited_once_with(ANY, "provider", 8, "movie", 1, "FR")
