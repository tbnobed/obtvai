import assert from "node:assert/strict";
import { test } from "node:test";
import {
  THEME_STORAGE_KEY, parseStoredPreference, readPreference, resolveTheme, isThemePreference, normalizeStoredPreference,
} from "./theme.ts";

function mem(init: Record<string, string> = {}) {
  const m = new Map(Object.entries(init));
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) };
}

test("storage key is stable", () => assert.equal(THEME_STORAGE_KEY, "obtv-theme"));

test("no preference keeps the historic dark default (not system)", () => {
  assert.equal(readPreference(mem()), "dark");
  assert.equal(resolveTheme(readPreference(mem()), false), "dark");
});

test("invalid / legacy values fall back to dark", () => {
  for (const v of ["", "blue", "DARK", "null", null, undefined]) assert.equal(parseStoredPreference(v as string), "dark");
  assert.equal(isThemePreference("system"), true);
});

test("explicit choices persist across reloads", () => {
  const s = mem();
  for (const p of ["light", "dark", "system"] as const) {
    s.setItem(THEME_STORAGE_KEY, p);
    assert.equal(readPreference(s), p);
  }
});

test("explicit light/dark ignore OS; system follows OS changes", () => {
  assert.equal(resolveTheme("light", true), "light");
  assert.equal(resolveTheme("dark", false), "dark");
  assert.equal(resolveTheme("system", true), "dark");
  assert.equal(resolveTheme("system", false), "light");
});

test("throwing storage (privacy mode) is safe", () => {
  assert.equal(readPreference({ getItem: () => { throw new Error("denied"); } }), "dark");
  assert.equal(readPreference(null), "dark");
});

test("normalize removes invalid stored values, keeps valid ones", () => {
  const m = new Map<string, string>([[THEME_STORAGE_KEY, "purple"]]);
  const s = { getItem: (k: string) => m.get(k) ?? null, removeItem: (k: string) => void m.delete(k) };
  assert.equal(normalizeStoredPreference(s), "dark");
  assert.equal(m.has(THEME_STORAGE_KEY), false);
  m.set(THEME_STORAGE_KEY, "light");
  assert.equal(normalizeStoredPreference(s), "light");
  assert.equal(m.get(THEME_STORAGE_KEY), "light");
});
