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

    <div class="session-kpis">
      <article><span>Temps restant</span><strong>{{ remainingLabel(session) }}</strong><small>{{ estimatedEnd(session) }}</small></article>
      <article><span>Débit du flux</span><strong>{{ formatBandwidth(session.bandwidth_kbps) }}</strong><small>{{ bandwidthHint(session.bandwidth_kbps) }}</small></article>
      <article><span>Dernier signal</span><strong>{{ relativeDate(session.last_seen_at) }}</strong><small>{{ session.state==='paused'?'lecture en pause':'session synchronisée' }}</small></article>
    </div>

    <SessionLocationMap :session="session"/>

    <section class="stream-route">
      <span class="eyebrow">Chemin du flux</span>
      <div>
        <article><Server/><span><small>Source</small><strong>{{ session.quality || 'Auto' }}<template v-if="session.video_codec"> · {{ session.video_codec.toUpperCase() }}</template></strong></span></article>
        <i :class="{warning:session.playback_method==='transcode'}"></i>
        <article><Workflow/><span><small>Traitement</small><strong>{{ methodLabel(session.playback_method) }}</strong></span></article>
        <i></i>
        <article><MonitorPlay/><span><small>Destination</small><strong>{{ session.player || session.platform || 'Plex' }}</strong></span></article>
      </div>
    </section>

    <section class="session-detail-section">
      <span class="eyebrow">Lecture</span>
      <dl>
        <div><dt>État</dt><dd>{{ stateLabel(session.state) }}</dd></div>
        <div><dt>Qualité</dt><dd>{{ session.quality || 'Automatique' }}</dd></div>
        <div><dt>Vidéo</dt><dd>{{ decisionLabel(session.video_decision) }}<template v-if="session.video_codec"> · {{ session.video_codec.toUpperCase() }}</template></dd></div>
        <div><dt>Audio</dt><dd>{{ decisionLabel(session.audio_decision) }}<template v-if="session.audio_codec"> · {{ session.audio_codec.toUpperCase() }}</template></dd></div>
        <div><dt>Débit</dt><dd>{{ formatBandwidth(session.bandwidth_kbps) }}</dd></div>
        <div><dt>Réseau</dt><dd>{{ networkLabel(session) }}</dd></div>
        <div><dt>Durée totale</dt><dd>{{ formatDuration(session.duration_ms) }}</dd></div>
        <div><dt>Temps visionné</dt><dd>{{ formatDuration(session.progress_ms || session.watched_ms) }}</dd></div>
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
        <div><dt>Identifiant</dt><dd class="session-id">{{ session.session_id || '—' }}</dd></div>
      </dl>
    </section>
  </DrawerShell>
</template>

<script setup>
import { formatDurationExact as formatDuration, formatBandwidth, formatDateTime, formatTime } from '@/utils/format';
import { MonitorPlay, Server, Workflow } from '@lucide/vue';
import DrawerShell from '@/components/DrawerShell.vue';
import MediaArtwork from './MediaArtwork.vue';
import PlaybackMethodBadge from './PlaybackMethodBadge.vue';
import SessionLocationMap from './SessionLocationMap.vue';
defineProps({ session: { type: Object, required: true } });
defineEmits(['close']);
function displayTitle(item){return item.grandparent_title?`${item.grandparent_title} · ${item.title}`:(item.title||'Session Plex')}
const formatDate=value=>formatDateTime(value,'—');
function relativeDate(value){if(!value)return '—';const seconds=Math.max(0,Math.floor((Date.now()-new Date(value).getTime())/1000));return seconds<10?'À l’instant':seconds<60?`${seconds} s`:`${Math.floor(seconds/60)} min`}
function remainingLabel(item){const remaining=Math.max(0,(item.duration_ms||0)-(item.progress_ms||item.watched_ms||0));return item.duration_ms?formatDuration(remaining):'Inconnu'}
function estimatedEnd(item){const remaining=Math.max(0,(item.duration_ms||0)-(item.progress_ms||item.watched_ms||0));if(!remaining||item.state==='paused')return item.state==='paused'?'Estimation suspendue':'Fin non estimée';return `Fin vers ${formatTime(Date.now()+remaining)}`}
function bandwidthHint(value){if(!value)return 'débit non communiqué';return value>=20000?'bande passante élevée':value>=8000?'bande passante modérée':'flux léger'}
function mediaTypeLabel(value){return {movie:'Film',episode:'Épisode',track:'Musique'}[value]||'Média'}
function stateLabel(value){return {playing:'Lecture',paused:'En pause',buffering:'Mise en mémoire'}[value]||value||'Terminée'}
function decisionLabel(value){return {transcode:'Transcodage',copy:'Copie directe',directplay:'Lecture directe'}[String(value||'').toLowerCase()]||'—'}
function methodLabel(value){return {transcode:'Transcodage',direct_stream:'Remux direct',direct_play:'Aucune conversion'}[value]||'Lecture Plex'}
function networkLabel(item){const scope=item.location==='lan'?'Local':item.location==='wan'?'Distant':null;const place=[item.geo_city,item.geo_country_code||item.geo_country].filter(Boolean).join(', ');return [scope,place,item.address].filter(Boolean).join(' · ')||'Adresse masquée'}
</script>

<style scoped>
.session-hero{display:flex;gap:18px;align-items:center;margin:8px 0 20px}.session-hero>div:last-child{display:grid;gap:5px;min-width:0}.session-hero h3{margin:4px 0 0;font-size:18px}.session-hero p,.session-hero span{margin:0;color:var(--muted);font-size:11px}.session-progress{display:grid;gap:8px;padding:14px;border:1px solid var(--border);border-radius:12px;background:var(--surface-2)}.session-progress>div:first-child{display:flex;justify-content:space-between}.session-progress span,.session-progress small{color:var(--muted);font-size:10px}.progress-track{height:6px;overflow:hidden;border-radius:99px;background:rgba(255,255,255,.1)}.progress-track i{display:block;height:100%;border-radius:inherit;background:var(--accent)}.session-kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:10px}.session-kpis article{display:grid;gap:3px;padding:11px;border:1px solid var(--border);border-radius:10px;background:var(--surface-2)}.session-kpis span,.session-kpis small{color:var(--muted);font-size:9px}.session-kpis strong{font-size:13px}.stream-route{margin-top:22px}.stream-route>div{display:grid;grid-template-columns:minmax(0,1fr) 28px minmax(0,1fr) 28px minmax(0,1fr);align-items:center;margin-top:8px}.stream-route article{display:flex;align-items:center;gap:8px;min-width:0;padding:10px;border:1px solid var(--border);border-radius:10px;background:var(--surface-2)}.stream-route article>svg{width:17px;color:var(--accent)}.stream-route article span{display:grid;min-width:0}.stream-route small{color:var(--muted);font-size:8px;text-transform:uppercase}.stream-route strong{overflow:hidden;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.stream-route i{height:2px;background:var(--border)}.stream-route i.warning{background:#fb923c}.session-detail-section{margin-top:22px}.session-detail-section dl{display:grid;grid-template-columns:1fr 1fr;margin:8px 0 0;border:1px solid var(--border);border-radius:12px}.session-detail-section dl>div{display:grid;gap:4px;padding:12px;border-bottom:1px solid var(--border)}.session-detail-section dl>div:nth-child(odd){border-right:1px solid var(--border)}.session-detail-section dl>div:nth-last-child(-n+2){border-bottom:0}.session-detail-section dt{color:var(--muted);font-size:9px;text-transform:uppercase}.session-detail-section dd{margin:0;font-size:12px}.session-id{overflow:hidden;color:var(--muted);font-family:monospace;text-overflow:ellipsis;white-space:nowrap}@media(max-width:620px){.session-kpis{grid-template-columns:1fr}.stream-route>div{grid-template-columns:1fr}.stream-route i{width:2px;height:14px;margin:auto}.stream-route article{width:100%}}@media(max-width:520px){.session-hero{align-items:flex-start}.session-detail-section dl{grid-template-columns:1fr}.session-detail-section dl>div,.session-detail-section dl>div:nth-child(odd){border-right:0;border-bottom:1px solid var(--border)}.session-detail-section dl>div:last-child{border-bottom:0}}
</style>
