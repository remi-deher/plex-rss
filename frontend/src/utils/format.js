// Formatage fr-FR partagé par toute l'app.
//
// Avant ce module, `formatDate` était redéfini dans 21 fichiers, avec quatre valeurs de
// repli différentes pour une date absente ('-', '—', 'Aucune', 'Non renseignée') et trois
// formats de durée incompatibles. Chaque fonction ci-dessous reproduit **exactement** la
// sortie de la version qu'elle remplace : les variantes qui subsistent (tiret vs cadratin,
// `formatDuration` vs `formatDurationExact`) sont des différences d'affichage réelles,
// pas des doublons — les harmoniser est une décision produit, pas une refactorisation.

const LOCALE = 'fr-FR';

const dateTimeFormatter = (options) => new Intl.DateTimeFormat(LOCALE, options);

// ---------------------------------------------------------------------------
// Dates
// ---------------------------------------------------------------------------

/** Date + heure, format long (« 4 août 2026 à 14:30 »). Le plus courant dans l'app. */
export function formatDateTime(value, empty = '-') {
  return value ? dateTimeFormatter({ dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : empty;
}

/** Date + heure, format compact (« 04/08/2026 14:30 ») — tableaux et journaux. */
export function formatDateTimeShort(value, empty = '-') {
  return value ? dateTimeFormatter({ dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) : empty;
}

/** Date + heure à la seconde — suivi d'exécution des tâches planifiées. */
export function formatDateTimeSeconds(value, empty = '-') {
  return value ? dateTimeFormatter({ dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value)) : empty;
}

/** Date seule, format long (« 4 août 2026 »). */
export function formatDate(value, empty = '-') {
  return value ? dateTimeFormatter({ dateStyle: 'medium' }).format(new Date(value)) : empty;
}

/** Date seule, format compact (« 04/08/2026 »). */
export function formatDateShort(value, empty = '-') {
  return value ? dateTimeFormatter({ dateStyle: 'short' }).format(new Date(value)) : empty;
}

// Les dates « nues » (YYYY-MM-DD, sans heure) sont ancrées à midi : `new Date('2026-08-04')`
// est interprété en UTC et recule d'un jour dans les fuseaux à l'ouest de Greenwich.
const atNoon = (day) => new Date(`${day}T12:00:00`);

/** Jour/mois d'une date nue (« 04/08 ») — axes de graphiques. */
export function formatDayMonth(value, empty = '') {
  return value ? dateTimeFormatter({ day: '2-digit', month: '2-digit' }).format(atNoon(value)) : empty;
}

/** Date nue en clair (« mardi 4 août ») — infobulles et en-têtes de calendrier. */
export function formatLongDay(value, options = { weekday: 'long', day: 'numeric', month: 'long' }) {
  return value ? dateTimeFormatter(options).format(atNoon(value)) : '';
}

/** Date en clair sans jour de semaine (« 4 août 2026 ») — sorties à venir. */
export function formatReleaseDate(value, empty = '-') {
  return value ? dateTimeFormatter({ day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(value)) : empty;
}

/** Heure seule (« 14:30 »). */
export function formatTime(value, empty = '-') {
  return value ? dateTimeFormatter({ hour: '2-digit', minute: '2-digit' }).format(new Date(value)) : empty;
}

/** Mois et année (« août 2026 ») — en-tête du calendrier. */
export function formatMonthYear(value) {
  return value ? dateTimeFormatter({ month: 'long', year: 'numeric' }).format(new Date(value)) : '';
}

// ---------------------------------------------------------------------------
// Durées
// ---------------------------------------------------------------------------

/** Durée en minutes puis heures, sans « 0 min » superflu (« 45 min », « 2 h », « 2 h 5 min »). */
export function formatDuration(ms) {
  const minutes = Math.round((ms || 0) / 60000);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `${hours} h${rest ? ` ${rest} min` : ''}`;
}

/** Idem, mais les minutes sont toujours affichées (« 2 h 0 min ») — historique de lectures. */
export function formatDurationExact(ms) {
  const minutes = Math.round((ms || 0) / 60000);
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

/** Durée exprimée en heures décimales (« 3,4 h ») — classements par temps cumulé. */
export function formatDurationHours(ms) {
  const hours = (ms || 0) / 3600000;
  return hours < 1 ? `${Math.round(hours * 60)} min` : `${formatNumber(hours)} h`;
}

/** Durée arrondie à l'heure entière (« 1 240 h ») — volumes cumulés des insights. */
export function formatDurationRoundHours(ms) {
  return `${formatInteger(Math.round((ms || 0) / 3600000))} h`;
}

/** Durée technique courte (« 840 ms », « 2.4 s ») — temps d'exécution d'une tâche. */
export function formatElapsed(ms, empty = '-') {
  if (ms == null) return empty;
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

// ---------------------------------------------------------------------------
// Tailles, débits, nombres
// ---------------------------------------------------------------------------

/** Taille en Go/To (« 42.5 Go », « 1.3 To »). */
export function formatBytes(bytes) {
  if (!bytes) return '0 Go';
  const gigabytes = bytes / (1024 * 1024 * 1024);
  return gigabytes > 1024 ? `${(gigabytes / 1024).toFixed(1)} To` : `${gigabytes.toFixed(1)} Go`;
}

/** Taille sur l'échelle complète (« 512 Ko », « 4,2 Go ») — inventaire des fichiers.
 *  Distinct de `formatBytes`, qui part du Go (espace disque des volumes *arr). */
export function formatFileSize(bytes) {
  if (!bytes) return '0 o';
  const units = ['o', 'Ko', 'Mo', 'Go', 'To'];
  const exponent = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${formatNumber(bytes / 1024 ** exponent)} ${units[exponent]}`;
}

/** Débit converti de kb/s en Mb/s (« 12,4 Mb/s »). */
export function formatBandwidth(kbps, empty = '—') {
  return kbps ? `${formatNumber(kbps / 1000)} Mb/s` : empty;
}

/** Nombre localisé, au plus une décimale. */
export function formatNumber(value) {
  return Number(value || 0).toLocaleString(LOCALE, { maximumFractionDigits: 1 });
}

/** Nombre localisé avec séparateur de milliers, sans arrondi imposé (« 12 480 »). */
export function formatInteger(value) {
  return Number(value || 0).toLocaleString(LOCALE);
}

/** Pourcentage signé (« +12,5 % », « -3 % ») — comparaisons de période. */
export function signedPercent(value) {
  const number = Number(value || 0);
  return `${number > 0 ? '+' : ''}${formatNumber(number)} %`;
}
