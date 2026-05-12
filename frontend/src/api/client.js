const API_BASE = "/api";

async function jsonFetch(path, params) {
  const url = new URL(API_BASE + path, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
    });
  }
  const response = await fetch(url.toString());
  if (!response.ok) {
    throw new Error(`API ${path} → ${response.status}`);
  }
  return response.json();
}

async function jsonRequest(path, method, body) {
  const response = await fetch(API_BASE + path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    throw new Error(`API ${path} → ${response.status}`);
  }
  return response.json();
}

export const api = {
  health: () => jsonFetch("/health"),
  letters: ({ favoritesOnly = false, sortBy } = {}) =>
    jsonFetch("/entities/letters", {
      favorites_only: favoritesOnly ? "true" : undefined,
      sort_by: sortBy || undefined,
    }),
  entityTimeline: (slug) => jsonFetch(`/entities/${slug}/timeline`),
  entities: ({
    letter,
    favoritesOnly = false,
    sortBy,
    limit = 200,
    offset = 0,
  } = {}) =>
    jsonFetch("/entities", {
      letter,
      favorites_only: favoritesOnly ? "true" : undefined,
      sort_by: sortBy || undefined,
      limit,
      offset,
    }),
  entity: (slug) => jsonFetch(`/entities/${slug}`),
  entityImages: (slug, filters = {}) =>
    jsonFetch(`/entities/${slug}/images`, filters),
  search: (q) => jsonFetch("/entities/search", { q }),
  searchGlobal: (q, { scope = "all", limit = 10 } = {}) =>
    jsonFetch("/search", { q, scope, limit }),
  queue: () => jsonFetch("/queue"),
  deleteEntity: (slug) => jsonRequest(`/entities/${slug}`, "DELETE"),
  flagged: (sourceProvider) =>
    jsonFetch("/flagged", sourceProvider ? { source_provider: sourceProvider } : {}),
  deleteImage: (id) => jsonRequest(`/images/${id}`, "DELETE"),
  reassignImage: (id, target_slug) =>
    jsonRequest(`/images/${id}`, "PATCH", { target_slug }),
  flagImage: (id) => jsonRequest(`/images/${id}/flag`, "POST"),
  confirmImage: (id) => jsonRequest(`/images/${id}/confirm`, "POST"),
  imageLandmarks: (id) => jsonFetch(`/images/${id}/landmarks`),
  workerStatus: () => jsonFetch("/admin/worker-status"),
  backups: () => jsonFetch("/admin/backups"),
  backupNow: () => jsonRequest("/admin/backup-now", "POST"),
  restoreBackup: (filename) =>
    jsonRequest(
      `/admin/restore-backup?filename=${encodeURIComponent(filename)}`,
      "POST",
    ),
  mergeConflicts: () => jsonFetch("/admin/merge-conflicts"),
  wuddStatus: () => jsonFetch("/admin/wudd-status"),
  recheckNotPerson: (limit = 50) =>
    jsonRequest(`/admin/recheck-not-person?limit=${limit}`, "POST"),
  collectEntity: (slug, limit = 200) =>
    jsonRequest(`/entities/${slug}/collect?limit=${limit}`, "POST"),
  searchDdg: (slug, limit = 20) =>
    jsonRequest(`/entities/${slug}/search-ddg?limit=${limit}`, "POST"),
  ingestDdgImage: (slug, body) =>
    jsonRequest(`/entities/${slug}/ingest-ddg-image`, "POST", body),
  setFavorite: (slug) => jsonRequest(`/entities/${slug}/favorite`, "PUT"),
  unsetFavorite: (slug) => jsonRequest(`/entities/${slug}/favorite`, "DELETE"),
  duplicateCandidates: () => jsonFetch("/entities/duplicate-candidates"),
  mergeEntities: (canonicalSlug, sourceSlug) =>
    jsonRequest(
      `/entities/${canonicalSlug}/merge?source=${encodeURIComponent(sourceSlug)}`,
      "POST",
    ),
};
