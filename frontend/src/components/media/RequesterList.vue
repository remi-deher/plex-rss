<template>
  <div v-if="requesterIds.length > 1" class="requester-breakdown">
    <div v-for="(uid, index) in requesterIds" :key="`${uid}-${index}`" class="requester-line">
      <span class="requester-name">
        {{ row.requesters?.[index] || uid }}
        <span v-if="index === 0" class="badge tiny">Principal</span>
        <span
          v-if="notifiedStatus(row, uid) !== null"
          :class="['notif-dot', notifiedStatus(row, uid) ? 'ok' : 'pending']"
          :title="notifiedStatus(row, uid) ? 'Deja notifie' : 'Pas encore notifie'"
        />
      </span>
      <div v-if="admin" class="requester-menu-wrap">
        <button class="icon-button" title="Actions" aria-label="Actions" @click.stop="toggleMenu(uid)">
          <MoreVertical />
        </button>
        <div v-if="openMenu === uid" class="requester-menu" @click.stop>
          <button :disabled="busy" @click="emitAndClose('notify-user', row.id, uid, ['request'])">
            <Mail /> Renvoyer mail demande
          </button>
          <button v-if="row.status === 'available'" :disabled="busy" @click="emitAndClose('notify-user', row.id, uid, ['available'])">
            <MailCheck /> Renvoyer mail dispo
          </button>
          <button v-if="index !== 0" :disabled="busy" @click="emitAndClose('promote-requester', row, uid)">
            <Crown /> Promouvoir principal
          </button>
          <button class="danger" :disabled="busy" @click="emitAndClose('remove-requester', row, uid)">
            <UserMinus /> Retirer
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
// Liste des co-demandeurs d'une demande, avec leur état de notification et un menu
// d'actions. N'apparaît qu'à partir de deux demandeurs : à un seul, la ligne principale
// de la carte suffit.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { Crown, Mail, MailCheck, MoreVertical, UserMinus } from '@lucide/vue';

import { notifiedStatus } from './requestRules';

const props = defineProps({
  row: { type: Object, required: true },
  admin: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
});
const emit = defineEmits(['notify-user', 'promote-requester', 'remove-requester']);

const requesterIds = computed(() => props.row.requester_ids || []);
const openMenu = ref(null);

function toggleMenu(uid) {
  openMenu.value = openMenu.value === uid ? null : uid;
}
function emitAndClose(event, ...args) {
  emit(event, ...args);
  openMenu.value = null;
}
// Le menu se ferme au clic ailleurs. L'écouteur est posé sur le document parce qu'un clic
// hors du composant doit aussi le fermer.
function handleOutsideClick(event) {
  if (!event.target.closest('.requester-menu-wrap')) openMenu.value = null;
}
onMounted(() => document.addEventListener('click', handleOutsideClick));
onBeforeUnmount(() => document.removeEventListener('click', handleOutsideClick));
</script>
