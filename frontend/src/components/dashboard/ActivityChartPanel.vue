<template>
  <section class="panel span-two">
    <div class="panel-head">
      <div><span class="eyebrow">Tendance</span><h2>Activité sur {{ period }} jours</h2></div>
      <div class="activity-head-actions">
        <div class="activity-period"><button v-for="days in [7,30]" :key="days" :class="{active:period===days}" @click="period=days">{{ days }} j</button></div>
        <span class="activity-trend" :class="trend.direction">{{ trend.label }}</span>
      </div>
    </div>
    <div class="activity-series" aria-label="Type d'activite">
      <button v-for="option in seriesOptions" :key="option.key" :class="[option.key,{active:activeSeries===option.key}]" :aria-pressed="activeSeries===option.key" @click="activeSeries=option.key"><i></i>{{ option.label }}</button>
    </div>
    <div class="activity-summary">
      <div><span>Total</span><strong>{{ total }}</strong><small>{{ activeOption.unit }}</small></div>
      <div><span>Moyenne</span><strong>{{ average }}</strong><small>par jour</small></div>
      <div><span>Pic</span><strong>{{ peak.value }}</strong><small>{{ peak.label }}</small></div>
    </div>
    <div class="activity-chart">
      <div class="y-axis">
        <span>{{ max }}</span>
        <span>{{ Math.round(max / 2) }}</span>
        <span>0</span>
      </div>
      <div class="chart-area">
        <div
          v-for="(value, index) in values"
          :key="index"
          class="bar-wrapper"
        >
          <div class="bar-value-top" v-if="value > 0 && (value / max) < 0.15">{{ value }}</div>
          <div
            class="bar"
            :class="activeSeries"
            :style="{ height: `${Math.max(2, value / max * 100)}%` }"
            :title="`${labels[index]} : ${value}`"
            role="img"
            :aria-label="`${formatLongDate(labels[index])} : ${value} ${activeOption.unit}`"
          >
            <span class="bar-value" v-if="value > 0 && (value / max) >= 0.15">{{ value }}</span>
          </div>
          <div class="x-label" v-if="index % 4 === 0 || index === values.length - 1">
            {{ formatChartDate(labels[index]) }}
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { formatLongDay as formatLongDate, formatNumber } from '@/utils/format';
import { computed,ref } from 'vue';

const props = defineProps({ timeline: { type: Object, default: () => ({ labels: [], values: [] }) } });
const activeSeries=ref('requests');
const period=ref(30);
const seriesOptions=[{key:'requests',label:'Demandes',unit:'demandes'},{key:'availability',label:'Disponibilites',unit:'medias disponibles'},{key:'notifications',label:'Notifications',unit:'envois reussis'}];
const activeOption=computed(()=>seriesOptions.find(item=>item.key===activeSeries.value)||seriesOptions[0]);
const allValues=computed(()=>props.timeline.series?.[activeSeries.value]||(activeSeries.value==='requests'?props.timeline.values:[])||[]);
const values=computed(()=>allValues.value.slice(-period.value));
const labels=computed(()=>(props.timeline.labels||[]).slice(-period.value));

const total = computed(() => values.value.reduce((a, b) => a + b, 0));
const max = computed(() => Math.max(1, ...values.value));
const average = computed(() => formatNumber((total.value || 0) / Math.max(1, values.value.length)));
const peak = computed(() => {
  const points=values.value,periodLabels=labels.value;
  const value=Math.max(0,...points),index=points.indexOf(value);
  return {value,label:index<0?'Aucune activite':formatLongDate(periodLabels[index],{day:'numeric',month:'short'})};
});
const trend = computed(() => {
  const points=values.value,recent=points.slice(-7).reduce((a,b)=>a+b,0),previous=points.slice(-14,-7).reduce((a,b)=>a+b,0);
  if(!recent&&!previous)return {direction:'stable',label:'Aucune activite recente'};
  if(!previous)return {direction:'up',label:`+${recent} sur 7 jours`};
  const change=Math.round((recent-previous)/previous*100);
  if(Math.abs(change)<5)return {direction:'stable',label:'Stable sur 7 jours'};
  return {direction:change>0?'up':'down',label:`${change>0?'+':''}${change}% sur 7 jours`};
});

function formatChartDate(v) {
  if (!v) return '';
  const d = new Date(v);
  return `${d.getDate().toString().padStart(2, '0')}/${(d.getMonth() + 1).toString().padStart(2, '0')}`;
}

</script>

<style scoped>
.activity-head-actions{display:flex!important;grid-auto-flow:column;align-items:center;gap:var(--space-2)!important}.activity-period{display:flex;border:1px solid var(--border);border-radius:var(--radius-pill);padding:2px}.activity-period button{border:0;background:transparent;color:var(--muted);padding:4px 8px;border-radius:var(--radius-pill);font-size:var(--fs-xs)}.activity-period button.active{background:var(--accent);color:#111}
.panel-head>div{display:grid;gap: var(--space-1);min-width:0}.eyebrow{font-size:var(--fs-xs)}.activity-trend{padding:6px 9px;border-radius:var(--radius-pill);border:1px solid var(--border);font-size:var(--fs-xs);font-weight:700}.activity-trend.up{color:var(--success);background:rgba(34,197,94,.08);border-color:rgba(34,197,94,.22)}.activity-trend.down{color:var(--danger);background:rgba(239,68,68,.08);border-color:rgba(239,68,68,.22)}.activity-series{display:flex;max-width:100%;gap: var(--space-2);margin-top:12px;overflow-x:auto}.activity-series button{display:flex;align-items:center;gap: var(--space-2);padding:7px 10px;border:1px solid var(--border);border-radius:var(--radius-pill);background:transparent;color:var(--muted);white-space:nowrap}.activity-series button.active{background:var(--surface-2);color:var(--text);border-color:var(--muted)}.activity-series i{width:7px;height:7px;border-radius:50%;background:var(--accent)}.activity-series .availability i{background:var(--success)}.activity-series .notifications i{background:#8b5cf6}.activity-chart .bar.availability{background:var(--success)}.activity-chart .bar.notifications{background:#8b5cf6}.activity-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap: var(--space-2);margin-top:14px}.activity-summary>div{display:grid;grid-template-columns:auto 1fr;align-items:baseline;min-width:0;gap:var(--space-1) var(--space-2);padding:10px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--surface-2)}.activity-summary span{grid-column:1/-1;font-size:var(--fs-xs);}.activity-summary strong{font-size:var(--fs-xl);color:var(--text)}.activity-summary small{font-size:var(--fs-xs)}@media(max-width:520px){.panel-head{align-items:flex-start;gap: var(--space-3)}.activity-trend{flex:none}.activity-summary{grid-template-columns:1fr}.activity-summary>div{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;padding:9px 11px}.activity-summary span{grid-column:1}.activity-summary strong{grid-column:2;grid-row:1;font-size:var(--fs-lg)}.activity-summary small{grid-column:1/-1}.activity-chart{height:190px;gap: var(--space-2)}.activity-chart .y-axis{min-width:24px;padding-right:5px}.activity-chart .chart-area{gap: var(--space-1)}}
@media(max-width:520px){.activity-head-actions{align-items:flex-end!important;flex-direction:column}.activity-trend{font-size:var(--fs-xs)}}
</style>
