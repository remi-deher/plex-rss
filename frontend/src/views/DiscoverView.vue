<template>
  <div class="page">
    <header class="page-head"><div><h1>Decouvrir</h1><p>Catalogue TMDB, recommandations et nouvelles demandes.</p></div><input v-model="query" class="search" type="search" placeholder="Rechercher un film ou une serie" @input="scheduleSearch"></header>
    <div class="toolbar wrap"><div class="segmented"><button v-for="entry in mediaTypes" :key="entry.value" :class="{active:mediaType===entry.value}" @click="setMediaType(entry.value)">{{ entry.label }}</button></div><div class="segmented"><button v-for="entry in sections" :key="entry.value" :class="{active:section===entry.value}" @click="setSection(entry.value)">{{ entry.label }}</button></div><select v-if="section==='genres'" v-model="genre" @change="load"><option value="">Tous les genres</option><option v-for="entry in genres" :key="entry.id" :value="entry.id">{{ entry.name }}</option></select></div>
    <p v-if="error" class="notice error-text">{{ error }}</p>
    <section class="media-grid"><button v-for="item in items" :key="`${item.media_type}:${item.tmdb_id||item.id}`" class="media-card interactive" @click="selected=item"><div class="poster-shell"><img v-if="item.poster_url" :src="item.poster_url" alt="" loading="lazy"><div v-else class="poster-fallback"><Film /></div><span v-if="item.available||item.in_library" class="language-tag vf">Disponible</span><span v-else-if="item.requested" class="language-tag unknown">{{ statusLabel(item.request_status) }}</span></div><div><strong>{{ item.title||item.name }}</strong><span>{{ item.media_type==='show'?'Serie':'Film' }}<template v-if="item.year"> · {{ item.year }}</template></span></div></button></section>
    <p v-if="loading" class="empty"><LoaderCircle class="spin"/> Chargement du catalogue</p><p v-else-if="!items.length" class="empty">Aucun resultat.</p>
    <MediaDetailDrawer v-if="selected" :item="selected" mode="discover" @close="selected=null" @select="selected=$event" @updated="load" />
  </div>
</template>
<script setup>
import { onMounted,ref } from 'vue';import { Film,LoaderCircle } from '@lucide/vue';import { api } from '@/api';import MediaDetailDrawer from '@/components/MediaDetailDrawer.vue';
const items=ref([]),query=ref(''),mediaType=ref('all'),section=ref('trending'),genre=ref(''),genres=ref([]),selected=ref(null),loading=ref(false),error=ref('');let timer;
const mediaTypes=[{value:'all',label:'Tout'},{value:'movie',label:'Films'},{value:'show',label:'Series'}];const sections=[{value:'trending',label:'Tendances'},{value:'popular',label:'Populaires'},{value:'coming-soon',label:'A venir'},{value:'genres',label:'Genres'}];
function statusLabel(value){return ({pending_approval:'A approuver',pending:'En attente',sent_to_arr:'Transmise',failed:'Echec',available:'Disponible'})[value]||'Demandee'}
function setMediaType(value){mediaType.value=value;if(value==='all'&&section.value==='genres')section.value='trending';loadGenres();load()}
function setSection(value){section.value=value;query.value='';load()}
async function loadGenres(){if(mediaType.value==='all')return;genres.value=await api(`/api/discover/genres?media_type=${mediaType.value}`).catch(()=>[])}
async function load(){loading.value=true;error.value='';try{const q=query.value.trim();if(q){items.value=await api(`/api/discover/search?query=${encodeURIComponent(q)}`)}else if(section.value==='trending'){items.value=await api(`/api/discover/trending?media_type=${mediaType.value}`)}else if(section.value==='popular'){items.value=await api(`/api/discover/popular?media_type=${mediaType.value==='all'?'movie':mediaType.value}`)}else if(section.value==='coming-soon'){items.value=await api(`/api/discover/coming-soon?media_type=${mediaType.value==='all'?'movie':mediaType.value}`)}else{const type=mediaType.value==='all'?'movie':mediaType.value;items.value=await api(`/api/discover/discover?media_type=${type}${genre.value?`&genre=${genre.value}`:''}`)}}catch(e){error.value=e.message;items.value=[]}finally{loading.value=false}}
function scheduleSearch(){clearTimeout(timer);timer=setTimeout(load,300)}
onMounted(async()=>{await loadGenres();await load()});
</script>
