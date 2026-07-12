export async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
    ...options,
  });
  if (response.redirected && response.url.includes("/login")) {
    window.location.href = response.url;
    return null;
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || data.message || `HTTP ${response.status}`);
  }
  return data;
}

export function cachedResource(key, ttlMs, loader) {
  const now = Date.now();
  const raw = localStorage.getItem(key);
  const cached = raw ? JSON.parse(raw) : null;
  const fresh = cached && now - cached.savedAt < ttlMs;
  const refresh = loader().then((data) => {
    localStorage.setItem(key, JSON.stringify({ savedAt: Date.now(), data }));
    return data;
  });
  return { cached: cached?.data || null, fresh, refresh };
}
