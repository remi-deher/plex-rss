<template>
  <section class="panel popular-panel">
    <div class="panel-head"><div><span class="eyebrow">Engagement</span><h2>Médias les plus regardés</h2></div></div>
    <div class="popular-list">
      <article v-for="(item,index) in items" :key="`${item.media_type}:${item.title}`">
        <b>{{ index+1 }}</b>
        <MediaArtwork :src="item.thumb_url" :alt="item.title" :type="item.media_type" size="small"/>
        <div><strong>{{ item.title }}</strong><span>{{ item.sessions }} lectures · {{ item.users }} utilisateur{{ item.users>1?'s':'' }}</span></div>
        <em>{{ formatDuration(item.watch_ms) }}<small v-if="item.watch_hours_per_gb!=null">{{ item.watch_hours_per_gb }} h/Go</small></em>
      </article>
      <p v-if="!items.length" class="empty">Aucun média classable.</p>
    </div>
  </section>
</template>

<script setup>
import MediaArtwork from './MediaArtwork.vue';
defineProps({items:{type:Array,default:()=>[]}});
function formatDuration(ms){const hours=(ms||0)/3600000;return hours<1?`${Math.round(hours*60)} min`:`${hours.toLocaleString('fr-FR',{maximumFractionDigits:1})} h`}
</script>

<style scoped>
.popular-list{display:grid;margin-top:10px}.popular-list article{display:grid;grid-template-columns:22px 42px minmax(0,1fr) auto;gap:9px;align-items:center;padding:8px 0;border-bottom:1px solid var(--border)}.popular-list b{color:var(--accent)}.popular-list article>div{display:grid;min-width:0}.popular-list strong,.popular-list span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.popular-list span,.popular-list small{color:var(--muted);font-size:9px}.popular-list em{display:grid;justify-items:end;font-size:11px;font-style:normal}@media(max-width:480px){.popular-list article{grid-template-columns:20px 42px minmax(0,1fr)}.popular-list em{grid-column:3;justify-items:start}}
</style>
