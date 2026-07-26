<template>
  <section class="panel live-panel">
    <div class="panel-head">
      <div><span class="eyebrow"><i></i>En direct</span><h2>Lectures Plex</h2></div>
      <RouterLink to="/activity">Voir l’activité</RouterLink>
    </div>
    <div v-if="sessions.length" class="live-list">
      <article v-for="session in sessions" :key="session.session_id" class="live-session">
        <div class="live-poster"><img v-if="session.thumb_url" :src="session.thumb_url" alt=""><Play v-else/></div>
        <div class="live-main">
          <div><strong>{{ displayTitle(session) }}</strong><span>{{ session.user_name }} · {{ session.player || session.platform || 'Plex' }}</span></div>
          <div class="progress-track"><i :style="{width:`${session.progress||0}%`}"></i></div>
          <small>{{ Math.round(session.progress||0) }} % · {{ methodLabel(session.playback_method) }}</small>
        </div>
        <span class="method" :class="session.playback_method">{{ session.quality || 'Auto' }}</span>
      </article>
    </div>
    <p v-else class="empty">Aucune lecture en cours.</p>
  </section>
</template>

<script setup>
import { Play } from '@lucide/vue';
defineProps({sessions:{type:Array,default:()=>[]}});
function displayTitle(item){return item.grandparent_title?`${item.grandparent_title} · ${item.title}`:item.title}
function methodLabel(value){return {transcode:'Transcodage',direct_stream:'Direct Stream',direct_play:'Lecture directe'}[value]||'Lecture'}
</script>

<style scoped>
.live-panel{grid-column:1/-1}.eyebrow{display:flex;align-items:center;gap:6px}.eyebrow i{width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 4px rgba(34,197,94,.12)}.panel-head a{color:var(--accent);font-size:12px}.live-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px;margin-top:12px}.live-session{display:grid;grid-template-columns:45px minmax(0,1fr) auto;gap:10px;align-items:center;padding:9px;border:1px solid var(--border);border-radius:10px;background:var(--surface-2)}.live-poster{display:grid;place-items:center;width:45px;height:58px;overflow:hidden;border-radius:6px;background:#171717}.live-poster img{width:100%;height:100%;object-fit:cover}.live-poster svg{width:18px}.live-main{display:grid;gap:6px;min-width:0}.live-main>div:first-child{display:grid}.live-main strong,.live-main span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.live-main span,.live-main small{color:var(--muted);font-size:10px}.progress-track{height:4px;overflow:hidden;border-radius:99px;background:rgba(255,255,255,.1)}.progress-track i{display:block;height:100%;background:var(--accent)}.method{padding:4px 6px;border-radius:999px;background:rgba(34,197,94,.1);color:#4ade80;font-size:9px}.method.transcode{background:rgba(249,115,22,.12);color:#fb923c}
</style>
