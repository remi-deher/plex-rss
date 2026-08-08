import {
  Clock, DatabaseZap, Download, Link, ListRestart,
  Plug, ScrollText, ServerCog, Tv,
} from '@lucide/vue';

/**
 * Source unique des sections de la page Paramètres — consommée par le flyout
 * sidebar (AdminNavigation.vue) et par la recherche de section
 * (SettingsView.vue). Chaque entrée navigue vers `/settings?tab=<key>` sauf
 * si `to` est fourni (route indépendante, ex. Journaux, qui n'est pas un
 * onglet de SettingsView).
 *
 * Les sections notifications (Canaux/Règles/Modèles) ne sont volontairement
 * pas ici : elles restent des onglets de SettingsView, mais leur navigation
 * passe par le flyout Notifications (voir notificationSections.js).
 */
export const settingsSections = [
  { key: 'overview', label: 'Vue d’ensemble', mobileLabel: 'Aperçu', group: '', icon: ServerCog },

  { key: 'plex', label: 'Plex & Bibliothèque', mobileLabel: 'Plex', group: 'Services', icon: Tv },
  { key: 'services', label: 'Intégrations', mobileLabel: 'Intégrations', group: 'Services', icon: Plug },
  { key: 'webhooks', label: 'Webhooks & API', mobileLabel: 'Webhooks', group: 'Services', icon: Link },

  { key: 'downloads', label: 'Téléchargements', mobileLabel: 'Downloads', group: 'Bibliothèque & acquisition', icon: Download },
  { key: 'scheduled-tasks', label: 'Planification & Maintenance', mobileLabel: 'Planning', group: 'Bibliothèque & acquisition', icon: Clock },

  { key: 'acquisitions', label: 'Acquisitions & Conflits', mobileLabel: 'Acquisitions', group: 'Exploitation', icon: ListRestart },
  { key: 'logs', label: 'Journaux', mobileLabel: 'Journaux', group: 'Exploitation', icon: ScrollText, to: '/logs' },

  { key: 'data', label: 'Données & RGPD', mobileLabel: 'Données', group: 'Système', icon: DatabaseZap },
];
