import { computed, ref } from 'vue';

import { api } from '@/api';

/**
 * Accordéon saisons/épisodes d'une série, chargé progressivement (façon Seerr).
 *
 * Trois sources indépendantes alimentent la vue et se complètent au fil de l'eau :
 *   1. l'enveloppe TMDB (titres, numéros, nombre de saisons) — rapide, affiche l'accordéon ;
 *   2. la disponibilité Sonarr (`has_file`, `air_date_utc`) ;
 *   3. le statut VF/VO en base.
 * Aucune n'attend les autres : une panne Sonarr n'empêche jamais l'enveloppe ou le statut
 * VF de s'afficher, elle reste localisée et visible.
 *
 * Les épisodes d'une saison ne sont demandés à TMDB qu'au dépliement de cette saison,
 * jamais toutes les saisons d'un coup au chargement de la fiche.
 *
 * Cette logique vivait dans le `<script setup>` de MediaDetailView, dont elle était la
 * partie la plus dense — et la seule non testable en l'état.
 *
 * @param {() => ({source: string, id: number|string, mediaType: string} | null)} resolveTarget
 *   Renvoie la source (`library` | `requests`), l'identifiant et le type du média courant,
 *   ou null si la fiche n'est pas encore chargée.
 */
export function useSeasonEpisodes(resolveTarget) {
  const envelope = ref(null);
  const availability = ref(null);
  const vfStatus = ref(null);
  // Films : ancien flux de scan Plex des pistes audio, distinct du chemin séries.
  const movieVfDetail = ref(null);

  const envelopeError = ref(false);
  const availabilityError = ref(false);
  const vfStatusError = ref(false);

  const seasonEpisodes = ref({});
  const seasonLoading = ref({});
  const seasonErrors = ref({});

  const isShow = () => resolveTarget()?.mediaType === 'show';
  const basePath = () => {
    const target = resolveTarget();
    return target ? `/api/${target.source}/${target.id}` : null;
  };

  function reset() {
    envelope.value = null;
    availability.value = null;
    vfStatus.value = null;
    movieVfDetail.value = null;
    envelopeError.value = false;
    availabilityError.value = false;
    vfStatusError.value = false;
    seasonEpisodes.value = {};
    seasonLoading.value = {};
    seasonErrors.value = {};
  }

  /** Films uniquement : scan Plex des pistes audio. */
  async function loadMovieVf() {
    movieVfDetail.value = await api(`${basePath()}/vf-detail`);
  }

  async function loadEnvelope() {
    if (!isShow()) return;
    envelopeError.value = false;
    try {
      envelope.value = await api(`${basePath()}/episodes`);
    } catch {
      envelopeError.value = true;
    }
  }

  /**
   * Disponibilité Sonarr. Erreur capturée ici volontairement, sans propagation : chaque
   * source est indépendante. Par défaut lecture en base (alimentée en arrière-plan) ;
   * `force` resynchronise Sonarr immédiatement au lieu d'attendre le cycle planifié.
   */
  async function loadAvailability(force = false) {
    if (!isShow()) return;
    availabilityError.value = false;
    try {
      availability.value = await api(`${basePath()}/episodes-availability${force ? '?force=true' : ''}`);
    } catch {
      availabilityError.value = true;
    }
  }

  async function loadVfStatus() {
    if (!isShow()) return;
    vfStatusError.value = false;
    try {
      vfStatus.value = await api(`${basePath()}/episodes-vf-status`);
    } catch {
      vfStatusError.value = true;
    }
  }

  /** Déplie une saison : ses épisodes ne sont demandés à TMDB qu'à ce moment-là. */
  async function loadSeason(seasonNumber) {
    if (seasonEpisodes.value[seasonNumber] || seasonLoading.value[seasonNumber]) return;
    seasonLoading.value = { ...seasonLoading.value, [seasonNumber]: true };
    seasonErrors.value = { ...seasonErrors.value, [seasonNumber]: false };
    try {
      const data = await api(`${basePath()}/episodes/${seasonNumber}`);
      seasonEpisodes.value = { ...seasonEpisodes.value, [seasonNumber]: data.episodes };
    } catch {
      seasonErrors.value = { ...seasonErrors.value, [seasonNumber]: true };
    } finally {
      seasonLoading.value = { ...seasonLoading.value, [seasonNumber]: false };
    }
  }

  /** Relance un scan VF et rafraîchit ce qui en dépend. */
  async function rescan() {
    await api(`${basePath()}/vff-scan`, { method: 'POST' });
    if (isShow()) await Promise.all([loadAvailability(true), loadVfStatus()]);
    else await loadMovieVf();
  }

  /** Charge en parallèle les trois sources d'une série. */
  function loadAll() {
    return Promise.all([loadEnvelope(), loadAvailability(), loadVfStatus()]);
  }

  function episodeStatus(episode, availabilityInfo, knownVfStatus) {
    if (knownVfStatus) return knownVfStatus;
    const hasFile = availabilityInfo?.has_file;
    if (hasFile === undefined) return 'unknown';
    if (hasFile) return 'present';
    // Sonarr (air_date_utc) fait foi car précis à l'heure près ; TMDB (air_date, date
    // seule) sert de repli quand Sonarr n'a pas répondu.
    const airDate = availabilityInfo?.air_date_utc || episode.air_date;
    const hasAired = !airDate || new Date(airDate) <= new Date();
    return hasAired ? 'absent' : 'tba';
  }

  /**
   * Fusion réactive des trois sources : chaque champ se met à jour dès que son fetch
   * résout, sans attendre les deux autres.
   */
  const detail = computed(() => {
    if (!isShow()) return movieVfDetail.value;
    if (!envelope.value) return null;

    const availBySeason = Object.fromEntries((availability.value?.seasons || []).map(s => [s.season_number, s.episodes]));
    const vfBySeason = Object.fromEntries((vfStatus.value?.seasons || []).map(s => [s.season_number, s.episodes]));

    const seasons = envelope.value.seasons.map((season) => {
      const episodes = seasonEpisodes.value[season.season_number];
      if (!episodes) {
        // Saison pas encore dépliée : ni compteurs ni épisodes tant que TMDB n'a pas été
        // interrogé pour CETTE saison précise.
        return {
          season_number: season.season_number,
          name: season.name,
          episode_count: season.episode_count,
          loaded: false,
          loading: !!seasonLoading.value[season.season_number],
          error: !!seasonErrors.value[season.season_number],
          counts: {},
          episodes: [],
        };
      }

      const availEps = availBySeason[season.season_number] || {};
      const vfEps = vfBySeason[season.season_number] || {};
      const counts = { vf: 0, vf_secondary: 0, vo: 0, present: 0, absent: 0, tba: 0, unknown: 0 };
      const merged = episodes.map((episode) => {
        const availInfo = availEps[episode.episode_number];
        const status = episodeStatus(episode, availInfo, vfEps[episode.episode_number]);
        counts[status] = (counts[status] || 0) + 1;
        return {
          episode: episode.episode_number,
          title: episode.title,
          air_date: availInfo?.air_date_utc || episode.air_date,
          status,
          has_file: availInfo?.has_file,
          overview: episode.overview,
          still_url: episode.still_url,
        };
      });
      return { season_number: season.season_number, name: season.name, loaded: true, counts, episodes: merged };
    });

    return { enabled: true, media_type: 'show', vf_available: true, seasons };
  });

  return {
    detail,
    envelopeError,
    availabilityError,
    vfStatusError,
    reset,
    loadAll,
    loadMovieVf,
    loadSeason,
    rescan,
  };
}
