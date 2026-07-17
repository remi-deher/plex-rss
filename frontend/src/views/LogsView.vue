<template>
  <div class="page">
    <header class="page-head">
      <div><h1>Journaux</h1><p>Diagnostic applicatif, parcours des demandes et tâches planifiées.</p></div>
      <button class="icon-button" :disabled="loading" title="Actualiser" @click="load"><RefreshCw :class="{spin: loading}" /></button>
    </header>
    <nav class="detail-tabs">
      <button v-for="item in tabs" :key="item.id" :class="{active: tab === item.id}" @click="tab = item.id; load()">{{ item.label }}</button>
    </nav>
    <div class="toolbar wrap">
      <input v-model="search" class="search" type="search" placeholder="Filtrer les journaux" @keyup.enter="load">
      <select v-if="tab === 'diagnostic'" v-model="category" @change="load">
        <option value="">Toutes les sections</option><option value="request">Demande</option><option value="arr">Arr</option><option value="plex">Plex</option><option value="vf_vo">VF / VO</option><option value="notification">Notification</option>
      </select>
      <select v-if="tab === 'app'" v-model="level"><option value="">Tous les niveaux</option><option>INFO</option><option>WARNING</option><option>ERROR</option><option>CRITICAL</option></select>
      <select v-if="tab === 'polls'" v-model="job" @change="load"><option value="">Toutes les tâches</option><option v-for="name in jobs" :key="name">{{ name }}</option></select>
      <button v-if="tab === 'pending' && rows.length" class="secondary danger" @click="purge"><Trash2 />Purger la file</button>
    </div>
    <p v-if="error" class="notice error-text">{{ error }}</p>
    <section class="panel table-wrap">
      <table><thead><tr><th>Date</th><th>Section</th><th>Description</th><th>Résultat</th></tr></thead>
        <tbody><tr v-for="row in filtered" :key="keyOf(row)"><td>{{ dateOf(row) }}</td><td><span class="badge" :class="badgeOf(row)">{{ typeOf(row) }}</span></td><td><strong>{{ titleOf(row) }}</strong><small class="table-detail">{{ detailOf(row) }}</small></td><td>{{ resultOf(row) }}</td></tr></tbody>
      </table><p v-if="!loading && !filtered.length" class="empty">Aucune entrée pour ce filtre.</p>
    </section>
    <ConfirmModal v-bind="confirmDialog" @cancel="resolveConfirm(false)" @confirm="resolveConfirm(true)" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { RefreshCw, Trash2 } from '@lucide/vue';
import { api } from '@/api';
import ConfirmModal from '@/components/ConfirmModal.vue';
import { useConfirm } from '@/composables/useConfirm';

const tab = ref('diagnostic'), rows = ref([]), loading = ref(false), error = ref('');
const search = ref(''), level = ref(''), category = ref(''), job = ref('');
const { dialog: confirmDialog, askConfirm, resolveConfirm } = useConfirm();
const tabs = [{ id: 'diagnostic', label: 'Parcours demandes' }, { id: 'app', label: 'Application' }, { id: 'polls', label: 'Tâches planifiées' }, { id: 'audit', label: 'Audit admin' }, { id: 'pending', label: 'File notifications' }];
const jobs = computed(() => [...new Set(rows.value.map(x => x.job).filter(Boolean))]);
const filtered = computed(() => rows.value.filter(row => (!level.value || row.level === level.value) && (!search.value || JSON.stringify(row).toLowerCase().includes(search.value.toLowerCase()))));

function endpoint() {
  if (tab.value === 'diagnostic') return `/api/diagnostic-logs?limit=300${category.value ? `&category=${encodeURIComponent(category.value)}` : ''}${search.value ? `&search=${encodeURIComponent(search.value)}` : ''}`;
  if (tab.value === 'polls') return `/api/poll-history?limit=200${job.value ? `&job=${encodeURIComponent(job.value)}` : ''}`;
  if (tab.value === 'audit') return '/api/admin-action-logs?limit=200';
  if (tab.value === 'pending') return '/api/notifications/pending';
  return '/api/logs';
}
async function load() { loading.value = true; error.value = ''; try { const data = await api(endpoint()); rows.value = Array.isArray(data) ? data : (data.items || []); } catch (e) { error.value = e.message; } finally { loading.value = false; } }
async function purge() { if (!await askConfirm({ title: 'Purger la file de notifications ?', message: 'Toutes les notifications en attente seront supprimées définitivement.', confirmLabel: 'Purger la file', danger: true })) return; await api('/api/notifications/pending/purge', { method: 'POST', body: JSON.stringify({ ids: [], mark_handled: false }) }); await load(); }
function keyOf(r) { return `${tab.value}-${r.id || r.time || r.created_at}-${r.message || r.action || r.job}`; }
function dateOf(r) { const v = r.created_at || r.time || r.started_at; return v ? new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(v.replace?.(' ', 'T') || v)) : '-'; }
function typeOf(r) { if (tab.value === 'diagnostic') return ({ request: 'Demande', arr: 'Arr', plex: 'Plex', vf_vo: 'VF / VO', notification: 'Notification' }[r.category] || r.category || '-'); return r.level || r.job || r.action || r.event_label || r.event || '-'; }
function titleOf(r) { return tab.value === 'diagnostic' ? (r.title || `Demande #${r.request_id || '-'}`) : (r.message || r.summary || r.media_title || `Demande #${r.req_id || '-'}`); }
function detailOf(r) { if (tab.value === 'diagnostic') return `${r.action} — ${r.message || ''} ${r.details ? JSON.stringify(r.details) : ''}`; if (tab.value === 'app') return r.logger || ''; if (tab.value === 'polls') return r.error_detail || `${r.items_processed || 0} élément(s) traité(s)`; if (tab.value === 'audit') return r.actor_name || ''; return (r.recipients || []).join(', '); }
function resultOf(r) { if (tab.value === 'diagnostic') return r.status || '-'; if (tab.value === 'polls') return r.errors ? `${r.errors} erreur(s)` : `${r.duration_ms || 0} ms`; if (tab.value === 'audit') return `${r.target_count || 0} cible(s)`; return r.valid ? 'Valide' : 'Invalide'; }
function badgeOf(r) { if (r.status === 'error' || r.level === 'ERROR' || r.level === 'CRITICAL' || r.errors || r.valid === false) return 'failed'; if (r.status === 'warning' || r.status === 'ignored' || r.level === 'WARNING') return 'pending'; return 'available'; }
onMounted(load);
</script>
