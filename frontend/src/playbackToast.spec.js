import { describe, expect, it } from 'vitest';
import { playbackStartsFromEvent, playbackTitle } from './playbackToast';

describe('playback toast helpers', () => {
  it('formate un épisode avec sa série', () => {
    expect(playbackTitle({ grandparent_title: 'Foundation', title: 'Création et destruction' }))
      .toBe('Foundation · Création et destruction');
  });

  it('extrait uniquement les nouvelles lectures du payload SSE', () => {
    const started = [{ session_id: 'one', user_name: 'Rémi', title: 'Dune' }];
    expect(playbackStartsFromEvent({ detail: { payload: { active: 2, started } } })).toEqual(started);
    expect(playbackStartsFromEvent({ detail: { payload: { active: 2 } } })).toEqual([]);
  });
});
