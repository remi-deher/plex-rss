<template>
  <section class="panel preview-panel">
    <div class="panel-head"><h2>Apercu</h2><div class="actions"><span class="badge">{{ deviceLabel }}</span><span class="badge">{{ eventLabel }}</span></div></div>
    <div class="preview-viewport" :class="`device-${deviceMode}`">
      <iframe :srcdoc="previewHtml" title="Apercu email" sandbox="allow-same-origin"></iframe>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue';
const props=defineProps({
  previewHtml: { type: String, default: '' },
  eventLabel: { type: String, default: '' },
  deviceMode: { type: String, default: 'desktop' },
});
const deviceLabel=computed(()=>({desktop:'Ordinateur',tablet:'Tablette',phone:'Telephone'})[props.deviceMode]||'Ordinateur');
</script>

<style scoped>
.preview-viewport{display:flex;justify-content:center;overflow:auto;margin-top:12px;padding:10px;background:var(--surface-2);border:1px solid var(--border);border-radius:7px}.preview-viewport iframe{display:block;margin:0;width:100%;max-width:100%;transition:width .2s ease}.preview-viewport.device-tablet iframe{width:768px}.preview-viewport.device-phone iframe{width:375px}
</style>
