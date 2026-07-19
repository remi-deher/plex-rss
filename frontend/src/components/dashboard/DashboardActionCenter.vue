<template>
  <section class="dashboard-action-center" :class="{clear:!attentionCount}">
    <header class="dashboard-section-head">
      <div><span>Priorité</span><h2>À traiter</h2><p>{{ attentionCount ? `${attentionCount} élément${attentionCount>1?'s':''} demande${attentionCount>1?'nt':''} votre attention.` : 'Aucune intervention nécessaire pour le moment.' }}</p></div>
      <StatusBadge :status="attentionCount?'warning':'active'" :label="attentionCount?`${attentionCount} à traiter`:'Tout est en ordre'"/>
    </header>

    <div v-if="attentionCount" class="dashboard-action-grid">
      <section v-if="pending.length" class="action-stack">
        <div class="action-stack-head"><div><strong>Approbations</strong><span>{{ pending.length }} demande{{ pending.length>1?'s':'' }}</span></div><RouterLink to="/library?status=pending_approval">Tout voir</RouterLink></div>
        <article v-for="row in pending.slice(0,3)" :key="row.id" class="dashboard-action-row">
          <div><strong>{{ row.title }}</strong><span>{{ row.requested_by || row.plex_user || row.plex_user_id || 'Utilisateur Plex' }}</span></div>
          <div class="actions"><button class="icon-button success" title="Approuver" @click="$emit('action',row,'approve')"><Check/></button><button class="icon-button danger" title="Refuser" @click="$emit('action',row,'reject')"><X/></button></div>
        </article>
      </section>

      <section v-if="blocked.length" class="action-stack is-danger">
        <div class="action-stack-head"><div><strong>Téléchargements bloqués</strong><span>{{ blocked.length }} intervention{{ blocked.length>1?'s':'' }}</span></div><RouterLink to="/downloads">Ouvrir la file</RouterLink></div>
        <article v-for="row in blocked.slice(0,3)" :key="row.id||row.queue_id||row.title" class="dashboard-action-row">
          <div><strong>{{ row.title }}</strong><span>{{ row.instance || 'Sonarr / Radarr' }} · {{ reason(row) }}</span></div>
          <StatusBadge status="blocked" label="À vérifier"/>
        </article>
      </section>

      <RouterLink v-if="failedCount" class="action-summary-link" :to="{path:'/library',query:{status:'failed'}}"><AlertTriangle/><div><strong>{{ failedCount }} demande{{ failedCount>1?'s':'' }} en échec</strong><span>Consulter et relancer les demandes concernées</span></div><ChevronRight/></RouterLink>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue';
import { AlertTriangle, Check, ChevronRight, X } from '@lucide/vue';
const props=defineProps({pending:{type:Array,default:()=>[]},queue:{type:Array,default:()=>[]},failedCount:{type:Number,default:0}});
defineEmits(['action']);
const blocked=computed(()=>props.queue.filter(row=>{const value=`${row.status||''} ${row.tracked_state||''}`.toLowerCase();return Boolean(row.error)||['error','warning','failed','importpending'].some(key=>value.includes(key))}));
const attentionCount=computed(()=>props.pending.length+blocked.value.length+Number(props.failedCount||0));
function reason(row){return row.error||row.waiting_reason||((row.tracked_state||'').toLowerCase()==='importpending'?'Import en attente':'Téléchargement en erreur')}
</script>
