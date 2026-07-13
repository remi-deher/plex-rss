import { onMounted, onUnmounted } from "vue";

const TYPES = ["request.updated", "download.updated", "health.updated", "job.updated", "notification.updated"];
let source;

export function connectRealtime() {
  if (source || typeof EventSource === "undefined") return source;
  source = new EventSource("/api/events");
  for (const type of TYPES) {
    source.addEventListener(type, (message) => {
      let detail = {};
      try { detail = JSON.parse(message.data); } catch { /* Ignore malformed events. */ }
      window.dispatchEvent(new CustomEvent(`plexarr:${type}`, { detail }));
    });
  }
  return source;
}

export function useRealtime(types, callback) {
  const listeners = types.map((type) => [`plexarr:${type}`, (event) => callback(type, event.detail)]);
  onMounted(() => {
    connectRealtime();
    listeners.forEach(([name, listener]) => window.addEventListener(name, listener));
  });
  onUnmounted(() => listeners.forEach(([name, listener]) => window.removeEventListener(name, listener)));
}
