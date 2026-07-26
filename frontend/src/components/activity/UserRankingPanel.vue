<template>
  <section class="panel">
    <div class="panel-head"><div><span class="eyebrow">Audience</span><h2>Utilisateurs actifs</h2></div></div>
    <div class="ranking">
      <div v-for="(user,index) in users" :key="user.name"><b>{{ index+1 }}</b><span><strong>{{ user.name }}</strong><small>{{ user.sessions }} sessions</small></span><em>{{ formatDuration(user.watch_ms) }}</em></div>
      <p v-if="!users.length" class="empty">Pas encore de données.</p>
    </div>
  </section>
</template>

<script setup>
defineProps({users:{type:Array,default:()=>[]},formatDuration:{type:Function,required:true}});
</script>

<style scoped>
.ranking{display:grid;margin-top:12px}.ranking>div{display:grid;grid-template-columns:24px 1fr auto;gap:8px;align-items:center;padding:9px 0;border-bottom:1px solid var(--border)}.ranking b{color:var(--accent)}.ranking span{display:grid}.ranking small,.ranking em{font-size:10px;color:var(--muted);font-style:normal}
</style>
