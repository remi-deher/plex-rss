<template>
  <div class="mdh-backdrop" :style="detail.backdrop_url ? { backgroundImage: `url(${detail.backdrop_url})` } : {}">
    <div class="mdh-scrim"></div>
    <div class="mdh-content">
      <button class="mdh-back icon-button" title="Retour" aria-label="Retour" @click="$emit('back')"><ArrowLeft /></button>
      <div class="mdh-row" :class="{ 'is-music': isMusic }">
        <div class="mdh-poster" :class="{ 'is-music': isMusic }">
          <img v-if="detail.poster_url" :src="detail.poster_url" alt="" decoding="async">
          <div v-else class="mdh-poster-fallback">
            <Music2 v-if="isMusic" />
            <Film v-else />
          </div>
        </div>
        <div class="mdh-info">
          <span class="eyebrow">{{ typeLabel }}</span>
          <h1>{{ detail.title }}</h1>
          <div class="mdh-badges">
            <span v-if="isMusic" class="badge music-badge">{{ detail.media_type === 'artist' ? '🎤 Artiste' : '💿 Album' }}</span>
            <span v-if="detail.year" class="badge">{{ detail.year }}</span>
            <span v-if="detail.vote" class="badge"><Star size="14" />{{ detail.vote }}</span>
            <span v-if="statusLabel && !isMusic" class="badge" :class="statusClass">{{ statusLabel }}</span>
            <span v-if="detail.origin_label && !isMusic" class="badge origin-badge">{{ detail.origin_label }}</span>
            <template v-if="!isMusic">
              <template v-if="detail.vf_granularity === 'partial'">
                <span class="badge warning">VF Partiel</span>
              </template>
              <template v-else-if="detail.vf_granularity === 'vo'">
                <span class="badge mdh-language-vo">VO</span>
              </template>
              <template v-else-if="detail.has_vf">
                <span class="badge available mdh-language-vf">VF</span>
              </template>
            </template>
          </div>
          <p v-if="detail.waiting_reason && !isMusic" class="mdh-waiting">{{ detail.waiting_reason }}</p>
          <dl v-if="releaseDates.length && !isMusic" class="mdh-dates">
            <div v-for="entry in releaseDates" :key="entry.label">
              <dt>{{ entry.label }}</dt>
              <dd>{{ entry.value }}</dd>
            </div>
          </dl>
          <div class="mdh-overview-wrapper">
            <p class="mdh-overview" :class="{ clamped: !showFullOverview && isOverviewLong }">
              {{ overviewText }}
            </p>
            <button
              v-if="isOverviewLong"
              type="button"
              class="overview-toggle-btn"
              @click="showFullOverview = !showFullOverview"
            >
              {{ showFullOverview ? 'Voir moins' : 'Plus...' }}
            </button>
          </div>
          <div v-if="detail.genres?.length" class="tag-row">
            <span v-for="genre in detail.genres" :key="genre" class="badge">{{ genre }}</span>
          </div>
          <div class="mdh-links">
            <button v-if="plexWebUrl" type="button" class="primary-button mdh-listen-btn" @click="openPlexLink(detail?.plex_guid)">
              <Headphones size="16" /> Écouter sur Plex
            </button>
            <a v-if="detail.imdb_id && !isMusic" :href="`https://www.imdb.com/title/${detail.imdb_id}`" target="_blank" class="badge mdh-link"><ExternalLink size="14" /> IMDb</a>
            <a v-if="detail.tmdb_id && !isMusic" :href="`https://www.themoviedb.org/${detail.media_type === 'show' ? 'tv' : 'movie'}/${detail.tmdb_id}`" target="_blank" class="badge mdh-link"><ExternalLink size="14" /> TMDB</a>
            <a v-if="admin && detail.arr_url && !isMusic" :href="detail.arr_url" target="_blank" class="badge available mdh-link"><ExternalLink size="14" /> {{ detail.media_type === 'movie' ? 'Radarr' : 'Sonarr' }}</a>
            <button v-if="!isMusic" class="badge danger mdh-link" @click="$emit('report-issue')"><Flag size="14" /> Signaler un problème</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { mediaTypeLabel } from '@/utils/labels';
import { computed, ref } from 'vue';
import { ArrowLeft, ExternalLink, Film, Flag, Headphones, Music2, Star } from '@lucide/vue';
import { formatPlexWebUrl, openPlexLink } from '@/mediaUrl';

const props = defineProps({
  detail: { type: Object, required: true },
  statusLabel: { type: String, default: '' },
  statusClass: { type: String, default: '' },
  admin: { type: Boolean, default: false },
});

const isMusic = computed(() => props.detail?.media_type === 'artist' || props.detail?.media_type === 'album');
const plexWebUrl = computed(() => formatPlexWebUrl(props.detail?.plex_guid));
defineEmits(['back', 'report-issue']);

const showFullOverview = ref(false);
const overviewText = computed(() => props.detail.overview || (isMusic.value ? 'Aucune biographie disponible pour cet artiste.' : 'Aucun résumé disponible.'));
const isOverviewLong = computed(() => overviewText.value.length > 260);

const typeLabel = computed(() => mediaTypeLabel(props.detail.media_type));

function formatDate(value) {
  if (!value) return '';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' });
}

const releaseDates = computed(() => {
  const d = props.detail;
  if (d.media_type === 'movie') {
    const dates = d.release_dates || {};
    return [
      { key: 'cinema', label: 'Cinéma', value: formatDate(dates.cinema) },
      { key: 'plateforme', label: 'Plateforme', value: formatDate(dates.plateforme) },
      { key: 'dvd_bluray', label: 'DVD / Blu-ray', value: formatDate(dates.dvd_bluray) },
    ].filter(entry => entry.value);
  }
  if (d.media_type === 'show') {
    const nextEpisode = d.next_episode_to_air?.air_date;
    return [
      { key: 'next_episode', label: 'Prochain épisode', value: formatDate(nextEpisode) },
      { key: 'first_air', label: 'Première diffusion', value: formatDate(d.first_air_date) },
      { key: 'season_air', label: 'Saison en cours depuis', value: formatDate(d.current_season_air_date) },
    ].filter(entry => entry.value);
  }
  return [];
});
</script>

<style scoped>
.mdh-backdrop {
  position: relative;
  background-size: cover;
  background-position: center top;
  background-color: var(--surface-2);
  margin: -28px -28px 24px -28px;
  padding-top: 24px;
}
.mdh-scrim {
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(10,10,10,.55) 0%, rgba(10,10,10,.85) 70%, var(--bg, #0d0d0d) 100%);
}
.mdh-content {
  position: relative;
  padding: 12px 28px 28px;
  max-width: 1280px;
  margin: 0 auto;
}
.mdh-back {
  margin-bottom: 16px;
}
.mdh-row {
  display: flex;
  gap: var(--space-5);
  align-items: flex-end;
}
.mdh-row.is-music {
  align-items: flex-start;
}
.mdh-poster {
  flex: 0 0 180px;
  width: 180px;
  aspect-ratio: 2 / 3;
  border-radius: var(--radius-md);
  overflow: hidden;
  box-shadow: 0 16px 40px rgba(0,0,0,.5);
  background: var(--surface-2);
}
.mdh-poster.is-music {
  flex: 0 0 220px;
  width: 220px;
  height: 220px;
  aspect-ratio: 1 / 1;
  border-radius: var(--radius-lg, 12px);
  box-shadow: 0 16px 40px rgba(0,0,0,.6);
}
.mdh-poster img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.mdh-poster-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
}
.mdh-info {
  flex: 1;
  min-width: 0;
  padding-bottom: 4px;
}
.mdh-info h1 {
  margin: 4px 0 10px;
  font-size: var(--fs-3xl);
  line-height: 1.2;
}
.mdh-badges {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: 12px;
}
.mdh-badges > .badge {
  min-height: 28px;
  padding: 3px 10px;
  border-color: rgba(255, 255, 255, .22);
  background: #27272a;
  color: #fff;
  font-size: var(--fs-sm);
  font-weight: 800;
  line-height: 1.25;
  text-shadow: 0 1px 1px rgba(0, 0, 0, .55);
}
.music-badge {
  border-color: #a855f7 !important;
  background: #7e22ce !important;
  color: #fff !important;
}
.mdh-badges > .badge.available,
.mdh-badges > .mdh-language-vf {
  border-color: #22c55e;
  background: #166534;
  color: #fff;
}
.mdh-badges > .mdh-language-vo {
  border-color: #ef4444;
  background: #991b1b;
  color: #fff;
}
.mdh-overview-wrapper {
  max-width: 800px;
  margin-bottom: 12px;
}
.mdh-overview {
  color: var(--text);
  opacity: .92;
  font-size: var(--fs-sm);
  line-height: 1.6;
  margin: 0;
}
.mdh-overview.clamped {
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.overview-toggle-btn {
  background: transparent;
  border: 0;
  color: var(--accent);
  font-size: var(--fs-xs);
  font-weight: 700;
  cursor: pointer;
  padding: 4px 0 0 0;
  display: inline-flex;
  align-items: center;
}
.overview-toggle-btn:hover {
  text-decoration: underline;
}
.mdh-dates {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-5);
  max-width: 760px;
  margin: 0 0 10px;
}
.mdh-dates > div {
  display: grid;
  gap: 2px;
}
.mdh-dates dt {
  color: var(--muted);
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: .02em;
}
.mdh-dates dd {
  margin: 0;
  color: var(--text);
  font-size: var(--fs-sm);
  font-weight: 650;
}
.mdh-waiting {
  max-width: 760px;
  margin: 0 0 10px;
  padding: 8px 10px;
  border-left: 3px solid var(--accent);
  border-radius: var(--radius-xs);
  background: rgba(0, 0, 0, .28);
  color: var(--muted);
  font-size: var(--fs-sm);
}
.origin-badge {
  border-color: rgba(255, 255, 255, .24);
}
.mdh-links {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin-top: 14px;
}
.mdh-link {
  text-decoration: none;
  color: inherit;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  border: none;
}

.mdh-listen-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 18px;
  border-radius: var(--radius-md);
  background: var(--accent);
  color: #fff;
  font-weight: 700;
  font-size: var(--fs-sm);
  border: 0;
  cursor: pointer;
  transition: transform 0.2s ease, background-color 0.2s ease;
}
.mdh-listen-btn:hover {
  transform: translateY(-1px);
  background: var(--accent-hover, #e05206);
}

@media (max-width: 720px) {
  .mdh-backdrop {
    margin: -16px -16px 16px -16px;
  }
  .mdh-content {
    padding: 8px 16px 20px;
  }
  .mdh-row {
    flex-direction: column;
    align-items: center;
    text-align: center;
  }
  .mdh-poster {
    flex-basis: auto;
    width: 160px;
    margin-bottom: 12px;
  }
  .mdh-poster.is-music {
    width: 180px;
    height: 180px;
  }
  .mdh-badges,
  .mdh-links,
  .tag-row,
  .mdh-dates {
    justify-content: center;
  }
}
</style>
