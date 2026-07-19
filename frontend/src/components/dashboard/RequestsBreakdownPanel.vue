<template>
  <section class="panel">
    <div class="panel-head">
      <h2>Repartition des demandes</h2>
    </div>
    <div class="breakdown-grid">
      <div class="breakdown-card movie-card">
        <div class="breakdown-icon"><Film /></div>
        <div class="breakdown-info">
          <strong>{{ counts.by_type?.movie?.total ?? 0 }}</strong>
          <span>Films</span>
        </div>
        <div class="breakdown-sub">
          <span class="bsub-item"><span class="dot green"></span>{{ counts.by_type?.movie?.available ?? 0 }} dispos</span>
          <span class="bsub-item"><span class="dot yellow"></span>{{ counts.by_type?.movie?.sent_to_arr ?? 0 }} en cours</span>
          <span class="bsub-item"><span class="dot red"></span>{{ counts.by_type?.movie?.failed ?? 0 }} echoues</span>
        </div>
      </div>
      <div class="breakdown-card show-card">
        <div class="breakdown-icon"><Tv /></div>
        <div class="breakdown-info">
          <strong>{{ counts.by_type?.show?.total ?? 0 }}</strong>
          <span>Series</span>
        </div>
        <div class="breakdown-sub">
          <span class="bsub-item"><span class="dot green"></span>{{ counts.by_type?.show?.available ?? 0 }} dispos</span>
          <span class="bsub-item"><span class="dot yellow"></span>{{ counts.by_type?.show?.sent_to_arr ?? 0 }} en cours</span>
          <span class="bsub-item"><span class="dot red"></span>{{ counts.by_type?.show?.failed ?? 0 }} echoues</span>
        </div>
      </div>
    </div>
    <div v-if="counts.total" class="type-ratio-bar">
      <div
        class="ratio-segment movie-seg"
        :style="{ width: `${(counts.by_type?.movie?.total ?? 0) / counts.total * 100}%` }"
        :title="`Films : ${counts.by_type?.movie?.total ?? 0}`"
      ></div>
      <div
        class="ratio-segment show-seg"
        :style="{ width: `${(counts.by_type?.show?.total ?? 0) / counts.total * 100}%` }"
        :title="`Series : ${counts.by_type?.show?.total ?? 0}`"
      ></div>
    </div>
  </section>
</template>

<script setup>
import { Film, Tv } from '@lucide/vue';

defineProps({ counts: { type: Object, default: () => ({}) } });
</script>
