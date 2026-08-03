<template>
  <section class="panel live-panel">
    <div class="panel-head">
      <div>
        <span class="eyebrow"><i :class="{ idle: !playingCount }"></i>En direct</span>
        <h2>Lectures Plex</h2>
        <p v-if="sessions.length" class="live-summary">{{ summary }}</p>
      </div>
      <!-- `.panel-link` : meme pastille fantome que les autres panneaux du tableau de bord
           (« Tout voir », « Voir le calendrier »...). Ce lien etait le seul rendu en texte
           nu, sans etat au survol ni la cible tactile de 44 px que components.css garantit
           aux `.panel-link` sur ecran tactile. -->
      <RouterLink v-if="showLink" :to="{path:'/activity',query:{view:'live'}}" class="panel-link">Voir l’activité</RouterLink>
    </div>

    <div v-if="sessions.length" class="live-list">
      <article
        v-for="session in sessions"
        :key="session.session_id"
        class="live-session"
        :class="{ interactive, paused: isPaused(session) }"
        :tabindex="interactive?0:undefined"
        :role="interactive?'button':undefined"
        @click="select(session)"
        @keydown.enter="select(session)"
        @keydown.space.prevent="select(session)"
      >
        <div v-if="session.thumb_url" class="live-backdrop" :style="{backgroundImage:`url(${session.thumb_url})`}" aria-hidden="true"></div>
        <div class="live-card-body">
        <div class="live-art">
          <MediaArtwork :src="session.thumb_url" :alt="displayTitle(session)" :type="session.media_type" size="medium"/>
          <span v-if="stateIcon(session)" class="live-state" :title="stateLabel(session)">
            <component :is="stateIcon(session)" />
          </span>
        </div>

        <div class="live-main">
          <div class="live-user">
            <span class="live-avatar">{{ initials(session.user_name) }}</span>
            <span>{{ session.user_name || 'Utilisateur Plex' }}</span>
            <component :is="deviceIcon(session)" class="live-device" :aria-label="session.player || session.platform || 'Lecteur Plex'" />
          </div>
          <div class="live-title">
            <strong>{{ displayTitle(session) }}</strong>
            <span>{{ mediaSubtitle(session) }}</span>
          </div>
          <div class="live-client">
            <span><component :is="deviceIcon(session)"/>{{ deviceLabel(session) }}</span>
            <span><Network/>{{ addressLabel(session) }}</span>
          </div>
          <div class="progress-track"><i :class="{ paused: isPaused(session) }" :style="{width:`${percent(session)}%`}"></i></div>
          <div class="live-progress-label"><small>{{ percent(session) }} %</small><small>{{ formatRemaining(session) }}</small></div>
        </div>
        </div>

        <footer class="live-footer">
          <span class="live-location" :title="session.address || geoLabel(session)"><MapPin/>{{ geoLabel(session) }}</span>
          <span v-if="session.quality || locationLabel(session)" class="live-quality">
            {{ session.quality || 'Auto' }}<template v-if="locationLabel(session)"> · {{ locationLabel(session) }}</template>
          </span>
          <PlaybackMethodBadge :method="session.playback_method" :title="decisionDetail(session)" />
          <span v-if="session.bandwidth_kbps" class="live-bandwidth">{{ formatBandwidth(session.bandwidth_kbps) }}</span>
        </footer>
      </article>
    </div>
    <div v-else-if="!collectionEnabled" class="live-disabled" role="status">
      <PowerOff/>
      <div>
        <strong>Collecte en direct désactivée</strong>
        <span>Aucune lecture Plex ne peut apparaître tant que ce réglage est désactivé.</span>
      </div>
      <RouterLink :to="{path:'/settings',query:{tab:'connections'}}" class="secondary">Activer la collecte</RouterLink>
    </div>
    <p v-else class="empty">Aucune lecture en cours.</p>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { Loader, MapPin, Monitor, Network, Pause, PowerOff, Smartphone, Tablet, Tv } from '@lucide/vue';
import MediaArtwork from './MediaArtwork.vue';
import PlaybackMethodBadge from './PlaybackMethodBadge.vue';
import { usePolling } from '@/composables/usePolling';
import { formatBandwidth } from '@/utils/format';

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  showLink: { type: Boolean, default: true },
  interactive: { type: Boolean, default: false },
  collectionEnabled: { type: Boolean, default: true },
});
const emit = defineEmits(['select']);

// Interpolation locale de la progression.
//
// `progress_ms` ne change qu'a l'arrivee de nouvelles donnees (evenement SSE
// `activity.updated`, publie par l'ecouteur websocket Plex et par la collecte periodique).
// Entre deux, la barre restait figee : une lecture en cours donnait exactement la meme
// image qu'une lecture a l'arret. On avance donc l'affichage a la seconde, en repartant de
// la derniere valeur connue des que le serveur en envoie une nouvelle -- l'estimation ne
// derive pas, elle est corrigee a chaque rafraichissement.
const receivedAt = ref(Date.now());
const now = ref(Date.now());
watch(() => props.sessions, () => { receivedAt.value = Date.now(); now.value = Date.now(); });
usePolling(() => { now.value = Date.now(); }, 1000);

function isPaused(session) {
  return ['paused', 'buffering'].includes(String(session.state || '').toLowerCase());
}

function elapsedMs(session) {
  const base = session.progress_ms || 0;
  // Une lecture en pause ou en mise en memoire tampon n'avance pas.
  if (String(session.state || 'playing').toLowerCase() !== 'playing') return base;
  const projected = base + (now.value - receivedAt.value);
  return session.duration_ms ? Math.min(projected, session.duration_ms) : projected;
}

function percent(session) {
  if (session.duration_ms) return Math.min(100, Math.round((elapsedMs(session) / session.duration_ms) * 100));
  return Math.min(100, Math.round(session.progress || 0));
}

const playingCount = computed(() => props.sessions.filter(session => !isPaused(session)).length);

/** Synthese d'en-tete : l'essentiel du panneau lisible sans parcourir les lignes. */
const summary = computed(() => {
  const total = props.sessions.length;
  const parts = [`${total} lecture${total > 1 ? 's' : ''}`];
  const paused = total - playingCount.value;
  if (paused) parts.push(`${paused} en pause`);
  const bandwidth = props.sessions.reduce((sum, session) => sum + (session.bandwidth_kbps || 0), 0);
  if (bandwidth) parts.push(formatBandwidth(bandwidth));
  const transcodes = props.sessions.filter(session => session.playback_method === 'transcode').length;
  if (transcodes) parts.push(`${transcodes} transcodage${transcodes > 1 ? 's' : ''}`);
  return parts.join(' · ');
});

const STATE_ICONS = { paused: Pause, buffering: Loader };
const STATE_LABELS = { paused: 'En pause', buffering: 'Mise en mémoire tampon' };

function stateIcon(session) {
  return STATE_ICONS[String(session.state || '').toLowerCase()] || null;
}

function stateLabel(session) {
  return STATE_LABELS[String(session.state || '').toLowerCase()] || 'En lecture';
}

/** `lan` / `wan` cote Plex : un flux distant est le cas couteux, il merite d'etre visible. */
function locationLabel(session) {
  const value = String(session.location || '').toLowerCase();
  if (value === 'lan') return 'Local';
  if (value === 'wan') return 'Distant';
  return '';
}

/** Detail du transcodage : le badge dit *que* ca transcode, ceci dit *pourquoi*. */
const DECISION_LABELS = { transcode: 'transcodée', copy: 'copiée', directplay: 'directe' };
function decisionDetail(session) {
  const parts = [];
  if (session.video_decision) parts.push(`Vidéo ${DECISION_LABELS[session.video_decision] || session.video_decision}`);
  if (session.audio_decision) parts.push(`Audio ${DECISION_LABELS[session.audio_decision] || session.audio_decision}`);
  if (session.subtitle_decision) {
    parts.push(`Sous-titres ${DECISION_LABELS[session.subtitle_decision] || session.subtitle_decision}`);
  }
  return parts.join(' · ');
}

function mediaSubtitle(session) {
  return [session.parent_title, session.year].filter(Boolean).join(' · ') || 'Lecture Plex';
}

function deviceLabel(session) {
  return session.player || session.product || session.platform || 'Appareil inconnu';
}

function addressLabel(session) {
  return session.address || 'IP indisponible';
}

function initials(name) {
  return String(name || '?').split(/\s+/).slice(0, 2).map(part => part[0]).join('').toUpperCase();
}

function deviceIcon(session) {
  const value = [session.platform, session.player, session.product].filter(Boolean).join(' ').toLowerCase();
  if (/iphone|android|mobile/.test(value)) return Smartphone;
  if (/ipad|tablet/.test(value)) return Tablet;
  if (/tv|roku|shield|chromecast|firestick/.test(value)) return Tv;
  return Monitor;
}

function geoLabel(session) {
  if (session.geo_status === 'anonymized') return 'IP anonymisée';
  if (session.geo_status === 'local') return 'local';
  const location = [session.geo_city, session.geo_region, session.geo_country_code || session.geo_country]
    .filter(Boolean).join(', ');
  return location || session.address || 'Localisation inconnue';
}

function displayTitle(item) {
  return item.grandparent_title ? `${item.grandparent_title} · ${item.title}` : item.title;
}

function select(session) {
  if (props.interactive) emit('select', session);
}

function formatRemaining(session) {
  if (isPaused(session)) return stateLabel(session);
  if (!session.duration_ms) return 'Durée inconnue';
  const remaining = Math.max(0, session.duration_ms - elapsedMs(session));
  const minutes = Math.ceil(remaining / 60000);
  if (minutes < 1) return 'bientôt terminé';
  return minutes < 60
    ? `${minutes} min restantes`
    : `${Math.floor(minutes / 60)} h ${minutes % 60} min restantes`;
}
</script>

<style scoped>
.live-panel{grid-column:1/-1}
.live-disabled{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:14px;align-items:center;margin-top:14px;padding:16px;border:1px solid color-mix(in srgb,var(--accent) 35%,var(--border));border-radius:12px;background:color-mix(in srgb,var(--accent) 7%,var(--surface-2))}.live-disabled>svg{width:22px;height:22px;color:var(--accent)}.live-disabled>div{display:grid;gap:4px}.live-disabled strong{font-size:14px}.live-disabled span{color:color-mix(in srgb,var(--text) 72%,transparent);font-size:12px;line-height:1.45}.live-disabled .secondary{white-space:nowrap}
.eyebrow{display:flex;align-items:center;gap:6px}
.eyebrow i{width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 4px rgba(34,197,94,.12)}
.eyebrow i.idle{background:var(--muted);box-shadow:0 0 0 4px rgba(148,163,184,.1)}
.live-summary{margin:4px 0 0;color:color-mix(in srgb,var(--text) 70%,transparent);font-size:12px;line-height:1.45}
.live-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px;margin-top:14px}
.live-session{position:relative;overflow:hidden;border:1px solid var(--border);border-radius:14px;background:var(--surface-2);box-shadow:0 10px 30px rgba(0,0,0,.15)}
.live-session.paused .live-card-body{opacity:.76}
.live-session.interactive{cursor:pointer;transition:border-color .15s,transform .15s}
.live-session.interactive:hover,.live-session.interactive:focus-visible{border-color:color-mix(in srgb,var(--accent) 55%,var(--border));transform:translateY(-2px);outline:none}
.live-backdrop{position:absolute;inset:-20px;background-position:center;background-size:cover;opacity:.11;filter:blur(24px);transform:scale(1.15);pointer-events:none}
.live-card-body{position:relative;display:grid;grid-template-columns:54px minmax(0,1fr);gap:14px;padding:14px}

.live-art{position:relative;display:flex}
/* Pastille d'etat sur la vignette : une lecture en pause etait jusqu'ici indiscernable
   d'une lecture en cours. */
.live-state{position:absolute;right:-5px;bottom:-5px;display:grid;place-items:center;width:21px;height:21px;border-radius:50%;background:rgba(10,10,10,.94);color:#fff;box-shadow:0 1px 6px rgba(0,0,0,.6)}
.live-state svg{width:10px;height:10px}

.live-main{display:flex;flex-direction:column;min-width:0}
.live-user{display:flex;align-items:center;gap:8px;min-width:0;color:color-mix(in srgb,var(--text) 76%,transparent);font-size:12px;font-weight:600}
.live-user>span:nth-child(2){overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.live-avatar{display:grid;flex:none;place-items:center;width:24px;height:24px;border:2px solid color-mix(in srgb,var(--surface) 80%,transparent);border-radius:50%;background:color-mix(in srgb,var(--accent) 18%,var(--surface));color:var(--accent);font-size:8px;font-weight:850}
.live-device{width:15px;height:15px;margin-left:auto;color:var(--muted)}
.live-title{display:grid;min-width:0;margin:10px 0 8px}
.live-title strong,.live-title span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.live-title strong{font-size:15px;line-height:1.35}.live-title span{margin-top:3px;color:color-mix(in srgb,var(--text) 68%,transparent);font-size:11px}
.live-client{display:flex;flex-wrap:wrap;gap:7px 14px;margin-bottom:11px}.live-client span{display:flex;align-items:center;gap:6px;min-width:0;color:color-mix(in srgb,var(--text) 76%,transparent);font-size:11px;line-height:1.3}.live-client svg{flex:none;width:14px;height:14px;color:var(--accent)}
.progress-track{height:5px;overflow:hidden;border-radius:99px;background:rgba(255,255,255,.1)}
.progress-track i{display:block;height:100%;background:var(--accent);transition:width 1s linear}
.progress-track i.paused{background:var(--muted);transition:none}
.live-progress-label{display:flex;justify-content:space-between;margin-top:6px;color:color-mix(in srgb,var(--text) 70%,transparent);font-size:11px}

.live-footer{position:relative;display:grid;grid-template-columns:minmax(0,1fr) auto auto auto;gap:8px;align-items:center;padding:9px 14px;border-top:1px solid var(--border);background:color-mix(in srgb,var(--surface) 70%,transparent)}
.live-location{display:flex;align-items:center;gap:5px;min-width:0;overflow:hidden;color:color-mix(in srgb,var(--text) 72%,transparent);font-size:11px;text-overflow:ellipsis;white-space:nowrap}.live-location svg{flex:none;width:13px;height:13px;color:var(--accent)}
.live-quality,.live-bandwidth{color:color-mix(in srgb,var(--text) 70%,transparent);font-size:11px;white-space:nowrap}
.live-bandwidth{font-variant-numeric:tabular-nums}

@media(max-width:560px){
  .live-disabled{grid-template-columns:auto minmax(0,1fr);align-items:start}.live-disabled .secondary{grid-column:1/-1;width:100%;min-height:44px}
  .live-list{grid-template-columns:1fr}
  .live-footer{grid-template-columns:minmax(0,1fr) auto auto}.live-quality{display:none}
}
</style>
