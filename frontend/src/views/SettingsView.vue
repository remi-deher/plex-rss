<template>
  <div class="page">
    <header class="page-head">
      <div><h1>Parametres</h1><p>Connexions, notifications, automatisation et exploitation.</p></div>
      <button v-if="['connections','webhooks','notifications','automation'].includes(tab)" class="primary" :disabled="saving" @click="save">
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
    <NotificationsTab v-else-if="tab==='notifications'"/>
    <AutomationTab v-else-if="tab==='automation'"/>
    <SettingsOperationsPanel v-else-if="tab==='operations'"/>
    <EmailTemplatesPanel v-else-if="tab==='templates'"/>
    <DataTab v-else/>
  </div>
</template>
<script setup>
import { markRaw, onMounted, ref } from 'vue';
import { Bell, Bot, DatabaseZap, FileCode2, Link, Plug, Save, ServerCog } from '@lucide/vue';
import EmailTemplatesPanel from '@/components/EmailTemplatesPanel.vue';
import SettingsOperationsPanel from '@/components/SettingsOperationsPanel.vue';
import ConnectionsTab from '@/components/settings/ConnectionsTab.vue';
import WebhooksTab from '@/components/settings/WebhooksTab.vue';
import NotificationsTab from '@/components/settings/NotificationsTab.vue';
import AutomationTab from '@/components/settings/AutomationTab.vue';
import DataTab from '@/components/settings/DataTab.vue';
import { load, save, saving, error, message } from '@/settingsForm';

const tabs = [
  { key: 'connections', label: 'Connexions', icon: markRaw(Plug) },
  { key: 'webhooks', label: 'Webhooks', icon: markRaw(Link) },
  { key: 'notifications', label: 'Notifications', icon: markRaw(Bell) },
  { key: 'automation', label: 'Automatisation', icon: markRaw(Bot) },
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
