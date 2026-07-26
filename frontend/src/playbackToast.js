export function playbackTitle(item = {}) {
  return item.grandparent_title
    ? `${item.grandparent_title} · ${item.title || 'Lecture Plex'}`
    : (item.title || 'Lecture Plex');
}

export function playbackStartsFromEvent(event) {
  const started = event?.detail?.payload?.started;
  return Array.isArray(started) ? started : [];
}
