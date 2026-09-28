import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useGetSearchHistory, getGetSearchHistoryQueryKey, useListSavedSearches, getListSavedSearchesQueryKey,
  useCreateSavedSearch, useDeleteSavedSearch, useListEmotionFacets, getListEmotionFacetsQueryKey,
  useListEmotionMoments, getListEmotionMomentsQueryKey, useBackfillSentiment,
} from "@workspace/api-client-react";
import { Button } from "@/components/ui/button";
import { Bookmark, BookmarkPlus, HeartPulse, History, Loader2, Play, X } from "lucide-react";
import type { PlayerClip } from "@/components/project/clip-player-dialog";
import { formatTC } from "@/lib/timecode";
import { parseScope, type SearchScope } from "@/lib/library-search";

const EMOTION_COLORS: Record<string, string> = {
  joy: "#facc15", humor: "#fb923c", excitement: "#f97316", warmth: "#4ade80", pride: "#34d399",
  surprise: "#a78bfa", sadness: "#60a5fa", anger: "#f87171", tension: "#ef4444", fear: "#c084fc",
};

const chip = "inline-flex items-center gap-1 h-6 px-2 rounded-full border text-xs transition-colors";

/** Save button for the committed query. */
export function SaveSearchButton({ query, scope }: { query: string; scope: SearchScope }) {
  const qc = useQueryClient();
  const { data: saved } = useListSavedSearches({ query: { queryKey: getListSavedSearchesQueryKey() } });
  const create = useCreateSavedSearch();
  const term = query.trim();
  const already = saved?.some((s) => s.query.trim().toLowerCase() === term.toLowerCase() && s.search_type === scope);
  return (
    <Button variant="outline" size="icon" className="h-9 w-9 shrink-0 bg-card/60"
      data-testid="button-save-search"
      aria-label={already ? "Search already saved" : "Save this search"}
      title={already ? "Already saved" : "Save this search. It re-runs live as new footage is indexed"}
      disabled={term.length < 2 || !!already || create.isPending}
      onClick={() => create.mutate({ data: { name: term, query: term, search_type: scope } }, {
        onSuccess: () => qc.invalidateQueries({ queryKey: getListSavedSearchesQueryKey() }),
      })}>
      <BookmarkPlus className="h-4 w-4" />
    </Button>
  );
}

/**
 * Saved searches, recent history and emotion browsing, shown under the
 * library search bar. Picking a saved or recent search commits it.
 */
export function SearchShelf({ onRun, showHistory, onPlay }: {
  onRun: (query: string, scope: SearchScope) => void;
  showHistory: boolean;
  onPlay: (clip: PlayerClip) => void;
}) {
  const qc = useQueryClient();
  const { data: saved } = useListSavedSearches({ query: { queryKey: getListSavedSearchesQueryKey() } });
  const { data: history } = useGetSearchHistory({ query: { queryKey: getGetSearchHistoryQueryKey() } });
  const del = useDeleteSavedSearch();
  const [emotion, setEmotion] = useState<string | null>(null);
  const [emotionsOpen, setEmotionsOpen] = useState(false);
  const { data: facets } = useListEmotionFacets({ query: { queryKey: getListEmotionFacetsQueryKey(), enabled: emotionsOpen } });
  const params = { emotion: emotion ?? "", limit: 100 };
  const { data: moments, isLoading: momentsLoading } = useListEmotionMoments(params, {
    query: { queryKey: getListEmotionMomentsQueryKey(params), enabled: !!emotion },
  });
  const backfill = useBackfillSentiment();

  return (
    <div className="space-y-2" data-testid="search-shelf">
      <div className="flex items-center gap-1.5 flex-wrap text-xs">
        {!!saved?.length && (
          <>
            <Bookmark className="h-3.5 w-3.5 text-primary" aria-hidden />
            {saved.map((sv) => (
              <span key={sv.id} className={`${chip} border-primary/40 pr-1`}>
                <button type="button" onClick={() => onRun(sv.query, parseScope(sv.search_type))} className="hover:text-primary">{sv.name}</button>
                <button type="button" aria-label={`Remove saved search ${sv.name}`} title="Remove saved search"
                  className="rounded-full p-0.5 opacity-50 hover:opacity-100 hover:text-destructive"
                  onClick={() => del.mutate({ savedId: sv.id }, { onSuccess: () => qc.invalidateQueries({ queryKey: getListSavedSearchesQueryKey() }) })}>
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
            <span className="w-2" />
          </>
        )}
        {showHistory && !!history?.length && (
          <>
            <History className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
            {history.slice(0, 6).map((h) => (
              <button key={h.id} type="button" className={`${chip} border-border text-muted-foreground hover:text-foreground`} onClick={() => onRun(h.query, "combined")}>
                {h.query}
              </button>
            ))}
            <span className="w-2" />
          </>
        )}
        <button type="button" data-testid="button-emotions"
          onClick={() => { setEmotionsOpen((o) => !o); if (emotionsOpen) setEmotion(null); }}
          aria-expanded={emotionsOpen}
          className={`${chip} ${emotionsOpen ? "border-primary text-primary" : "border-border text-muted-foreground hover:text-foreground"}`}>
          <HeartPulse className="h-3 w-3" /> Emotions
        </button>
        {emotionsOpen && (facets?.length ? facets.map((f) => (
          <button key={f.emotion} type="button"
            onClick={() => setEmotion((cur) => (cur === f.emotion ? null : f.emotion))}
            className={`${chip} capitalize ${emotion === f.emotion ? "bg-muted" : ""}`}
            style={{ borderColor: `${EMOTION_COLORS[f.emotion] ?? "#71717a"}88`, color: EMOTION_COLORS[f.emotion] }}>
            {f.emotion} <span className="tabular-nums opacity-70">{f.count}</span>
          </button>
        )) : (
          <>
            <span className="text-muted-foreground">none scored yet</span>
            <Button size="sm" variant="outline" className="h-6 px-2 text-xs" disabled={backfill.isPending || backfill.isSuccess}
              onClick={() => backfill.mutate(undefined as never, { onSuccess: () => qc.invalidateQueries({ queryKey: getListEmotionFacetsQueryKey() }) })}>
              {backfill.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : backfill.isSuccess ? "Queued, check back after processing" : "Analyze emotions across library"}
            </Button>
          </>
        ))}
      </div>
      {emotion && (
        <div className="rounded-md border border-border bg-card/60 p-3">
          <div className="flex items-center justify-between mb-2">
            <p className="text-sm font-medium capitalize" style={{ color: EMOTION_COLORS[emotion] }}>
              {momentsLoading ? "Loading moments" : `${moments?.items.length ?? 0} ${emotion} moment${(moments?.items.length ?? 0) === 1 ? "" : "s"}`}
            </p>
            <Button size="icon" variant="ghost" className="h-6 w-6" aria-label="Close emotion moments" onClick={() => setEmotion(null)}><X className="h-3.5 w-3.5" /></Button>
          </div>
          {moments?.items.length ? (
            <div className="flex gap-2 overflow-x-auto pb-1">
              {moments.items.map((m, i) => (
                <button key={`${m.media_id}-${m.start_time}-${i}`} type="button"
                  onClick={() => onPlay({ media_id: m.media_id, start_time: m.start_time, end_time: m.end_time, label: m.text, filename: m.filename })}
                  className="w-48 shrink-0 text-left rounded bg-muted/50 overflow-hidden hover:ring-1 hover:ring-primary/50">
                  <div className="relative aspect-video bg-muted flex items-center justify-center">
                    {m.thumbnail_url ? <img src={`/api/thumbnails/${m.thumbnail_url}`} alt="" loading="lazy" className="w-full h-full object-cover" /> : <Play className="h-5 w-5 text-muted-foreground" />}
                    <span className="absolute bottom-1 left-1 text-[10px] font-mono px-1 rounded bg-background/80">{formatTC(m.start_time, 25, false)}</span>
                  </div>
                  <div className="p-2">
                    <div className="truncate text-xs font-medium">{m.filename}</div>
                    <p className="text-[11px] text-muted-foreground line-clamp-2">{m.speaker ? `${m.speaker}: ` : ""}&ldquo;{m.text}&rdquo;</p>
                  </div>
                </button>
              ))}
            </div>
          ) : momentsLoading ? <div className="h-24 animate-pulse bg-muted rounded" /> : <p className="text-sm text-muted-foreground">No moments carry this emotion.</p>}
        </div>
      )}
    </div>
  );
}
