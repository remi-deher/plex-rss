import { computed, onMounted, ref } from 'vue';

import { api } from '@/api';

// La session est identique pour toute la page : App.vue, Bibliothèque et la fiche média
// interrogeaient chacun /api/session, soit trois requêtes pour la même donnée — la fiche
// média la relançant même à chaque changement de route. La promesse est donc mémoïsée au
// niveau du module. Connexion et déconnexion passent par une navigation complète
// (`href="/logout"`), qui jette ce cache : aucun risque de session périmée.
let pending = null;

/** Charge la session (mémoïsée). Renvoie `null` si l'utilisateur n'est pas authentifié. */
export function loadSession() {
  pending ||= api('/api/session').catch(() => null);
  return pending;
}

/** Oublie la session mémoïsée — à appeler après une action qui change les droits. */
export function invalidateSession() {
  pending = null;
}

export function isAdminSession(session) {
  return Boolean(session?.is_owner || session?.role === 'admin');
}

export function isModeratorSession(session) {
  return session?.role === 'moderator';
}

/** Peut modérer le contenu (demandes, conflits, corrections VF) — admin ou modérateur.
 * Ne donne pas accès à la configuration système (Settings/Utilisateurs/*arr), qui reste
 * gardée par isAdminSession strict. */
export function canModerateSession(session) {
  return isAdminSession(session) || isModeratorSession(session);
}

/**
 * Session courante, chargée au montage.
 * @returns {{session: import('vue').Ref, isAdmin: import('vue').ComputedRef<boolean>, ready: import('vue').Ref<boolean>}}
 */
export function useSession() {
  const session = ref(null);
  const ready = ref(false);
  const isAdmin = computed(() => isAdminSession(session.value));
  const canModerate = computed(() => canModerateSession(session.value));

  onMounted(async () => {
    session.value = await loadSession();
    ready.value = true;
  });

  return { session, isAdmin, canModerate, ready };
}
