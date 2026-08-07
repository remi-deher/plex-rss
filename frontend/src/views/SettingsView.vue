<template>
  <div class="page">
    <PageHeader title="Paramètres" description="Connexions, notifications, automatisation et exploitation." :eyebrow="currentTabLabel">
      <button v-if="['plex','services','webhooks','notifications-channels','notifications-rules','downloads','scheduled-tasks','data'].includes(tab)" class="primary" :disabled="saving" @click="save">
        <Save/>{{ saving ? 'Enregistrement...' : 'Enregistrer' }}
      </button>
    </PageHeader>
    <NotificationsSubnav v-if="isNotificationsTab" :active="tab"/>
    <div class="settings-search"><Search/><input v-model="sectionSearch" type="search" placeholder="Rechercher dans tous les paramètres" aria-label="Rechercher une section"><div v-if="sectionSearch" class="settings-search-results"><button v-for="item in filteredTabs" :key="item.key" @click="selectItem(item);sectionSearch=''">{{ item.label }}<span>{{ item.group }}</span></button><p v-if="!filteredTabs.length">Aucune section trouvée.</p></div></div>
    <UiFeedback v-if="error" type="error" title="Enregistrement impossible" :message="error" />
    <UiFeedback v-if="message" type="success" :message="message" />

    <SettingsOverview v-if="tab==='overview'" @select="selectTab"/>
    <ConnectionsTab v-else-if="tab==='plex'"/>
    <ServicesTab v-else-if="tab==='services'"/>
    <WebhooksTab v-else-if="tab==='webhooks'"/>
    <NotificationsChannelsTab v-else-if="tab==='notifications-channels'"/>
    <NotificationsRulesTab v-else-if="tab==='notifications-rules'"/>
    <DownloadsTab v-else-if="tab==='downloads'"/>
    <PlanningMaintenanceTab v-else-if="tab==='scheduled-tasks'"/>
    <AcquisitionsConflictsTab v-else-if="tab==='acquisitions'"/>
    <EmailTemplatesPanel v-else-if="tab==='templates'"/>
    <DataPrivacyTab v-else/>
    <FormSaveBar v-if="!standaloneTabs.has(tab)" :dirty="isDirty" :saving="saving" @save="save"/>
    <ConfirmModal v-bind="confirmDialog" @cancel="resolveConfirm(false)" @confirm="resolveConfirm(true)" />
  </div>
</template>
<script setup>
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref, watch } from 'vue';
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router';
import { Save, Search } from '@lucide/vue';
import SettingsOverview from '@/components/settings/SettingsOverview.vue';
import NotificationsSubnav from '@/components/settings/NotificationsSubnav.vue';
import ConfirmModal from '@/components/ConfirmModal.vue';
import { useConfirm } from '@/composables/useConfirm';
import { load, save, saving, error, message, isDirty } from '@/settingsForm';
import { settingsSections } from '@/settingsSections';
import { notificationSections } from '@/notificationSections';

const { dialog: confirmDialog, askConfirm, resolveConfirm } = useConfirm();
const ConnectionsTab = defineAsyncComponent(() => import('@/components/settings/ConnectionsTab.vue'));
const ServicesTab = defineAsyncComponent(() => import('@/components/settings/ServicesTab.vue'));
const WebhooksTab = defineAsyncComponent(() => import('@/components/settings/WebhooksTab.vue'));
const NotificationsChannelsTab = defineAsyncComponent(() => import('@/components/settings/NotificationsChannelsTab.vue'));
const NotificationsRulesTab = defineAsyncComponent(() => import('@/components/settings/NotificationsRulesTab.vue'));
const DownloadsTab = defineAsyncComponent(() => import('@/components/settings/DownloadsTab.vue'));
const PlanningMaintenanceTab = defineAsyncComponent(() => import('@/components/settings/PlanningMaintenanceTab.vue'));
const AcquisitionsConflictsTab = defineAsyncComponent(() => import('@/components/settings/AcquisitionsConflictsTab.vue'));
const EmailTemplatesPanel = defineAsyncComponent(() => import('@/components/EmailTemplatesPanel.vue'));
const DataPrivacyTab = defineAsyncComponent(() => import('@/components/settings/DataPrivacyTab.vue'));

// Sections affichées via `?tab=` (exclut Journaux, qui est une route à part) +
// les 3 onglets notifications (Canaux/Règles/Modèles), dont la navigation
// visible passe par NotificationsSubnav plutôt que par settingsSections.
const notificationTabDefs = notificationSections.filter(item => item.to?.path === '/settings');
const tabs = [...settingsSections.filter(item => !item.to), ...notificationTabDefs];
const route=useRoute(),router=useRouter();
const tab = computed(()=>tabs.some(item=>item.key===route.query.tab)?route.query.tab:'overview');
const isNotificationsTab = computed(() => notificationTabDefs.some(item => item.key === tab.value));
const standaloneTabs = new Set(['acquisitions', 'templates']);
let settingsLoadPromise;
function ensureSettingsLoaded(value = tab.value) {
  if (standaloneTabs.has(value)) return Promise.resolve();
  if (!settingsLoadPromise) settingsLoadPromise = load().catch(error => {
    settingsLoadPromise = undefined;
    throw error;
  });
  return settingsLoadPromise;
}
const currentTabLabel = computed(() => tabs.find(item => item.key === tab.value)?.label || 'Vue d’ensemble');
const sectionSearch = ref('');
const searchableSections = [...settingsSections, ...notificationSections];
const filteredTabs = computed(() => {
  const query = sectionSearch.value.trim().toLowerCase();
  return query ? searchableSections.filter(item => `${item.label} ${item.group}`.toLowerCase().includes(query)) : [];
});
function selectTab(value) {
  router.replace({path:'/settings',query:{tab:value}});
}
function selectItem(item) {
  if (item.to) router.push(item.to);
  else selectTab(item.key);
}
function warnUnsaved(event){if(!isDirty.value)return;event.preventDefault();event.returnValue=''}
onBeforeRouteLeave(()=>!isDirty.value||askConfirm({title:'Quitter sans enregistrer ?',message:'Des modifications ne sont pas enregistrées. Quitter cette page ?',confirmLabel:'Quitter',danger:true}));
onBeforeRouteUpdate(()=>!isDirty.value||askConfirm({title:'Changer de section sans enregistrer ?',message:'Des modifications ne sont pas enregistrées. Changer de section ?',confirmLabel:'Continuer',danger:true}));
onMounted(()=>window.addEventListener('beforeunload',warnUnsaved));
onUnmounted(()=>window.removeEventListener('beforeunload',warnUnsaved));

watch(tab, value => ensureSettingsLoaded(value).catch(() => {}));
onMounted(() => ensureSettingsLoaded().catch(() => {}));
</script>
<style scoped>
.settings-search{position:relative;display:flex;align-items:center;gap: var(--space-3);width:min(100%,620px);min-height:48px;margin-bottom:16px;padding:10px 14px;border:1px solid var(--border);border-radius:var(--radius-md);background:var(--surface)}.settings-search:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 12%,transparent)}.settings-search>svg{flex:none;width:18px;color:var(--muted)}.settings-search>input{width:100%;border:0;background:transparent;outline:0;color:var(--text);font-size:var(--fs-md)}.settings-search-results{position:absolute;z-index:30;top:calc(100% + 7px);left:0;right:0;display:grid;padding:7px;border:1px solid var(--border);border-radius:var(--radius-md);background:var(--surface);box-shadow:0 12px 28px rgba(0,0,0,.3)}.settings-search-results button{display:flex;justify-content:space-between;min-height:44px;padding:10px;border:0;border-radius:var(--radius-sm);background:transparent;color:var(--text);font-size:var(--fs-sm);text-align:left}.settings-search-results button:hover{background:var(--surface-2)}.settings-search-results span,.settings-search-results p{color:var(--muted);font-size:var(--fs-xs)}
@media(max-width:640px){.settings-search{width:100%}}
</style>
