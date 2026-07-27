import { api } from '@/api';

import { useAsyncAction } from './useAsyncAction';

/**
 * Mutations d'une demande de média : approbation, refus, relance, clôture, notifications,
 * gestion des co-demandeurs, suppression.
 *
 * Ces onze fonctions vivaient dans le `<script setup>` de MediaDetailView, chacune avec sa
 * propre copie du bloc `busy = true / try / catch / finally`, et étaient rebranchées une par
 * une en treize `@events` vers MediaRequestsTab. Les regrouper ici les met à côté du
 * composant qui les déclenche et supprime le prop-drilling.
 *
 * @param {{
 *   detail: import('vue').Ref,
 *   newRequesterId: import('vue').Ref<string>,
 *   askConfirm: (options: object) => Promise<boolean>,
 *   reload: () => Promise<any>,
 *   busy: import('vue').Ref<boolean>,
 *   error: import('vue').Ref<string>,
 *   onDeleted?: () => void,
 * }} context
 */
export function useRequestActions({ detail, newRequesterId, askConfirm, reload, busy, error, onDeleted }) {
  const { run } = useAsyncAction({ askConfirm, onDone: reload, busy, error });

  const post = (path, body) => api(path, {
    method: 'POST',
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const putRequesters = (requestId, ids) => api(`/api/requests/${requestId}/requesters`, {
    method: 'PUT',
    body: JSON.stringify({ requester_ids: ids }),
  });

  /** Approuve ou relance une demande (`action` = 'approve' | 'retry'). */
  const requestAction = (id, action) => run(() => post(`/api/requests/${id}/${action}`));

  async function rejectRequest(row) {
    const reason = prompt('Motif du refus', 'Demande refusee par un administrateur');
    if (reason === null) return;
    await run(() => post(`/api/requests/${row.id}/reject`, { reason }));
  }

  /**
   * Clôture une demande. Deux questions distinctes : notifier la disponibilité, et — si le
   * média n'est pas déjà en VF — arrêter la surveillance VO → VF.
   */
  async function closeRequest(row) {
    const notify = await askConfirm({
      title: 'Notifier la disponibilité ?',
      message: 'Un email de disponibilité sera envoyé au demandeur.',
      confirmLabel: 'Notifier',
    });
    let stopVfTracking = false;
    if (row.has_vf !== true) {
      stopVfTracking = await askConfirm({
        title: 'Arrêter la surveillance VO → VF ?',
        message: 'La demande ne sera plus vérifiée pour une amélioration en VF.',
        confirmLabel: 'Arrêter la surveillance',
        danger: true,
      });
    }
    await run(() => post(
      `/api/requests/${row.id}/mark-processed?event=available&notify=${notify}&stop_vf_tracking=${stopVfTracking}`,
    ));
  }

  const resendMail = (id, event) => run(() => post(`/api/requests/${id}/resend-mail?event=${event}`));

  const notifyUser = (requestId, plexUserId, events) => run(
    () => post(`/api/requests/${requestId}/notify-user`, { plex_user_id: plexUserId, events }),
  );

  /**
   * Ajoute un co-demandeur à toutes les lignes de demande du média, puis propose de lui
   * renvoyer les emails déjà partis — sans quoi il ne saurait pas que le média a été
   * demandé, ni qu'il est disponible.
   */
  async function addRequester() {
    const newUserId = newRequesterId.value;
    const rows = detail.value?.requests || [];
    const alreadyInProgress = rows.filter(row => row.request_mail_sent || row.status === 'available');

    const { ok } = await run(async () => {
      for (const row of rows) {
        const ids = [...(row.requester_ids || [row.plex_user_id])];
        if (!ids.includes(newUserId)) ids.push(newUserId);
        await putRequesters(row.id, ids);
      }
    });
    if (!ok) return;
    newRequesterId.value = '';

    if (!alreadyInProgress.length) return;
    const catchUp = await askConfirm({
      title: 'Renvoyer les notifications précédentes ?',
      message: 'Le nouveau co-demandeur recevra également les emails déjà envoyés pour cette demande.',
      confirmLabel: 'Renvoyer les notifications',
    });
    if (!catchUp) return;
    for (const row of alreadyInProgress) {
      const events = [];
      if (row.request_mail_sent) events.push('request');
      if (row.status === 'available') events.push('available');
      if (events.length) await notifyUser(row.id, newUserId, events);
    }
  }

  /** Notifie les co-demandeurs qui ne l'ont pas encore été pour l'état courant. */
  const catchUpAll = (row) => run(async () => {
    for (const uid of row.requester_ids || []) {
      const notified = row.requester_notifications?.[uid];
      const wanted = row.status === 'available' ? notified?.available : notified?.request;
      // `false` = explicitement pas encore notifié ; `undefined` = rien à rattraper.
      if (wanted !== false) continue;
      await post(`/api/requests/${row.id}/notify-user`, {
        plex_user_id: uid,
        events: row.status === 'available' ? ['available'] : ['request'],
      });
    }
  });

  /** Fait passer un co-demandeur en demandeur principal (premier de la liste). */
  const promoteRequester = (row, uid) => run(
    () => putRequesters(row.id, [uid, ...(row.requester_ids || []).filter(id => id !== uid)]),
  );

  const removeRequester = (row, uid) => run(
    () => putRequesters(row.id, (row.requester_ids || []).filter(id => id !== uid)),
    {
      confirm: {
        title: 'Retirer ce demandeur ?',
        message: 'Il ne recevra plus les notifications de cette demande.',
        confirmLabel: 'Retirer',
        danger: true,
      },
    },
  );

  /** Supprime la demande ; la fiche n'a plus d'objet, d'où `onDeleted` (retour à la liste). */
  async function deleteRequest(id) {
    const { ok } = await run(() => api(`/api/requests/${id}`, { method: 'DELETE' }), {
      reload: false,
      confirm: {
        title: 'Supprimer cette demande ?',
        message: 'La demande sera supprimée définitivement.',
        confirmLabel: 'Supprimer',
        danger: true,
      },
    });
    if (ok) onDeleted?.();
  }

  return {
    requestAction,
    rejectRequest,
    closeRequest,
    resendMail,
    notifyUser,
    addRequester,
    catchUpAll,
    promoteRequester,
    removeRequester,
    deleteRequest,
  };
}
