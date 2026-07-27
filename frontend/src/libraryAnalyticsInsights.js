export const DEFAULT_INSIGHT = {
  kind: 'storage',
  title: 'Fichiers les plus volumineux',
  unit: 'bytes',
};

const DISTRIBUTIONS = {
  types: 'media_type',
  studios: 'studio',
  video_codecs: 'video_codec',
  audio_codecs: 'audio_codec',
  resolutions: 'video_resolution',
  containers: 'container',
};

function distribution(rows, field, limit = 12) {
  const counts = new Map();
  rows.forEach(row => {
    const label = String(row[field] || 'Inconnu');
    counts.set(label, (counts.get(label) || 0) + 1);
  });
  const total = rows.length || 1;
  return [...counts.entries()]
    .sort((left, right) => right[1] - left[1])
    .slice(0, limit)
    .map(([label, count]) => ({ label, count, percent: Math.round(count / total * 1000) / 10 }));
}

export function filterAnalyticsItems(items = [], filters = {}) {
  const search = String(filters.search || '').trim().toLocaleLowerCase('fr');
  return items.filter(row => {
    if (filters.media_type && row.media_type !== filters.media_type) return false;
    for (const field of ['library', 'studio', 'video_codec', 'audio_codec', 'container']) {
      if (filters[field] && String(row[field]) !== String(filters[field])) return false;
    }
    if (search) {
      const haystack = [row.title, row.parent_title, row.grandparent_title, row.studio]
        .filter(Boolean).join(' ').toLocaleLowerCase('fr');
      if (!haystack.includes(search)) return false;
    }
    if (filters.subtitle === 'with' && !Number(row.subtitle_count || 0)) return false;
    if (filters.subtitle === 'without' && Number(row.subtitle_count || 0)) return false;
    if (filters.subtitle_type && !(row.subtitle_types || []).includes(filters.subtitle_type)) return false;
    if (filters.subtitle_language && !(row.subtitle_languages || []).includes(filters.subtitle_language)) return false;
    if (filters.audio_language && !(row.audio_languages || []).includes(filters.audio_language)) return false;
    if (filters.watched === 'yes' && !Number(row.play_count || 0)) return false;
    if (filters.watched === 'no' && Number(row.play_count || 0)) return false;
    const sizeGb = Number(row.size_bytes || 0) / (1024 ** 3);
    if (filters.min_size_gb !== '' && filters.min_size_gb != null && sizeGb < Number(filters.min_size_gb)) return false;
    if (filters.max_size_gb !== '' && filters.max_size_gb != null && sizeGb > Number(filters.max_size_gb)) return false;
    return true;
  });
}

export function analyticsForFilters(snapshot = {}, filters = {}) {
  const items = filterAnalyticsItems(snapshot.items || [], filters);
  const sizeBytes = items.reduce((total, row) => total + Number(row.size_bytes || 0), 0);
  const durationMs = items.reduce((total, row) => total + Number(row.duration_ms || 0), 0);
  return {
    ...snapshot,
    items,
    summary: {
      items: items.length,
      size_bytes: sizeBytes,
      duration_ms: durationMs,
      plays: items.reduce((total, row) => total + Number(row.play_count || 0), 0),
      viewers: new Set(items.flatMap(row => row.viewers || [])).size,
    },
    insights: [
      { kind: 'storage', title: 'Poids du catalogue filtré', value: sizeBytes, unit: 'bytes' },
      { kind: 'unwatched', title: 'Jamais visionnés', value: items.filter(row => !Number(row.play_count || 0)).length, unit: 'items' },
      { kind: 'subtitles', title: 'Sans sous-titres', value: items.filter(row => !Number(row.subtitle_count || 0)).length, unit: 'items' },
    ],
    distributions: Object.fromEntries(
      Object.entries(DISTRIBUTIONS).map(([key, field]) => [key, distribution(items, field)]),
    ),
  };
}

export function insightSelection(insight) {
  return {
    kind: insight.kind,
    title: insight.title,
    unit: insight.unit,
  };
}

export function distributionSelection(chart, value) {
  return {
    kind: 'distribution',
    title: `${chart.title} · ${value}`,
    field: chart.field,
    value,
  };
}

export function insightRows(items = [], selection = DEFAULT_INSIGHT) {
  const rows = [...items];
  if (selection.kind === 'unwatched') {
    return rows.filter(row => !Number(row.play_count || 0));
  }
  if (selection.kind === 'subtitles') {
    return rows.filter(row => !Number(row.subtitle_count || 0));
  }
  if (selection.kind === 'distribution' && selection.field) {
    return rows.filter(row => String(row[selection.field] || 'Inconnu') === String(selection.value));
  }
  return rows.sort((left, right) => Number(right.size_bytes || 0) - Number(left.size_bytes || 0));
}
