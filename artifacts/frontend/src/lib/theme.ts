/**
 * Theme preference model. Pure, DOM-free logic so it can be unit-tested and
 * mirrored exactly by the pre-paint inline script in index.html.
 *
 * - Storage key: "obtv-theme" (values: "light" | "dark" | "system").
 * - No stored / invalid value  -> "dark" (preserves the historic dark default
 *   for returning users). Only an explicit "system" follows the OS.
 */
export const THEME_STORAGE_KEY = "obtv-theme";
export const DEFAULT_THEME_PREFERENCE = "dark" as const;
export const THEME_PREFERENCES = ["light", "dark", "system"] as const;

export type ThemePreference = (typeof THEME_PREFERENCES)[number];
export type ResolvedTheme = "light" | "dark";

export function isThemePreference(v: unknown): v is ThemePreference {
  return typeof v === "string" && (THEME_PREFERENCES as readonly string[]).includes(v);
}

export function parseStoredPreference(raw: string | null | undefined): ThemePreference {
  return isThemePreference(raw) ? raw : DEFAULT_THEME_PREFERENCE;
}

export function resolveTheme(pref: ThemePreference, systemPrefersDark: boolean): ResolvedTheme {
  if (pref === "system") return systemPrefersDark ? "dark" : "light";
  return pref;
}

export function readPreference(storage: Pick<Storage, "getItem"> | null | undefined): ThemePreference {
  try { return parseStoredPreference(storage?.getItem(THEME_STORAGE_KEY)); }
  catch { return DEFAULT_THEME_PREFERENCE; }
}

/**
 * Drop an invalid stored value so next-themes never applies it as a class.
 * Removing (not rewriting) keeps "no preference" semantics => dark default.
 */
export function normalizeStoredPreference(storage: Pick<Storage, "getItem" | "removeItem"> | null | undefined): ThemePreference {
  try {
    const raw = storage?.getItem(THEME_STORAGE_KEY) ?? null;
    if (raw !== null && !isThemePreference(raw)) storage?.removeItem(THEME_STORAGE_KEY);
    return parseStoredPreference(raw);
  } catch { return DEFAULT_THEME_PREFERENCE; }
}
