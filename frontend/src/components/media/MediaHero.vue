<template>
  <div class="detail-hero">
    <div v-if="detail.poster_url" class="detail-hero-bg" :style="{ backgroundImage: `url(${detail.poster_url})` }"></div>
    <img v-if="detail.poster_url" :src="detail.poster_url" alt="" style="position: relative; z-index: 1;" />
    <div class="detail-copy" style="position: relative; z-index: 1;">
      <div class="inline-row compact" style="flex-wrap: wrap;">
        <span v-if="detail.year" class="badge">{{ detail.year }}</span>
        <span v-if="detail.vote" class="badge"><Star />{{ detail.vote }}</span>
        <span v-if="statusLabel" class="badge" :class="statusClass">{{ statusLabel }}</span>
        <span v-if="detail.requests && detail.requests.length > 0" class="badge" title="Demandeur principal">
          <User size="14" style="margin-right: 4px;" /> {{ detail.requests[0].requested_by || detail.requests[0].plex_user || 'Utilisateur' }}
        </span>
        <template v-if="detail.vf_granularity === 'partial'">
            <span class="badge warning" title="VF Incomplète">VF Partiel</span>
        </template>
        <template v-else-if="detail.vf_granularity === 'vo'">
            <span class="badge" title="Présent en VO">VO</span>
        </template>
        <template v-else-if="detail.has_vf">
            <span class="badge available" title="Présent en VF">VF</span>
        </template>
      </div>
      <p>{{ detail.overview || 'Aucun resume disponible.' }}</p>
      <div v-if="detail.genres?.length" class="tag-row">
        <span v-for="genre in detail.genres" :key="genre" class="badge">{{ genre }}</span>
      </div>
      <div class="inline-row compact" style="margin-top: 0.5rem; flex-wrap: wrap; gap: 6px;">
          <a v-if="detail.imdb_id" :href="`https://www.imdb.com/title/${detail.imdb_id}`" target="_blank" class="badge" style="text-decoration: none; color: inherit; cursor: pointer; display: inline-flex; align-items: center;"><ExternalLink size="14" style="margin-right: 4px;" /> IMDb</a>
          <a v-if="detail.tmdb_id && detail.media_type === 'movie'" :href="`https://www.themoviedb.org/movie/${detail.tmdb_id}`" target="_blank" class="badge" style="text-decoration: none; color: inherit; cursor: pointer; display: inline-flex; align-items: center;"><ExternalLink size="14" style="margin-right: 4px;" /> TMDB</a>
          <a v-if="detail.tmdb_id && detail.media_type === 'show'" :href="`https://www.themoviedb.org/tv/${detail.tmdb_id}`" target="_blank" class="badge" style="text-decoration: none; color: inherit; cursor: pointer; display: inline-flex; align-items: center;"><ExternalLink size="14" style="margin-right: 4px;" /> TMDB</a>
          <a v-if="detail.plex_guid" :href="`https://app.plex.tv/desktop/#!/provider/tv.plex.provider.discover/details?key=${encodeURIComponent(detail.plex_guid)}`" target="_blank" class="badge available" style="text-decoration: none; cursor: pointer; display: inline-flex; align-items: center;"><ExternalLink size="14" style="margin-right: 4px;" /> Plex</a>
          <a v-if="admin && detail.arr_url" :href="detail.arr_url" target="_blank" class="badge available" style="text-decoration: none; cursor: pointer; display: inline-flex; align-items: center;"><ExternalLink size="14" style="margin-right: 4px;" /> {{ detail.media_type === 'movie' ? 'Radarr' : 'Sonarr' }}</a>
          <button class="badge danger" @click="$emit('report-issue')" style="cursor: pointer; border: none; display: inline-flex; align-items: center;"><Flag size="14" style="margin-right: 4px;" /> Signaler un problème</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Star, User, ExternalLink, Flag } from "@lucide/vue";

defineProps({
  detail: { type: Object, required: true },
  statusLabel: { type: String, default: '' },
  statusClass: { type: String, default: '' },
  admin: { type: Boolean, default: false }
});

defineEmits(['report-issue']);
</script>
