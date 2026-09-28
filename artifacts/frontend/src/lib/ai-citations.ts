// Pure helpers for AI archive answers — no React, no aliases, so node:test can run them.

export type CitationLike = {
  media_id: string;
  filename: string;
  start_time: number;
  end_time: number;
  snippet?: string | null;
};

export type ChatMessage = {
  role: string;
  content: string;
  citations?: CitationLike[] | null;
  project_id?: string | null;
  project_name?: string | null;
};

export type CitationGroup = {
  mediaId: string;
  filename: string;
  /** 1-based source numbers in the order the answer cited them */
  moments: (CitationLike & { index: number })[];
};

export function formatTimecode(seconds: number): string {
  const total = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

/** Link into the existing asset player at a moment. */
export function momentHref(mediaId: string, startTime: number): string {
  const t = Math.max(0, Math.floor(Number.isFinite(startTime) ? startTime : 0));
  return `/library/${encodeURIComponent(mediaId)}?t=${t}`;
}

/** Asset-level (metadata) citations carry 0-0 / empty ranges: they point at the asset, not a moment. */
export function isAssetLevelCitation(c: { start_time: number; end_time: number }): boolean {
  const st = Number(c.start_time) || 0, en = Number(c.end_time) || 0;
  return st <= 0 && en <= st;
}

/** Link for a citation: asset-level ones open the asset without a misleading t=0. */
export function citationHref(mediaId: string, c: { start_time: number; end_time: number }): string {
  return isAssetLevelCitation(c) ? `/library/${encodeURIComponent(mediaId)}` : momentHref(mediaId, c.start_time);
}

/** Classify a media lookup error: 404/410 means gone; anything else is transient. */
export function mediaLookupState(error: unknown): "missing" | "transient" {
  const status = (error as { status?: number } | null)?.status;
  return status === 404 || status === 410 ? "missing" : "transient";
}

/** Group citations by media, preserving first-cited order; moments sorted by time, exact duplicates dropped. */
export function groupCitations(citations: CitationLike[] | null | undefined): CitationGroup[] {
  const groups = new Map<string, CitationGroup>();
  (citations ?? []).forEach((c, i) => {
    if (!c || !c.media_id) return;
    let g = groups.get(c.media_id);
    if (!g) {
      g = { mediaId: c.media_id, filename: c.filename, moments: [] };
      groups.set(c.media_id, g);
    }
    const dup = g.moments.some(m => Math.floor(m.start_time) === Math.floor(c.start_time));
    if (!dup) g.moments.push({ ...c, index: i + 1 });
  });
  for (const g of groups.values()) g.moments.sort((a, b) => a.start_time - b.start_time);
  return Array.from(groups.values());
}

/**
 * Merge persisted messages with optimistic ones. Each saved message "consumes"
 * one matching pending message (multiset match on role+content), so an
 * optimistic reply is shown until its persisted copy actually exists.
 */
export function mergeMessages<S extends ChatMessage, P extends ChatMessage>(saved: S[], pending: P[], baseline = 0): (S | P)[] {
  // Only persisted messages newer than the history seen when the ask began can
  // stand in for optimistic ones — older identical turns must not hide them.
  const counts = new Map<string, number>();
  for (const m of saved.slice(Math.max(0, baseline))) {
    const k = `${m.role}\u0000${m.content}`;
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  const rest = pending.filter(m => {
    const k = `${m.role}\u0000${m.content}`;
    const n = counts.get(k) ?? 0;
    if (n > 0) { counts.set(k, n - 1); return false; }
    return true;
  });
  return [...saved, ...rest];
}

/** True once every pending message has a persisted counterpart. */
export function pendingPersisted(saved: ChatMessage[], pending: ChatMessage[], baseline = 0): boolean {
  return mergeMessages(saved, pending, baseline).length === saved.length;
}
