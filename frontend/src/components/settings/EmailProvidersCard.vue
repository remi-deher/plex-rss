<template>
  <SettingsCard
    title="Fournisseurs d'envoi d'email"
    :subtitle="`${providers.length} fournisseur(s) configure(s)`"
    :icon="Mail"
    :status="providers.some(p => p.enabled) ? 'active' : 'inactive'"
    :collapsible="false"
  >
    <template #actions>
      <button class="secondary" @click.stop="openModal()"><Plus/>Ajouter</button>
    </template>
    <small style="margin-top:-4px;margin-bottom:4px;color:var(--muted)">
      Plusieurs fournisseurs peuvent être actifs en parallèle : en cas d'échec, l'envoi bascule
      automatiquement sur le suivant, par ordre de priorité (haut de liste = essayé en premier).
    </small>
    <div v-if="providers.length" class="table-wrap table-cards rich">
      <table>
        <thead>
          <tr><th></th><th>Nom</th><th>Type</th><th>Statut</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="(provider, index) in providers" :key="provider.id">
            <td class="actions">
              <button class="icon-button" title="Monter" aria-label="Monter" :disabled="index===0" @click="move(index,-1)"><ChevronUp/></button>
              <button class="icon-button" title="Descendre" aria-label="Descendre" :disabled="index===providers.length-1" @click="move(index,1)"><ChevronDown/></button>
            </td>
            <td class="card-title"><strong>{{ provider.name }}</strong></td>
            <td data-label="Type"><span class="badge">{{ typeLabel(provider.provider_type) }}</span></td>
            <td data-label="Statut">
              <span class="badge" :class="provider.enabled?'available':'failed'">{{ provider.enabled?'Actif':'Inactif' }}</span>
              <span v-if="provider.provider_type==='smtp_oauth2'" class="badge" :class="provider.oauth_connected?'available':'failed'">
                {{ provider.oauth_connected?'Microsoft connecté':'Microsoft non connecté' }}
              </span>
            </td>
            <td class="actions card-actions">
              <button class="icon-button" title="Tester" aria-label="Tester" @click="testProvider(provider)"><PlugZap/></button>
              <button class="icon-button" title="Modifier" aria-label="Modifier" @click="openModal(provider)"><Pencil/></button>
              <button class="icon-button" :title="provider.enabled?'Desactiver':'Activer'" :aria-label="provider.enabled?'Desactiver':'Activer'" @click="toggle(provider)"><Power/></button>
              <button class="icon-button danger" title="Supprimer" aria-label="Supprimer" @click="remove(provider)"><Trash2/></button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="empty">Aucun fournisseur configuré — les notifications par email ne peuvent pas partir.</p>
  </SettingsCard>

  <ModalShell
    v-if="showModal"
    :title="editingId?'Modifier le fournisseur':'Ajouter un fournisseur'"
    panel-class="arr-instance-modal"
    :busy="busy"
    @close="closeModal"
  >
    <div class="compact-form">
        <label>Nom<input v-model="form.name" placeholder="ex: Hotmail perso"></label>
        <label>Type
          <select v-model="form.provider_type">
            <option value="smtp">SMTP — Utilisateur / mot de passe</option>
            <option value="smtp_oauth2">SMTP — OAuth2 (Microsoft — hotmail.fr / outlook.com)</option>
            <option value="brevo">API Brevo (sans serveur SMTP)</option>
          </select>
        </label>

        <template v-if="form.provider_type==='smtp'">
          <label>Serveur SMTP<input v-model="form.smtp_host"></label>
          <label>Port<input v-model.number="form.smtp_port" type="number"></label>
          <label class="check"><input v-model="form.smtp_tls" type="checkbox"> TLS</label>
          <label>Utilisateur<input v-model="form.smtp_user"></label>
          <label>Mot de passe<input v-model="form.smtp_password" type="password" placeholder="Laisser vide pour conserver"></label>
        </template>

        <template v-else-if="form.provider_type==='smtp_oauth2'">
          <small style="margin-top:-8px;color:var(--muted)">
            Microsoft a désactivé l'authentification par mot de passe pour outlook.com/hotmail.fr : il faut
            enregistrer une application dans <a href="https://portal.azure.com" target="_blank" rel="noopener">Azure AD (App registrations)</a>,
            l'autoriser pour les comptes personnels, y ajouter l'URI de redirection
            <code>{{ redirectUri }}</code>, puis renseigner ci-dessous son Client ID (et son secret s'il s'agit d'un client confidentiel).
          </small>
          <label>Serveur SMTP<input v-model="form.smtp_host" placeholder="smtp-mail.outlook.com"></label>
          <label>Port<input v-model.number="form.smtp_port" type="number"></label>
          <label class="check"><input v-model="form.smtp_tls" type="checkbox"> TLS</label>
          <label>Boîte Microsoft (hotmail.fr / outlook.com)<input v-model="form.oauth_mailbox" type="email" placeholder="vous@hotmail.fr"></label>
          <label>Tenant<input v-model="form.oauth_tenant" placeholder="consumers"><small>« consumers » pour un compte personnel hotmail.fr/outlook.com</small></label>
          <label>Client ID<input v-model="form.oauth_client_id"></label>
          <label>Client secret (optionnel)<input v-model="form.oauth_client_secret" type="password" placeholder="Laisser vide pour conserver / si client public"></label>
          <div v-if="editingId" class="check" style="align-items:center;gap:10px">
            <span class="settings-card-status" :class="editingProviderConnected ? 'active' : 'error'">
              {{ editingProviderConnected ? 'Compte Microsoft connecté' : 'Non connecté' }}
            </span>
            <button type="button" class="secondary" @click="connectMicrosoft"><PlugZap/>{{ editingProviderConnected ? 'Reconnecter' : 'Connecter avec Microsoft' }}</button>
            <button v-if="editingProviderConnected" type="button" class="secondary" @click="disconnectMicrosoft">Déconnecter</button>
          </div>
          <small v-else style="color:var(--muted)">Enregistrez d'abord le fournisseur pour pouvoir le connecter à un compte Microsoft.</small>
        </template>

        <template v-else-if="form.provider_type==='brevo'">
          <small style="margin-top:-8px;color:var(--muted)">
            Envoi via l'API <a href="https://developers.brevo.com/docs/getting-started" target="_blank" rel="noopener">Brevo</a>
            (pas de serveur SMTP) : créez une clé API dans Brevo (Paramètres &gt; Clés API), et vérifiez
            l'adresse expéditrice de l'application dans Brevo (Expéditeurs &amp; IP) avant le premier envoi.
          </small>
          <label>Clé API Brevo<input v-model="form.brevo_api_key" type="password" placeholder="Laisser vide pour conserver"></label>
        </template>

        <label class="check"><input v-model="form.enabled" type="checkbox"> Fournisseur actif</label>
    </div>
    <template #actions>
      <button class="primary" :disabled="busy||!form.name" @click="save"><Save/>{{ editingId?'Mettre a jour':'Ajouter' }}</button>
      <button class="secondary" @click="closeModal">Annuler</button>
    </template>
  </ModalShell>
  <ConfirmModal v-bind="confirmDialog" @cancel="resolveConfirm(false)" @confirm="resolveConfirm(true)" />
</template>

<script setup>
import ModalShell from '@/components/ui/ModalShell.vue';
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ChevronDown, ChevronUp, Mail, Pencil, Plus, PlugZap, Power, Save, Trash2 } from '@lucide/vue';
import { api } from '@/api';
import { success, fail } from '@/settingsForm';
import SettingsCard from './SettingsCard.vue';
import ConfirmModal from '../ConfirmModal.vue';
import { useConfirm } from '@/composables/useConfirm';

const busy = ref(false);
const providers = ref([]);
const editingId = ref(null);
const showModal = ref(false);
const defaults = {
  name: '', provider_type: 'smtp', enabled: true,
  smtp_host: '', smtp_port: 587, smtp_tls: true, smtp_user: '', smtp_password: '',
  oauth_tenant: 'consumers', oauth_client_id: '', oauth_client_secret: '', oauth_mailbox: '',
  brevo_api_key: '',
};
const form = reactive({ ...defaults });
const { dialog: confirmDialog, askConfirm, resolveConfirm } = useConfirm();

const redirectUri = `${window.location.origin}/api/email-providers/smtp-oauth/callback`;
const editingProviderConnected = computed(() => {
  const p = providers.value.find(x => x.id === editingId.value);
  return Boolean(p && p.oauth_connected);
});

const typeLabels = { smtp: 'SMTP', smtp_oauth2: 'SMTP OAuth2', brevo: 'Brevo' };
function typeLabel(t) { return typeLabels[t] || t; }

async function load() { providers.value = await api('/api/email-providers'); }
function reset() { editingId.value = null; Object.assign(form, defaults); }
function openModal(provider) {
  reset();
  if (provider) { editingId.value = provider.id; Object.assign(form, defaults, provider); }
  showModal.value = true;
}
function closeModal() { showModal.value = false; reset(); }

async function save() {
  busy.value = true;
  try {
    await api(editingId.value ? `/api/email-providers/${editingId.value}` : '/api/email-providers', {
      method: editingId.value ? 'PUT' : 'POST', body: JSON.stringify(form),
    });
    success(editingId.value ? 'Fournisseur mis a jour.' : 'Fournisseur ajoute.');
    showModal.value = false;
    reset();
    await load();
  } catch (e) { fail(e); } finally { busy.value = false; }
}

async function testProvider(provider) {
  const recipient = prompt('Adresse de test', '');
  if (!recipient) return;
  try {
    const data = await api(`/api/test/email-provider/${provider.id}`, { method: 'POST', body: JSON.stringify({ recipient }) });
    if (data.success) success(data.message); else fail(new Error(data.message));
  } catch (e) { fail(e); }
}

async function toggle(provider) { await api(`/api/email-providers/${provider.id}/toggle`, { method: 'PATCH' }); await load(); }

async function remove(provider) {
  if (!await askConfirm({ title: 'Supprimer ce fournisseur ?', message: `${provider.name} sera supprimé définitivement.`, confirmLabel: 'Supprimer', danger: true })) return;
  await api(`/api/email-providers/${provider.id}`, { method: 'DELETE' });
  await load();
}

async function move(index, delta) {
  const target = index + delta;
  if (target < 0 || target >= providers.value.length) return;
  const order = providers.value.map(p => p.id);
  [order[index], order[target]] = [order[target], order[index]];
  await api('/api/email-providers/reorder', { method: 'POST', body: JSON.stringify({ order }) });
  await load();
}

async function connectMicrosoft() {
  if (!editingId.value) return;
  await save();
  window.location.href = `/api/email-providers/${editingId.value}/smtp-oauth/authorize`;
}

async function disconnectMicrosoft() {
  if (!editingId.value) return;
  try {
    await api(`/api/email-providers/${editingId.value}/smtp-oauth/disconnect`, { method: 'POST' });
    success('Compte Microsoft déconnecté.');
    await load();
  } catch (e) { fail(e); }
}

const route = useRoute();
const router = useRouter();

onMounted(async () => {
  await load();
  const status = route.query.email_oauth;
  if (!status) return;
  if (status === 'success') success('Compte Microsoft connecté.');
  else fail(new Error(route.query.msg || "Échec de la connexion au compte Microsoft."));
  const { email_oauth, msg, ...rest } = route.query;
  router.replace({ path: '/settings', query: rest });
});
</script>
