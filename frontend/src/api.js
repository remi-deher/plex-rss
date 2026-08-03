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

/**
 * Lit un flux SSE ponctuel et appelle `onPayload` à chaque trame reçue.
 *
 * `EventSource` n'est pas utilisable ici : il ne sait pas envoyer d'en-têtes, se
 * reconnecte tout seul indéfiniment et n'expose aucune fin de flux — or on veut une
 * requête unique, qui se termine. On lit donc le corps de la réponse à la main.
 *
 * Lève si le transport ne suit pas (réponse non-OK, navigateur sans ReadableStream) :
 * l'appelant doit prévoir un repli sur l'endpoint non streamé.
 */
export async function streamEvents(path, onPayload, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { Accept: "text/event-stream" },
    ...options,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `HTTP ${response.status}`);
  }
  if (!response.body) throw new Error("Flux non supporté par ce navigateur");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        finished = true;
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      // Une trame SSE se termine par une ligne vide ; le reste du tampon est une trame
      // encore incomplete, on la garde pour la prochaine lecture.
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const data = frame
          .split("\n")
          .filter(line => line.startsWith("data:"))
          .map(line => line.slice(5).trim())
          .join("");
        if (!data) continue;
        try {
          onPayload(JSON.parse(data));
        } catch {
          /* Trame illisible : on continue, les suivantes restent exploitables. */
        }
      }
    }
  } finally {
    // Uniquement en sortie anormale (erreur, démontage de la vue). Annuler un flux déjà
    // terminé fait apparaître la requête en ERR_ABORTED dans les outils de développement,
    // ce qui masquerait un vrai échec.
    if (!finished) reader.cancel().catch(() => {});
  }
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
