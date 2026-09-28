import { Link } from "wouter";
import type { SearchResponse, SearchResult } from "@workspace/api-client-react";
import { Button } from "@/components/ui/button";
import { Check, ExternalLink, Film, Play, SearchX } from "lucide-react";
import { formatTC } from "@/lib/timecode";
import { groupSearchResults, MATCH_LABEL, momentKey, SEARCH_LIMIT, type AssetMatchGroup } from "@/lib/library-search";

const MAX_MOMENTS_SHOWN = 6;

type Props = {
  data: SearchResponse | null;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  view: "grid" | "list";
  gridClass: string;
  selectedAssets: Set<string>;
  onToggleAsset: (id: string) => void;
  selectedMoments: Record<string, SearchResult>;
  onToggleMoment: (r: SearchResult) => void;
  onPlay: (r: SearchResult) => void;
  onClearSearch: () => void;
};

function Checkbox({ on, label, onClick, className = "" }: { on: boolean; label: string; onClick: () => void; className?: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={on}
      title={label}
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); onClick(); }}
      className={`h-5 w-5 shrink-0 rounded border flex items-center justify-center transition-colors ${on ? "bg-primary border-primary text-primary-foreground" : "bg-background/70 border-muted-foreground/40 text-transparent hover:border-foreground"} ${className}`}
    >
      <Check className="h-3.5 w-3.5" />
    </button>
  );
}

function MomentRow({ r, selected, onToggle, onPlay }: { r: SearchResult; selected: boolean; onToggle: () => void; onPlay: () => void }) {
  return (
    <li className={`group/m flex items-start gap-2 rounded-md px-1.5 py-1 text-xs ${selected ? "bg-primary/10" : "hover:bg-muted/50"}`} data-testid="search-moment">
      <Checkbox on={selected} label={selected ? "Deselect moment" : "Select moment"} onClick={onToggle} className="mt-0.5 h-4 w-4" />
      <Link
        href={`/library/${r.media_id}?t=${Math.floor(r.start_time)}`}
        className="font-mono tabular-nums text-primary hover:underline underline-offset-2 shrink-0 mt-px"
        title="Open the asset at this moment"
        data-testid="link-search-timestamp"
      >
        {formatTC(r.start_time, 25, false)}
      </Link>
      <span className="min-w-0 flex-1">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground mr-1.5">{MATCH_LABEL[r.match_type] ?? r.match_type}</span>
        {r.snippet ? <span className="text-foreground/85 line-clamp-2 inline">&ldquo;{r.snippet}&rdquo;</span> : null}
      </span>
      <button type="button" onClick={onPlay} title="Play this moment" aria-label="Play this moment"
        className="shrink-0 h-5 w-5 flex items-center justify-center rounded text-muted-foreground hover:text-foreground opacity-60 group-hover/m:opacity-100">
        <Play className="h-3.5 w-3.5" />
      </button>
    </li>
  );
}

function GroupCard({ g, list, p }: { g: AssetMatchGroup; list: boolean; p: Props }) {
  const assetOn = p.selectedAssets.has(g.media_id);
  const first = g.moments[0];
  const shown = g.moments.slice(0, MAX_MOMENTS_SHOWN);
  const hidden = g.moments.length - shown.length;
  const thumb = (
    <div className={`relative bg-muted overflow-hidden shrink-0 ${list ? "w-40 aspect-video rounded" : "w-full aspect-video"}`}>
      {g.thumbnail_url
        ? <img src={`/api/thumbnails/${g.thumbnail_url}`} alt="" loading="lazy" className="w-full h-full object-cover" />
        : <div className="absolute inset-0 flex items-center justify-center"><Film className="h-7 w-7 text-muted-foreground/50" /></div>}
      <span className="absolute top-1.5 right-1.5 text-[10px] font-mono tabular-nums px-1.5 py-0.5 rounded bg-background/85 text-foreground">#{g.rank + 1}</span>
      {first && (
        <button type="button" onClick={() => p.onPlay(first)} aria-label="Play best moment"
          className="absolute inset-0 flex items-center justify-center bg-background/0 hover:bg-background/40 transition-colors group/play">
          <Play className="h-7 w-7 text-foreground opacity-0 group-hover/play:opacity-100 transition-opacity" />
        </button>
      )}
    </div>
  );
  return (
    <article
      data-testid="search-asset-card"
      data-asset-id={g.media_id}
      className={`relative border bg-card rounded-md overflow-hidden flex ${list ? "flex-row gap-3 p-2" : "flex-col"} ${assetOn ? "border-primary ring-1 ring-primary" : "border-border"}`}
    >
      <Checkbox on={assetOn} label={assetOn ? "Deselect asset" : "Select asset"} onClick={() => p.onToggleAsset(g.media_id)}
        className={list ? "self-start mt-1" : "absolute top-1.5 left-1.5 z-10"} />
      {thumb}
      <div className={`min-w-0 flex-1 flex flex-col gap-1 ${list ? "" : "p-2.5"}`}>
        <div className="flex items-start gap-2">
          <Link href={`/library/${g.media_id}`} className="font-medium text-sm truncate flex-1 hover:underline underline-offset-2" title={g.filename} data-testid="link-search-asset">
            {g.filename}
          </Link>
          <Button asChild size="icon" variant="ghost" className="h-6 w-6 -mt-0.5 shrink-0" title="Open asset">
            <Link href={`/library/${g.media_id}`}><ExternalLink className="h-3.5 w-3.5" /></Link>
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-1 text-[10px] uppercase tracking-wider text-muted-foreground">
          {g.matchTypes.map((t) => <span key={t} className="px-1.5 py-0.5 rounded border border-border">{MATCH_LABEL[t] ?? t}</span>)}
          {g.moments.length > 0 && <span className="normal-case tracking-normal">{g.moments.length} moment{g.moments.length === 1 ? "" : "s"}</span>}
        </div>
        {shown.length > 0 && (
          <ul className="mt-0.5 space-y-0.5">
            {shown.map((m) => {
              const k = momentKey(m);
              return <MomentRow key={k} r={m} selected={!!p.selectedMoments[k]} onToggle={() => p.onToggleMoment(m)} onPlay={() => p.onPlay(m)} />;
            })}
          </ul>
        )}
        {hidden > 0 && (
          <Link href={`/library/${g.media_id}?t=${Math.floor(g.moments[MAX_MOMENTS_SHOWN].start_time)}`} className="text-xs text-muted-foreground hover:text-foreground px-1.5">
            +{hidden} more in this asset
          </Link>
        )}
        {g.filenameMatch && !g.moments.length && <p className="text-xs text-muted-foreground">Filename match</p>}
      </div>
    </article>
  );
}

export function LibrarySearchResults(p: Props) {
  if (p.error) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-md border border-destructive/40 p-4" role="alert" data-testid="search-error">
        <p className="text-sm">Search didn't complete. Your query and filters are unchanged.</p>
        <Button variant="outline" onClick={p.onRetry} data-testid="button-search-retry">Retry</Button>
      </div>
    );
  }
  if (p.loading && !p.data) {
    return (
      <div className={p.view === "grid" ? p.gridClass : "space-y-2"} data-testid="search-loading">
        {[...Array(8)].map((_, i) => <div key={i} className={`animate-pulse bg-muted rounded-md ${p.view === "grid" ? "aspect-[4/3]" : "h-24"}`} />)}
      </div>
    );
  }
  if (!p.data) return null;
  const groups = groupSearchResults(p.data.results);
  if (!groups.length) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center gap-3 py-16 text-muted-foreground" data-testid="search-empty">
        <SearchX className="h-10 w-10 opacity-50" />
        <p className="text-sm max-w-sm">Nothing in this scope matched &ldquo;{p.data.query}&rdquo;. Try other wording, widen the scope under Filters, or leave the current folder.</p>
        <Button variant="outline" size="sm" onClick={p.onClearSearch}>Back to browsing</Button>
      </div>
    );
  }
  const capped = p.data.results.length >= SEARCH_LIMIT;
  return (
    <div className={p.loading ? "opacity-60 transition-opacity" : "transition-opacity"}>
      <p className="text-xs text-muted-foreground mb-3 tabular-nums" data-testid="search-summary">
        {p.data.results.length} ranked match{p.data.results.length === 1 ? "" : "es"} across {groups.length} asset{groups.length === 1 ? "" : "s"}
        {capped ? ` · top ${SEARCH_LIMIT} only, refine to narrow` : ""} · ordered by relevance
      </p>
      <div className={p.view === "grid" ? p.gridClass : "space-y-2"}>
        {groups.map((g) => <GroupCard key={g.media_id} g={g} list={p.view === "list"} p={p} />)}
      </div>
    </div>
  );
}
