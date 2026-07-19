<template>
  <div class="page">
    <PageHeader title="Paramètres" description="Connexions, notifications, automatisation et exploitation." :eyebrow="currentTabLabel">
      <button v-if="['connections','webhooks','notifications-channels','notifications-rules','library','downloads','scheduled-tasks'].includes(tab)" class="primary" :disabled="saving" @click="save">
        <Save/>{{ saving ? 'Enregistrement...' : 'Enregistrer' }}
      </button>
    </PageHeader>
    <label class="settings-section-select">Section des parametres
      <select :value="tab" @change="selectTab($event.target.value)">
        <optgroup v-for="group in tabGroups" :key="group.label" :label="group.label"><option v-for="item in group.items" :key="item.key" :value="item.key">{{ item.label }}</option></optgroup>
      </select>
    </label>
    <UiFeedback v-if="error" type="error" title="Enregistrement impossible" :message="error" />
    <UiFeedback v-if="message" type="success" :message="message" />

    <ConnectionsTab v-if="tab==='connections'"/>
    <WebhooksTab v-else-if="tab==='webhooks'"/>
    <NotificationsChannelsTab v-else-if="tab==='notifications-channels'"/>
    <NotificationsRulesTab v-else-if="tab==='notifications-rules'"/>
    <LibraryTab v-else-if="tab==='library'"/>
    <DownloadsTab v-else-if="tab==='downloads'"/>
    <ScheduledTasksTab v-else-if="tab==='scheduled-tasks'"/>
    <SettingsOperationsPanel v-else-if="tab==='operations'"/>
    <EmailTemplatesPanel v-else-if="tab==='templates'"/>
    <DataTab v-else/>
    <FormSaveBar v-if="tab!=='templates'" :dirty="isDirty" :saving="saving" @save="save"/>
  </div>
</template>
<script setup>
import { computed, markRaw, onMounted, onUnmounted } from 'vue';
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router';
import { Bell, BookMarked, Clock, DatabaseZap, Download, FileCode2, ListChecks, Link, Plug, Save, ServerCog } from '@lucide/vue';
import EmailTemplatesPanel from '@/components/EmailTemplatesPanel.vue';
import SettingsOperationsPanel from '@/components/SettingsOperationsPanel.vue';
import ConnectionsTab from '@/components/settings/ConnectionsTab.vue';
import WebhooksTab from '@/components/settings/WebhooksTab.vue';
import NotificationsChannelsTab from '@/components/settings/NotificationsChannelsTab.vue';
import NotificationsRulesTab from '@/components/settings/NotificationsRulesTab.vue';
import LibraryTab from '@/components/settings/LibraryTab.vue';
import DownloadsTab from '@/components/settings/DownloadsTab.vue';
import ScheduledTasksTab from '@/components/settings/ScheduledTasksTab.vue';
import DataTab from '@/components/settings/DataTab.vue';
import { load, save, saving, error, message, isDirty } from '@/settingsForm';

const tabs = [
  { key: 'connections', label: 'Connexions', icon: markRaw(Plug) },
  { key: 'webhooks', label: 'Webhooks', icon: markRaw(Link) },
  { key: 'notifications-channels', label: 'Notifs · Canaux', icon: markRaw(Bell) },
  { key: 'notifications-rules', label: 'Notifs · Regles', icon: markRaw(ListChecks) },
  { key: 'library', label: 'Bibliotheque', icon: markRaw(BookMarked) },
  { key: 'downloads', label: 'Telechargements', icon: markRaw(Download) },
  { key: 'scheduled-tasks', label: 'Planification', icon: markRaw(Clock) },
  { key: 'operations', label: 'Exploitation', icon: markRaw(ServerCog) },
  { key: 'templates', label: 'Emails', icon: markRaw(FileCode2) },
  { key: 'data', label: 'Donnees', icon: markRaw(DatabaseZap) },
];
const tabGroups=[
  {label:'Parametres',items:tabs.filter(item=>['connections','webhooks','library','downloads'].includes(item.key))},
  {label:'Notifications',items:tabs.filter(item=>['notifications-channels','notifications-rules','templates'].includes(item.key))},
  {label:'Exploitation',items:tabs.filter(item=>['scheduled-tasks','operations','data'].includes(item.key))},
];
const route=useRoute(),router=useRouter();
const tab = computed(()=>tabs.some(item=>item.key===route.query.tab)?route.query.tab:'connections');
const currentTabLabel = computed(() => tabs.find(item => item.key === tab.value)?.label || 'Connexions');
function selectTab(value) {
  router.replace({path:'/settings',query:{tab:value}});
}
function warnUnsaved(event){if(!isDirty.value)return;event.preventDefault();event.returnValue=''}
onBeforeRouteLeave(()=>!isDirty.value||window.confirm('Des modifications ne sont pas enregistrées. Quitter cette page ?'));
onBeforeRouteUpdate(()=>!isDirty.value||window.confirm('Des modifications ne sont pas enregistrées. Changer de section ?'));
onMounted(()=>window.addEventListener('beforeunload',warnUnsaved));
onUnmounted(()=>window.removeEventListener('beforeunload',warnUnsaved));

onMounted(load);
</script>
<style scoped>
.settings-section-select{display:none;gap:6px;color:var(--muted);font-size:12px}.settings-section-select select{width:100%}
@media(max-width:1024px){.settings-section-select{display:grid}}
@media(max-width:640px){.settings-section-select{position:sticky;top:8px;z-index:8;padding:10px;background:var(--surface);border:1px solid var(--border);border-radius:8px}}
</style>
