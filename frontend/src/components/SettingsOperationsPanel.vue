<template>
  <div class="settings-grid">
    <section class="operations-summary span-two">
      <RouterLink to="/downloads" class="operation-summary-card" :class="{alert:acquisitions.counts.blocked_imports}"><Download/><div><span>Interventions</span><strong>{{ acquisitions.counts.blocked_imports }}</strong><small>Imports bloqués</small></div></RouterLink>
      <RouterLink to="/issues" class="operation-summary-card"><CircleAlert/><div><span>Signalements</span><strong>À traiter</strong><small>Ouvrir le centre d’incidents</small></div></RouterLink>
      <RouterLink to="/settings?tab=conflicts" class="operation-summary-card" :class="{alert:conflicts.length}"><WandSparkles/><div><span>Deduplication</span><strong>{{ conflicts.length }}</strong><small>Conflit(s) a examiner</small></div></RouterLink>
      <RouterLink to="/settings?tab=acquisitions" class="operation-summary-card" :class="{alert:acquisitions.counts.blocked_imports}"><ListRestart/><div><span>Acquisitions</span><strong>{{ acquisitions.counts.active_batches }}</strong><small>Lot(s) en cours</small></div></RouterLink>
      <RouterLink to="/logs" class="operation-summary-card"><ScrollText/><div><span>Diagnostic</span><strong>Journaux</strong><small>Analyser l’activité récente</small></div></RouterLink>
      <RouterLink to="/maintenance" class="operation-summary-card"><Wrench/><div><span>Opérations</span><strong>Maintenance</strong><small>Lancer une tâche contrôlée</small></div></RouterLink>
      <RouterLink to="/settings?tab=scheduled-tasks" class="operation-summary-card"><Clock/><div><span>Automatisation</span><strong>Planification</strong><small>Voir les tâches planifiées</small></div></RouterLink>
    </section>
  </div>
</template>
<script setup>
import { onMounted, ref } from 'vue';
import { CircleAlert, Clock, Download, ListRestart, ScrollText, WandSparkles, Wrench } from '@lucide/vue';
import { api } from '@/api';

const conflicts = ref([]);
const acquisitions = ref({ items: [], counts: { active_batches: 0, active_queue: 0, blocked_imports: 0 } });

async function loadConflicts(){const data=await api('/api/conflicts');conflicts.value=[...(data.tmdb_conflicts||[]),...(data.orphaned||[]),...(data.long_pending||[])]}
async function loadAcquisitions(){acquisitions.value=await api('/api/acquisition-batches')}

onMounted(()=>Promise.all([loadConflicts(),loadAcquisitions()]));
</script>
<style scoped>
.operations-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap: var(--space-2)}.operation-summary-card{display:flex;align-items:flex-start;gap: var(--space-3);padding:13px;border:1px solid var(--border);border-radius:var(--radius-md);background:var(--surface);color:var(--text);text-decoration:none}.operation-summary-card:hover{border-color:var(--accent)}.operation-summary-card.alert{border-color:rgba(239,68,68,.35)}.operation-summary-card>svg{width:19px;color:var(--muted)}.operation-summary-card.alert>svg{color:var(--danger)}.operation-summary-card>div{display:grid;gap: var(--space-1)}.operation-summary-card span{color:var(--muted);font-size:var(--fs-xs);}.operation-summary-card strong{font-size:var(--fs-md)}.operation-summary-card small{color:var(--muted);font-size:var(--fs-xs)}
@media(max-width:900px){.operations-summary{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:520px){.operations-summary{grid-template-columns:1fr}}
</style>
