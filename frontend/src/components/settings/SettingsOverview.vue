<template>
  <div class="settings-overview">
    <section class="settings-health-grid">
      <button v-for="card in cards" :key="card.key" class="settings-health-card" @click="$emit('select',card.key)">
        <component :is="card.icon"/>
        <div><span>{{ card.group }}</span><strong>{{ card.label }}</strong><small>{{ card.detail }}</small></div>
        <span class="health-state" :class="card.state">{{ stateLabel(card.state) }}</span>
      </button>
    </section>
    <section class="panel configuration-progress">
      <div class="panel-head"><div><span class="eyebrow">Configuration</span><h2>{{ configuredCount }} sections opérationnelles sur {{ cards.length }}</h2></div><strong>{{ progress }}%</strong></div>
      <progress :value="progress" max="100"></progress>
      <p>Les sections incomplètes restent accessibles et indiquent les éléments à renseigner.</p>
    </section>
  </div>
</template>
<script setup>
import { computed,markRaw } from 'vue';
import { Bell,BookMarked,Clock,Download,Link,Plug } from '@lucide/vue';
import { form,secretsPresent } from '@/settingsForm';
defineEmits(['select']);
const cards=computed(()=>[
  {key:'connections',group:'Services',label:'Plex et métadonnées',icon:markRaw(Plug),state:form.plex_url&&secretsPresent.plex_token?'active':'incomplete',detail:form.plex_url||'URL Plex à configurer'},
  {key:'webhooks',group:'Automatisation',label:'Webhooks et API',icon:markRaw(Link),state:form.public_base_url?'active':'incomplete',detail:form.public_base_url||'Adresse publique non définie'},
  {key:'notifications-channels',group:'Notifications',label:'Canaux d’envoi',icon:markRaw(Bell),state:form.email_enabled||form.discord_enabled||form.telegram_enabled||form.ntfy_enabled||form.gotify_enabled?'active':'inactive',detail:enabledChannels.value},
  {key:'library',group:'Médias',label:'Bibliothèque et langues',icon:markRaw(BookMarked),state:form.vff_enabled?'active':'inactive',detail:form.vff_enabled?'Analyse audio activée':'Analyse audio désactivée'},
  {key:'downloads',group:'Acquisition',label:'Téléchargements',icon:markRaw(Download),state:'active',detail:`Confirmation ${form.availability_confirmation_mode||'hybride'}`},
  {key:'scheduled-tasks',group:'Exploitation',label:'Planification',icon:markRaw(Clock),state:form.poll_interval_seconds?'active':'incomplete',detail:`Contrôle toutes les ${Math.round((form.poll_interval_seconds||0)/60)} min`},
]);
const enabledChannels=computed(()=>{const names=[];if(form.email_enabled)names.push('Email');if(form.discord_enabled)names.push('Discord');if(form.telegram_enabled)names.push('Telegram');if(form.ntfy_enabled)names.push('ntfy');if(form.gotify_enabled)names.push('Gotify');return names.length?names.join(', '):'Aucun canal actif'});
const configuredCount=computed(()=>cards.value.filter(card=>card.state==='active').length);
const progress=computed(()=>Math.round(configuredCount.value/cards.value.length*100));
function stateLabel(state){return ({active:'Configuré',inactive:'Désactivé',incomplete:'À compléter'})[state]}
</script>
<style scoped>
.settings-overview{display:grid;gap:14px}.settings-health-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.settings-health-card{display:grid;grid-template-columns:auto 1fr;gap:10px;padding:15px;border:1px solid var(--border);border-radius:12px;background:var(--surface);color:var(--text);text-align:left}.settings-health-card:hover{border-color:var(--accent);transform:translateY(-1px)}.settings-health-card>svg{width:20px;color:var(--accent)}.settings-health-card>div{display:grid;gap:3px;min-width:0}.settings-health-card div span{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.07em}.settings-health-card strong{font-size:13px}.settings-health-card small{overflow:hidden;color:var(--muted);font-size:10px;text-overflow:ellipsis;white-space:nowrap}.health-state{grid-column:2;justify-self:start;padding:4px 7px;border-radius:999px;font-size:9px;background:var(--surface-2);color:var(--muted)}.health-state.active{color:var(--success);background:rgba(34,197,94,.1)}.health-state.incomplete{color:var(--accent);background:rgba(229,160,13,.1)}.configuration-progress .panel-head>div{display:grid;gap:2px}.configuration-progress progress{width:100%}.configuration-progress p{margin-bottom:0;color:var(--muted);font-size:11px}@media(max-width:900px){.settings-health-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:560px){.settings-health-grid{grid-template-columns:1fr}.settings-health-card{padding:13px}}
</style>
