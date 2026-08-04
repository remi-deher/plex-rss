<template>
  <PanelCard title="File de téléchargement" :description="summary">
    <template #action><RouterLink to="/downloads" class="panel-link">Tout voir</RouterLink></template>

    <component
      :is="queueDetailPath(item) ? 'RouterLink' : 'article'"
      v-for="item in visible"
      :key="rowKey(item)"
      :to="queueDetailPath(item)"
      class="queue-row"
    >
      <img
        v-if="item.poster_url"
        :src="item.poster_url"
        class="mini-poster"
        :alt="`Affiche de ${item.title}`"
        loading="lazy"
        decoding="async"
      >
      <div v-else class="mini-poster mini-poster-fallback"><Film /></div>

      <div class="queue-main">
        <div class="queue-heading">
          <strong>{{ item.title }}</strong>
          <span class="badge" :class="badgeClass(item)">{{ shortStatus(item) }}</span>
        </div>

        <div
          class="queue-progress"
          role="progressbar"
          :aria-valuenow="percent(item)"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-label="`Progression de ${item.title}`"
        >
          <i :class="progressClass(item)" :style="{ width: `${percent(item)}%` }" />
        </div>

        <span class="queue-meta">{{ metaLine(item) }}</span>
      </div>
    </component>

    <p v-if="hidden > 0" class="queue-more">
      et {{ hidden }} autre{{ hidden > 1 ? 's' : '' }} en file
    </p>
    <p v-if="!queue.length && !loading" class="empty">Aucun téléchargement en cours.</p>
    <p v-if="loading" class="empty">
      <LoaderCircle class="spin" style="width:16px;height:16px" /> Chargement…
    </p>
  </PanelCard>
</template>

<script setup>
import { computed } from 'vue';
import PanelCard from '@/components/ui/PanelCard.vue';
import { Film, LoaderCircle } from '@lucide/vue';
import { formatFileSize } from '@/utils/format';
import {
  isImportPending,
  isUnmatched,
  queueCounts,
  queueDetailPath,
  requiresIntervention,
  rowKey,
  statusKey,
  statusLabel,
} from '@/downloads/queueRules';

const props = defineProps({
  /** File complete : le tri par urgence doit precéder la troncature (voir `visible`). */
  queue: { type: Array, default: () => [] },
  limit: { type: Number, default: 5 },
  loading: { type: Boolean, default: false },
});

/**
 * Les elements demandant une intervention passent devant.
 *
 * Le tableau de bord passait auparavant `queue.slice(0, 5)` : la troncature ayant lieu
 * avant tout tri, un telechargement bloque pouvait etre absent du panneau alors que c'est
 * precisement ce qu'on vient y chercher. Le panneau recoit donc la file entiere et decide
 * lui-meme de ce qu'il montre.
 */
const sorted = computed(() => {
  const rank = item => (requiresIntervention(item) ? 0 : 1);
  return [...props.queue].sort((a, b) => rank(a) - rank(b) || (b.progress || 0) - (a.progress || 0));
});

const visible = computed(() => sorted.value.slice(0, props.limit));
const hidden = computed(() => Math.max(0, props.queue.length - visible.value.length));

/** Synthese portant sur toute la file, pas seulement sur les lignes affichees. */
const summary = computed(() => {
  if (!props.queue.length) return '';
  const counts = queueCounts(props.queue);
  const parts = [];
  if (counts.downloading) parts.push(`${counts.downloading} en cours`);
  if (counts.queued) parts.push(`${counts.queued} en file`);
  if (counts.paused) parts.push(`${counts.paused} en pause`);
  if (counts.importPending) parts.push(`${counts.importPending} à importer`);
  if (counts.blocked) parts.push(`${counts.blocked} bloqué${counts.blocked > 1 ? 's' : ''}`);
  const remaining = props.queue.reduce((sum, item) => sum + (item.sizeleft || 0), 0);
  if (remaining > 0) parts.push(`${formatFileSize(remaining)} restants`);
  return parts.join(' · ');
});

// Le panneau recalculait sa progression depuis `item.size_left` et affichait
// `item.size_left_label` dans son badge. L'API (/api/arr/queue) ne renvoie ni l'un ni
// l'autre : les champs s'appellent `sizeleft` et `progress`. La progression retombait
// donc systematiquement sur `item.status` — le libelle brut de *arr, en anglais — et le
// badge affichait invariablement « En cours ».
//
// La classification passe desormais par `queueRules`, partagee avec la page
// Telechargements, pour que les deux vues disent la meme chose du meme element.

function percent(item) {
  if (item.progress != null) return Math.min(100, Math.max(0, Math.round(item.progress)));
  if (item.size > 0 && item.sizeleft != null) {
    return Math.min(100, Math.max(0, Math.round((1 - item.sizeleft / item.size) * 100)));
  }
  return 0;
}

/**
 * Ce qui bloque reellement l'element prime sur son statut *arr, et l'erreur prime sur
 * tout le reste : un torrent a la fois en erreur et non rattache doit annoncer l'erreur,
 * sans quoi le badge ("Non rattache") contredirait la barre de progression, rouge.
 */
function shortStatus(item) {
  if (statusKey(item) === 'error') return 'Erreur';
  if (isImportPending(item)) return 'À importer';
  if (isUnmatched(item)) return 'Non rattaché';
  return statusLabel(item);
}

function badgeClass(item) {
  if (statusKey(item) === 'error') return 'failed';
  if (isImportPending(item) || isUnmatched(item)) return 'pending_approval';
  return { completed: 'available', paused: 'pending', queued: 'pending' }[statusKey(item)] || '';
}

function progressClass(item) {
  const key = statusKey(item);
  if (key === 'error') return 'is-error';
  if (key === 'completed') return 'is-done';
  if (key === 'paused' || key === 'queued') return 'is-idle';
  return '';
}

/** Temps restant « 00:18:05 » → « 18 min ». Les heures ne sont gardees que si elles existent. */
function formatTimeLeft(value) {
  const parts = String(value || '').split(':').map(Number);
  if (parts.length < 3 || parts.some(Number.isNaN)) return null;
  const [hours, minutes] = parts;
  if (hours > 0) return `${hours} h ${String(minutes).padStart(2, '0')}`;
  if (minutes > 0) return `${minutes} min`;
  return 'moins d’une minute';
}

/**
 * Ligne secondaire : ce qui aide a decider. Un element qui demande une intervention
 * affiche sa cause, pas son debit — savoir qu'il reste 2 Go a telecharger n'a aucun
 * interet sur un element en erreur depuis hier.
 */
function metaLine(item) {
  if (item.error) return item.error;
  if (isImportPending(item)) return `${item.instance} — téléchargé, import impossible`;
  if (isUnmatched(item)) return `${item.instance} — aucune demande associée`;
  if (item.waiting_reason) return `${item.instance} — ${item.waiting_reason}`;

  const parts = [item.download_client || item.instance];
  if (item.sizeleft > 0) parts.push(`${formatFileSize(item.sizeleft)} restants`);
  const eta = formatTimeLeft(item.timeleft);
  if (eta && statusKey(item) === 'downloading') parts.push(eta);
  return parts.join(' · ');
}
</script>

<style scoped>
.queue-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: var(--space-3);
  align-items: center;
  padding: 9px 0;
  border-bottom: 1px solid var(--border);
  color: inherit;
  text-decoration: none;
}
.queue-row:last-of-type { border-bottom: 0; }

.mini-poster-fallback {
  display: grid;
  place-items: center;
  background: var(--surface-2);
  color: var(--muted);
}
.mini-poster-fallback svg { width: 40%; }

.queue-main { display: grid; gap: var(--space-1); min-width: 0; }

/* `minmax(0, 1fr)` : sans cela un titre long pousse le badge hors de la ligne au lieu de
   se laisser tronquer — c'est exactement le debordement mesure sur ce panneau. */
.queue-heading {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--space-2);
  align-items: center;
}
.queue-heading strong {
  overflow: hidden;
  font-size: var(--fs-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.queue-progress {
  height: 5px;
  overflow: hidden;
  border-radius: var(--radius-pill);
  background: rgba(255, 255, 255, .08);
}
.queue-progress i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--accent);
  transition: width .3s ease;
}
.queue-progress i.is-done { background: #22c55e; }
.queue-progress i.is-error { background: #ef4444; }
.queue-progress i.is-idle { background: var(--muted); }

.queue-meta {
  overflow: hidden;
  color: var(--muted);
  font-size: var(--fs-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.queue-more {
  margin: 8px 0 0;
  color: var(--muted);
  font-size: var(--fs-xs);
}
</style>
