<template>
  <DrawerShell wide eyebrow="Administration" :title="creating?'Nouvel utilisateur':displayName(editing)" :error="editorError" @close="$emit('close')">
    <nav class="detail-tabs"><button v-for="entry in editorTabs" :key="entry" :class="{active:editorTab===entry}" @click="editorTab=entry">{{ editorLabel(entry) }}</button></nav>

    <section v-if="editorTab==='profile'" class="drawer-section form-section">
      <div class="settings-grid two">
        <label>ID Plex<input v-model="form.plex_user_id" :disabled="!creating"></label>
        <label>Nom affiche<input v-model="form.display_name"></label>
        <label>Nom d'usage<input v-model="form.custom_name"></label>
        <label>Email Plex<input v-model="form.plex_email" type="email"></label>
        <label>Email de notification<input v-model="form.notification_email"></label>
        <label>Role<select v-model="form.role"><option value="user">Utilisateur</option><option value="admin">Administrateur</option></select></label>
        <label class="check"><input v-model="form.enabled" type="checkbox"> Traiter les demandes</label>
        <label class="check"><input v-model="form.can_login" type="checkbox"> Autoriser la connexion</label>
        <label class="check"><input v-model="form.auto_approve" type="checkbox"> Auto-approuver</label>
      </div>
      <div class="actions">
        <button class="primary" :disabled="busy" @click="$emit('save')"><Save/>Enregistrer</button>
        <button v-if="!creating" class="secondary danger" @click="$emit('delete')"><Trash2/>Supprimer</button>
      </div>
    </section>

    <section v-else-if="editorTab==='notifications'" class="drawer-section form-section">
      <div class="settings-grid two">
        <label class="check"><input v-model="form.notify_admin" type="checkbox"> Copier l'administrateur</label>
        <label class="check"><input v-model="form.notify_on_request" type="checkbox"> Nouvelle demande</label>
        <label class="check"><input v-model="form.notify_on_available" type="checkbox"> Disponibilite</label>
        <label class="check"><input v-model="form.notify_digest" type="checkbox"> Digest</label>
        <label class="check"><input v-model="form.notify_vf_movie" type="checkbox"> VF films</label>
        <label class="check"><input v-model="form.notify_vf_series" type="checkbox"> VF series</label>
        <label class="check"><input v-model="form.notify_vf_anime" type="checkbox"> VF animes</label>
        <label>Granularite series<select v-model="form.series_notify_granularity"><option value="minimal">Finale</option><option value="jalons">Jalons</option><option value="tout">Chaque episode</option></select></label>
        <label>Webhook Discord personnel<input v-model="form.discord_webhook_url"></label>
        <label>Chat Telegram personnel<input v-model="form.telegram_chat_id"></label>
      </div>
      <div class="actions">
        <button class="primary" @click="$emit('save')"><Save/>Enregistrer</button>
        <button v-if="!creating" class="secondary" @click="$emit('test-email')"><MailCheck/>Tester l'email</button>
      </div>
    </section>

    <section v-else-if="editorTab==='seer'" class="drawer-section">
      <div class="panel-head"><h3>Liaison Seer</h3><span class="badge">{{ editing.seer_user_id?`Compte #${editing.seer_user_id}`:'Non lie' }}</span></div>
      <div class="actions">
        <button class="secondary" @click="$emit('user-action','seer-automatch')"><Link/>Association automatique</button>
        <button v-if="editing.seer_user_id" class="secondary" @click="$emit('user-action','seer-complete')"><RefreshCw/>Completer les donnees</button>
        <button v-if="editing.seer_user_id" class="secondary danger" @click="$emit('unlink-seer')"><Unlink/>Dissocier</button>
      </div>
      <label>Fusionner cet utilisateur dans
        <select v-model="mergeTarget">
          <option value="">Selectionner...</option>
          <option v-for="user in users.filter(x=>x.id!==editing.id)" :key="user.id" :value="user.id">{{ displayName(user) }}</option>
        </select>
      </label>
      <button class="secondary danger" :disabled="!mergeTarget" @click="$emit('merge',mergeTarget)"><Merge/>Fusionner</button>
    </section>

    <section v-else-if="editorTab==='activity'" class="drawer-section">
      <section class="metric-grid compact-metrics">
        <article v-for="(value,key) in editing.stats||{}" :key="key" class="metric-card"><span>{{ key }}</span><strong>{{ value??'-' }}</strong></article>
      </section>
      <article v-for="row in editing.activity?.recent||[]" :key="row.id" class="detail-row">
        <div><strong>{{ row.title }}</strong><span>{{ row.status }} · {{ row.source }} · {{ formatDate(row.requested_at) }}</span></div>
      </article>
      <p v-if="!editing.activity?.recent?.length" class="empty">Aucune activite recente.</p>
    </section>

    <section v-else class="drawer-section">
      <article v-for="effect in editing.diagnostic?.effects||[]" :key="effect.key" class="detail-row">
        <div><strong>{{ effect.label }}</strong><span>{{ effect.detail }}</span></div>
        <span class="badge" :class="effect.ok?'available':'failed'">{{ effect.ok?'OK':'Attention' }}</span>
      </article>
      <p v-if="!editing.diagnostic" class="empty">Aucun diagnostic disponible.</p>
    </section>
  </DrawerShell>
</template>

<script setup>
import { ref } from 'vue';
import { Link, MailCheck, Merge, RefreshCw, Save, Trash2, Unlink } from '@lucide/vue';
import DrawerShell from '@/components/DrawerShell.vue';

const props = defineProps({
  editing: { type: Object, required: true },
  creating: { type: Boolean, default: false },
  form: { type: Object, required: true },
  users: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
  editorError: { type: String, default: '' },
});
defineEmits(['close', 'save', 'delete', 'test-email', 'user-action', 'unlink-seer', 'merge']);

const editorTabs = ['profile', 'notifications', 'seer', 'activity', 'diagnostic'];
const editorTab = ref('profile');
const mergeTarget = ref('');

function displayName(user) { return user?.custom_name || user?.display_name || user?.plex_user_id || ''; }
function editorLabel(value) { return ({ profile: 'Profil', notifications: 'Notifications', seer: 'Seer', activity: 'Activite', diagnostic: 'Diagnostic' })[value]; }
function formatDate(value) { return value ? new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium' }).format(new Date(value)) : '-'; }

defineExpose({ resetTab: () => { editorTab.value = 'profile'; mergeTarget.value = ''; } });
</script>
