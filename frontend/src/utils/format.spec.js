import { describe, expect, it } from 'vitest';

import {
  formatBandwidth,
  formatBytes,
  formatDate,
  formatDateShort,
  formatDateTime,
  formatDateTimeSeconds,
  formatDateTimeShort,
  formatDayMonth,
  formatDuration,
  formatDurationExact,
  formatDurationHours,
  formatDurationRoundHours,
  formatElapsed,
  formatFileSize,
  formatInteger,
  formatLongDay,
  formatMonthYear,
  formatNumber,
  formatReleaseDate,
  formatTime,
  signedPercent,
} from './format';

// Date construite en heure locale : le rendu attendu ne dépend donc pas du fuseau de la
// machine de test, seulement de la locale fr-FR.
const MOMENT = new Date(2026, 7, 4, 16, 30, 0);

// fr-FR sépare les milliers par une espace fine insécable (U+202F), pas par une espace
// ordinaire : l'écrire en échappement rend l'attendu lisible et non ambigu.
const NNBSP = ' ';

describe('formatage des dates', () => {
  it('rend chaque variante au format fr-FR attendu', () => {
    expect(formatDateTime(MOMENT)).toBe('4 août 2026, 16:30');
    expect(formatDateTimeShort(MOMENT)).toBe('04/08/2026 16:30');
    expect(formatDateTimeSeconds(MOMENT)).toBe('04/08/2026 16:30:00');
    expect(formatDate(MOMENT)).toBe('4 août 2026');
    expect(formatDateShort(MOMENT)).toBe('04/08/2026');
    expect(formatReleaseDate(MOMENT)).toBe('4 août 2026');
    expect(formatTime(MOMENT)).toBe('16:30');
    expect(formatMonthYear(MOMENT)).toBe('août 2026');
  });

  it('utilise la valeur de repli fournie quand la date est absente', () => {
    for (const empty of [null, undefined, '']) {
      expect(formatDateTime(empty)).toBe('-');
      expect(formatDateTime(empty, '—')).toBe('—');
      expect(formatDateShort(empty, 'Aucune')).toBe('Aucune');
      expect(formatDateTime(empty, 'Non renseignée')).toBe('Non renseignée');
    }
  });

  // Une date nue interprétée par `new Date('2026-08-04')` est lue en UTC et reculerait
  // d'un jour à l'ouest de Greenwich : ces deux fonctions l'ancrent à midi.
  it('ancre les dates nues à midi pour ne pas décaler le jour', () => {
    expect(formatDayMonth('2026-08-04')).toBe('04/08');
    expect(formatLongDay('2026-08-04')).toBe('mardi 4 août');
    expect(formatLongDay('2026-08-04', { day: 'numeric', month: 'short' })).toBe('4 août');
    expect(formatDayMonth('')).toBe('');
    expect(formatLongDay(null)).toBe('');
  });
});

describe('formatage des durées', () => {
  it('omet les minutes nulles', () => {
    expect(formatDuration(0)).toBe('0 min');
    expect(formatDuration(2700000)).toBe('45 min');
    expect(formatDuration(7200000)).toBe('2 h');
    expect(formatDuration(5400000)).toBe('1 h 30 min');
  });

  // Variante volontairement distincte (historique de lectures) : « 2 h 0 min » y est
  // conservé pour aligner les colonnes du tableau.
  it('affiche toujours les minutes en variante exacte', () => {
    expect(formatDurationExact(7200000)).toBe('2 h 0 min');
    expect(formatDurationExact(5400000)).toBe('1 h 30 min');
    expect(formatDurationExact(null)).toBe('0 min');
  });

  it('bascule en heures décimales au-delà d’une heure', () => {
    expect(formatDurationHours(1800000)).toBe('30 min');
    expect(formatDurationHours(12240000)).toBe('3,4 h');
  });

  it('arrondit à l’heure entière pour les volumes cumulés', () => {
    expect(formatDurationRoundHours(4464000000)).toBe(`1${NNBSP}240 h`);
    expect(formatDurationRoundHours(null)).toBe('0 h');
  });

  it('exprime les temps d’exécution en ms puis en s', () => {
    expect(formatElapsed(null)).toBe('-');
    expect(formatElapsed(840)).toBe('840 ms');
    expect(formatElapsed(2400)).toBe('2.4 s');
  });
});

describe('formatage des tailles et des nombres', () => {
  // Deux échelles distinctes : formatBytes part du Go (espace disque des volumes *arr),
  // formatFileSize couvre o -> To (inventaire de fichiers).
  it('distingue l’échelle disque de l’échelle fichier', () => {
    expect(formatBytes(0)).toBe('0 Go');
    expect(formatBytes(5.5 * 1024 ** 3)).toBe('5.5 Go');
    expect(formatBytes(2 * 1024 ** 4)).toBe('2.0 To');
    expect(formatFileSize(0)).toBe('0 o');
    expect(formatFileSize(1024)).toBe('1 Ko');
    expect(formatFileSize(5.5 * 1024 ** 3)).toBe('5,5 Go');
  });

  it('convertit les débits de kb/s en Mb/s', () => {
    expect(formatBandwidth(0)).toBe('—');
    expect(formatBandwidth(12400)).toBe('12,4 Mb/s');
    expect(formatBandwidth(0, '-')).toBe('-');
  });

  it('localise les nombres et les pourcentages signés', () => {
    expect(formatNumber(12.34)).toBe('12,3');
    expect(formatNumber(null)).toBe('0');
    expect(formatInteger(12480)).toBe(`12${NNBSP}480`);
    expect(signedPercent(12.5)).toBe('+12,5 %');
    expect(signedPercent(-3)).toBe('-3 %');
    expect(signedPercent(0)).toBe('0 %');
  });
});
