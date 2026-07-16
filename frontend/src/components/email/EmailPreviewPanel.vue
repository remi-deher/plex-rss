<template>
  <section class="panel preview-panel">
    <div class="panel-head"><h2>Apercu</h2><span class="badge">{{ eventLabel }}</span></div>
    <iframe :srcdoc="previewHtml" title="Apercu email" sandbox="allow-same-origin"></iframe>
  </section>
</template>

<script setup>
defineProps({
  previewHtml: { type: String, default: '' },
  eventLabel: { type: String, default: '' },
});
</script>
