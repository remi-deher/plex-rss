<template>
  <div class="settings-grid">
    <div class="settings-cards span-two">
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
    </div>
  </div>
  <ConfirmModal v-bind="confirmDialog" @cancel="resolveConfirm(false)" @confirm="resolveConfirm(true)" />
</template>
<script setup>
import { onMounted, ref } from 'vue';
import { Check, RefreshCw, Trash2, WandSparkles } from '@lucide/vue';
import { api } from '@/api';
import SettingsCard from './SettingsCard.vue';
import ConfirmModal from '../ConfirmModal.vue';
import { useConfirm } from '@/composables/useConfirm';

const conflicts = ref([]);
const { dialog: confirmDialog, askConfirm, resolveConfirm } = useConfirm();

async function loadConflicts(){const data=await api('/api/conflicts');conflicts.value=[...(data.tmdb_conflicts||[]),...(data.orphaned||[]).map(x=>({...x,type:'orphan'})),...(data.long_pending||[]).map(x=>({...x,type:'pending'}))]}
async function autoResolve(){await api('/api/conflicts/auto-resolve',{method:'POST'});await loadConflicts()}
async function resolve(group){const entries=group.entries||[];if(entries.length<2)return;const keep=group.recommended_id||entries[0].id;await api('/api/conflicts/resolve',{method:'POST',body:JSON.stringify({keep_id:keep,delete_ids:entries.filter(x=>x.id!==keep).map(x=>x.id)})});await loadConflicts()}
async function ignore(group){await api('/api/conflicts/ignore',{method:'POST',body:JSON.stringify({key:group.key})});await loadConflicts()}
async function removeOrphan(group){if(!await askConfirm({title:'Supprimer ce conflit ?',message:`${group.title} sera supprimé définitivement.`,confirmLabel:'Supprimer',danger:true}))return;await api(`/api/conflicts/orphan/${group.id}`,{method:'DELETE'});await loadConflicts()}

onMounted(loadConflicts);
</script>
