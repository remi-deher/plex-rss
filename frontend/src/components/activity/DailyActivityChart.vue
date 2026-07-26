<template>
  <section class="panel span-two">
    <div class="panel-head"><div><span class="eyebrow">Tendance</span><h2>Lectures quotidiennes</h2></div></div>
    <div v-if="points.length" class="watch-chart">
      <div v-for="point in points" :key="point.date" class="watch-bar" :title="`${point.date} · ${point.sessions} session(s)`">
        <b>{{point.sessions}}</b><i :style="{height:`${Math.max(3,(point.sessions||0)/maximum*100)}%`}"></i><span>{{ shortDate(point.date) }}</span>
      </div>
    </div>
    <p v-else class="empty">Aucune lecture sur cette période.</p>
  </section>
</template>

<script setup>
import { formatDayMonth as shortDate } from '@/utils/format';
import { computed } from 'vue';
const props=defineProps({points:{type:Array,default:()=>[]}});
const maximum=computed(()=>Math.max(1,...props.points.map(value=>value.sessions||0)));
</script>

<style scoped>
.watch-chart{display:flex;align-items:flex-end;gap:5px;height:240px;padding-top:20px;overflow-x:auto}.watch-bar{position:relative;display:grid;grid-template-rows:1fr auto;align-items:end;gap:6px;min-width:18px;height:100%;flex:1}.watch-bar b{position:absolute;top:-16px;left:50%;color:var(--muted);font-size:8px;font-weight:600;transform:translateX(-50%)}.watch-bar i{display:block;min-height:3px;border-radius:5px 5px 2px 2px;background:linear-gradient(180deg,#fbbf24,var(--accent))}.watch-bar span{font-size:8px;color:var(--muted);transform:rotate(-45deg);white-space:nowrap}@media(max-width:900px){.watch-chart{height:190px}}@media(max-width:640px){.watch-chart{gap:7px;scroll-snap-type:x proximity}.watch-bar{flex:0 0 34px;scroll-snap-align:start}.watch-bar span{font-size:10px;transform:none;text-align:center}.watch-bar b{font-size:10px}}
</style>
