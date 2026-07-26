import { describe, expect, it } from 'vitest';

import {
  canAct,
  isImportPending,
  isUnmatched,
  needsEpisodeImport,
  queueCounts,
  queueDetailPath,
  requiresIntervention,
  rowKey,
  statusKey,
  statusLabel,
} from './queueRules';

const row = (overrides = {}) => ({
  instance_id: 1, queue_id: 10, arr_type: 'sonarr', request_id: 5, status: 'downloading', ...overrides,
});

describe('statusKey', () => {
  it('normalise les libellés *arr', () => {
    expect(statusKey(row({ status: 'downloading' }))).toBe('downloading');
    expect(statusKey(row({ status: 'Queued' }))).toBe('queued');
    expect(statusKey(row({ status: 'Paused' }))).toBe('paused');
    expect(statusKey(row({ status: 'Warning' }))).toBe('error');
    expect(statusKey(row({ status: 'Failed' }))).toBe('error');
  });

  // `row.error` l'emporte : c'est ce qui distingue les règles de la page Téléchargements
  // de celles qu'avait le tableau de bord, qui ne regardait que les sous-chaînes.
  it('donne la priorité au message d’erreur sur le libellé de statut', () => {
    expect(statusKey(row({ status: 'downloading', error: 'disque plein' }))).toBe('error');
  });

  it('considère terminé au-delà de 100 % de progression', () => {
    expect(statusKey(row({ status: 'ok', progress: 100 }))).toBe('completed');
    expect(statusKey(row({ status: 'ok', progress: 42 }))).toBe('downloading');
  });

  it('donne un libellé français pour chaque statut', () => {
    expect(statusLabel(row({ status: 'Paused' }))).toBe('En pause');
    expect(statusLabel(row({ error: 'x' }))).toBe('Erreur');
  });
});

describe('catégories nécessitant une intervention', () => {
  it('repère un import bloqué, mais seulement sur un élément actionnable', () => {
    expect(isImportPending(row({ tracked_state: 'importPending' }))).toBe(true);
    // Sans instance_id/queue_id, aucune action n'est possible : ce n'est pas un import bloqué.
    expect(isImportPending(row({ tracked_state: 'importPending', queue_id: null }))).toBe(false);
    expect(canAct(row({ queue_id: null }))).toBe(false);
  });

  it('repère un téléchargement que rien ne réclame', () => {
    expect(isUnmatched(row({ request_id: null, library_id: null }))).toBe(true);
    expect(isUnmatched(row({ request_id: null, library_id: 7 }))).toBe(false);
    // Un client direct (pas de arr_type) n'est jamais « non associé ».
    expect(isUnmatched(row({ request_id: null, library_id: null, arr_type: null }))).toBe(false);
  });

  it('repère une erreur Sonarr sur une série connue', () => {
    expect(needsEpisodeImport(row({ error: 'x', arr_media_id: 3 }))).toBe(true);
    expect(needsEpisodeImport(row({ error: 'x', arr_media_id: null }))).toBe(false);
    expect(needsEpisodeImport(row({ arr_type: 'radarr', error: 'x', arr_media_id: 3 }))).toBe(false);
  });

  it('regroupe les quatre cas', () => {
    expect(requiresIntervention(row())).toBe(false);
    expect(requiresIntervention(row({ error: 'x', arr_media_id: null }))).toBe(true);
    expect(requiresIntervention(row({ tracked_state: 'importPending' }))).toBe(true);
    expect(requiresIntervention(row({ request_id: null, library_id: null }))).toBe(true);
  });
});

describe('queueCounts', () => {
  // Le défaut corrigé : le tableau de bord comptait un `importPending` dans « En attente
  // d'import » ET dans « Bloqués », puis y ajoutait encore les échecs.
  it('partitionne strictement, sans compter deux fois', () => {
    const rows = [
      row({ status: 'downloading' }),
      row({ queue_id: 11, status: 'downloading' }),
      row({ queue_id: 12, status: 'Queued' }),
      row({ queue_id: 13, status: 'Paused' }),
      row({ queue_id: 14, tracked_state: 'importPending' }),
      row({ queue_id: 15, error: 'disque plein', arr_media_id: null }),
    ];
    const counts = queueCounts(rows);

    expect(counts).toEqual({
      downloading: 2, queued: 1, paused: 1, completed: 0,
      intervention: 2, importPending: 1, blocked: 1,
    });
    // Chaque ligne compte pour exactement une catégorie.
    const partition = counts.downloading + counts.queued + counts.paused + counts.completed + counts.intervention;
    expect(partition).toBe(rows.length);
    expect(counts.importPending + counts.blocked).toBe(counts.intervention);
  });

  it('ne compte pas un élément en intervention parmi les téléchargements actifs', () => {
    // status 'downloading' mais import bloqué : c'est une intervention, pas un actif.
    const counts = queueCounts([row({ status: 'downloading', tracked_state: 'importPending' })]);
    expect(counts.downloading).toBe(0);
    expect(counts.importPending).toBe(1);
  });

  it('tolère une file absente', () => {
    expect(queueCounts(null).intervention).toBe(0);
    expect(queueCounts([]).downloading).toBe(0);
  });
});

describe('rowKey et queueDetailPath', () => {
  it('reste stable pour un téléchargement direct sans queue_id', () => {
    expect(rowKey({ title: 'Dune' })).toBe('direct:Dune');
    expect(rowKey({ instance_id: 2, queue_id: 9 })).toBe('2:9');
  });

  it('pointe vers la bibliothèque si possible, sinon la demande, sinon nulle part', () => {
    expect(queueDetailPath({ library_id: 4 })).toBe('/media/library/4');
    expect(queueDetailPath({ request_id: 7 })).toBe('/media/request/7');
    expect(queueDetailPath({ linked_request_id: 8 })).toBe('/media/request/8');
    expect(queueDetailPath({})).toBeNull();
  });
});
