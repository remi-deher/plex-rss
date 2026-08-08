<template>
  <section class="panel breakdown-panel" :class="`tone-${tone}`">
    <div class="panel-head">
      <div><span v-if="eyebrow" class="eyebrow">{{eyebrow}}</span><h2>{{title}}</h2></div>
      <div class="chart-actions">
        <button type="button" :class="{active:mode==='chart'}" aria-label="Afficher le graphique" @click="mode='chart'"><ChartNoAxesColumnIncreasing/></button>
        <button type="button" :class="{active:mode==='table'}" aria-label="Afficher le tableau" @click="mode='table'"><TableProperties/></button>
        <slot name="action"/>
      </div>
    </div>
    <div v-if="mode==='chart'" class="breakdown-list">
      <button v-for="item in normalized" :key="item.label" type="button" class="breakdown-row" :disabled="item.grouped||!interactive" @click="select(item)">
        <header><span :title="item.label">{{item.label}}</span><strong>{{formatValue(item.value)}}<small v-if="item.suffix">{{item.suffix}}</small></strong></header>
        <div class="bar-track"><i :style="{width:`${item.width}%`}"></i></div>
        <small v-if="item.detail">{{item.detail}}</small>
      </button>
      <p v-if="!normalized.length" class="empty">{{emptyText}}</p>
    </div>
    <div v-else class="breakdown-table" role="table" :aria-label="title">
      <div role="row" class="table-head"><span role="columnheader">Catégorie</span><span role="columnheader">Valeur</span><span role="columnheader">Part</span></div>
      <button v-for="item in normalized" :key="item.label" type="button" role="row" :disabled="item.grouped||!interactive" @click="select(item)">
        <span role="cell">{{item.label}}</span><strong role="cell">{{formatValue(item.value)}}{{item.suffix||''}}</strong><span role="cell">{{formatValue(item.percent)}} %</span>
      </button>
    </div>
    <button v-if="hasHidden" type="button" class="show-all" @click="expanded=!expanded">{{expanded?'Réduire':`Afficher les ${items.length} catégories`}}</button>
  </section>
</template>
<script setup>
import { formatNumber as formatValue } from '@/utils/format';
import { ChartNoAxesColumnIncreasing,TableProperties } from '@lucide/vue';
import { computed,onBeforeUnmount,onMounted,ref } from 'vue';
const props=defineProps({title:{type:String,required:true},eyebrow:{type:String,default:''},items:{type:Array,default:()=>[]},emptyText:{type:String,default:'Aucune donnée.'},tone:{type:String,default:'accent'},interactive:{type:Boolean,default:false}});
const emit=defineEmits(['select']),mode=ref('chart'),expanded=ref(false),viewport=ref(typeof window==='undefined'?1200:window.innerWidth);
const limit=computed(()=>viewport.value<=640?5:viewport.value<=1024?7:10),hasHidden=computed(()=>props.items.length>limit.value);
const visible=computed(()=>{if(expanded.value||!hasHidden.value)return props.items;const n=Math.max(1,limit.value-1),head=props.items.slice(0,n),tail=props.items.slice(n);return[...head,{label:'Autres',value:tail.reduce((s,x)=>s+Number(x.value||0),0),detail:`${tail.length} catégories regroupées`,grouped:true}]});
const total=computed(()=>props.items.reduce((s,x)=>s+Number(x.value||0),0)||1),maximum=computed(()=>Math.max(1,...visible.value.map(x=>Number(x.value||0))));
const normalized=computed(()=>visible.value.map(x=>({...x,percent:Number(x.value||0)/total.value*100,width:Math.max(x.value?4:0,Number(x.value||0)/maximum.value*100)})));
function select(x){if(props.interactive&&!x.grouped)emit('select',x.rawValue??x.label)}function resize(){viewport.value=window.innerWidth}
onMounted(()=>window.addEventListener('resize',resize,{passive:true}));onBeforeUnmount(()=>window.removeEventListener('resize',resize));
</script>
<style scoped>
.breakdown-panel{--chart-color:var(--accent);--chart-end:#fbbf24}.tone-blue{--chart-color:#38bdf8;--chart-end:#2563eb}.tone-green{--chart-color:#4ade80;--chart-end:#16a34a}.tone-red{--chart-color:#fb7185;--chart-end:#dc2626}.tone-purple{--chart-color:#c084fc;--chart-end:#7c3aed}.chart-actions{display:flex;align-items:center;gap: var(--space-1)}.chart-actions>button{display:grid;place-items:center;width:34px;height:34px;padding:0;border:1px solid transparent;border-radius:var(--radius-sm);background:transparent;color:var(--muted)}.chart-actions>button.active{border-color:var(--border);background:var(--surface-2);color:var(--chart-color)}.chart-actions svg{width:15px}.breakdown-list{display:grid;gap: var(--space-3);margin-top:14px}.breakdown-row{display:grid;gap: var(--space-1);width:100%;padding:3px 0;border:0;background:transparent;color:inherit;text-align:left}.breakdown-row:not(:disabled){cursor:pointer}.breakdown-row:not(:disabled):hover header span{color:var(--chart-color)}.breakdown-row:disabled{opacity:1}.breakdown-list header{display:flex;justify-content:space-between;gap: var(--space-3);font-size:var(--fs-sm)}.breakdown-list header span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.breakdown-list header strong{color:var(--chart-color);font-size:var(--fs-sm);font-variant-numeric:tabular-nums}.breakdown-list header small{margin-left:2px;color:var(--muted);font-size:var(--fs-xs)}.bar-track{height:10px;overflow:hidden;border-radius:var(--radius-pill);background:rgba(255,255,255,.08)}.breakdown-list i{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--chart-color),var(--chart-end))}.breakdown-row>small{color:var(--muted);font-size:var(--fs-xs)}.breakdown-table{display:grid;margin-top:12px}.breakdown-table>div,.breakdown-table>button{display:grid;grid-template-columns:minmax(0,1fr) 80px 65px;gap: var(--space-3);align-items:center;min-height:40px;padding:6px;border:0;border-bottom:1px solid var(--border);background:transparent;color:var(--text);font-size:var(--fs-xs);text-align:left}.breakdown-table>button:not(:disabled):hover{background:var(--surface-2)}.breakdown-table strong,.breakdown-table span:last-child{text-align:right;font-variant-numeric:tabular-nums}.table-head{color:var(--muted)!important;font-size:var(--fs-xs)!important;text-transform:uppercase}.show-all{margin-top:10px;padding:6px 0;border:0;background:transparent;color:var(--chart-color);font-size:var(--fs-xs)}@media(max-width:640px){.breakdown-list{gap: var(--space-3)}.bar-track{height:12px}.breakdown-list header,.breakdown-list header strong{font-size:var(--fs-sm)}.chart-actions>button{width:44px;height:44px}}
</style>
