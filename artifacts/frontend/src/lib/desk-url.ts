/** Pure helpers for URL-persisted desk filters (kept free of React for tests). */

export function readPage(raw: string | null | undefined): number {
  const n = parseInt(raw ?? "", 10);
  return Number.isFinite(n) && n >= 1 ? n : 1;
}

/** Applies a patch to a query string. Any non-page change resets the page; empty values and page=1 are dropped. */
export function patchSearch(search: string, patch: Record<string, string | undefined>): string {
  const sp = new URLSearchParams(search);
  const resetsPage = Object.keys(patch).some((k) => k !== "page");
  for (const [k, v] of Object.entries(patch)) {
    if (v == null || v === "") sp.delete(k); else sp.set(k, v);
  }
  if (resetsPage && !("page" in patch)) sp.delete("page");
  if (sp.get("page") === "1") sp.delete("page");
  return sp.toString();
}

/** When the current page came back empty but other rows exist, the last valid page; otherwise null. */
export function recoverPage(page: number, itemCount: number, total: number, limit: number): number | null {
  if (itemCount > 0 || page <= 1) return null;
  const last = Math.max(1, Math.ceil(total / limit));
  return last < page ? last : null;
}

export const offsetFor = (page: number, limit: number) => (page - 1) * limit;
