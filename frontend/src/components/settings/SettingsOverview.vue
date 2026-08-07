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
import { computed, markRaw } from 'vue';
import { Bell, Clock, Download, Link, Plug } from '@lucide/vue';
import { form, secretsPresent } from '@/settingsForm';

defineEmits(['select']);

const enabledChannels = computed(() => {
  const names = [];
  if (form.email_enabled) names.push('Email');
  if (form.discord_enabled) names.push('Discord');
  if (form.telegram_enabled) names.push('Telegram');
  if (form.ntfy_enabled) names.push('ntfy');
  if (form.gotify_enabled) names.push('Gotify');
  return names.length ? names.join(', ') : 'Aucun canal actif';
});

const cards = computed(() => [
  { key: 'plex', group: 'Services', label: 'Plex et bibliothèque', icon: markRaw(Plug), state: form.plex_url && secretsPresent.plex_token ? 'active' : 'incomplete', detail: form.plex_url || 'URL Plex à configurer' },
  { key: 'webhooks', group: 'Services', label: 'Webhooks et API', icon: markRaw(Link), state: form.public_base_url ? 'active' : 'incomplete', detail: form.public_base_url || 'Adresse publique non définie' },
  { key: 'notifications-channels', group: 'Notifications', label: 'Canaux d’envoi', icon: markRaw(Bell), state: form.email_enabled || form.discord_enabled || form.telegram_enabled || form.ntfy_enabled || form.gotify_enabled ? 'active' : 'inactive', detail: enabledChannels.value },
  { key: 'downloads', group: 'Bibliothèque & acquisition', label: 'Téléchargements', icon: markRaw(Download), state: 'active', detail: `Confirmation ${form.availability_confirmation_mode || 'hybride'}` },
  { key: 'scheduled-tasks', group: 'Exploitation', label: 'Planification', icon: markRaw(Clock), state: form.poll_interval_seconds ? 'active' : 'incomplete', detail: `Contrôle toutes les ${Math.round((form.poll_interval_seconds || 0) / 60)} min` },
]);

const configuredCount = computed(() => cards.value.filter(card => card.state === 'active').length);
const progress = computed(() => Math.round((configuredCount.value / cards.value.length) * 100));

function stateLabel(state) {
  return ({ active: 'Configuré', inactive: 'Désactivé', incomplete: 'À compléter' })[state] || 'Non configuré';
}
</script>
<style scoped>
.settings-overview{display:grid;gap: var(--space-4)}.settings-health-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap: var(--space-4)}.settings-health-card{display:grid;grid-template-columns:44px minmax(0,1fr) auto;gap:var(--space-2) var(--space-3);align-items:center;min-height:132px;padding:18px;border:1px solid var(--border);border-radius:var(--radius-lg);background:var(--surface);color:var(--text);text-align:left;transition:border-color .2s,transform .2s,box-shadow .2s}.settings-health-card:hover{border-color:var(--accent);transform:translateY(-2px);box-shadow:0 12px 26px rgba(0,0,0,.2)}.settings-health-card>svg{width:22px;height:22px;padding:10px;box-sizing:content-box;border:1px solid var(--border);border-radius:var(--radius-md);background:var(--surface-2);color:var(--muted)}.settings-health-card>div{display:grid;gap: var(--space-1);min-width:0}.settings-health-card div span{color:var(--muted);font-size:var(--fs-xs);font-weight:700;}.settings-health-card strong{font-size:var(--fs-md);line-height:1.3}.settings-health-card small{overflow:hidden;color:color-mix(in srgb,var(--text) 68%,transparent);font-size:var(--fs-sm);line-height:1.4;text-overflow:ellipsis;white-space:nowrap}.health-state{grid-column:2/-1;justify-self:start;padding:5px 9px;border-radius:var(--radius-pill);font-size:var(--fs-xs);font-weight:700;background:var(--surface-2);color:var(--muted)}.health-state.active{color:var(--success);background:rgba(34,197,94,.1)}.health-state.incomplete{color:var(--accent);background:rgba(229,160,13,.1)}.configuration-progress{padding:20px}.configuration-progress .panel-head>div{display:grid;gap: var(--space-1)}.configuration-progress progress{width:100%;height:10px}.configuration-progress p{margin-bottom:0;color:var(--muted);font-size:var(--fs-sm);line-height:1.5}@media(max-width:1024px){.settings-health-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:640px){.settings-health-grid{grid-template-columns:1fr;gap: var(--space-3)}.settings-health-card{grid-template-columns:42px minmax(0,1fr) auto;min-height:112px;padding:15px}.settings-health-card>svg{width:20px;height:20px}.settings-health-card strong{font-size:var(--fs-md)}.settings-health-card small{white-space:normal}.configuration-progress{padding:16px}.configuration-progress .panel-head{align-items:flex-start}.configuration-progress .panel-head strong{font-size:var(--fs-lg)}}
</style>
