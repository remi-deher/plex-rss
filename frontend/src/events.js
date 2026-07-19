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

// Un onglet mis en veille (laptop en veille, onglet en arriere-plan longtemps) peut
// perdre sa connexion SSE sans que le navigateur la rouvre proprement (readyState
// coince a CLOSED, ou le timer JS est throttle en arriere-plan et ne relance jamais).
// Resultat concret : la page reste figee sur les donnees d'avant la mise en veille
// jusqu'a un F5 manuel, meme si le backend a deja tout traite entre-temps. On force
// donc une reconnexion + un refetch immediat des vues montees des que l'onglet
// redevient visible, plutot que de compter uniquement sur le flux SSE.
const visibilityCallbacks = new Set();
let visibilityListenerInstalled = false;

function ensureVisibilityListener() {
  if (visibilityListenerInstalled || typeof document === "undefined") return;
  visibilityListenerInstalled = true;
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    if (source && source.readyState === EventSource.CLOSED) {
      source = undefined;
      connectRealtime();
    }
    visibilityCallbacks.forEach((callback) => callback());
  });
}

export function useRealtime(types, callback) {
  const listeners = types.map((type) => [`plexarr:${type}`, (event) => callback(type, event.detail)]);
  const onVisible = () => callback();
  onMounted(() => {
    connectRealtime();
    ensureVisibilityListener();
    listeners.forEach(([name, listener]) => window.addEventListener(name, listener));
    visibilityCallbacks.add(onVisible);
  });
  onUnmounted(() => {
    listeners.forEach(([name, listener]) => window.removeEventListener(name, listener));
    visibilityCallbacks.delete(onVisible);
  });
}
