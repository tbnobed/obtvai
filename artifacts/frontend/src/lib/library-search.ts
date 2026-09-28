// Pure helpers for the unified Media Library search. `q` is reserved for the
// archive assistant hand-off, so search lives in `search_q` + `scope`.
import type { SearchResult } from "@workspace/api-client-react";

export type SearchScope = "combined" | "filename" | "transcript" | "visual" | "person";

export const SEARCH_SCOPES: { value: SearchScope; label: string; hint: string }[] = [
  { value: "combined", label: "Everything", hint: "Filenames, transcripts, visuals and people" },
  { value: "filename", label: "Filenames", hint: "Asset names only" },
  { value: "transcript", label: "Transcripts", hint: "What was said" },
  { value: "visual", label: "Visuals", hint: "What is on screen" },
  { value: "person", label: "People", hint: "Who appears or speaks" },
];

export const SEARCH_LIMIT = 500;
export const MIN_QUERY = 2;

export function parseScope(raw: string | null | undefined): SearchScope {
  return SEARCH_SCOPES.some((s) => s.value === raw) ? (raw as SearchScope) : "combined";
}

export function readLibrarySearch(searchString: string): { query: string; scope: SearchScope } {
  const p = new URLSearchParams(searchString);
  return { query: (p.get("search_q") ?? "").trim(), scope: parseScope(p.get("scope")) };
}

/** Returns a new query string with search_q/scope applied; other params (folder, ask, conv, q...) preserved. */
export function withLibrarySearch(searchString: string, query: string, scope: SearchScope): string {
  const p = new URLSearchParams(searchString);
  const term = query.trim();
  if (term) p.set("search_q", term);
  else p.delete("search_q");
  if (term && scope !== "combined") p.set("scope", scope);
  else p.delete("scope");
  return p.toString();
}

/** Maps a legacy /search?q=&scope= URL onto the library. */
export function legacySearchRedirect(searchString: string): string {
  const p = new URLSearchParams(searchString);
  const qs = withLibrarySearch("", p.get("q") ?? "", parseScope(p.get("scope")));
  return `/library${qs ? `?${qs}` : ""}`;
}

export type LibrarySearchFilters = {
  media_type?: string;
  status?: string;
  folder?: string;
  person?: string;
  topic?: string;
};

export function buildSearchBody(query: string, scope: SearchScope, f: LibrarySearchFilters) {
  const body: Record<string, unknown> = { query: query.trim(), search_type: scope, limit: SEARCH_LIMIT };
  if (f.media_type && f.media_type !== "all") body.media_type = f.media_type;
  for (const k of ["status", "folder", "person", "topic"] as const) if (f[k]) body[k] = f[k];
  return body;
}

export type AssetMatchGroup = {
  media_id: string;
  filename: string;
  thumbnail_url?: string | null;
  /** 0-based rank of this asset's best hit in the backend ordering */
  rank: number;
  bestScore: number;
  /** Timed moments, in backend rank order */
  moments: SearchResult[];
  /** Matched on the filename (no meaningful timestamp) */
  filenameMatch: boolean;
  matchTypes: string[];
};

/** Groups ranked hits by asset, keeping first-hit order and per-asset rank order. */
export function groupSearchResults(results: SearchResult[]): AssetMatchGroup[] {
  const byId = new Map<string, AssetMatchGroup>();
  const order: AssetMatchGroup[] = [];
  results.forEach((r, i) => {
    let g = byId.get(r.media_id);
    if (!g) {
      g = { media_id: r.media_id, filename: r.filename, thumbnail_url: r.thumbnail_url, rank: i, bestScore: r.score, moments: [], filenameMatch: false, matchTypes: [] };
      byId.set(r.media_id, g);
      order.push(g);
    }
    if (!g.thumbnail_url && r.thumbnail_url) g.thumbnail_url = r.thumbnail_url;
    g.bestScore = Math.max(g.bestScore, r.score);
    if (!g.matchTypes.includes(r.match_type)) g.matchTypes.push(r.match_type);
    if (r.match_type === "filename") g.filenameMatch = true;
    else g.moments.push(r);
  });
  return order;
}

export const momentKey = (r: SearchResult) => `${r.media_id}:${r.start_time}:${r.end_time}:${r.match_type}`;

export const MATCH_LABEL: Record<string, string> = {
  filename: "Filename",
  transcript: "Transcript",
  visual: "Visual",
  person: "Person",
};
