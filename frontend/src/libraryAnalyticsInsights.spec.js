import { describe, expect, it } from 'vitest';

import {
  DEFAULT_INSIGHT,
  analyticsForFilters,
  distributionSelection,
  insightRows,
  insightSelection,
} from './libraryAnalyticsInsights';

const items = [
  { title: 'A', size_bytes: 10, play_count: 0, subtitle_count: 0, video_codec: 'hevc' },
  { title: 'B', size_bytes: 30, play_count: 2, subtitle_count: 1, video_codec: 'h264' },
  { title: 'C', size_bytes: 20, play_count: 0, subtitle_count: 2, video_codec: 'hevc' },
];

describe('library analytics insight table', () => {
  it('defaults to files sorted by storage usage', () => {
    expect(insightRows(items, DEFAULT_INSIGHT).map(row => row.title)).toEqual(['B', 'C', 'A']);
  });

  it('turns insight cards into live table predicates', () => {
    expect(insightRows(items, insightSelection({ kind: 'unwatched', title: 'Jamais visionnés' })))
      .toEqual([items[0], items[2]]);
    expect(insightRows(items, insightSelection({ kind: 'subtitles', title: 'Sans sous-titres' })))
      .toEqual([items[0]]);
  });

  it('uses a distribution click without changing inventory filters', () => {
    const selection = distributionSelection(
      { title: 'Codecs vidéo', field: 'video_codec' },
      'hevc',
    );
    expect(insightRows(items, selection)).toEqual([items[0], items[2]]);
  });

  it('filters and rebuilds all aggregates locally', () => {
    const snapshot = {
      items: [
        { ...items[0], media_type: 'movie', duration_ms: 100, viewers: ['Rémi'] },
        { ...items[1], media_type: 'episode', duration_ms: 200, viewers: ['Rémi', 'Alex'] },
        { ...items[2], media_type: 'movie', duration_ms: 300, viewers: [] },
      ],
      options: { video_codec: ['h264', 'hevc'] },
    };
    const result = analyticsForFilters(snapshot, { media_type: 'movie', watched: 'no' });
    expect(result.items.map(row => row.title)).toEqual(['A', 'C']);
    expect(result.summary).toEqual({
      items: 2, size_bytes: 30, duration_ms: 400, plays: 0, viewers: 1,
    });
    expect(result.distributions.video_codecs).toEqual([
      { label: 'hevc', count: 2, percent: 100 },
    ]);
    expect(result.options).toBe(snapshot.options);
  });

  it('combines exact audio and subtitle language/type filters', () => {
    const rows = [
      { title: 'VF', audio_languages: ['Français'], subtitle_languages: ['Français'], subtitle_types: ['Français · SRT'] },
      { title: 'VO', audio_languages: ['English'], subtitle_languages: ['Français'], subtitle_types: ['Français · PGS · Forcé'] },
    ];
    const result = analyticsForFilters({ items: rows }, {
      audio_language: 'English',
      subtitle_language: 'Français',
      subtitle_type: 'Français · PGS · Forcé',
    });
    expect(result.items.map(row => row.title)).toEqual(['VO']);
  });
});
