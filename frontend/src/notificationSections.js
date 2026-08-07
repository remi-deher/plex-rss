import { Bell, FileCode2, History, Inbox, ListChecks } from '@lucide/vue';

/**
 * Source unique des sections du contexte Notifications — utilisée à la fois
 * sur /notifications (Journal, File d'attente) et dans les onglets Paramètres
 * qui configurent les notifications (Canaux, Règles, Modèles). Contrairement
 * à settingsSections.js, ce contexte a sa propre barre de navigation
 * (NotificationsSubnav) affichée à la place de la barre Paramètres quand on
 * est dans cet espace.
 */
export const notificationSections = [
  { key: 'history', label: 'Journal', group: 'Notifications', icon: History, to: '/notifications?tab=history' },
  { key: 'pending', label: 'File d’attente', group: 'Notifications', icon: Inbox, to: '/notifications?tab=pending' },
  { key: 'notifications-channels', label: 'Canaux', group: 'Notifications', icon: Bell, to: { path: '/settings', query: { tab: 'notifications-channels' } } },
  { key: 'notifications-rules', label: 'Règles', group: 'Notifications', icon: ListChecks, to: { path: '/settings', query: { tab: 'notifications-rules' } } },
  { key: 'templates', label: 'Modèles d’emails', group: 'Notifications', icon: FileCode2, to: { path: '/settings', query: { tab: 'templates' } } },
];
