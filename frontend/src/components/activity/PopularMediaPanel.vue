<template>
  <section class="panel popular-panel">
    <div class="panel-head"><div><span class="eyebrow">{{ eyebrow }}</span><h2>{{ title }}</h2></div></div>
    <div class="popular-list">
      <article v-for="(item,index) in items" :key="`${item.media_type}:${item.title}`">
        <b>{{ index+1 }}</b>
        <MediaArtwork :src="item.thumb_url" :alt="item.title" :type="item.media_type" size="small"/>
        <div><strong>{{ item.title }}</strong><span>{{ item.sessions }} lectures · {{ item.users }} utilisateur{{ item.users>1?'s':'' }}</span><small>{{ item.completed }} terminée{{ item.completed>1?'s':'' }} · {{ item.completion_rate }} %</small></div>
        <em>{{ formatDuration(item.watch_ms) }}<small v-if="item.rewatches">{{ item.rewatches }} revisionnage{{ item.rewatches>1?'s':'' }}</small><small v-else-if="item.watch_hours_per_gb!=null">{{ item.watch_hours_per_gb }} h/Go</small></em>
      </article>
      <p v-if="!items.length" class="empty">Aucun média classable.</p>
    </div>
  </section>
</template>

<script setup>
import { formatDurationHours as formatDuration } from '@/utils/format';
import MediaArtwork from './MediaArtwork.vue';
defineProps({
  items:{type:Array,default:()=>[]},
  title:{type:String,default:'Médias les plus regardés'},
  eyebrow:{type:String,default:'Consommation'},
});
</script>

<style scoped>
.popular-list{display:grid;margin-top:10px}.popular-list article{display:grid;grid-template-columns:22px 42px minmax(0,1fr) auto;gap: var(--space-2);align-items:center;padding:8px 0;border-bottom:1px solid var(--border)}.popular-list b{color:var(--text)}.popular-list article>div{display:grid;min-width:0}.popular-list strong,.popular-list span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.popular-list span,.popular-list small{color:var(--muted);font-size:var(--fs-xs)}.popular-list em{display:grid;justify-items:end;font-size:var(--fs-xs);font-style:normal}@media(max-width:480px){.popular-list article{grid-template-columns:20px 42px minmax(0,1fr)}.popular-list em{grid-column:3;justify-items:start}}
</style>
