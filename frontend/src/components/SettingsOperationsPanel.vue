<template>
  <div class="settings-grid">
    <div class="settings-cards span-two">
      <SettingsCard title="Analyse VF" :icon="ScanSearch" status="neutral" :collapsible="false">
        <template #actions>
          <button class="icon-button" title="Actualiser" @click.stop="loadVff"><RefreshCw/></button>
        </template>
        <div class="status-stack">
          <span>Scan : {{ scanStatus.status||scanStatus.state||'inconnu' }}</span>
          <span>Synchronisation Plex : {{ syncStatus.status||syncStatus.state||'inconnue' }}</span>
        </div>
        <div class="actions">
          <button class="secondary" @click="vff('/api/vff/scan?force=true')"><ScanSearch/>Scanner maintenant</button>
          <button class="secondary" @click="vff('/api/vff/sync-plex')"><RefreshCw/>Synchroniser Plex</button>
        </div>
      </SettingsCard>

      <SettingsCard title="Secrets" subtitle="Token API et secret webhook" :icon="KeyRound" status="neutral" :collapsible="false">
        <template #actions>
          <button class="icon-button" title="Actualiser" @click.stop="loadSecrets"><RefreshCw/></button>
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
          <button class="icon-button" title="Actualiser" @click.stop="loadConflicts"><RefreshCw/></button>
        </template>
        <article v-for="group in conflicts" :key="group.key||group.tmdb_id" class="detail-row">
          <div><strong>{{ group.title||group.key||`TMDB ${group.tmdb_id}` }}</strong><span>{{ (group.entries||[]).length || 1 }} entree(s) · {{ group.type||'' }}</span></div>
          <div class="actions">
            <button v-if="group.entries?.length" class="secondary" @click="resolve(group)">Fusionner</button>
            <button v-if="group.type==='orphan'" class="secondary danger" @click="removeOrphan(group)"><Trash2/>Supprimer</button>
            <button class="icon-button" title="Ignorer" @click="ignore(group)"><Check/></button>
          </div>
        </article>
        <p v-if="!conflicts.length" class="empty">Aucun conflit detecte.</p>
      </SettingsCard>
    </div>
  </div>
</template>
<script setup>
import { onMounted,ref } from 'vue';import { Check,KeyRound,RefreshCw,ScanSearch,Trash2,WandSparkles } from '@lucide/vue';import { api } from '@/api';import SettingsCard from './settings/SettingsCard.vue';
const scanStatus=ref({}),syncStatus=ref({}),conflicts=ref([]),apiToken=ref(''),webhookSecret=ref(''),tokenActive=ref(false),webhookActive=ref(false);
async function loadVff(){[scanStatus.value,syncStatus.value]=await Promise.all([api('/api/vff/scan-status').catch(()=>({})),api('/api/vff/sync-status').catch(()=>({}))])}async function vff(path){await api(path,{method:'POST'});setTimeout(loadVff,1000)}
async function loadSecrets(){const [token,webhook]=await Promise.all([api('/api/settings/token').catch(()=>({})),api('/api/settings/webhook-secret').catch(()=>({}))]);tokenActive.value=Boolean(token.active);webhookActive.value=Boolean(webhook.active)}async function generateToken(){const data=await api('/api/settings/token',{method:'POST',body:JSON.stringify({scopes:['*']})});apiToken.value=data.api_token;tokenActive.value=true}async function deleteToken(){await api('/api/settings/token',{method:'DELETE'});apiToken.value='';tokenActive.value=false}async function generateWebhook(){const data=await api('/api/settings/webhook-secret',{method:'POST'});webhookSecret.value=data.webhook_secret;webhookActive.value=true}async function deleteWebhook(){await api('/api/settings/webhook-secret',{method:'DELETE'});webhookSecret.value='';webhookActive.value=false}
async function loadConflicts(){const data=await api('/api/conflicts');conflicts.value=[...(data.tmdb_conflicts||[]),...(data.orphaned||[]).map(x=>({...x,type:'orphan'})),...(data.long_pending||[]).map(x=>({...x,type:'pending'}))]}async function autoResolve(){await api('/api/conflicts/auto-resolve',{method:'POST'});await loadConflicts()}async function resolve(group){const entries=group.entries||[];if(entries.length<2)return;const keep=group.recommended_id||entries[0].id;await api('/api/conflicts/resolve',{method:'POST',body:JSON.stringify({keep_id:keep,delete_ids:entries.filter(x=>x.id!==keep).map(x=>x.id)})});await loadConflicts()}async function ignore(group){await api('/api/conflicts/ignore',{method:'POST',body:JSON.stringify({key:group.key})});await loadConflicts()}async function removeOrphan(group){if(!confirm(`Supprimer ${group.title} ?`))return;await api(`/api/conflicts/orphan/${group.id}`,{method:'DELETE'});await loadConflicts()}
onMounted(()=>Promise.all([loadVff(),loadSecrets(),loadConflicts()]));
</script>
