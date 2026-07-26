// Classification des éléments de la file *arr — fonctions pures, source unique.
//
// Ces règles vivaient dans le `<script setup>` de DownloadsView, et le tableau de bord en
// avait sa propre version, divergente : il concaténait `status` et `tracked_state` puis
// cherchait des sous-chaînes, si bien qu'un élément `importPending` était compté à la fois
// dans « En attente d'import » et dans « Bloqués ». Un même téléchargement donnait donc
// deux chiffres différents selon la page — et le tableau de bord ne correspondait pas à la
// page qu'il ouvre.
//
// Les règles retenues sont celles de DownloadsView : c'est la page qui agit réellement sur
// la file (relancer, retirer, associer), donc celle dont la classification est éprouvée.

import { mediaDetailPath } from '@/mediaUrl';

/** Identifiant stable d'une ligne, y compris pour un téléchargement direct sans queue_id. */
export function rowKey(row) {
  return `${row.instance_id || row.instance || 'direct'}:${row.queue_id || row.download_id || row.request_id || row.title}`;
}

/** Une action (relance, retrait) n'est possible que sur un élément suivi par une instance *arr. */
export function canAct(row) {
  return row.instance_id != null && row.queue_id != null;
}

/**
 * Statut normalisé : 'error' | 'paused' | 'queued' | 'completed' | 'downloading'.
 * `row.error` l'emporte : un élément porteur d'un message d'erreur est en erreur, quel
 * que soit le libellé de statut renvoyé par *arr.
 */
export function statusKey(row) {
  const value = (row.status || '').toLowerCase();
  if (row.error || value.includes('error') || value.includes('warning') || value.includes('failed')) return 'error';
  if (value.includes('pause')) return 'paused';
  if (value.includes('queue')) return 'queued';
  if ((row.progress || 0) >= 100) return 'completed';
  return 'downloading';
}

const STATUS_LABELS = {
  error: 'Erreur',
  paused: 'En pause',
  queued: 'En file',
  completed: 'Terminé',
  downloading: 'En cours',
};

export function statusLabel(row) {
  return STATUS_LABELS[statusKey(row)];
}

/** Fichier téléchargé que *arr n'arrive pas à importer (fréquent sur les épisodes « TBA »). */
export function isImportPending(row) {
  return (row.tracked_state || '').toLowerCase() === 'importpending' && canAct(row);
}

/** Téléchargement qu'aucune demande ni entrée de bibliothèque ne réclame. */
export function isUnmatched(row) {
  return row.request_id == null && row.library_id == null && ['sonarr', 'radarr'].includes(row.arr_type);
}

/** Erreur Sonarr sur une série connue : l'épisode cible doit être choisi à la main. */
export function needsEpisodeImport(row) {
  return row.arr_type === 'sonarr' && statusKey(row) === 'error' && row.arr_media_id != null;
}

/** Une intervention humaine est nécessaire pour que ce téléchargement aboutisse. */
export function requiresIntervention(row) {
  return isUnmatched(row) || needsEpisodeImport(row) || isImportPending(row) || statusKey(row) === 'error';
}

/** Fiche média correspondante, ou null si le téléchargement n'est rattaché à rien. */
export function queueDetailPath(row) {
  if (row.library_id) return mediaDetailPath({ library_id: row.library_id }, 'library');
  const id = row.request_id || row.linked_request_id;
  return id ? mediaDetailPath({ request_id: id }, 'request') : null;
}

/**
 * Compteurs par catégorie, alignés sur les trois groupes affichés par /downloads.
 *
 * La partition est stricte : un élément nécessitant une intervention n'est jamais compté
 * en plus dans `downloading` / `queued` / `paused` / `completed`, et `importPending` est
 * sorti de `blocked` pour ne pas être compté deux fois.
 */
export function queueCounts(rows) {
  const counts = {
    downloading: 0, queued: 0, paused: 0, completed: 0,
    intervention: 0, importPending: 0, blocked: 0,
  };
  for (const row of rows || []) {
    if (requiresIntervention(row)) {
      counts.intervention += 1;
      if (isImportPending(row)) counts.importPending += 1;
      else counts.blocked += 1;
      continue;
    }
    counts[statusKey(row)] += 1;
  }
  return counts;
}
