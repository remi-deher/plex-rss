<template>
  <section class="panel breakdown-panel">
    <div class="panel-head"><div><span v-if="eyebrow" class="eyebrow">{{ eyebrow }}</span><h2>{{ title }}</h2></div><slot name="action"/></div>
    <div class="breakdown-list">
      <div v-for="item in normalized" :key="item.label">
        <header><span>{{ item.label }}</span><strong>{{ formatValue(item.value) }}<small v-if="item.suffix">{{ item.suffix }}</small></strong></header>
        <div><i :style="{width:`${item.width}%`}"></i></div>
        <small v-if="item.detail">{{ item.detail }}</small>
      </div>
      <p v-if="!normalized.length" class="empty">{{ emptyText }}</p>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue';
const props=defineProps({
  title:{type:String,required:true},
  eyebrow:{type:String,default:''},
  items:{type:Array,default:()=>[]},
  emptyText:{type:String,default:'Aucune donnée sur cette période.'},
});
const maximum=computed(()=>Math.max(1,...props.items.map(item=>Number(item.value||0))));
const normalized=computed(()=>props.items.map(item=>({...item,width:Math.max(item.value?3:0,Number(item.value||0)/maximum.value*100)})));
function formatValue(value){return Number(value||0).toLocaleString('fr-FR',{maximumFractionDigits:1})}
</script>

<style scoped>
.breakdown-list{display:grid;gap:13px;margin-top:14px}.breakdown-list>div{display:grid;gap:5px}.breakdown-list header{display:flex;justify-content:space-between;gap:10px;font-size:11px}.breakdown-list header span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.breakdown-list header strong{color:var(--accent);font-size:11px}.breakdown-list header small{margin-left:2px;color:var(--muted);font-size:8px}.breakdown-list>div>div{height:6px;overflow:hidden;border-radius:99px;background:rgba(255,255,255,.07)}.breakdown-list i{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--accent),#fbbf24)}.breakdown-list>div>small{color:var(--muted);font-size:9px}
</style>
