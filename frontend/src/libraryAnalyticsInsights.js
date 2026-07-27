export const DEFAULT_INSIGHT = {
  kind: 'storage',
  title: 'Fichiers les plus volumineux',
  unit: 'bytes',
};

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
