<template>
  <div class="page">
    <header class="page-head">
      <div><h1>Parametres</h1><p>Connexions, notifications, automatisation et exploitation.</p></div>
      <button v-if="['connections','webhooks','notifications-channels','notifications-rules','library','downloads','scheduled-tasks'].includes(tab)" class="primary" :disabled="saving" @click="save">
        <Save/>{{ saving ? 'Enregistrement...' : 'Enregistrer' }}
      </button>
    </header>
    <div class="segmented settings-tabs">
      <button v-for="item in tabs" :key="item.key" :class="{active:tab===item.key}" @click="selectTab(item.key)">
        <component :is="item.icon"/>{{ item.label }}
      </button>
    </div>
    <p v-if="error" class="notice error-text">{{ error }}</p>
    <p v-if="message" class="notice success-text">{{ message }}</p>

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
  </div>
</template>
<script setup>
import { markRaw, onMounted, ref } from 'vue';
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
import { load, save, saving, error, message } from '@/settingsForm';

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
const tab = ref(new URLSearchParams(location.search).get('tab') || 'connections');
function selectTab(value) {
  tab.value = value;
  history.replaceState(null, '', `/settings?tab=${value}`);
}

onMounted(load);
</script>
