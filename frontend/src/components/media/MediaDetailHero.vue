<template>
  <div class="mdh-backdrop" :style="detail.backdrop_url ? { backgroundImage: `url(${detail.backdrop_url})` } : {}">
    <div class="mdh-scrim"></div>
    <div class="mdh-content">
      <button class="mdh-back icon-button" title="Retour" @click="$emit('back')"><ArrowLeft /></button>
      <div class="mdh-row">
        <div class="mdh-poster">
          <img v-if="detail.poster_url" :src="detail.poster_url" alt="">
          <div v-else class="mdh-poster-fallback"><Film /></div>
        </div>
        <div class="mdh-info">
          <span class="eyebrow">{{ typeLabel }}</span>
          <h1>{{ detail.title }}</h1>
          <div class="mdh-badges">
            <span v-if="detail.year" class="badge">{{ detail.year }}</span>
            <span v-if="detail.vote" class="badge"><Star size="14" />{{ detail.vote }}</span>
            <span v-if="statusLabel" class="badge" :class="statusClass">{{ statusLabel }}</span>
            <span v-if="detail.origin_label" class="badge origin-badge">{{ detail.origin_label }}</span>
            <template v-if="detail.vf_granularity === 'partial'">
              <span class="badge warning">VF Partiel</span>
            </template>
            <template v-else-if="detail.vf_granularity === 'vo'">
              <span class="badge">VO</span>
            </template>
            <template v-else-if="detail.has_vf">
              <span class="badge available">VF</span>
            </template>
          </div>
          <p v-if="detail.waiting_reason" class="mdh-waiting">{{ detail.waiting_reason }}</p>
          <p class="mdh-overview">{{ detail.overview || 'Aucun resume disponible.' }}</p>
          <div v-if="detail.genres?.length" class="tag-row">
            <span v-for="genre in detail.genres" :key="genre" class="badge">{{ genre }}</span>
          </div>
          <div class="mdh-links">
            <a v-if="detail.imdb_id" :href="`https://www.imdb.com/title/${detail.imdb_id}`" target="_blank" class="badge mdh-link"><ExternalLink size="14" /> IMDb</a>
            <a v-if="detail.tmdb_id" :href="`https://www.themoviedb.org/${detail.media_type === 'show' ? 'tv' : 'movie'}/${detail.tmdb_id}`" target="_blank" class="badge mdh-link"><ExternalLink size="14" /> TMDB</a>
            <a v-if="detail.plex_guid" :href="`https://app.plex.tv/desktop/#!/provider/tv.plex.provider.discover/details?key=${encodeURIComponent(detail.plex_guid)}`" target="_blank" class="badge available mdh-link"><ExternalLink size="14" /> Plex</a>
            <a v-if="admin && detail.arr_url" :href="detail.arr_url" target="_blank" class="badge available mdh-link"><ExternalLink size="14" /> {{ detail.media_type === 'movie' ? 'Radarr' : 'Sonarr' }}</a>
            <button class="badge danger mdh-link" @click="$emit('report-issue')"><Flag size="14" /> Signaler un probleme</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { ArrowLeft, ExternalLink, Film, Flag, Star } from '@lucide/vue';

const props = defineProps({
  detail: { type: Object, required: true },
  statusLabel: { type: String, default: '' },
  statusClass: { type: String, default: '' },
  admin: { type: Boolean, default: false },
});
defineEmits(['back', 'report-issue']);

const typeLabel = computed(() => (props.detail.media_type === 'show' ? 'Serie' : 'Film'));
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
  gap: 24px;
  align-items: flex-end;
}
.mdh-poster {
  flex: 0 0 180px;
  width: 180px;
  aspect-ratio: 2 / 3;
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 16px 40px rgba(0,0,0,.5);
  background: var(--surface-2);
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
  font-size: 28px;
  line-height: 1.2;
}
.mdh-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}
.mdh-overview {
  max-width: 760px;
  color: var(--text);
  opacity: .9;
  margin-bottom: 10px;
}
.mdh-waiting {
  max-width: 760px;
  margin: 0 0 10px;
  padding: 8px 10px;
  border-left: 3px solid var(--accent);
  border-radius: 4px;
  background: rgba(0, 0, 0, .28);
  color: var(--muted);
  font-size: 13px;
}
.origin-badge {
  border-color: rgba(255, 255, 255, .24);
}
.mdh-links {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}
.mdh-link {
  text-decoration: none;
  color: inherit;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
}

@media (max-width: 720px) {
  .mdh-row { flex-direction: column; align-items: flex-start; }
  .mdh-poster { flex-basis: 130px; width: 130px; }
}
</style>
