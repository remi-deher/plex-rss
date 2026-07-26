<template>
  <section class="panel live-panel">
    <div class="panel-head">
      <div><span class="eyebrow"><i></i>En direct</span><h2>Lectures Plex</h2></div>
      <RouterLink v-if="showLink" :to="{path:'/activity',query:{view:'live'}}">Voir l’activité</RouterLink>
    </div>
    <div v-if="sessions.length" class="live-list">
      <article v-for="session in sessions" :key="session.session_id" class="live-session" :class="{interactive}" @click="select(session)" @keydown.enter="select(session)" @keydown.space.prevent="select(session)" :tabindex="interactive?0:undefined" :role="interactive?'button':undefined">
        <MediaArtwork :src="session.thumb_url" :alt="displayTitle(session)" :type="session.media_type" size="small"/>
        <div class="live-main">
          <div><strong>{{ displayTitle(session) }}</strong><span>{{ session.user_name }} · {{ session.player || session.platform || 'Plex' }}</span></div>
          <div class="progress-track"><i :style="{width:`${session.progress||0}%`}"></i></div>
          <small>{{ Math.round(session.progress||0) }} % · {{ formatRemaining(session) }}</small>
        </div>
        <div class="live-meta"><span>{{ session.quality || 'Auto' }}</span><PlaybackMethodBadge :method="session.playback_method"/></div>
      </article>
    </div>
    <p v-else class="empty">Aucune lecture en cours.</p>
  </section>
</template>

<script setup>
import MediaArtwork from './MediaArtwork.vue';
import PlaybackMethodBadge from './PlaybackMethodBadge.vue';
const props=defineProps({sessions:{type:Array,default:()=>[]},showLink:{type:Boolean,default:true},interactive:{type:Boolean,default:false}});
const emit=defineEmits(['select']);
function displayTitle(item){return item.grandparent_title?`${item.grandparent_title} · ${item.title}`:item.title}
function select(session){if(props.interactive)emit('select',session)}
function formatRemaining(session){const remaining=Math.max(0,(session.duration_ms||0)-(session.progress_ms||0));if(!remaining)return 'Durée inconnue';const minutes=Math.ceil(remaining/60000);return minutes<60?`${minutes} min restantes`:`${Math.floor(minutes/60)} h ${minutes%60} min restantes`}
</script>

<style scoped>
.live-panel{grid-column:1/-1}.eyebrow{display:flex;align-items:center;gap:6px}.eyebrow i{width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 4px rgba(34,197,94,.12)}.panel-head a{color:var(--accent);font-size:12px}.live-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px;margin-top:12px}.live-session{display:grid;grid-template-columns:42px minmax(0,1fr) auto;gap:10px;align-items:center;padding:9px;border:1px solid var(--border);border-radius:10px;background:var(--surface-2)}.live-session.interactive{cursor:pointer;transition:border-color .15s,transform .15s}.live-session.interactive:hover,.live-session.interactive:focus-visible{border-color:color-mix(in srgb,var(--accent) 45%,var(--border));transform:translateY(-1px);outline:none}.live-main{display:grid;gap:6px;min-width:0}.live-main>div:first-child{display:grid}.live-main strong,.live-main span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.live-main span,.live-main small{color:var(--muted);font-size:10px}.progress-track{height:4px;overflow:hidden;border-radius:99px;background:rgba(255,255,255,.1)}.progress-track i{display:block;height:100%;background:var(--accent)}.live-meta{display:grid;justify-items:end;gap:6px}.live-meta>span{color:var(--muted);font-size:10px}@media(max-width:480px){.live-list{grid-template-columns:1fr}.live-meta>span{display:none}}
</style>
