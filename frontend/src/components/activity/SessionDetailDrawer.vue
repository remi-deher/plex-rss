<template>
  <DrawerShell wide eyebrow="Session Plex" :title="displayTitle(session)" @close="$emit('close')">
    <div class="session-hero">
      <MediaArtwork :src="session.thumb_url" :alt="displayTitle(session)" :type="session.media_type" size="large"/>
      <div>
        <span>{{ session.parent_title || mediaTypeLabel(session.media_type) }}<template v-if="session.year"> · {{ session.year }}</template></span>
        <h3>{{ session.user_name || 'Utilisateur Plex' }}</h3>
        <p>{{ session.player || session.product || session.platform || 'Lecteur Plex' }}</p>
        <PlaybackMethodBadge :method="session.playback_method"/>
      </div>
    </div>

    <div class="session-progress">
      <div><span>Progression</span><strong>{{ Math.round(session.progress || 0) }} %</strong></div>
      <div class="progress-track"><i :style="{width:`${session.progress || 0}%`}"></i></div>
      <small>{{ formatDuration(session.progress_ms || session.watched_ms) }} / {{ formatDuration(session.duration_ms) }}</small>
    </div>

    <section class="session-detail-section">
      <span class="eyebrow">Lecture</span>
      <dl>
        <div><dt>État</dt><dd>{{ stateLabel(session.state) }}</dd></div>
        <div><dt>Qualité</dt><dd>{{ session.quality || 'Automatique' }}</dd></div>
        <div><dt>Vidéo</dt><dd>{{ decisionLabel(session.video_decision) }}<template v-if="session.video_codec"> · {{ session.video_codec.toUpperCase() }}</template></dd></div>
        <div><dt>Audio</dt><dd>{{ decisionLabel(session.audio_decision) }}<template v-if="session.audio_codec"> · {{ session.audio_codec.toUpperCase() }}</template></dd></div>
        <div><dt>Débit</dt><dd>{{ formatBandwidth(session.bandwidth_kbps) }}</dd></div>
        <div><dt>Réseau</dt><dd>{{ session.address || 'Adresse masquée' }}</dd></div>
      </dl>
    </section>

    <section class="session-detail-section">
      <span class="eyebrow">Contexte</span>
      <dl>
        <div><dt>Bibliothèque</dt><dd>{{ session.library || '—' }}</dd></div>
        <div><dt>Plateforme</dt><dd>{{ session.platform || '—' }}</dd></div>
        <div><dt>Lecteur</dt><dd>{{ session.player || session.product || '—' }}</dd></div>
        <div><dt>Début</dt><dd>{{ formatDate(session.started_at) }}</dd></div>
        <div><dt>Dernière activité</dt><dd>{{ formatDate(session.last_seen_at || session.ended_at) }}</dd></div>
        <div><dt>Source</dt><dd>{{ session.source === 'tautulli' ? 'Tautulli' : 'Plex' }}</dd></div>
      </dl>
    </section>
  </DrawerShell>
</template>

<script setup>
import DrawerShell from '@/components/DrawerShell.vue';
import MediaArtwork from './MediaArtwork.vue';
import PlaybackMethodBadge from './PlaybackMethodBadge.vue';
defineProps({ session: { type: Object, required: true } });
defineEmits(['close']);
function displayTitle(item){return item.grandparent_title?`${item.grandparent_title} · ${item.title}`:(item.title||'Session Plex')}
function formatDuration(ms){if(!ms)return '0 min';const minutes=Math.round(ms/60000);return minutes<60?`${minutes} min`:`${Math.floor(minutes/60)} h ${minutes%60} min`}
function formatBandwidth(value){return value?`${(value/1000).toLocaleString('fr-FR',{maximumFractionDigits:1})} Mb/s`:'—'}
function formatDate(value){return value?new Intl.DateTimeFormat('fr-FR',{dateStyle:'medium',timeStyle:'short'}).format(new Date(value)):'—'}
function mediaTypeLabel(value){return {movie:'Film',episode:'Épisode',track:'Musique'}[value]||'Média'}
function stateLabel(value){return {playing:'Lecture',paused:'En pause',buffering:'Mise en mémoire'}[value]||value||'Terminée'}
function decisionLabel(value){return {transcode:'Transcodage',copy:'Copie directe',directplay:'Lecture directe'}[String(value||'').toLowerCase()]||'—'}
</script>

<style scoped>
.session-hero{display:flex;gap:18px;align-items:center;margin:8px 0 20px}.session-hero>div:last-child{display:grid;gap:5px;min-width:0}.session-hero h3{margin:4px 0 0;font-size:18px}.session-hero p,.session-hero span{margin:0;color:var(--muted);font-size:11px}.session-progress{display:grid;gap:8px;padding:14px;border:1px solid var(--border);border-radius:12px;background:var(--surface-2)}.session-progress>div:first-child{display:flex;justify-content:space-between}.session-progress span,.session-progress small{color:var(--muted);font-size:10px}.progress-track{height:6px;overflow:hidden;border-radius:99px;background:rgba(255,255,255,.1)}.progress-track i{display:block;height:100%;border-radius:inherit;background:var(--accent)}.session-detail-section{margin-top:22px}.session-detail-section dl{display:grid;grid-template-columns:1fr 1fr;margin:8px 0 0;border:1px solid var(--border);border-radius:12px}.session-detail-section dl>div{display:grid;gap:4px;padding:12px;border-bottom:1px solid var(--border)}.session-detail-section dl>div:nth-child(odd){border-right:1px solid var(--border)}.session-detail-section dl>div:nth-last-child(-n+2){border-bottom:0}.session-detail-section dt{color:var(--muted);font-size:9px;text-transform:uppercase}.session-detail-section dd{margin:0;font-size:12px}@media(max-width:520px){.session-hero{align-items:flex-start}.session-detail-section dl{grid-template-columns:1fr}.session-detail-section dl>div,.session-detail-section dl>div:nth-child(odd){border-right:0;border-bottom:1px solid var(--border)}.session-detail-section dl>div:last-child{border-bottom:0}}
</style>
