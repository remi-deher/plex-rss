import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models import LibraryAnalyticsSnapshot
from app.services.library_analytics import (
    analytics_payload,
    apply_filters,
    parse_plex_item,
    refresh_library_analytics_snapshot,
)


def sample_item():
    return {
        "ratingKey": "42",
        "type": "episode",
        "title": "Le pilote",
        "grandparentTitle": "Une série",
        "studio": "Plexarr Studio",
        "year": 2026,
        "duration": 3600000,
        "Media": [{
            "videoCodec": "hevc",
            "audioCodec": "eac3",
            "videoResolution": "4k",
            "Part": [{
                "size": 5 * 1024**3,
                "container": "mkv",
                "Stream": [
                    {"streamType": 2, "codec": "eac3", "language": "Français", "channels": 6},
                    {"streamType": 3, "language": "Français"},
                    {"streamType": 3, "language": "English"},
                ],
            }],
        }],
    }


def test_parse_plex_item_extracts_raw_technical_metadata():
    row = parse_plex_item(sample_item(), "Séries", "show")
    assert row["media_type"] == "episode"
    assert row["video_codec"] == "HEVC"
    assert row["audio_codec"] == "EAC3"
    assert row["size_bytes"] == 5 * 1024**3
    assert row["audio_track_count"] == 1
    assert row["subtitle_count"] == 2
    assert row["subtitle_languages"] == ["English", "Français"]


def test_filters_combine_media_technical_storage_and_audience_fields():
    row = parse_plex_item(sample_item(), "Séries", "show")
    row.update(play_count=2, viewers=["Rémi"], watch_time_ms=1000)
    assert apply_filters([row], {
        "media_type": "episode", "video_codec": "HEVC", "subtitle": "with",
        "watched": "yes", "min_size_gb": 4.5, "max_size_gb": 5.5,
    }) == [row]
    assert apply_filters([row], {"subtitle": "without"}) == []
    assert apply_filters([row], {"watched": "no"}) == []


@pytest.mark.asyncio
async def test_refresh_persists_a_complete_precomputed_snapshot(monkeypatch):
    row = parse_plex_item(sample_item(), "Séries", "show")
    monkeypatch.setattr(
        "app.services.library_analytics.fetch_plex_catalog",
        AsyncMock(return_value={"items": [row], "generated_at": "2026-07-26T10:00:00", "libraries": []}),
    )
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
    db = SimpleNamespace(
        execute=AsyncMock(return_value=result),
        get=AsyncMock(return_value=None),
        add=lambda value: setattr(db, "added", value),
        commit=AsyncMock(),
    )

    payload = await refresh_library_analytics_snapshot(SimpleNamespace(), db)

    assert payload["summary"]["items"] == 1
    assert isinstance(db.added, LibraryAnalyticsSnapshot)
    assert json.loads(db.added.payload_json)["insights"] == payload["insights"]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_normal_request_serves_database_snapshot_without_recalculation(monkeypatch):
    row = parse_plex_item(sample_item(), "Séries", "show")
    row.update(play_count=0, viewers=[], watch_time_ms=0)
    stored = {
        "generated_at": "2026-07-26T10:00:00",
        "summary": {"items": 1},
        "insights": [],
        "distributions": {},
        "largest": [],
        "options": {},
        "items": [row],
    }
    snapshot = LibraryAnalyticsSnapshot(payload_json=json.dumps(stored))
    db = SimpleNamespace(get=AsyncMock(return_value=snapshot))
    fetch = AsyncMock(side_effect=AssertionError("Plex ne doit pas être interrogé"))
    monkeypatch.setattr("app.services.library_analytics.fetch_plex_catalog", fetch)

    payload = await analytics_payload(SimpleNamespace(), db, {}, refresh=False)

    assert payload == stored
    fetch.assert_not_awaited()
