"""Tests unitaires pour app/services/tmdb.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, SearchCache, Settings
from app.services import tmdb


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _mock_response(json_data=None, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    return resp


def _mock_client(get_return=None):
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=get_return)
    return client


# ---------------------------------------------------------------------------
# _api_key
# ---------------------------------------------------------------------------


def test_api_key_raises_when_not_configured(db):
    db.add(Settings(tmdb_api_key=None))
    db.commit()
    with pytest.raises(tmdb.TmdbNotConfigured):
        tmdb._api_key(db)


def test_api_key_raises_when_no_settings_row(db):
    with pytest.raises(tmdb.TmdbNotConfigured):
        tmdb._api_key(db)


def test_api_key_returns_stripped_key(db):
    db.add(Settings(tmdb_api_key="  abc123  "))
    db.commit()
    assert tmdb._api_key(db) == "abc123"


# ---------------------------------------------------------------------------
# _poster / _backdrop
# ---------------------------------------------------------------------------


def test_poster_none_without_path():
    assert tmdb._poster(None) is None


def test_poster_builds_url():
    assert tmdb._poster("/abc.jpg") == "https://image.tmdb.org/t/p/w342/abc.jpg"


def test_backdrop_builds_url_with_custom_size():
    assert tmdb._backdrop("/bg.jpg", size="w1280") == "https://image.tmdb.org/t/p/w1280/bg.jpg"


# ---------------------------------------------------------------------------
# _cache_get / _cache_put
# ---------------------------------------------------------------------------


def test_cache_get_returns_none_when_absent(db):
    assert tmdb._cache_get(db, "missing-key") is None


def test_cache_put_then_get_roundtrip(db):
    tmdb._cache_put(db, "trending-week", {"results": [1, 2, 3]})
    assert tmdb._cache_get(db, "trending-week") == {"results": [1, 2, 3]}


def test_cache_put_updates_existing_row(db):
    tmdb._cache_put(db, "k", {"a": 1})
    tmdb._cache_put(db, "k", {"a": 2})
    assert db.query(SearchCache).filter(SearchCache.query == "k").count() == 1
    assert tmdb._cache_get(db, "k") == {"a": 2}


def test_cache_get_returns_none_on_corrupt_json(db):
    db.add(SearchCache(query="bad", category="tmdb", results_json="not json"))
    db.commit()
    assert tmdb._cache_get(db, "bad") is None


# ---------------------------------------------------------------------------
# _norm / _norm_list
# ---------------------------------------------------------------------------


def test_norm_movie():
    item = {
        "media_type": "movie",
        "id": 27205,
        "title": "Inception",
        "release_date": "2010-07-16",
        "overview": "A thief...",
        "poster_path": "/p.jpg",
        "vote_average": 8.36,
        "genre_ids": [28, 878],
    }
    result = tmdb._norm(item)
    assert result["tmdb_id"] == 27205
    assert result["media_type"] == "movie"
    assert result["title"] == "Inception"
    assert result["year"] == 2010
    assert result["vote"] == 8.4


def test_norm_show_uses_name_and_first_air_date():
    item = {"media_type": "tv", "id": 1396, "name": "Breaking Bad", "first_air_date": "2008-01-20"}
    result = tmdb._norm(item)
    assert result["media_type"] == "show"
    assert result["title"] == "Breaking Bad"
    assert result["year"] == 2008


def test_norm_ignores_person_results():
    assert tmdb._norm({"media_type": "person", "id": 1}) is None


def test_norm_forced_type_overrides_media_type():
    item = {"id": 5, "title": "X", "release_date": "2020-01-01"}
    result = tmdb._norm(item, forced_type="movie")
    assert result["media_type"] == "movie"


def test_norm_list_filters_out_invalid_entries():
    data = {"results": [{"media_type": "movie", "id": 1, "title": "A"}, {"media_type": "person", "id": 2}]}
    result = tmdb._norm_list(data)
    assert len(result) == 1
    assert result[0]["tmdb_id"] == 1


def test_norm_list_empty_when_no_results_key():
    assert tmdb._norm_list({}) == []


# ---------------------------------------------------------------------------
# check_connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_connection_not_configured(db):
    ok, msg = await tmdb.check_connection(db)
    assert ok is False
    assert "non configurée" in msg


@pytest.mark.asyncio
async def test_check_connection_valid_key(db):
    db.add(Settings(tmdb_api_key="abc"))
    db.commit()
    client = _mock_client(get_return=_mock_response(status_code=200))
    with patch("app.services.tmdb.httpx.AsyncClient", return_value=client):
        ok, msg = await tmdb.check_connection(db)
    assert ok is True
    assert "valide" in msg


@pytest.mark.asyncio
async def test_check_connection_invalid_key(db):
    db.add(Settings(tmdb_api_key="abc"))
    db.commit()
    client = _mock_client(get_return=_mock_response(status_code=401))
    with patch("app.services.tmdb.httpx.AsyncClient", return_value=client):
        ok, msg = await tmdb.check_connection(db)
    assert ok is False
    assert "invalide" in msg


@pytest.mark.asyncio
async def test_check_connection_network_error(db):
    db.add(Settings(tmdb_api_key="abc"))
    db.commit()
    client = AsyncMock()
    client.__aenter__ = AsyncMock(side_effect=Exception("timeout"))
    with patch("app.services.tmdb.httpx.AsyncClient", return_value=client):
        ok, msg = await tmdb.check_connection(db)
    assert ok is False
    assert "timeout" in msg


# ---------------------------------------------------------------------------
# _get (cache + fetch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_fetches_and_caches(db):
    db.add(Settings(tmdb_api_key="abc"))
    db.commit()
    client = _mock_client(get_return=_mock_response({"results": []}))
    with patch("app.services.tmdb.httpx.AsyncClient", return_value=client):
        data = await tmdb._get(db, "/trending/all/week")
    assert data == {"results": []}
    assert db.query(SearchCache).count() == 1


@pytest.mark.asyncio
async def test_get_returns_cached_value_without_http_call(db):
    db.add(Settings(tmdb_api_key="abc"))
    db.commit()
    client = _mock_client(get_return=_mock_response({"results": ["fresh"]}))
    with patch("app.services.tmdb.httpx.AsyncClient", return_value=client):
        await tmdb._get(db, "/trending/all/week")
        data = await tmdb._get(db, "/trending/all/week")
    assert client.get.call_count == 1
    assert data == {"results": ["fresh"]}


@pytest.mark.asyncio
async def test_get_bypasses_cache_when_disabled(db):
    db.add(Settings(tmdb_api_key="abc"))
    db.commit()
    client = _mock_client(get_return=_mock_response({"results": []}))
    with patch("app.services.tmdb.httpx.AsyncClient", return_value=client):
        await tmdb._get(db, "/trending/all/week", cache=False)
        await tmdb._get(db, "/trending/all/week", cache=False)
    assert client.get.call_count == 2


# ---------------------------------------------------------------------------
# trending / popular / genres / search (thin wrappers over _get + _norm_list)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trending_returns_normalized_list(db):
    db.add(Settings(tmdb_api_key="abc"))
    db.commit()
    payload = {"results": [{"media_type": "movie", "id": 1, "title": "A", "release_date": "2020-01-01"}]}
    client = _mock_client(get_return=_mock_response(payload))
    with patch("app.services.tmdb.httpx.AsyncClient", return_value=client):
        result = await tmdb.trending(db)
    assert len(result) == 1
    assert result[0]["title"] == "A"


@pytest.mark.asyncio
async def test_genres_returns_raw_genres_list(db):
    db.add(Settings(tmdb_api_key="abc"))
    db.commit()
    payload = {"genres": [{"id": 28, "name": "Action"}]}
    client = _mock_client(get_return=_mock_response(payload))
    with patch("app.services.tmdb.httpx.AsyncClient", return_value=client):
        result = await tmdb.genres(db, "movie")
    assert result == [{"id": 28, "name": "Action"}]


@pytest.mark.asyncio
async def test_search_returns_normalized_list(db):
    db.add(Settings(tmdb_api_key="abc"))
    db.commit()
    payload = {"results": [{"media_type": "tv", "id": 9, "name": "Show"}]}
    client = _mock_client(get_return=_mock_response(payload))
    with patch("app.services.tmdb.httpx.AsyncClient", return_value=client):
        result = await tmdb.search(db, "query")
    assert result[0]["title"] == "Show"
