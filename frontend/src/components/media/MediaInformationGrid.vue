<template>
  <div class="media-information-grid">
    <article class="information-card state-card">
      <header><Activity/><div><span>État actuel</span><strong>{{ currentState }}</strong></div></header>
      <dl>
        <div><dt>Plex</dt><dd>{{ detail.in_library ? 'Disponible' : 'Absent' }}</dd></div>
        <div><dt>Source</dt><dd>{{ detail.origin_label || 'Ajout direct' }}</dd></div>
        <div><dt>Prochaine action</dt><dd>{{ nextAction }}</dd></div>
      </dl>
      <p v-if="detail.waiting_reason" class="information-note">{{ detail.waiting_reason }}</p>
    </article>

    <article class="information-card">
      <header><Layers3/><div><span>Couverture</span><strong>{{ coverageTitle }}</strong></div></header>
      <dl v-if="detail.media_type==='show'">
        <div><dt>Saisons complètes</dt><dd>{{ coverage.complete }} / {{ coverage.total }}</dd></div>
        <div><dt>Épisodes</dt><dd>{{ coverage.available }} / {{ coverage.episodes }}</dd></div>
        <div><dt>Langue</dt><dd>{{ languageLabel }}</dd></div>
      </dl>
      <dl v-else><div><dt>Disponibilité</dt><dd>{{ detail.in_library ? 'Dans Plex' : 'En attente' }}</dd></div><div><dt>Langue</dt><dd>{{ languageLabel }}</dd></div></dl>
    </article>

    <article class="information-card">
      <header><CalendarClock/><div><span>Prochaines sorties</span><strong>{{ upcoming.length ? `${upcoming.length} planifiée${upcoming.length>1?'s':''}` : 'Aucune sortie' }}</strong></div></header>
      <ul v-if="upcoming.length" class="compact-list"><li v-for="event in upcoming" :key="`${event.date}:${event.subtitle}`"><div><strong>{{ event.subtitle || event.title }}</strong><small>{{ formatDate(event.date) }}</small></div><span class="badge">{{ event.tracked ? 'Suivi' : 'Catalogue' }}</span></li></ul>
      <p v-else class="empty-copy">Aucune date future connue.</p>
    </article>

    <article class="information-card">
      <header><Users/><div><span>Demandes</span><strong>{{ requestersCount }} demandeur{{ requestersCount>1?'s':'' }}</strong></div></header>
      <dl><div><dt>Première demande</dt><dd>{{ firstRequestDate }}</dd></div><div><dt>Source</dt><dd>{{ detail.origin_label || 'Inconnue' }}</dd></div><div><dt>Demandes liées</dt><dd>{{ requests.length }}</dd></div></dl>
    </article>

    <article class="information-card notification-card">
      <header><BellRing/><div><span>Notifications</span><strong>{{ notifications.length ? `${notifications.length} événement${notifications.length>1?'s':''}` : 'Aucun envoi' }}</strong></div></header>
      <ul v-if="notifications.length" class="compact-list"><li v-for="log in notifications.slice(0,5)" :key="log.id"><div><strong>{{ eventLabel(log) }}</strong><small>{{ log.recipient }} · {{ formatDate(log.sent_at) }}</small></div><span class="badge" :class="log.success?'available':'failed'">{{ log.success ? 'Envoyée' : 'Échec' }}</span></li></ul>
      <p v-else class="empty-copy">Aucune notification enregistrée pour ce média.</p>
    </article>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { Activity,BellRing,CalendarClock,Layers3,Users } from '@lucide/vue';

const props=defineProps({detail:{type:Object,required:true},vfDetail:{type:Object,default:null}});
const requests=computed(()=>props.detail.requests||[]);
const notifications=computed(()=>props.detail.notification_history||[]);
const currentState=computed(()=>props.detail.operational_status_label||(props.detail.in_library?'Disponible':'En attente'));
const nextAction=computed(()=>props.detail.in_library?'Aucune action requise':props.detail.waiting_reason?'Vérifier le blocage':props.detail.arr_id?'Attendre Sonarr / Radarr':'Envoyer vers Sonarr / Radarr');
const seasonRows=computed(()=>requests.value.flatMap(request=>request.seasons||[]));
const coverage=computed(()=>{const rows=seasonRows.value,total=rows.length,complete=rows.filter(row=>row.status==='complete'||(row.episodes_total_count>0&&row.episodes_available_count>=row.episodes_total_count)).length;return {total,complete,available:rows.reduce((sum,row)=>sum+(row.episodes_available_count||0),0),episodes:rows.reduce((sum,row)=>sum+(row.episodes_total_count||0),0)}});
const coverageTitle=computed(()=>props.detail.media_type==='show'?(coverage.value.total?`${coverage.value.complete} saison${coverage.value.complete>1?'s':''} complète${coverage.value.complete>1?'s':''}`:'Couverture inconnue'):(props.detail.in_library?'Film disponible':'Film attendu'));
const languageLabel=computed(()=>props.detail.vf_granularity==='partial'?'VF partielle':props.detail.vf_granularity==='vo'?'VO':props.detail.has_vf?'VF':'Non analysée');
const upcoming=computed(()=>(props.detail.calendar||[]).filter(event=>new Date(event.date)>new Date()).slice(0,3));
const requesterIds=computed(()=>new Set(requests.value.flatMap(request=>request.requester_ids||[request.plex_user_id]).filter(Boolean)));
const requestersCount=computed(()=>requesterIds.value.size);
const firstRequestDate=computed(()=>{const dates=requests.value.map(request=>request.requested_at).filter(Boolean).sort();return dates.length?formatDate(dates[0]):'Non renseignée'});
function formatDate(value){if(!value)return 'Non renseignée';return new Intl.DateTimeFormat('fr-FR',{dateStyle:'medium',timeStyle:'short'}).format(new Date(value))}
function eventLabel(log){const labels={request:'Demande enregistrée',available:'Média disponible',vf_available:'VF disponible'};let label=labels[log.event]||String(log.event||'Notification').replaceAll('_',' ');if(log.season_number!=null)label+=` · Saison ${log.season_number}`;if(log.episode_number!=null)label+=` épisode ${log.episode_number}`;return label}
</script>

<style scoped>
.media-information-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-bottom:18px}.information-card{display:grid;align-content:start;gap:13px;padding:14px;border:1px solid var(--border);border-radius:12px;background:var(--surface-2)}.information-card>header{display:flex;align-items:center;gap:9px}.information-card>header svg{width:19px;color:var(--accent)}.information-card>header div{display:grid;gap:2px}.information-card>header span{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.06em}.information-card>header strong{font-size:14px}.information-card dl{display:grid;gap:7px;margin:0}.information-card dl>div{display:flex;justify-content:space-between;gap:12px}.information-card dt{color:var(--muted);font-size:11px}.information-card dd{margin:0;text-align:right;font-size:11px;font-weight:700}.information-note{margin:0;padding:8px;border-left:2px solid var(--accent);background:rgba(229,160,13,.07);font-size:11px}.compact-list{display:grid;gap:8px;margin:0;padding:0;list-style:none}.compact-list li{display:flex;align-items:center;justify-content:space-between;gap:10px}.compact-list li>div{display:grid;gap:2px;min-width:0}.compact-list strong,.compact-list small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.compact-list strong{font-size:11px}.compact-list small,.empty-copy{color:var(--muted);font-size:10px}.empty-copy{margin:0}.notification-card{grid-column:1/-1}@media(max-width:720px){.media-information-grid{grid-template-columns:1fr}.notification-card{grid-column:auto}}
</style>
