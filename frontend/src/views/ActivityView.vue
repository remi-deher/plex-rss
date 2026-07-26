<template>
  <div class="page activity-page">
    <PageHeader title="Activité Plex" description="Lectures en direct, historique et tendances de consommation.">
      <div class="period-picker"><button v-for="value in [7,30,90,365]" :key="value" :class="{active:days===value}" @click="days=value;load()">{{ value }} j</button></div>
      <button class="secondary" :disabled="loading" @click="refresh"><RefreshCw :class="{spin:loading}"/>Actualiser</button>
    </PageHeader>
    <UiFeedback v-if="error" type="error" :message="error" retry @retry="load"/>
    <LiveSessionsPanel :sessions="data.active"/>

    <div class="metric-grid activity-metrics">
      <article class="metric-card"><PlayCircle/><div><span>Sessions</span><strong>{{ summary.sessions||0 }}</strong><small>sur {{ days }} jours</small></div></article>
      <article class="metric-card"><Clock3/><div><span>Temps regardé</span><strong>{{ formatDuration(summary.watch_ms) }}</strong><small>durée cumulée</small></div></article>
      <article class="metric-card"><Users/><div><span>Utilisateurs</span><strong>{{ summary.users||0 }}</strong><small>comptes actifs</small></div></article>
      <article class="metric-card"><Cpu/><div><span>Transcodage</span><strong>{{ summary.transcode_rate||0 }} %</strong><small>{{ summary.transcodes||0 }} sessions</small></div></article>
    </div>

    <div class="activity-grid">
      <section class="panel span-two">
        <div class="panel-head"><div><span class="eyebrow">Tendance</span><h2>Lectures quotidiennes</h2></div></div>
        <div class="watch-chart">
          <div v-for="point in chart" :key="point.date" class="watch-bar" :title="`${point.date} · ${point.sessions} session(s)`">
            <i :style="{height:`${Math.max(3,point.sessions/chartMax*100)}%`}"></i><span>{{ shortDate(point.date) }}</span>
          </div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><div><span class="eyebrow">Audience</span><h2>Utilisateurs actifs</h2></div></div>
        <div class="ranking"><div v-for="(user,index) in data.users" :key="user.name"><b>{{ index+1 }}</b><span><strong>{{ user.name }}</strong><small>{{ user.sessions }} sessions</small></span><em>{{ formatDuration(user.watch_ms) }}</em></div><p v-if="!data.users.length" class="empty">Pas encore de données.</p></div>
      </section>
    </div>

    <section class="panel">
      <div class="panel-head"><div><span class="eyebrow">Historique</span><h2>Dernières lectures</h2></div></div>
      <div class="history-table">
        <article v-for="item in data.history" :key="`${item.source}:${item.session_id}`">
          <div><strong>{{ displayTitle(item) }}</strong><span>{{ item.user_name }} · {{ item.player||item.platform||'Plex' }}</span></div>
          <span class="history-method" :class="item.playback_method">{{ methodLabel(item.playback_method) }}</span>
          <span>{{ formatDuration(item.watched_ms) }}</span><time>{{ formatDate(item.started_at) }}</time>
        </article>
        <p v-if="!data.history.length" class="empty">L’historique se remplira dès les prochaines lectures ou après un import Tautulli.</p>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed,onMounted,ref } from 'vue';
import { Clock3,Cpu,PlayCircle,RefreshCw,Users } from '@lucide/vue';
import { api } from '@/api';
import { useRealtime } from '@/events';
import LiveSessionsPanel from '@/components/activity/LiveSessionsPanel.vue';
const days=ref(30),loading=ref(false),error=ref(''),data=ref({active:[],history:[],daily:[],users:[],summary:{}});
const summary=computed(()=>data.value.summary||{});
const chart=computed(()=>data.value.daily||[]);
const chartMax=computed(()=>Math.max(1,...chart.value.map(v=>v.sessions||0)));
async function load(){loading.value=true;error.value='';try{data.value=await api(`/api/playback?days=${days.value}`)}catch(e){error.value=e.message}finally{loading.value=false}}
async function refresh(){loading.value=true;try{data.value=await api('/api/playback/refresh',{method:'POST'})}catch(e){error.value=e.message}finally{loading.value=false}}
function formatDuration(ms){const minutes=Math.round((ms||0)/60000);if(minutes<60)return `${minutes} min`;const hours=Math.floor(minutes/60),rest=minutes%60;return `${hours} h${rest?` ${rest} min`:''}`}
function formatDate(value){return value?new Intl.DateTimeFormat('fr-FR',{dateStyle:'short',timeStyle:'short'}).format(new Date(value)):'-'}
function shortDate(value){return value?new Intl.DateTimeFormat('fr-FR',{day:'2-digit',month:'2-digit'}).format(new Date(`${value}T12:00:00`)):''}
function displayTitle(item){return item.grandparent_title?`${item.grandparent_title} · ${item.title}`:item.title}
function methodLabel(value){return {transcode:'Transcodage',direct_stream:'Direct Stream',direct_play:'Lecture directe'}[value]||'Lecture'}
useRealtime(['activity.updated'],load);onMounted(load);
</script>

<style scoped>
.period-picker{display:flex;padding:2px;border:1px solid var(--border);border-radius:99px}.period-picker button{border:0;border-radius:99px;background:transparent;color:var(--muted);padding:6px 9px}.period-picker button.active{background:var(--accent);color:#111}.activity-metrics{margin:16px 0}.activity-grid{display:grid;grid-template-columns:2fr 1fr;gap:14px;margin-bottom:14px}.watch-chart{display:flex;align-items:flex-end;gap:5px;height:240px;padding-top:20px;overflow-x:auto}.watch-bar{display:grid;grid-template-rows:1fr auto;align-items:end;gap:6px;min-width:18px;height:100%;flex:1}.watch-bar i{display:block;min-height:3px;border-radius:5px 5px 2px 2px;background:linear-gradient(180deg,#fbbf24,var(--accent))}.watch-bar span{font-size:8px;color:var(--muted);transform:rotate(-45deg);white-space:nowrap}.ranking{display:grid;margin-top:12px}.ranking>div{display:grid;grid-template-columns:24px 1fr auto;gap:8px;align-items:center;padding:9px 0;border-bottom:1px solid var(--border)}.ranking b{color:var(--accent)}.ranking span{display:grid}.ranking small,.ranking em{font-size:10px;color:var(--muted);font-style:normal}.history-table{display:grid;margin-top:10px}.history-table article{display:grid;grid-template-columns:minmax(220px,1fr) 110px 80px 150px;gap:12px;align-items:center;padding:10px;border-bottom:1px solid var(--border)}.history-table article>div{display:grid;min-width:0}.history-table article>div strong,.history-table article>div span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.history-table article>div span,.history-table time{color:var(--muted);font-size:10px}.history-method{font-size:10px;color:#4ade80}.history-method.transcode{color:#fb923c}@media(max-width:900px){.activity-grid{grid-template-columns:1fr}.history-table article{grid-template-columns:1fr auto}.history-table article>span:last-of-type,.history-table time{font-size:10px}.watch-chart{height:190px}}@media(max-width:540px){.history-table article{grid-template-columns:1fr auto}.history-method{grid-column:2;grid-row:1}.history-table article>span:last-of-type,.history-table time{grid-row:2}.period-picker{order:3}}
</style>
