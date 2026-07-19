// Topic normalization — mirror of services/api/app/topic_norm.py (keep in sync).
// "Abraham_Accords", "abraham accords", "Abraham-Accords" all collapse to one key.

const SMALL_WORDS = new Set(["a", "an", "and", "at", "for", "in", "of", "on", "or", "the", "to", "vs"]);

// Words that must keep a fixed casing in labels.
const PROPER_CASING: Record<string, string> = {
  ai: "AI",
  gpu: "GPU",
  gpus: "GPUs",
  llm: "LLM",
  llms: "LLMs",
  tv: "TV",
  qa: "Q&A",
  q3: "Q3",
  us: "US",
  uk: "UK",
  eu: "EU",
  un: "UN",
  nato: "NATO",
  covid: "COVID",
  tiktok: "TikTok",
  youtube: "YouTube",
  aws: "AWS",
};

// Full normalized keys whose label isn't derivable word-by-word.
const SPECIAL_LABELS: Record<string, string> = {
  "b roll": "B-roll",
};

/** Canonical filter key: lowercase, _/- become spaces, whitespace collapsed. */
export function normalizeTopicKey(raw: string): string {
  return raw
    .toLowerCase()
    .replace(/[_\-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Human-readable label for a normalized key: title case with proper-noun casing. */
export function topicLabel(key: string): string {
  if (SPECIAL_LABELS[key]) return SPECIAL_LABELS[key];
  const words = key.split(" ");
  return words
    .map((w, i) => {
      if (PROPER_CASING[w]) return PROPER_CASING[w];
      if (i > 0 && SMALL_WORDS.has(w)) return w;
      return w.charAt(0).toUpperCase() + w.slice(1);
    })
    .join(" ");
}

/** Group raw topic strings (with per-topic counts) by normalized key, summing counts. */
export function groupTopics(rawCounts: Iterable<[string, number]>): { key: string; topic: string; asset_count: number }[] {
  const grouped = new Map<string, number>();
  for (const [raw, count] of rawCounts) {
    const key = normalizeTopicKey(raw);
    if (!key) continue;
    grouped.set(key, (grouped.get(key) ?? 0) + count);
  }
  return [...grouped.entries()]
    .map(([key, asset_count]) => ({ key, topic: topicLabel(key), asset_count }))
    .sort((a, b) => b.asset_count - a.asset_count || a.key.localeCompare(b.key));
}
