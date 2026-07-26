<template>
  <section class="panel">
    <div class="panel-head"><div><span class="eyebrow">Capacité</span><h2>Lectures simultanées</h2></div><strong class="peak">{{ peak }} au pic</strong></div>
    <div v-if="daily.length" class="concurrency-chart">
      <div v-for="point in daily" :key="point.date" :title="`${point.date} · ${point.peak} flux`"><i :style="{height:`${Math.max(4,point.peak/maximum*100)}%`}"></i><span>{{ shortDate(point.date) }}</span></div>
    </div>
    <p v-else class="empty">Aucune simultanéité mesurable.</p>
    <footer v-if="peakAt">Pic observé le {{ formatDate(peakAt) }}</footer>
  </section>
</template>

<script setup>
import { computed } from 'vue';
const props=defineProps({daily:{type:Array,default:()=>[]},peak:{type:Number,default:0},peakAt:{type:String,default:''}});
const maximum=computed(()=>Math.max(1,...props.daily.map(point=>point.peak||0)));
function shortDate(value){return new Intl.DateTimeFormat('fr-FR',{day:'2-digit',month:'2-digit'}).format(new Date(`${value}T12:00:00`))}
function formatDate(value){return new Intl.DateTimeFormat('fr-FR',{dateStyle:'medium',timeStyle:'short'}).format(new Date(value))}
</script>

<style scoped>
.peak{color:var(--accent);font-size:12px}.concurrency-chart{display:flex;align-items:flex-end;gap:5px;height:180px;margin-top:16px}.concurrency-chart>div{display:grid;grid-template-rows:1fr auto;align-items:end;gap:5px;height:100%;min-width:14px;flex:1}.concurrency-chart i{display:block;border-radius:5px 5px 2px 2px;background:linear-gradient(180deg,#60a5fa,#2563eb)}.concurrency-chart span{overflow:hidden;color:var(--muted);font-size:7px;text-align:center}.panel>footer{margin-top:10px;color:var(--muted);font-size:9px}
</style>
