// Pure helpers for workspaces, collections and library scope. Kept free of
// runtime imports so they can be unit-tested with node directly.
import type { EditorialRules, CollectionItem, Workspace, Collection } from "@workspace/api-client-react";

export const ALL_LIBRARY = "all";

/** Default team workspaces offered when none exist yet. */
export const DEFAULT_WORKSPACES: { name: string; description: string; rules: EditorialRules }[] = [
  { name: "Praise", description: "Praise program media — matched by filename or path.", rules: { text: "praise" } },
  { name: "Stakelbeck", description: "Stakelbeck on Terror media — matched by filename or path.", rules: { text: "stakelbeck" } },
];

export type ScopeSelection = {
  /** null = All Library */
  workspaceId: string | null;
  collectionId: string | null;
  /** true when the URL said so explicitly (vs. the remembered default) */
  explicit: boolean;
};

/**
 * URL wins: ?ws=all → All Library, ?ws=<id>, ?col=<id>. With no URL
 * scope, fall back to the remembered workspace.
 */
export function readScope(searchString: string, remembered: string | null | undefined): ScopeSelection {
  const p = new URLSearchParams(searchString);
  const ws = p.get("ws");
  const col = p.get("col");
  if (ws === ALL_LIBRARY) return { workspaceId: null, collectionId: null, explicit: true };
  if (ws || col) return { workspaceId: ws || null, collectionId: col || null, explicit: true };
  return { workspaceId: remembered ?? null, collectionId: null, explicit: false };
}

export function withScope(searchString: string, workspaceId: string | null, collectionId: string | null): string {
  const p = new URLSearchParams(searchString);
  p.delete("ws"); p.delete("col");
  if (!workspaceId && !collectionId) p.set("ws", ALL_LIBRARY);
  else {
    if (workspaceId) p.set("ws", workspaceId);
    if (collectionId) p.set("col", collectionId);
  }
  return p.toString();
}

export function cleanRules(r: EditorialRules): EditorialRules {
  const out: EditorialRules = {};
  if (r.text && r.text.trim()) out.text = r.text.trim();
  if (r.air_year != null && Number.isFinite(Number(r.air_year))) out.air_year = Math.trunc(Number(r.air_year));
  if (r.status && r.status.trim()) out.status = r.status.trim();
  if (r.media_type && r.media_type.trim() && r.media_type !== "all") out.media_type = r.media_type.trim();
  if (r.topic && r.topic.trim()) out.topic = r.topic.trim();
  return out;
}

export function rulesSummary(r: EditorialRules | null | undefined): string {
  if (!r) return "";
  const parts: string[] = [];
  if (r.text) parts.push(`“${r.text}” in name/path`);
  if (r.air_year != null) parts.push(`aired ${r.air_year}`);
  if (r.status) parts.push(`status ${r.status}`);
  if (r.media_type && r.media_type !== "all") parts.push(r.media_type === "images" ? "images only" : "no images");
  if (r.topic) parts.push(`topic ${r.topic}`);
  return parts.join(" · ");
}

export function hasRules(r: EditorialRules | null | undefined): boolean {
  return !!r && Object.keys(cleanRules(r)).length > 0;
}

/** Parses "90", "1:30", "01:01:30" or "1:30.5" into seconds. */
export function parseTime(raw: string): number | null {
  const s = raw.trim();
  if (!s) return null;
  const parts = s.split(":");
  if (parts.length > 3 || parts.some((x) => x === "" || !/^\d+(\.\d+)?$/.test(x))) return null;
  return parts.reduce((acc, x) => acc * 60 + Number(x), 0);
}

export function formatTime(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec)) return "";
  const t = Math.max(0, sec);
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = Math.floor(t % 60);
  const pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

/** null when valid; otherwise a human error. Both null = whole asset. */
export function itemRangeError(start: number | null, end: number | null): string | null {
  if (start == null && end == null) return null;
  if (start == null || end == null) return "Set both in and out, or clear both for the whole asset.";
  if (!(start >= 0)) return "In point must be zero or later.";
  if (!(end > start)) return "Out point must be after the in point.";
  return null;
}

export function isTimed(item: CollectionItem): boolean {
  return item.start != null && item.end != null;
}

/** Same media + same range already present? Avoids duplicate selects. */
export function containsItem(items: CollectionItem[], mediaId: string, start: number | null, end: number | null): boolean {
  return items.some((i) => i.media_id === mediaId && (i.start ?? null) === start && (i.end ?? null) === end);
}

export function collectionsForWorkspace(collections: Collection[], workspaceId: string | null): Collection[] {
  return collections
    .filter((c) => (workspaceId ? c.workspace_id === workspaceId || c.workspace_id == null : true))
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
}

export function sortedWorkspaces(ws: Workspace[], mine: string[]): Workspace[] {
  return [...ws].sort((a, b) => {
    const am = mine.includes(a.id) ? 0 : 1;
    const bm = mine.includes(b.id) ? 0 : 1;
    return am - bm || a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
  });
}

export function toggleId(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}
