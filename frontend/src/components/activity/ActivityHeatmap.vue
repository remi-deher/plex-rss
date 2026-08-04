<template>
  <section class="panel heatmap-panel">
    <div class="panel-head"><div><span class="eyebrow">Habitudes</span><h2>Heures les plus actives</h2></div><strong>{{ peakLabel }}</strong></div>
    <div class="heatmap-scroll">
      <div class="heatmap-grid">
        <span></span><small v-for="hour in hours" :key="hour">{{ hour }}</small>
        <template v-for="(day,dayIndex) in days" :key="day">
          <strong>{{ day }}</strong>
          <i v-for="hour in hours" :key="`${day}-${hour}`" :style="{opacity:opacity(dayIndex,hour)}" :title="tooltip(dayIndex,hour)"></i>
        </template>
      </div>
    </div>
    <div class="heatmap-mobile">
      <article v-for="slot in topSlots" :key="`${slot.weekday}:${slot.hour}`">
        <strong>{{days[slot.weekday]}} · {{String(slot.hour).padStart(2,'0')}} h</strong><span>{{slot.sessions}} lecture(s)</span>
        <i :style="{width:`${slot.sessions/maximum*100}%`}"></i>
      </article>
    </div>
    <footer><span>Moins</span><i v-for="value in [.12,.3,.5,.72,1]" :key="value" :style="{opacity:value}"></i><span>Plus</span></footer>
  </section>
</template>

<script setup>
import { computed } from 'vue';
const props=defineProps({points:{type:Array,default:()=>[]}});
const days=['Lun','Mar','Mer','Jeu','Ven','Sam','Dim'];
const hours=Array.from({length:24},(_,index)=>index);
const lookup=computed(()=>new Map(props.points.map(point=>[`${point.weekday}:${point.hour}`,point])));
const maximum=computed(()=>Math.max(1,...props.points.map(point=>point.sessions||0)));
const peak=computed(()=>props.points.reduce((best,point)=>(point.sessions||0)>(best.sessions||0)?point:best,{}));
const peakLabel=computed(()=>peak.value.sessions?`${days[peak.value.weekday]} · ${String(peak.value.hour).padStart(2,'0')} h`:'—');
const topSlots=computed(()=>[...props.points].filter(p=>p.sessions).sort((a,b)=>b.sessions-a.sessions).slice(0,5));
function point(day,hour){return lookup.value.get(`${day}:${hour}`)||{sessions:0}}
function opacity(day,hour){const value=point(day,hour).sessions||0;return value?Math.max(.14,value/maximum.value):.045}
function tooltip(day,hour){const value=point(day,hour);return `${days[day]} ${String(hour).padStart(2,'0')} h · ${value.sessions||0} lecture(s)`}
</script>

<style scoped>
.panel-head>strong{color:var(--text);font-size:var(--fs-xs)}.heatmap-scroll{margin-top:14px;overflow-x:auto}.heatmap-grid{display:grid;grid-template-columns:38px repeat(24,minmax(22px,1fr));gap: var(--space-1);min-width:760px}.heatmap-grid small{color:var(--muted);font-size:var(--fs-xs);text-align:center}.heatmap-grid>strong{align-self:center;color:var(--muted);font-size:var(--fs-xs)}.heatmap-grid i{aspect-ratio:1;border-radius:var(--radius-xs);background:var(--accent)}.heatmap-mobile{display:none}.heatmap-panel footer{display:flex;align-items:center;justify-content:flex-end;gap: var(--space-1);margin-top:9px;color:var(--muted);font-size:var(--fs-xs)}.heatmap-panel footer i{width:10px;height:10px;border-radius:var(--radius-xs);background:var(--accent)}@media(max-width:640px){.heatmap-scroll,.heatmap-panel footer{display:none}.heatmap-mobile{display:grid;gap: var(--space-3);margin-top:14px}.heatmap-mobile article{display:grid;grid-template-columns:1fr auto;gap: var(--space-1)}.heatmap-mobile strong,.heatmap-mobile span{font-size:var(--fs-sm)}.heatmap-mobile span{color:var(--muted);font-variant-numeric:tabular-nums}.heatmap-mobile i{grid-column:1/-1;height:12px;border-radius:var(--radius-pill);background:linear-gradient(90deg,var(--accent),#fbbf24)}}
</style>
