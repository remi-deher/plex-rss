<template>
  <Teleport to="body">
    <div class="toast-stack" role="status" aria-live="polite" aria-atomic="false" aria-label="Notifications">
      <TransitionGroup name="toast">
        <article v-for="toast in toasts" :key="toast.id" class="app-toast" :class="toast.type">
          <div class="toast-icon"><img v-if="toast.image" :src="toast.image" alt=""><Play v-else-if="toast.type==='playback'"/><Info v-else/></div>
          <div><strong>{{ toast.title }}</strong><p>{{ toast.message }}</p></div>
          <button type="button" aria-label="Fermer la notification" @click="$emit('dismiss',toast.id)"><X/></button>
        </article>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup>
import { Info, Play, X } from '@lucide/vue';
defineProps({toasts:{type:Array,default:()=>[]}});
defineEmits(['dismiss']);
</script>

<style scoped>
.toast-stack{position:fixed;z-index:1200;right:max(18px,var(--safe-right));bottom:max(18px,var(--safe-bottom));display:grid;gap: var(--space-3);width:min(380px,calc(100vw - 28px));pointer-events:none}.app-toast{display:grid;grid-template-columns:38px minmax(0,1fr) 44px;gap: var(--space-3);align-items:center;padding:12px;border:1px solid color-mix(in srgb,var(--accent) 28%,var(--border));border-radius:var(--radius-md);background:color-mix(in srgb,var(--surface) 94%,black);box-shadow:0 18px 50px rgba(0,0,0,.42);pointer-events:auto}.toast-icon{display:grid;place-items:center;width:38px;height:38px;overflow:hidden;border-radius:var(--radius-sm);background:rgba(229,160,13,.14);color:var(--accent)}.toast-icon img{width:100%;height:100%;object-fit:cover}.toast-icon svg{width:17px}.app-toast div:nth-child(2){display:grid;gap: var(--space-1);min-width:0}.app-toast strong{font-size:var(--fs-sm)}.app-toast p{overflow:hidden;margin:0;color:var(--muted);font-size:var(--fs-xs);line-height:1.4;text-overflow:ellipsis;white-space:nowrap}.app-toast button{display:grid;place-items:center;width:44px;height:44px;border:0;border-radius:var(--radius-sm);background:transparent;color:var(--muted)}.app-toast button:hover{background:rgba(255,255,255,.06);color:var(--text)}.app-toast button svg{width:16px}.toast-enter-active,.toast-leave-active{transition:opacity .2s,transform .2s}.toast-enter-from,.toast-leave-to{opacity:0;transform:translateX(22px)}@media(max-width:600px){.toast-stack{right:max(14px,var(--safe-right));bottom:calc(82px + var(--safe-bottom))}.app-toast{padding:10px}}
</style>
