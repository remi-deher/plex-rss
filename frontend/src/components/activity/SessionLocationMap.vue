<template>
  <section class="session-location">
    <div class="location-head">
      <span><MapPin/><small>Localisation du flux</small><strong>{{ locationLabel }}</strong></span>
      <a v-if="mapLink" :href="mapLink" target="_blank" rel="noopener noreferrer">Ouvrir la carte<ExternalLink/></a>
    </div>
    <iframe
      v-if="embedUrl"
      :src="embedUrl"
      :title="`Carte de ${locationLabel}`"
      loading="lazy"
      referrerpolicy="no-referrer"
    ></iframe>
    <div v-else class="location-placeholder"><MapPinned/><span>{{ placeholder }}</span></div>
    <dl>
      <div><dt>Adresse IP</dt><dd>{{ addressLabel }}</dd></div>
      <div><dt>Ville</dt><dd>{{ session.geo_city || '—' }}</dd></div>
      <div><dt>Région</dt><dd>{{ session.geo_region || '—' }}</dd></div>
      <div><dt>Pays</dt><dd>{{ session.geo_country || session.geo_country_code || '—' }}</dd></div>
    </dl>
  </section>
</template>

<script setup>
import { computed } from 'vue';
import { ExternalLink, MapPin, MapPinned } from '@lucide/vue';

const props = defineProps({ session: { type: Object, required: true } });
const latitude = computed(() => Number(props.session.geo_lat));
const longitude = computed(() => Number(props.session.geo_lon));
const hasCoordinates = computed(() => props.session.geo_lat != null && props.session.geo_lat !== ''
  && props.session.geo_lon != null && props.session.geo_lon !== ''
  && Number.isFinite(latitude.value) && Number.isFinite(longitude.value));
const locationLabel = computed(() => {
  if (props.session.geo_status === 'anonymized') return 'Adresse anonymisée';
  if (props.session.geo_status === 'local') return 'Réseau local';
  return [props.session.geo_city, props.session.geo_region, props.session.geo_country_code || props.session.geo_country]
    .filter(Boolean).join(', ') || 'Localisation inconnue';
});
const addressLabel = computed(() => props.session.address || (props.session.geo_status === 'anonymized' ? 'Adresse masquée' : '—'));
const placeholder = computed(() => props.session.geo_status === 'anonymized'
  ? 'Désactivez l’anonymisation des IP dans les paramètres pour autoriser le lookup.'
  : props.session.geo_status === 'local'
    ? 'Une adresse du réseau local ne peut pas être positionnée sur une carte publique.'
    : 'Coordonnées indisponibles pour cette session.');
const bounds = computed(() => {
  if (!hasCoordinates.value) return '';
  const delta = .12;
  return [longitude.value - delta, latitude.value - delta, longitude.value + delta, latitude.value + delta].join(',');
});
const embedUrl = computed(() => hasCoordinates.value
  ? `https://www.openstreetmap.org/export/embed.html?bbox=${encodeURIComponent(bounds.value)}&layer=mapnik&marker=${latitude.value}%2C${longitude.value}`
  : '');
const mapLink = computed(() => hasCoordinates.value
  ? `https://www.openstreetmap.org/?mlat=${latitude.value}&mlon=${longitude.value}#map=10/${latitude.value}/${longitude.value}`
  : '');
</script>

<style scoped>
.session-location{overflow:hidden;margin-top:22px;border:1px solid var(--border);border-radius:13px;background:var(--surface-2)}
.location-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 14px}.location-head>span{display:grid;grid-template-columns:19px minmax(0,1fr);align-items:center;min-width:0}.location-head svg{grid-row:1/3;width:16px;color:var(--accent)}.location-head small{color:var(--muted);font-size:8px;text-transform:uppercase}.location-head strong{overflow:hidden;font-size:12px;text-overflow:ellipsis;white-space:nowrap}.location-head a{display:flex;align-items:center;gap:5px;color:var(--accent);font-size:10px;text-decoration:none;white-space:nowrap}.location-head a svg{width:12px}
iframe{display:block;width:100%;height:220px;border:0;border-block:1px solid var(--border);filter:saturate(.72) contrast(.95)}
.location-placeholder{display:grid;place-items:center;min-height:130px;padding:24px;border-block:1px solid var(--border);color:var(--muted);text-align:center}.location-placeholder svg{width:28px;margin-bottom:7px}.location-placeholder span{max-width:360px;font-size:10px}
dl{display:grid;grid-template-columns:repeat(4,1fr);margin:0}dl>div{display:grid;gap:3px;padding:10px 12px;border-right:1px solid var(--border)}dl>div:last-child{border:0}dt{color:var(--muted);font-size:8px;text-transform:uppercase}dd{overflow:hidden;margin:0;font-size:10px;text-overflow:ellipsis;white-space:nowrap}
@media(max-width:620px){iframe{height:180px}dl{grid-template-columns:1fr 1fr}dl>div:nth-child(2){border-right:0}dl>div:nth-child(-n+2){border-bottom:1px solid var(--border)}}
</style>
