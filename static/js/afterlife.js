export const AFTERLIFE_FEATURE_DEFAULTS = Object.freeze({
  afterlife_shell: false,
  afterlife_today: false,
  afterlife_aide_projects: false,
  afterlife_andromeda: false,
  afterlife_jarvis: false,
  afterlife_storage_locations: false,
});

export function normalizeAfterlifeFeatures(value) {
  const flags = { ...AFTERLIFE_FEATURE_DEFAULTS };
  if (!value || typeof value !== 'object' || Array.isArray(value)) return flags;
  for (const key of Object.keys(flags)) flags[key] = value[key] === true;
  return flags;
}

export async function loadAfterlifeFeatures(fetcher = fetch) {
  try {
    const response = await fetcher('/api/system/build', { headers: { accept: 'application/json' } });
    if (!response?.ok) return { ...AFTERLIFE_FEATURE_DEFAULTS };
    const body = await response.json();
    return normalizeAfterlifeFeatures(body?.feature_flags);
  } catch {
    // Unfinished UI must fail closed. Do not revive a cached flag while offline.
    return { ...AFTERLIFE_FEATURE_DEFAULTS };
  }
}

export function activeAfterlifeSpaces(flags, available = { aide: true, today: true, andromeda: true }) {
  const safe = normalizeAfterlifeFeatures(flags);
  if (!safe.afterlife_shell) return [];
  return [
    safe.afterlife_today && available.today ? 'today' : '',
    available.aide ? 'aide' : '',
    safe.afterlife_andromeda && available.andromeda ? 'andromeda' : '',
  ].filter(Boolean);
}
