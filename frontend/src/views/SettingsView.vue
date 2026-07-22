<template>
  <div class="page">
    <PageHeader title="Paramètres" description="Connexions, notifications, automatisation et exploitation." :eyebrow="currentTabLabel">
      <button v-if="['connections','webhooks','notifications-channels','notifications-rules','library','downloads','scheduled-tasks','privacy'].includes(tab)" class="primary" :disabled="saving" @click="save">
        <Save/>{{ saving ? 'Enregistrement...' : 'Enregistrer' }}
      </button>
    </PageHeader>
    <label class="settings-section-select">Section des parametres
      <select :value="tab" @change="selectTab($event.target.value)">
        <optgroup v-for="group in tabGroups" :key="group.label" :label="group.label"><option v-for="item in group.items" :key="item.key" :value="item.key">{{ item.label }}</option></optgroup>
      </select>
    </label>
    <div class="settings-search"><Search/><input v-model="sectionSearch" type="search" placeholder="Rechercher une section de paramètres" aria-label="Rechercher une section"><div v-if="sectionSearch" class="settings-search-results"><button v-for="item in filteredTabs" :key="item.key" @click="selectTab(item.key);sectionSearch=''">{{ item.label }}<span>{{ groupFor(item.key) }}</span></button><p v-if="!filteredTabs.length">Aucune section trouvée.</p></div></div>
    <UiFeedback v-if="error" type="error" title="Enregistrement impossible" :message="error" />
    <UiFeedback v-if="message" type="success" :message="message" />

    <SettingsOverview v-if="tab==='overview'" @select="selectTab"/>
    <ConnectionsTab v-else-if="tab==='connections'"/>
    <WebhooksTab v-else-if="tab==='webhooks'"/>
    <NotificationsChannelsTab v-else-if="tab==='notifications-channels'"/>
    <NotificationsRulesTab v-else-if="tab==='notifications-rules'"/>
    <LibraryTab v-else-if="tab==='library'"/>
    <DownloadsTab v-else-if="tab==='downloads'"/>
    <ScheduledTasksTab v-else-if="tab==='scheduled-tasks'"/>
    <SettingsOperationsPanel v-else-if="tab==='operations'"/>
    <EmailTemplatesPanel v-else-if="tab==='templates'"/>
    <GdprTab v-else-if="tab==='privacy'"/>
    <DataTab v-else/>
    <FormSaveBar v-if="tab!=='templates'" :dirty="isDirty" :saving="saving" @save="save"/>
    <ConfirmModal v-bind="confirmDialog" @cancel="resolveConfirm(false)" @confirm="resolveConfirm(true)" />
  </div>
</template>
<script setup>
import { computed, markRaw, onMounted, onUnmounted, ref } from 'vue';
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router';
import { Bell, BookMarked, Clock, DatabaseZap, Download, FileCode2, ListChecks, Link, Plug, Save, Search, ServerCog, ShieldCheck } from '@lucide/vue';
import SettingsOverview from '@/components/settings/SettingsOverview.vue';
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
import GdprTab from '@/components/settings/GdprTab.vue';
import ConfirmModal from '@/components/ConfirmModal.vue';
import { useConfirm } from '@/composables/useConfirm';
import { load, save, saving, error, message, isDirty } from '@/settingsForm';

const { dialog: confirmDialog, askConfirm, resolveConfirm } = useConfirm();

const tabs = [
  { key: 'overview', label: 'Vue d’ensemble', icon: markRaw(ServerCog) },
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
  { key: 'privacy', label: 'RGPD', icon: markRaw(ShieldCheck) },
];
const tabGroups=[
  {label:'Parametres',items:tabs.filter(item=>['overview','connections','webhooks','library','downloads'].includes(item.key))},
  {label:'Notifications',items:tabs.filter(item=>['notifications-channels','notifications-rules','templates'].includes(item.key))},
  {label:'Exploitation',items:tabs.filter(item=>['scheduled-tasks','operations','data','privacy'].includes(item.key))},
];
const route=useRoute(),router=useRouter();
const tab = computed(()=>tabs.some(item=>item.key===route.query.tab)?route.query.tab:'overview');
const currentTabLabel = computed(() => tabs.find(item => item.key === tab.value)?.label || 'Vue d’ensemble');
const sectionSearch=ref('');
const filteredTabs=computed(()=>{const query=sectionSearch.value.trim().toLowerCase();return query?tabs.filter(item=>`${item.label} ${groupFor(item.key)}`.toLowerCase().includes(query)):[]});
function groupFor(key){return tabGroups.find(group=>group.items.some(item=>item.key===key))?.label||''}
function selectTab(value) {
  router.replace({path:'/settings',query:{tab:value}});
}
function warnUnsaved(event){if(!isDirty.value)return;event.preventDefault();event.returnValue=''}
onBeforeRouteLeave(()=>!isDirty.value||askConfirm({title:'Quitter sans enregistrer ?',message:'Des modifications ne sont pas enregistrées. Quitter cette page ?',confirmLabel:'Quitter',danger:true}));
onBeforeRouteUpdate(()=>!isDirty.value||askConfirm({title:'Changer de section sans enregistrer ?',message:'Des modifications ne sont pas enregistrées. Changer de section ?',confirmLabel:'Continuer',danger:true}));
onMounted(()=>window.addEventListener('beforeunload',warnUnsaved));
onUnmounted(()=>window.removeEventListener('beforeunload',warnUnsaved));

onMounted(load);
</script>
<style scoped>
.settings-section-select{display:none;gap:6px;color:var(--muted);font-size:12px}.settings-section-select select{width:100%}
.settings-search{position:relative;display:flex;align-items:center;gap:8px;max-width:520px;padding:9px 11px;border:1px solid var(--border);border-radius:9px;background:var(--surface)}.settings-search>svg{width:16px;color:var(--muted)}.settings-search>input{width:100%;border:0;background:transparent;outline:0;color:var(--text)}.settings-search-results{position:absolute;z-index:30;top:calc(100% + 5px);left:0;right:0;display:grid;padding:6px;border:1px solid var(--border);border-radius:9px;background:var(--surface);box-shadow:0 12px 28px rgba(0,0,0,.3)}.settings-search-results button{display:flex;justify-content:space-between;padding:9px;border:0;border-radius:6px;background:transparent;color:var(--text);text-align:left}.settings-search-results button:hover{background:var(--surface-2)}.settings-search-results span,.settings-search-results p{color:var(--muted);font-size:10px}
@media(max-width:1024px){.settings-section-select{display:grid}}
@media(max-width:640px){.settings-section-select{position:sticky;top:8px;z-index:8;padding:10px;background:var(--surface);border:1px solid var(--border);border-radius:8px}}
</style>
