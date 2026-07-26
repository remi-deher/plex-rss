<template>
  <section class="panel">
    <div class="panel-head"><div><span class="eyebrow">Engagement</span><h2>Taux de complétion</h2></div><small>règle Tautulli · 85 % ou générique</small></div>
    <div class="completion-list">
      <article v-for="item in items" :key="item.media_type">
        <div class="completion-ring" :style="{'--rate':`${item.completion_rate*3.6}deg`}"><strong>{{ item.completion_rate }}%</strong></div>
        <div><strong>{{ typeLabel(item.media_type) }}</strong><span>{{ item.completed }} sur {{ item.sessions }} terminées</span><small>Progression moyenne : {{ item.average_progress }} %</small></div>
      </article>
      <p v-if="!items.length" class="empty">Durées insuffisantes pour calculer la complétion.</p>
    </div>
  </section>
</template>

<script setup>
defineProps({items:{type:Array,default:()=>[]}});
function typeLabel(value){return {movie:'Films',episode:'Épisodes',track:'Musique'}[value]||'Autres'}
</script>

<style scoped>
.panel-head small{color:var(--muted);font-size:9px}.completion-list{display:grid;gap:12px;margin-top:14px}.completion-list article{display:flex;align-items:center;gap:12px}.completion-ring{display:grid;place-items:center;width:54px;height:54px;border-radius:50%;background:conic-gradient(var(--accent) var(--rate),rgba(255,255,255,.07) 0);position:relative}.completion-ring::after{content:'';position:absolute;inset:6px;border-radius:50%;background:var(--surface)}.completion-ring strong{z-index:1;font-size:10px}.completion-list article>div:last-child{display:grid}.completion-list span,.completion-list small{color:var(--muted);font-size:9px}
</style>
