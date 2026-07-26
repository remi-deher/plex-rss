<template>
  <div class="page activity-page">
    <PageHeader title="Activité Plex" :description="viewDescription" eyebrow="Supervision">
      <div v-if="currentView!=='live'" class="period-picker">
        <button v-for="value in [7,30,90,365]" :key="value" :class="{active:days===value}" @click="setDays(value)">{{ value }} j</button>
      </div>
      <button class="secondary" :disabled="loading" @click="refresh"><RefreshCw :class="{spin:loading}"/>Actualiser</button>
    </PageHeader>

    <ActivitySubnav :model-value="currentView" :live-count="data.active.length"/>
    <UiFeedback v-if="error" type="error" :message="error" retry @retry="load"/>
    <UiFeedback v-if="loading&&!loaded" type="loading" message="Chargement de l’activité Plex…"/>

    <template v-if="loaded">
      <template v-if="currentView==='overview'">
        <div class="metric-grid activity-metrics">
          <ActivityMetricCard label="En direct" :value="data.active.length" detail="lectures maintenant" :icon="Radio" accent/>
          <ActivityMetricCard label="Sessions" :value="summary.sessions||0" :detail="`sur ${days} jours`" :icon="PlayCircle"/>
          <ActivityMetricCard label="Temps regardé" :value="formatDuration(summary.watch_ms)" detail="durée cumulée" :icon="Clock3"/>
          <ActivityMetricCard label="Transcodage" :value="`${summary.transcode_rate||0} %`" :detail="`${summary.transcodes||0} sessions`" :icon="Cpu"/>
        </div>
        <LiveSessionsPanel :sessions="data.active" interactive @select="selectedSession=$event"/>
        <div class="activity-grid">
          <DailyActivityChart :points="chart"/>
          <UserRankingPanel :users="data.users" :format-duration="formatDuration"/>
        </div>
      </template>

      <template v-else-if="currentView==='live'">
        <section class="live-heading">
          <div><span class="live-indicator"><i></i>{{ data.active.length }} active{{ data.active.length>1?'s':'' }}</span><h2>Flux en direct</h2><p>Suivez la progression et ouvrez une session pour consulter son diagnostic complet.</p></div>
          <span class="live-updated">Actualisé {{ relativeUpdate }}</span>
        </section>
        <LiveSessionsPanel :sessions="data.active" :show-link="false" interactive @select="selectedSession=$event"/>
      </template>

      <template v-else-if="currentView==='history'">
        <FilterBar :active-count="historyFilterCount" :result-count="filteredHistory.length" @reset="resetHistoryFilters">
          <template #primary><label class="search-field"><Search/><input v-model="historySearch" type="search" placeholder="Média, utilisateur ou appareil"></label></template>
          <template #filters>
            <label>Lecture<select v-model="methodFilter"><option value="">Toutes</option><option value="direct_play">Lecture directe</option><option value="direct_stream">Direct Stream</option><option value="transcode">Transcodage</option></select></label>
            <label>Type<select v-model="typeFilter"><option value="">Tous</option><option value="movie">Films</option><option value="episode">Séries</option><option value="track">Musique</option></select></label>
          </template>
        </FilterBar>
        <HistoryTable :items="filteredHistory" @select="selectedSession=$event"/>
      </template>

      <template v-else-if="currentView==='stats'">
        <div class="metric-grid activity-metrics">
          <ActivityMetricCard label="Sessions" :value="summary.sessions||0" :detail="`sur ${days} jours`" :icon="PlayCircle" accent/>
          <ActivityMetricCard label="Temps regardé" :value="formatDuration(summary.watch_ms)" detail="durée cumulée" :icon="Clock3"/>
          <ActivityMetricCard label="Utilisateurs" :value="summary.users||0" detail="comptes actifs" :icon="Users"/>
          <ActivityMetricCard label="Moyenne" :value="formatDuration(averageWatch)" detail="par session" :icon="Timer"/>
        </div>
        <div class="activity-grid">
          <DailyActivityChart :points="chart"/>
          <UserRankingPanel :users="data.users" :format-duration="formatDuration"/>
        </div>
      </template>

      <template v-else-if="currentView==='quality'">
        <div class="metric-grid activity-metrics quality-metrics">
          <ActivityMetricCard v-for="method in qualitySummary" :key="method.key" :label="method.label" :value="method.count" :detail="`${method.rate} % des sessions`" :icon="method.icon" :accent="method.key==='direct_play'"/>
        </div>
        <section class="panel">
          <div class="panel-head"><div><span class="eyebrow">Diagnostic</span><h2>Derniers modes de lecture</h2></div></div>
          <div class="quality-list">
            <button v-for="item in data.history.slice(0,20)" :key="`${item.source}:${item.session_id}`" @click="selectedSession=item">
              <MediaArtwork :src="item.thumb_url" :alt="displayTitle(item)" :type="item.media_type" size="small"/>
              <span><strong>{{ displayTitle(item) }}</strong><small>{{ item.player||item.platform||'Plex' }} · {{ item.quality||'Auto' }}</small></span>
              <PlaybackMethodBadge :method="item.playback_method"/>
            </button>
            <p v-if="!data.history.length" class="empty">Aucune donnée de qualité sur cette période.</p>
          </div>
        </section>
      </template>

      <template v-else-if="currentView==='users'">
        <div class="user-cards">
          <article v-for="(user,index) in data.users" :key="user.name" class="panel user-card">
            <div class="user-avatar">{{ initials(user.name) }}</div>
            <div><h3>{{ user.name }}</h3><p>{{ user.sessions }} session{{ user.sessions>1?'s':'' }} sur {{ days }} jours</p></div>
            <strong>{{ formatDuration(user.watch_ms) }}</strong>
            <div class="user-share"><i :style="{width:`${userShare(user.sessions)}%`}"></i></div>
            <small>#{{ index+1 }} · {{ userShare(user.sessions) }} % des lectures</small>
          </article>
          <p v-if="!data.users.length" class="panel empty">Aucun utilisateur actif sur cette période.</p>
        </div>
      </template>
    </template>

    <SessionDetailDrawer v-if="selectedSession" :session="selectedSession" @close="selectedSession=null"/>
  </div>
</template>

<script setup>
import { computed,onMounted,onUnmounted,ref,watch } from 'vue';
import { useRoute,useRouter } from 'vue-router';
import { CheckCircle2,Clock3,Cpu,PlayCircle,Radio,RefreshCw,Repeat2,Search,Timer,Users,Zap } from '@lucide/vue';
import { api } from '@/api';
import { useRealtime } from '@/events';
import ActivityMetricCard from '@/components/activity/ActivityMetricCard.vue';
import ActivitySubnav from '@/components/activity/ActivitySubnav.vue';
import DailyActivityChart from '@/components/activity/DailyActivityChart.vue';
import HistoryTable from '@/components/activity/HistoryTable.vue';
import LiveSessionsPanel from '@/components/activity/LiveSessionsPanel.vue';
import MediaArtwork from '@/components/activity/MediaArtwork.vue';
import PlaybackMethodBadge from '@/components/activity/PlaybackMethodBadge.vue';
import SessionDetailDrawer from '@/components/activity/SessionDetailDrawer.vue';
import UserRankingPanel from '@/components/activity/UserRankingPanel.vue';

const route=useRoute(),router=useRouter();
const allowedViews=['overview','live','history','stats','quality','users'];
const currentView=computed(()=>allowedViews.includes(route.query.view)?route.query.view:'overview');
const days=ref(Number(route.query.days)||30),loading=ref(false),loaded=ref(false),error=ref('');
const data=ref({active:[],history:[],daily:[],users:[],summary:{}});
const selectedSession=ref(null),historySearch=ref(''),methodFilter=ref(''),typeFilter=ref(''),updatedAt=ref(Date.now()),clock=ref(Date.now());
let clockTimer;
const summary=computed(()=>data.value.summary||{});
const chart=computed(()=>data.value.daily||[]);
const viewDescription=computed(()=>({
  overview:'Vue synthétique des lectures, tendances et utilisateurs.',
  live:'Lectures en cours et diagnostic détaillé des flux.',
  history:'Recherchez et analysez les dernières lectures.',
  stats:'Tendances de consommation et engagement sur la période.',
  quality:'Lecture directe, Direct Stream et transcodage.',
  users:'Activité et temps de visionnage par utilisateur.',
})[currentView.value]);
const averageWatch=computed(()=>summary.value.sessions?Math.round((summary.value.watch_ms||0)/summary.value.sessions):0);
const relativeUpdate=computed(()=>{const seconds=Math.max(0,Math.floor((clock.value-updatedAt.value)/1000));return seconds<5?'à l’instant':`il y a ${seconds} s`});
const filteredHistory=computed(()=>data.value.history.filter(item=>{
  const needle=historySearch.value.trim().toLowerCase();
  const haystack=[displayTitle(item),item.user_name,item.player,item.platform].filter(Boolean).join(' ').toLowerCase();
  return (!needle||haystack.includes(needle))&&(!methodFilter.value||item.playback_method===methodFilter.value)&&(!typeFilter.value||item.media_type===typeFilter.value);
}));
const historyFilterCount=computed(()=>[historySearch.value,methodFilter.value,typeFilter.value].filter(Boolean).length);
const qualitySummary=computed(()=>{
  const total=Math.max(1,summary.value.sessions||0);
  const transcodes=Number(summary.value.transcodes||0);
  const directStream=data.value.history.filter(row=>row.playback_method==='direct_stream').length;
  const directPlay=Math.max(0,total-transcodes-directStream);
  return [
    {key:'direct_play',label:'Lecture directe',count:directPlay,rate:Math.round(directPlay/total*100),icon:CheckCircle2},
    {key:'direct_stream',label:'Direct Stream',count:directStream,rate:Math.round(directStream/total*100),icon:Repeat2},
    {key:'transcode',label:'Transcodage',count:transcodes,rate:Math.round(transcodes/total*100),icon:Cpu},
    {key:'total',label:'Sessions analysées',count:summary.value.sessions||0,rate:100,icon:Zap},
  ];
});

async function load(){if(loading.value)return;loading.value=true;error.value='';try{data.value=await api(`/api/playback?days=${days.value}`);loaded.value=true;updatedAt.value=Date.now()}catch(e){error.value=e.message}finally{loading.value=false}}
async function refresh(){loading.value=true;error.value='';try{data.value=await api('/api/playback/refresh',{method:'POST'});loaded.value=true;updatedAt.value=Date.now()}catch(e){error.value=e.message}finally{loading.value=false}}
function setDays(value){days.value=value;router.replace({query:{...route.query,days:value===30?undefined:String(value)}});load()}
function resetHistoryFilters(){historySearch.value='';methodFilter.value='';typeFilter.value=''}
function formatDuration(ms){const minutes=Math.round((ms||0)/60000);if(minutes<60)return `${minutes} min`;const hours=Math.floor(minutes/60),rest=minutes%60;return `${hours} h${rest?` ${rest} min`:''}`}
function displayTitle(item){return item.grandparent_title?`${item.grandparent_title} · ${item.title}`:item.title}
function initials(name){return String(name||'?').split(/\s+/).slice(0,2).map(part=>part[0]).join('').toUpperCase()}
function userShare(sessions){return Math.round(Number(sessions||0)/Math.max(1,summary.value.sessions||0)*100)}
watch(()=>route.query.days,value=>{const next=Number(value)||30;if(next!==days.value){days.value=next;load()}});
useRealtime(['activity.updated'],load);
onMounted(()=>{load();clockTimer=setInterval(()=>clock.value=Date.now(),1000)});
onUnmounted(()=>clearInterval(clockTimer));
</script>

<style scoped>
.period-picker{display:flex;padding:2px;border:1px solid var(--border);border-radius:99px}.period-picker button{border:0;border-radius:99px;background:transparent;color:var(--muted);padding:6px 9px}.period-picker button.active{background:var(--accent);color:#111}.activity-metrics{margin:0 0 14px}.activity-grid{display:grid;grid-template-columns:2fr 1fr;gap:14px;margin-top:14px}.live-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin:8px 2px 16px}.live-heading h2{margin:6px 0 3px}.live-heading p,.live-updated{margin:0;color:var(--muted);font-size:11px}.live-indicator{display:flex;align-items:center;gap:7px;color:#4ade80;font-size:10px;font-weight:700;text-transform:uppercase}.live-indicator i{width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 4px rgba(34,197,94,.12)}.search-field{display:flex;align-items:center;gap:8px;min-width:min(360px,100%);padding:0 11px;border:1px solid var(--border);border-radius:9px;background:var(--surface-2)}.search-field svg{width:15px;color:var(--muted)}.search-field input{width:100%;border:0;background:transparent}.quality-list{display:grid;margin-top:10px}.quality-list button{display:grid;grid-template-columns:42px minmax(0,1fr) auto;gap:11px;align-items:center;width:100%;padding:9px;border:0;border-bottom:1px solid var(--border);background:transparent;color:var(--text);text-align:left}.quality-list button:hover{background:rgba(255,255,255,.025)}.quality-list button>span{display:grid;min-width:0}.quality-list strong,.quality-list small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.quality-list small{color:var(--muted);font-size:10px}.user-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.user-card{display:grid;grid-template-columns:46px minmax(0,1fr) auto;gap:10px;align-items:center}.user-avatar{display:grid;grid-row:1/3;place-items:center;width:46px;height:46px;border-radius:50%;background:rgba(229,160,13,.13);color:var(--accent);font-weight:800}.user-card h3,.user-card p{margin:0}.user-card p,.user-card small{color:var(--muted);font-size:10px}.user-card>strong{color:var(--accent)}.user-share{grid-column:2/4;height:5px;overflow:hidden;border-radius:99px;background:rgba(255,255,255,.08)}.user-share i{display:block;height:100%;border-radius:inherit;background:var(--accent)}.user-card>small{grid-column:2/4}@media(max-width:900px){.activity-grid{grid-template-columns:1fr}}@media(max-width:540px){.period-picker{order:3}.live-heading{align-items:flex-start;flex-direction:column}.live-updated{display:none}.quality-list button{grid-template-columns:42px minmax(0,1fr)}.quality-list :deep(.playback-badge){grid-column:2}}
</style>
