<template>
  <section class="drawer-section">
    <div class="action-grid compact-actions">
      <button class="secondary" :disabled="busy" @click="$emit('recheck-plex')"><RefreshCw />Verifier dans Plex</button>
      <button class="secondary" :disabled="busy" @click="$emit('open-correction', 'media', null, null)"><MessageSquareWarning />Correction globale</button>
    </div>

    <MediaIssueForm
      v-if="showIssueForm"
      :busy="busy"
      @submit="$emit('report-issue', $event)"
      @cancel="$emit('cancel-issue')"
    />

    <MediaCorrectionForm
      v-if="showCorrectionForm"
      :initial-form="correctionForm"
      :users="users"
      :correction-options="correctionOptions"
      :busy="busy"
      @submit="$emit('submit-correction', $event)"
      @cancel="$emit('cancel-correction')"
    />

    <MediaAudioSection
      :vf-detail="vfDetail"
      :busy="busy"
      :available="Boolean(detail?.in_library)"
      :envelope-error="envelopeError"
      :availability-error="availabilityError"
      :vf-status-error="vfStatusError"
      @scan="$emit('scan-vff')"
      @correction="(...args) => $emit('open-correction', ...args)"
      @expand-season="(n) => $emit('expand-season', n)"
    />

    <article v-for="issue in detail.issues || []" :key="issue.id" class="detail-row" style="margin-top: 1rem;">
      <div><strong>{{ issue.issue_type }}</strong><span>{{ issue.message || 'Sans commentaire' }}</span></div>
      <span class="badge">{{ issue.status }}</span>
    </article>
  </section>
</template>

<script setup>
import { RefreshCw, MessageSquareWarning } from '@lucide/vue';
import MediaIssueForm from './MediaIssueForm.vue';
import MediaCorrectionForm from './MediaCorrectionForm.vue';
import MediaAudioSection from './MediaAudioSection.vue';

defineProps({
  detail: { type: Object, required: true },
  busy: { type: Boolean, default: false },
  showIssueForm: { type: Boolean, default: false },
  showCorrectionForm: { type: Boolean, default: false },
  users: { type: Array, default: () => [] },
  correctionOptions: { type: Array, default: () => [] },
  correctionForm: { type: Object, required: true },
  vfDetail: { type: Object, default: null },
  envelopeError: { type: Boolean, default: false },
  availabilityError: { type: Boolean, default: false },
  vfStatusError: { type: Boolean, default: false },
});
defineEmits([
  'recheck-plex', 'open-correction', 'report-issue', 'cancel-issue',
  'submit-correction', 'cancel-correction', 'scan-vff', 'expand-season',
]);
</script>
