import {
  BookMarked, Clock, DatabaseZap, Download, Link, ListRestart,
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
  { key: 'overview', label: 'Vue d’ensemble', group: '', icon: ServerCog },

  { key: 'plex', label: 'Plex', group: 'Services', icon: Tv },
  { key: 'services', label: 'Services', group: 'Services', icon: Plug },
  { key: 'webhooks', label: 'Webhooks & API', group: 'Services', icon: Link },

  { key: 'library', label: 'Bibliothèque & VF', group: 'Bibliothèque & acquisition', icon: BookMarked },
  { key: 'downloads', label: 'Téléchargements', group: 'Bibliothèque & acquisition', icon: Download },
  { key: 'scheduled-tasks', label: 'Planification & Maintenance', group: 'Bibliothèque & acquisition', icon: Clock },

  { key: 'acquisitions', label: 'Acquisitions & Conflits', group: 'Exploitation', icon: ListRestart },
  { key: 'logs', label: 'Journaux', group: 'Exploitation', icon: ScrollText, to: '/logs' },

  { key: 'data', label: 'Données & RGPD', group: 'Système', icon: DatabaseZap },
];
