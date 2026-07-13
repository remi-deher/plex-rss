<template>
  <div class="page">
    <header class="page-head">
      <div><h1>Demandes</h1><p>Suivi des medias demandes et de leur traitement.</p></div>
      <button class="icon-button" :disabled="loading" title="Actualiser" @click="load"><RefreshCw :class="{ spin: loading }" /></button>
    </header>
    <div class="toolbar">
      <input v-model="query" class="search" type="search" placeholder="Rechercher un titre" @input="scheduleLoad" />
      <select v-model="status" @change="load"><option value="">Tous les statuts</option><option v-for="value in statuses" :key="value">{{ value }}</option></select>
    </div>
    <p v-if="error" class="notice error-text">{{ error }}</p>
    <section class="panel table-wrap">
      <table><thead><tr><th>Titre</th><th>Type</th><th>Demandeur</th><th>Statut</th><th>Date</th><th></th></tr></thead>
        <tbody><tr v-for="row in filtered" :key="row.id"><td><strong>{{ row.title }}</strong><small v-if="row.year">{{ row.year }}</small></td><td>{{ row.media_type === 'show' ? 'Serie' : 'Film' }}</td><td>{{ row.plex_user || row.plex_user_id }}</td><td><span class="badge" :class="row.status">{{ label(row.status) }}</span></td><td>{{ formatDate(row.requested_at) }}</td><td class="actions"><button v-if="row.arr_id" class="icon-button" title="Rechercher une release" @click="router.push(`/releases/${row.id}`)"><Search /></button><button v-if="row.status === 'failed'" class="icon-button" title="Relancer" @click="act(row, 'retry')"><RotateCcw /></button><button v-if="row.status !== 'available'" class="icon-button danger" title="Annuler" @click="act(row, 'cancel')"><X /></button></td></tr></tbody>
      </table>
      <p v-if="!loading && filtered.length === 0" class="empty">Aucune demande.</p>
    </section>
  </div>
</template>
<script setup>
import { computed, onMounted, ref } from "vue";
import { RefreshCw, RotateCcw, Search, X } from "@lucide/vue";
import { useRouter } from "vue-router";
import { api } from "@/api";
const rows=ref([]), query=ref(""), status=ref(""), loading=ref(false), error=ref("");
const router=useRouter();
const statuses=["pending_approval","pending","sent_to_arr","available","failed"];
const filtered=computed(()=>status.value?rows.value.filter(r=>r.status===status.value):rows.value);
let timer;
function scheduleLoad(){clearTimeout(timer);timer=setTimeout(load,250)}
function label(v){return ({pending_approval:"A approuver",pending:"En attente",sent_to_arr:"Transmise",available:"Disponible",failed:"Echec"})[v]||v}
function formatDate(v){return v?new Intl.DateTimeFormat("fr-FR",{dateStyle:"medium"}).format(new Date(v)):"-"}
async function load(){loading.value=true;error.value="";try{rows.value=await api(`/api/requests${query.value.trim()?`?query=${encodeURIComponent(query.value.trim())}`:""}`)}catch(e){error.value=e.message}finally{loading.value=false}}
const admin=ref(false);
async function act(row, action){error.value="";try{if(action==='cancel'&&admin.value){await api(`/api/requests/${row.id}`,{method:'DELETE'})}else{await api(`/api/requests/${row.id}/${action}`,{method:"POST"})}await load()}catch(e){error.value=e.message}}
onMounted(async()=>{const session=await api('/api/session').catch(()=>null);admin.value=Boolean(session?.is_owner||session?.role==='admin');await load()});
</script>
