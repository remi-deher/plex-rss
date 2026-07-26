from app.services.library_analytics import apply_filters, parse_plex_item


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
