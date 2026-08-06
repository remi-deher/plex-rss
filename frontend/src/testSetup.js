// jsdom ne fournit pas IntersectionObserver : stub minimal pour les composants qui
// l'utilisent (ex. InfiniteScrollTrigger.vue), sans quoi leur montage lève une
// ReferenceError qui fait planter les tests qui les incluent indirectement (DiscoverView...).
if (typeof globalThis.IntersectionObserver === "undefined") {
  globalThis.IntersectionObserver = class IntersectionObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
