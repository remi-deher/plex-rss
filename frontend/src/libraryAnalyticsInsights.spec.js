import { describe, expect, it } from 'vitest';

import {
  DEFAULT_INSIGHT,
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
});
