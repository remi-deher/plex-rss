<template>
  <div class="settings-grid">
    <section class="operations-summary span-two">
      <RouterLink to="/downloads" class="operation-summary-card" :class="{alert:acquisitions.counts.blocked_imports}"><Download/><div><span>Interventions</span><strong>{{ acquisitions.counts.blocked_imports }}</strong><small>Imports bloqués</small></div></RouterLink>
      <RouterLink to="/issues" class="operation-summary-card"><CircleAlert/><div><span>Signalements</span><strong>À traiter</strong><small>Ouvrir le centre d’incidents</small></div></RouterLink>
      <RouterLink to="/logs" class="operation-summary-card"><ScrollText/><div><span>Diagnostic</span><strong>Journaux</strong><small>Analyser l’activité récente</small></div></RouterLink>
      <RouterLink to="/maintenance" class="operation-summary-card"><Wrench/><div><span>Opérations</span><strong>Maintenance</strong><small>Lancer une tâche contrôlée</small></div></RouterLink>
    </section>
    <nav class="operations-links span-two" aria-label="Navigation d'exploitation"><RouterLink to="/downloads">Téléchargements</RouterLink><RouterLink to="/issues">Incidents</RouterLink><RouterLink to="/settings?tab=scheduled-tasks">Planification</RouterLink><RouterLink to="/logs">Journaux</RouterLink><RouterLink to="/maintenance">Maintenance</RouterLink></nav>
    <div class="settings-cards span-two">
      <SettingsCard title="Secrets" subtitle="Token API et secret webhook" :icon="KeyRound" status="neutral" :collapsible="false">
        <template #actions>
          <button class="icon-button" title="Actualiser" aria-label="Actualiser" @click.stop="loadSecrets"><RefreshCw/></button>
        </template>
        <div>
          <strong style="display:block;margin-bottom:8px;font-size:13px">Token API</strong>
          <code class="secret-box">{{ apiToken || (tokenActive ? 'Actif (valeur masquee)' : 'Aucun token genere') }}</code>
          <div class="actions">
            <button class="secondary" @click="generateToken"><KeyRound/>Generer</button>
            <button class="secondary danger" @click="deleteToken"><Trash2/>Revoquer</button>
          </div>
        </div>
        <div>
          <strong style="display:block;margin-bottom:8px;font-size:13px">Secret webhook</strong>
          <code class="secret-box">{{ webhookSecret || (webhookActive ? 'Actif (valeur masquee)' : 'Aucun secret genere') }}</code>
          <div class="actions">
            <button class="secondary" @click="generateWebhook"><KeyRound/>Generer</button>
            <button class="secondary danger" @click="deleteWebhook"><Trash2/>Revoquer</button>
          </div>
        </div>
      </SettingsCard>

      <SettingsCard :title="`Conflits de deduplication`" :subtitle="`${conflicts.length} element(s) a examiner`" :icon="WandSparkles" :status="conflicts.length ? 'error' : 'active'" :collapsible="false">
        <template #actions>
          <button class="secondary" @click.stop="autoResolve"><WandSparkles/>Resolution automatique</button>
          <button class="icon-button" title="Actualiser" aria-label="Actualiser" @click.stop="loadConflicts"><RefreshCw/></button>
        </template>
        <article v-for="group in conflicts" :key="group.key||group.tmdb_id" class="detail-row">
          <div><strong>{{ group.title||group.key||`TMDB ${group.tmdb_id}` }}</strong><span>{{ (group.entries||[]).length || 1 }} entree(s) · {{ group.type||'' }}</span></div>
          <div class="actions">
            <button v-if="group.entries?.length" class="secondary" @click="resolve(group)">Fusionner</button>
            <button v-if="group.type==='orphan'" class="secondary danger" @click="removeOrphan(group)"><Trash2/>Supprimer</button>
            <button class="icon-button" title="Ignorer" aria-label="Ignorer" @click="ignore(group)"><Check/></button>
          </div>
        </article>
        <p v-if="!conflicts.length" class="empty">Aucun conflit detecte.</p>
      </SettingsCard>

      <SettingsCard title="Acquisitions de series" :subtitle="acquisitionSubtitle" :icon="ListRestart" :status="acquisitions.counts.blocked_imports ? 'error' : acquisitions.counts.active_batches ? 'neutral' : 'active'" :collapsible="false">
        <template #actions>
          <button class="icon-button" title="Actualiser" aria-label="Actualiser" @click.stop="loadAcquisitions"><RefreshCw/></button>
        </template>
        <div class="acquisition-counters">
          <span class="badge">{{ acquisitions.counts.active_batches }} lot(s)</span>
          <span class="badge">{{ acquisitions.counts.active_queue }} element(s) actif(s)</span>
          <span class="badge" :class="{ danger: acquisitions.counts.blocked_imports }">{{ acquisitions.counts.blocked_imports }} import(s) bloque(s)</span>
        </div>
        <article v-for="batch in acquisitions.items" :key="batch.id" class="acquisition-batch">
          <div class="acquisition-head">
            <div>
              <strong>{{ batch.title }}</strong>
              <span>{{ batchStatus(batch.status) }} · {{ sourceLabel(batch.source) }}</span>
            </div>
            <span class="badge">{{ scopeLabel(batch) }}</span>
          </div>
          <small>
            Ouvert {{ formatDate(batch.opened_at) }}
            <template v-if="batch.last_plex_change_at"> · dernier changement Plex {{ formatDate(batch.last_plex_change_at) }}</template>
          </small>
          <div v-if="batch.pending_events.length" class="acquisition-events">
            {{ batch.pending_events.length }} jalon(s) Plex en attente du recapitulatif.
          </div>
          <div v-for="row in batch.queue" :key="row.id" class="queue-observation" :class="{ blocked: row.state === 'import_blocked' }">
            <div>
              <strong>{{ episodeLabel(row) }}</strong>
              <span>{{ queueStateLabel(row.state) }} · {{ Math.round(row.progress || 0) }} %</span>
              <small v-if="row.error">{{ row.error }}</small>
            </div>
            <span v-if="row.state === 'import_blocked'" class="badge danger">Intervention Sonarr</span>
          </div>
        </article>
        <p v-if="!acquisitions.items.length" class="empty">Aucune acquisition de serie en cours.</p>
      </SettingsCard>
    </div>
  </div>
  <ConfirmModal v-bind="confirmDialog" @cancel="resolveConfirm(false)" @confirm="resolveConfirm(true)" />
</template>
<script setup>
import { computed,onMounted,ref } from 'vue';import { Check,CircleAlert,Download,KeyRound,ListRestart,RefreshCw,ScrollText,Trash2,WandSparkles,Wrench } from '@lucide/vue';import { api } from '@/api';import SettingsCard from './settings/SettingsCard.vue';import ConfirmModal from './ConfirmModal.vue';import { useConfirm } from '@/composables/useConfirm';
const conflicts=ref([]),apiToken=ref(''),webhookSecret=ref(''),tokenActive=ref(false),webhookActive=ref(false);
const acquisitions=ref({items:[],counts:{active_batches:0,active_queue:0,blocked_imports:0}});
const acquisitionSubtitle=computed(()=>acquisitions.value.counts.blocked_imports ? 'Intervention requise dans Sonarr' : acquisitions.value.counts.active_batches ? 'Telechargements et stabilisation en cours' : 'Aucun lot actif');
const { dialog: confirmDialog, askConfirm, resolveConfirm } = useConfirm();
async function loadSecrets(){const [token,webhook]=await Promise.all([api('/api/settings/token').catch(()=>({})),api('/api/settings/webhook-secret').catch(()=>({}))]);tokenActive.value=Boolean(token.active);webhookActive.value=Boolean(webhook.active)}async function generateToken(){const data=await api('/api/settings/token',{method:'POST',body:JSON.stringify({scopes:['*']})});apiToken.value=data.api_token;tokenActive.value=true}async function deleteToken(){await api('/api/settings/token',{method:'DELETE'});apiToken.value='';tokenActive.value=false}async function generateWebhook(){const data=await api('/api/settings/webhook-secret',{method:'POST'});webhookSecret.value=data.webhook_secret;webhookActive.value=true}async function deleteWebhook(){await api('/api/settings/webhook-secret',{method:'DELETE'});webhookSecret.value='';webhookActive.value=false}
async function loadConflicts(){const data=await api('/api/conflicts');conflicts.value=[...(data.tmdb_conflicts||[]),...(data.orphaned||[]).map(x=>({...x,type:'orphan'})),...(data.long_pending||[]).map(x=>({...x,type:'pending'}))]}async function autoResolve(){await api('/api/conflicts/auto-resolve',{method:'POST'});await loadConflicts()}async function resolve(group){const entries=group.entries||[];if(entries.length<2)return;const keep=group.recommended_id||entries[0].id;await api('/api/conflicts/resolve',{method:'POST',body:JSON.stringify({keep_id:keep,delete_ids:entries.filter(x=>x.id!==keep).map(x=>x.id)})});await loadConflicts()}async function ignore(group){await api('/api/conflicts/ignore',{method:'POST',body:JSON.stringify({key:group.key})});await loadConflicts()}async function removeOrphan(group){if(!await askConfirm({title:'Supprimer ce conflit ?',message:`${group.title} sera supprimé définitivement.`,confirmLabel:'Supprimer',danger:true}))return;await api(`/api/conflicts/orphan/${group.id}`,{method:'DELETE'});await loadConflicts()}
async function loadAcquisitions(){acquisitions.value=await api('/api/acquisition-batches')}
function formatDate(value){return value ? new Intl.DateTimeFormat('fr-FR',{dateStyle:'short',timeStyle:'short'}).format(new Date(value)) : '-'}
function batchStatus(status){return status==='stabilizing'?'Stabilisation Plex':'Activite Sonarr'}
function sourceLabel(source){return ({api:'API',rss:'Watchlist Plex',watchlist:'Watchlist Plex'})[source]||source||'Source inconnue'}
function scopeLabel(batch){return batch.expected_scope==='all_seasons'?`${batch.expected_seasons.length} saison(s) attendue(s)`:`${batch.expected_seasons.length} saison(s) surveillee(s)`}
function queueStateLabel(state){return ({queued:'En attente',downloading:'Telechargement',importing:'Import',awaiting_import:'Import en attente',import_blocked:'Import bloque'})[state]||state}
function episodeLabel(row){const season=row.season_number!=null?`S${String(row.season_number).padStart(2,'0')}`:'';const episode=row.episode_number!=null?`E${String(row.episode_number).padStart(2,'0')}`:'';return [season+episode,row.title].filter(Boolean).join(' · ')||'Element Sonarr'}
onMounted(()=>Promise.all([loadSecrets(),loadConflicts(),loadAcquisitions()]));
</script>
<style scoped>
.operations-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px}.operation-summary-card{display:flex;align-items:flex-start;gap:10px;padding:13px;border:1px solid var(--border);border-radius:10px;background:var(--surface);color:var(--text);text-decoration:none}.operation-summary-card:hover{border-color:var(--accent)}.operation-summary-card.alert{border-color:rgba(239,68,68,.35)}.operation-summary-card>svg{width:19px;color:var(--accent)}.operation-summary-card.alert>svg{color:var(--danger)}.operation-summary-card>div{display:grid;gap:2px}.operation-summary-card span{color:var(--muted);font-size:9px;text-transform:uppercase}.operation-summary-card strong{font-size:14px}.operation-summary-card small{color:var(--muted);font-size:9px}.operations-links{display:flex;gap:6px;overflow-x:auto}.operations-links a{padding:7px 10px;border:1px solid var(--border);border-radius:999px;color:var(--muted);font-size:10px;text-decoration:none;white-space:nowrap}.operations-links a.router-link-active{color:var(--accent);border-color:var(--accent)}
.acquisition-counters,.acquisition-events{display:flex;gap:8px;flex-wrap:wrap}.acquisition-batch{border-top:1px solid var(--border);padding:14px 0;display:grid;gap:8px}.acquisition-head,.queue-observation{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.acquisition-head div,.queue-observation div{display:grid;gap:3px}.queue-observation{padding:10px;border-radius:8px;background:var(--surface-2)}.queue-observation.blocked{border:1px solid var(--danger)}.badge.danger{background:color-mix(in srgb,var(--danger) 18%,transparent);color:var(--danger)}
@media(max-width:900px){.operations-summary{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:520px){.operations-summary{grid-template-columns:1fr}.operations-links{position:sticky;top:8px;z-index:8;padding:8px;background:var(--surface);border:1px solid var(--border);border-radius:9px}}
</style>
