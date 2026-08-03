import { afterEach, describe, expect, it, vi } from 'vitest';

import { streamEvents } from './api';

/** Réponse dont le corps délivre les morceaux fournis, un par lecture. */
function streamedResponse(chunks, { ok = true, status = 200 } = {}) {
  const encoder = new TextEncoder();
  return {
    ok,
    status,
    body: new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
    json: async () => ({}),
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('streamEvents', () => {
  it('remonte chaque trame séparément, dans l’ordre', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => streamedResponse([
      'data: {"next_poll":{"next_run_seconds":30}}\n\n',
      'data: {"counts":{"available":3}}\n\n',
      'data: {"pending":[]}\n\n',
    ])));

    const received = [];
    await streamEvents('/api/dashboard/snapshot/stream', payload => received.push(payload));

    expect(received).toEqual([
      { next_poll: { next_run_seconds: 30 } },
      { counts: { available: 3 } },
      { pending: [] },
    ]);
  });

  it('recolle une trame coupée entre deux morceaux réseau', async () => {
    // Cas réel : TCP ne respecte pas les frontières de trames.
    vi.stubGlobal('fetch', vi.fn(async () => streamedResponse([
      'data: {"counts":{"av',
      'ailable":7}}\n\ndata',
      ': {"pending":[1]}\n\n',
    ])));

    const received = [];
    await streamEvents('/x', payload => received.push(payload));

    expect(received).toEqual([{ counts: { available: 7 } }, { pending: [1] }]);
  });

  it('délivre plusieurs trames arrivées dans un même morceau', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => streamedResponse([
      'data: {"a":1}\n\ndata: {"b":2}\n\n',
    ])));

    const received = [];
    await streamEvents('/x', payload => received.push(payload));

    expect(received).toEqual([{ a: 1 }, { b: 2 }]);
  });

  it('ignore une trame illisible sans perdre les suivantes', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => streamedResponse([
      'data: {ceci nest pas du json\n\n',
      'data: {"counts":{"available":1}}\n\n',
    ])));

    const received = [];
    await streamEvents('/x', payload => received.push(payload));

    expect(received).toEqual([{ counts: { available: 1 } }]);
  });

  it('lève sur une réponse en erreur, pour laisser l’appelant se replier', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => streamedResponse([], { ok: false, status: 503 })));
    await expect(streamEvents('/x', () => {})).rejects.toThrow('HTTP 503');
  });

  it('lève quand le navigateur n’expose pas de corps lisible', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, body: null, json: async () => ({}) })));
    await expect(streamEvents('/x', () => {})).rejects.toThrow(/non supporté/i);
  });

  it('demande explicitement un flux d’évènements', async () => {
    const fetchMock = vi.fn(async () => streamedResponse(['data: {"a":1}\n\n']));
    vi.stubGlobal('fetch', fetchMock);

    await streamEvents('/api/dashboard/snapshot/stream', () => {});

    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers.Accept).toBe('text/event-stream');
    expect(options.credentials).toBe('same-origin');
  });
});
