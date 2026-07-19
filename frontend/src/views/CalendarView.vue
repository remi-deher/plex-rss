<template>
  <div class="page calendar-page">
    <PageHeader title="Calendrier" :description="`Sorties de ${periodLabel}`">
      <div class="calendar-navigation">
        <button class="icon-button" title="Mois precedent" @click="move(-1)"><ChevronLeft/></button>
        <button class="secondary" @click="today">Aujourd'hui</button>
        <button class="icon-button" title="Mois suivant" @click="move(1)"><ChevronRight/></button>
        <button class="icon-button" :disabled="loading" title="Actualiser" @click="load"><RefreshCw :class="{spin:loading}"/></button>
      </div>
    </PageHeader>

    <div class="calendar-command-bar">
      <div class="segmented calendar-view-switch" aria-label="Mode d'affichage">
        <button :class="{active:view==='agenda'}" @click="view='agenda'"><List/>Agenda</button>
        <button :class="{active:view==='month'}" @click="view='month'"><CalendarDays/>Mois</button>
      </div>
      <FilterBar :active-count="activeFilterCount" :result-count="filtered.length" @reset="resetFilters">
        <template #primary><input v-model="search" class="search" type="search" placeholder="Filtrer les titres" aria-label="Filtrer le calendrier"></template>
        <template #filters><select v-model="type"><option value="">Films et series</option><option value="movie">Films</option><option value="episode">Series</option></select><label class="check"><input v-model="tracked" type="checkbox" @change="load"> Suivis uniquement</label></template>
      </FilterBar>
    </div>

    <div class="calendar-legend" aria-label="Legende"><span><i class="available"></i>Disponible</span><span><i class="tracked"></i>Suivi</span><span><i></i>Catalogue</span></div>
    <UiFeedback v-if="error" type="error" title="Calendrier indisponible" :message="error" retry @retry="load" />

    <div v-if="view==='month'" class="month-calendar-shell" tabindex="0" aria-label="Calendrier mensuel, défilement horizontal disponible">
      <div class="month-calendar">
        <div v-for="label in weekLabels" :key="label" class="month-weekday">{{ label }}</div>
        <div v-for="cell in monthCells" :key="cell.key" class="month-cell" :class="{outside:!cell.current,today:cell.date===todayStr}">
          <header><span>{{ cell.day }}</span><small v-if="cell.date===todayStr">Aujourd'hui</small></header>
          <button v-for="event in cell.events.slice(0,3)" :key="eventKey(event)" class="month-event" :class="eventState(event)" :title="`${event.title} — ${event.subtitle}`" @click="openDetail(event)"><span v-if="formatTime(event.date)">{{ formatTime(event.date) }}</span><strong>{{ event.title }}</strong></button>
          <button v-if="cell.events.length>3" class="month-more" @click="showDay(cell.date)">+ {{ cell.events.length-3 }} autre{{ cell.events.length>4?'s':'' }}</button>
        </div>
      </div>
    </div>

    <div v-else class="calendar-agenda">
      <section v-for="group in grouped" :key="group.date" :id="'date-' + group.date" class="calendar-day" :class="{today:group.date===todayStr}">
        <h2>{{ longDate(group.date) }}<span v-if="group.date===todayStr" class="today-badge">Aujourd'hui</span></h2>
        <div class="calendar-events"><article v-for="event in group.events" :key="eventKey(event)" class="calendar-event" :class="{interactive:event.library_item_id||event.request_id}" @click="openDetail(event)"><img v-if="event.poster_url" :src="event.poster_url" alt="" loading="lazy" decoding="async"><div><strong>{{ event.title }}</strong><span><span v-if="formatTime(event.date)" class="time-text">{{ formatTime(event.date) }} · </span>{{ event.subtitle }} · {{ event.instance }}</span></div><span class="badge" :class="eventState(event)">{{ eventLabel(event) }}</span></article></div>
      </section>
    </div>
    <p v-if="!loading&&!filtered.length" class="empty">Aucune sortie sur cette periode.</p>
  </div>
</template>

<script setup>
import { computed,nextTick,onMounted,ref,watch } from 'vue';
import { CalendarDays,ChevronLeft,ChevronRight,List,RefreshCw } from '@lucide/vue';
import { api } from '@/api';
import { useRouter } from 'vue-router';
import { mediaDetailPath } from '@/mediaUrl';
const router=useRouter();
const events=ref([]),search=ref(''),type=ref(''),tracked=ref(false),loading=ref(false),error=ref(''),cursor=ref(new Date());
const view=ref(localStorage.getItem('calendar.view')||(window.matchMedia('(max-width:640px)').matches?'agenda':'month'));
const todayStr=localIso(new Date()),weekLabels=['Lun','Mar','Mer','Jeu','Ven','Sam','Dim'];
const bounds=computed(()=>{const y=cursor.value.getFullYear(),m=cursor.value.getMonth();return {start:new Date(y,m,1),end:new Date(y,m+1,1)}});
const periodLabel=computed(()=>new Intl.DateTimeFormat('fr-FR',{month:'long',year:'numeric'}).format(cursor.value));
const filtered=computed(()=>events.value.filter(e=>(!search.value||e.title.toLowerCase().includes(search.value.toLowerCase()))&&(!type.value||e.type===type.value)));
const eventsByDate=computed(()=>{const map=new Map();filtered.value.forEach(e=>{const key=e.date.slice(0,10);if(!map.has(key))map.set(key,[]);map.get(key).push(e)});return map});
const grouped=computed(()=>[...eventsByDate.value].map(([date,items])=>({date,events:items})));
const monthCells=computed(()=>{const start=bounds.value.start,first=(start.getDay()+6)%7,cells=[];for(let i=-first;i<42-first;i++){const d=new Date(start.getFullYear(),start.getMonth(),i+1),date=localIso(d);cells.push({key:date,date,day:d.getDate(),current:d.getMonth()===start.getMonth(),events:eventsByDate.value.get(date)||[]})}return cells});
const activeFilterCount=computed(()=>[search.value,type.value,tracked.value].filter(Boolean).length);
watch(view,value=>localStorage.setItem('calendar.view',value));
function localIso(d){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`}
function longDate(v){return new Intl.DateTimeFormat('fr-FR',{weekday:'long',day:'numeric',month:'long'}).format(new Date(`${v}T12:00:00`))}
function formatTime(v){if(!v)return '';const d=new Date(v);if(isNaN(d.getTime())||v.endsWith('T00:00:00Z')||v.endsWith('T00:00:00.000Z'))return '';return d.toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'})}
function eventKey(event){return `${event.instance}:${event.date}:${event.title}:${event.subtitle}`}
function eventState(event){return event.has_file?'available':event.tracked?'pending':''}
function eventLabel(event){return event.has_file?'Disponible':event.tracked?'Suivi':'Catalogue'}
function openDetail(event){if(event.library_item_id)router.push(mediaDetailPath({id:event.library_item_id},'library'));else if(event.request_id)router.push(mediaDetailPath({id:event.request_id},'request'))}
function showDay(date){view.value='agenda';nextTick(()=>document.getElementById(`date-${date}`)?.scrollIntoView({behavior:'smooth',block:'start'}))}
function resetFilters(){search.value='';type.value='';tracked.value=false;load()}
async function load(){loading.value=true;error.value='';try{events.value=await api(`/api/calendar?start=${localIso(bounds.value.start)}&end=${localIso(bounds.value.end)}&tracked_only=${tracked.value}`);if(view.value==='agenda')nextTick(()=>setTimeout(()=>{let el=document.getElementById(`date-${todayStr}`);if(!el){const upcoming=grouped.value.find(g=>g.date>=todayStr);if(upcoming)el=document.getElementById(`date-${upcoming.date}`)}el?.scrollIntoView({behavior:'smooth',block:'start'})},100))}catch(e){error.value=e.message}finally{loading.value=false}}
function move(delta){cursor.value=new Date(cursor.value.getFullYear(),cursor.value.getMonth()+delta,1);load()}
function today(){cursor.value=new Date();load()}
onMounted(()=>{if(window.matchMedia('(max-width:640px)').matches)view.value='agenda';load()});
</script>

<style scoped>
.calendar-navigation,.calendar-command-bar,.calendar-legend{display:flex;align-items:center;gap:8px}.calendar-command-bar{align-items:stretch}.calendar-command-bar :deep(.ui-filter-bar){flex:1}.calendar-view-switch button{gap:6px;min-width:92px}.calendar-view-switch svg{width:15px}.calendar-legend{justify-content:flex-end;color:var(--muted);font-size:11px}.calendar-legend span{display:flex;align-items:center;gap:5px}.calendar-legend i{width:7px;height:7px;border-radius:50%;background:var(--muted)}.calendar-legend i.available{background:var(--success)}.calendar-legend i.tracked{background:var(--accent)}.month-calendar-shell{max-width:100%;overflow-x:auto;border:1px solid var(--border);border-radius:12px;background:var(--surface);scrollbar-width:thin;overscroll-behavior-x:contain}.month-calendar{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));min-width:0}.month-weekday{position:sticky;top:0;z-index:2;padding:8px;text-align:center;border-bottom:1px solid var(--border);background:var(--surface);color:var(--muted);font-size:10px;font-weight:700;text-transform:uppercase}.month-cell{min-width:0;min-height:132px;padding:8px;border-right:1px solid var(--border);border-bottom:1px solid var(--border);background:rgba(255,255,255,.008);overflow:hidden}.month-cell:nth-child(7n){border-right:0}.month-cell:nth-last-child(-n+7){border-bottom:0}.month-cell.outside{opacity:.35}.month-cell.today{background:rgba(229,160,13,.06);box-shadow:inset 0 0 0 1px rgba(229,160,13,.3)}.month-cell header{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}.month-cell header>span{color:var(--text);font-weight:700}.month-cell header small{color:var(--accent);font-size:8px}.month-event,.month-more{display:flex;align-items:center;gap:4px;width:100%;min-width:0;margin:3px 0;padding:4px 5px;border:0;border-left:2px solid var(--muted);border-radius:3px;background:rgba(255,255,255,.035);color:var(--text);font-size:9px;text-align:left;cursor:pointer}.month-event.available{border-color:var(--success)}.month-event.pending{border-color:var(--accent)}.month-event span{flex:0 0 auto;font-size:8px}.month-event strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:9px}.month-more{display:block;border:0;background:transparent;color:var(--accent);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.today-badge{display:inline-flex;margin-left:7px;padding:3px 6px;border-radius:999px;background:rgba(229,160,13,.12);font-size:9px}@media(max-width:900px){.month-calendar{min-width:760px}.month-cell{min-height:112px;padding:6px}.calendar-command-bar{display:grid;grid-template-columns:1fr}.calendar-view-switch{justify-self:start}.calendar-legend{justify-content:flex-start}}@media(max-width:640px){.calendar-navigation{width:100%;justify-content:space-between}.calendar-command-bar{position:sticky;top:8px;z-index:20;padding:8px;border:1px solid var(--border);border-radius:10px;background:var(--surface)}.calendar-command-bar :deep(.ui-filter-bar){position:static;padding:0;border:0;background:transparent}.calendar-view-switch{width:100%}.calendar-view-switch button{flex:1}.month-calendar-shell{display:none}}
@media(max-width:640px){.calendar-view-switch button:last-child{display:none}}
</style>
