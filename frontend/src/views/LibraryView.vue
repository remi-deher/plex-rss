<template>
  <div class="page">
    <header class="page-head"><div><h1>Bibliotheque</h1><p>Medias indexes dans Plex et statut de langue.</p></div><button class="icon-button" :disabled="loading" title="Actualiser" @click="load"><RefreshCw :class="{spin:loading}" /></button></header>
    <div class="toolbar"><input v-model="query" class="search" type="search" placeholder="Rechercher dans la bibliotheque" @input="scheduleLoad" /><div class="segmented"><button :class="{active:type==='' }" @click="setType('')">Tout</button><button :class="{active:type==='movie'}" @click="setType('movie')">Films</button><button :class="{active:type==='show'}" @click="setType('show')">Series</button></div></div>
    <p v-if="error" class="notice error-text">{{ error }}</p>
    <section class="media-grid"><article v-for="item in items" :key="item.id" class="media-card"><div class="poster-shell"><img v-if="item.poster_url" :src="item.poster_url" alt="" loading="lazy"/><div v-else class="poster-fallback"><Film /></div><span class="language-tag" :class="item.has_vf===true?'vf':item.has_vf===false?'vo':'unknown'">{{ item.has_vf===true?'VF':item.has_vf===false?'VO':'?' }}</span></div><div><strong>{{ item.title }}</strong><span>{{ item.media_type==='show'?'Serie':'Film' }}<template v-if="item.year"> - {{ item.year }}</template></span></div></article></section>
    <p v-if="!loading && items.length===0" class="empty">Aucun media indexe.</p>
  </div>
</template>
<script setup>
import { onMounted,ref } from "vue";import { Film,RefreshCw } from "@lucide/vue";import { api } from "@/api";
const items=ref([]),query=ref(""),type=ref(""),loading=ref(false),error=ref("");let timer;
function scheduleLoad(){clearTimeout(timer);timer=setTimeout(load,250)} function setType(v){type.value=v;load()}
async function load(){loading.value=true;error.value="";const p=new URLSearchParams();if(query.value.trim())p.set("query",query.value.trim());if(type.value)p.set("media_type",type.value);try{items.value=await api(`/api/library?${p}`)}catch(e){error.value=e.message}finally{loading.value=false}}
onMounted(load);
</script>
