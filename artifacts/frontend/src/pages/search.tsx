import { useEffect, useRef, useState } from "react";
import { Link, useSearch } from "wouter";
import {
  useSemanticSearch,
  useGetSearchHistory,
  getGetSearchHistoryQueryKey,
} from "@workspace/api-client-react";
import type { SearchResult } from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Search, Play, Loader2, ExternalLink, History } from "lucide-react";
import { ClipPlayerDialog, type PlayerClip } from "@/components/project/clip-player-dialog";
import { formatTC } from "@/lib/timecode";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [playerClip, setPlayerClip] = useState<PlayerClip | null>(null);
  const searchMutation = useSemanticSearch();
  const { data: history } = useGetSearchHistory({
    query: { queryKey: getGetSearchHistoryQueryKey() },
  });
  const queryClient = useQueryClient();

  const runSearch = (q?: string) => {
    const term = (q ?? query).trim();
    if (term.length < 2) return;
    if (q) setQuery(q);
    searchMutation.mutate(
      { data: { query: term } },
      {
        onSuccess: () =>
          queryClient.invalidateQueries({ queryKey: getGetSearchHistoryQueryKey() }),
      },
    );
  };

  // Support /search?q=… deep links (e.g. from the Dashboard search box).
  const searchString = useSearch();
  const ranInitialQuery = useRef(false);
  useEffect(() => {
    if (ranInitialQuery.current) return;
    const q = new URLSearchParams(searchString).get("q");
    if (q && q.trim().length >= 2) {
      ranInitialQuery.current = true;
      runSearch(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchString]);

  const resultRow = (r: SearchResult, key: string) => (
    <div key={key} className="flex items-center justify-between bg-muted/50 p-2.5 rounded text-sm gap-3">
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{r.filename}</div>
        <div className="text-xs text-muted-foreground truncate">
          {formatTC(r.start_time, 25, false)}–{formatTC(r.end_time, 25, false)} ·{" "}
          {r.match_type === "visual" ? "Visual match" : "Transcript match"} · {(r.score * 100).toFixed(0)}%
          {r.snippet ? ` · “${r.snippet}”` : ""}
        </div>
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        <Button
          size="icon" variant="ghost" className="h-7 w-7" title="Play this clip"
          onClick={() =>
            setPlayerClip({
              media_id: r.media_id,
              start_time: r.start_time,
              end_time: r.end_time,
              label: r.snippet || undefined,
              filename: r.filename,
            })
          }
        >
          <Play className="h-3.5 w-3.5" />
        </Button>
        <Button asChild size="icon" variant="ghost" className="h-7 w-7" title="Open the asset at this timecode">
          <Link href={`/library/${r.media_id}?t=${Math.floor(r.start_time)}`}>
            <ExternalLink className="h-3.5 w-3.5" />
          </Link>
        </Button>
      </div>
    </div>
  );

  return (
    <div className="p-6 space-y-6 max-w-4xl mx-auto">
      <div>
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          <Search className="h-6 w-6" /> Search
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Natural-language search across every indexed asset — transcripts and visual scene content.
        </p>
      </div>

      <div className="flex gap-2">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder='e.g. "mayor talks about the housing vote" or "crowd outside city hall at night"'
          onKeyDown={(e) => e.key === "Enter" && runSearch()}
          autoFocus
        />
        <Button onClick={() => runSearch()} disabled={query.trim().length < 2 || searchMutation.isPending}>
          {searchMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
        </Button>
      </div>

      {!searchMutation.data && !searchMutation.isPending && !!history?.length && (
        <div className="flex items-center gap-2 flex-wrap">
          <History className="h-3.5 w-3.5 text-muted-foreground" />
          {history.slice(0, 8).map((h) => (
            <Badge
              key={h.id}
              variant="outline"
              className="cursor-pointer hover:bg-muted"
              onClick={() => runSearch(h.query)}
            >
              {h.query}
            </Badge>
          ))}
        </div>
      )}

      {searchMutation.isError && (
        <p className="text-sm text-red-400">Search failed — try again.</p>
      )}

      {searchMutation.data && (
        <Card>
          <CardHeader className="py-3">
            <CardTitle className="text-sm">
              {searchMutation.data.results.length} result{searchMutation.data.results.length === 1 ? "" : "s"} for “{searchMutation.data.query}”
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {searchMutation.data.results.length ? (
              searchMutation.data.results.map((r, i) => resultRow(r, `s-${i}`))
            ) : (
              <p className="text-sm text-muted-foreground">No matches. Try different wording — the search is semantic, not keyword-based.</p>
            )}
          </CardContent>
        </Card>
      )}

      <ClipPlayerDialog clip={playerClip} onClose={() => setPlayerClip(null)} />
    </div>
  );
}
