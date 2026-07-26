<template>
  <section class="panel">
    <div class="panel-head"><div><span class="eyebrow">Capacité</span><h2>Lectures simultanées</h2></div><strong class="peak">{{ peak }} au pic</strong></div>
    <div v-if="daily.length" class="concurrency-chart">
      <div v-for="point in daily" :key="point.date" :title="`${point.date} · ${point.peak} flux`"><b>{{point.peak}}</b><i :style="{height:`${Math.max(4,point.peak/maximum*100)}%`}"></i><span>{{ shortDate(point.date) }}</span></div>
    </div>
    <p v-else class="empty">Aucune simultanéité mesurable.</p>
    <footer v-if="peakAt">Pic observé le {{ formatDate(peakAt) }}</footer>
  </section>
</template>

<script setup>
import { formatDayMonth as shortDate, formatDateTime as formatDate } from '@/utils/format';
import { computed } from 'vue';
const props=defineProps({daily:{type:Array,default:()=>[]},peak:{type:Number,default:0},peakAt:{type:String,default:''}});
const maximum=computed(()=>Math.max(1,...props.daily.map(point=>point.peak||0)));
</script>

<style scoped>
.peak{color:var(--accent);font-size:12px}.concurrency-chart{display:flex;align-items:flex-end;gap:5px;height:180px;margin-top:16px;overflow-x:auto}.concurrency-chart>div{position:relative;display:grid;grid-template-rows:1fr auto;align-items:end;gap:5px;height:100%;min-width:14px;flex:1}.concurrency-chart b{position:absolute;top:-14px;left:50%;color:var(--muted);font-size:8px;transform:translateX(-50%)}.concurrency-chart i{display:block;border-radius:5px 5px 2px 2px;background:linear-gradient(180deg,#60a5fa,#2563eb)}.concurrency-chart span{overflow:hidden;color:var(--muted);font-size:7px;text-align:center}.panel>footer{margin-top:10px;color:var(--muted);font-size:9px}@media(max-width:640px){.concurrency-chart{gap:7px;scroll-snap-type:x proximity}.concurrency-chart>div{flex:0 0 34px;scroll-snap-align:start}.concurrency-chart span,.concurrency-chart b{font-size:10px}}
</style>
