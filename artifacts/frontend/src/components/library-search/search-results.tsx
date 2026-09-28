import { useState } from "react";
import { Link } from "wouter";
import type { SearchResponse, SearchResult } from "@workspace/api-client-react";
import { Button } from "@/components/ui/button";
import { Check, ChevronDown, ChevronUp, ExternalLink, Film, Play, SearchX } from "lucide-react";
import { formatTC } from "@/lib/timecode";
import { groupSearchResults, MATCH_LABEL, momentKey, SEARCH_LIMIT, type AssetMatchGroup } from "@/lib/library-search";

/** Moments revealed per "show more" step once a card is expanded. */
const MOMENT_PAGE = 6;

/**
 * Search results use their own grid: cards never shrink below 280px (320px
 * preferred) regardless of the browse card-size setting, and collapse to a
 * single column on narrow screens.
 */
export const SEARCH_GRID_CLASS =
  "grid gap-3 grid-cols-1 sm:grid-cols-[repeat(auto-fill,minmax(min(100%,320px),1fr))]";

type Props = {
  data: SearchResponse | null;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  view: "grid" | "list";
  selectedAssets: Set<string>;
  onToggleAsset: (id: string) => void;
  selectedMoments: Record<string, SearchResult>;
  onToggleMoment: (r: SearchResult) => void;
  onPlay: (r: SearchResult) => void;
  onClearSearch: () => void;
};

function Checkbox({ on, label, onClick, className = "", testId }: { on: boolean; label: string; onClick: () => void; className?: string; testId?: string }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-label={label}
      aria-checked={on}
      title={label}
      data-testid={testId}
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); onClick(); }}
      className={`h-5 w-5 shrink-0 rounded border flex items-center justify-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${on ? "bg-primary border-primary text-primary-foreground" : "bg-background/85 border-muted-foreground/50 text-transparent hover:border-foreground"} ${className}`}
    >
      <Check className="h-3.5 w-3.5" />
    </button>
  );
}

function TimeLink({ r }: { r: SearchResult }) {
  return (
    <Link
      href={`/library/${r.media_id}?t=${Math.floor(r.start_time)}`}
      className="font-mono tabular-nums text-[11px] font-medium px-1.5 py-0.5 rounded bg-primary/10 text-primary hover:bg-primary/20 shrink-0"
      title={`Open the asset at ${formatTC(r.start_time, 25, false)}`}
      data-testid="link-search-timestamp"
    >
      {formatTC(r.start_time, 25, false)}
    </Link>
  );
}

/** Snippet clamped to `lines`; the full text is one click away (and always in the title/aria). */
function Snippet({ text, lines }: { text: string; lines: 2 | 3 }) {
  const [full, setFull] = useState(false);
  const long = text.length > (lines === 2 ? 110 : 160);
  return (
    <span className="block min-w-0">
      <span
        className={`text-foreground/85 break-words ${full ? "block" : lines === 2 ? "line-clamp-2" : "line-clamp-3"}`}
        title={full ? undefined : text}
        data-testid="search-snippet"
      >
        {text}
      </span>
      {long && (
        <button type="button" onClick={() => setFull((f) => !f)} aria-expanded={full}
          className="text-[11px] text-muted-foreground hover:text-foreground underline underline-offset-2"
          data-testid="button-snippet-full">
          {full ? "Show less" : "Full text"}
        </button>
      )}
    </span>
  );
}

function MomentRow({ r, selected, onToggle, onPlay }: { r: SearchResult; selected: boolean; onToggle: () => void; onPlay: () => void }) {
  return (
    <li className={`flex items-start gap-2 rounded-md px-1.5 py-1.5 text-xs ${selected ? "bg-primary/10" : "hover:bg-muted/50"}`} data-testid="search-moment">
      <Checkbox on={selected} label={selected ? "Deselect moment" : "Select moment"} onClick={onToggle} className="mt-0.5 h-4 w-4" testId="checkbox-search-moment" />
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex items-center gap-1.5">
          <TimeLink r={r} />
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{MATCH_LABEL[r.match_type] ?? r.match_type}</span>
        </div>
        {r.snippet ? <Snippet text={r.snippet} lines={2} /> : null}
      </div>
      <button type="button" onClick={onPlay} title="Play this moment" aria-label={`Play moment at ${formatTC(r.start_time, 25, false)}`}
        className="shrink-0 h-6 w-6 flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted">
        <Play className="h-3.5 w-3.5" />
      </button>
    </li>
  );
}

function GroupCard({ g, list, p }: { g: AssetMatchGroup; list: boolean; p: Props }) {
  const [shown, setShown] = useState(0);
  const assetOn = p.selectedAssets.has(g.media_id);
  const best = g.moments[0];
  const rest = g.moments.slice(1);
  const visibleRest = rest.slice(0, shown);
  const expanded = shown > 0;
  const bestKey = best ? momentKey(best) : "";
  const count = g.moments.length;
  return (
    <article
      data-testid="search-asset-card"
      data-asset-id={g.media_id}
      className={`relative min-w-0 border bg-card rounded-lg overflow-hidden flex ${list ? "flex-col sm:flex-row sm:gap-3 sm:p-2" : "flex-col"} ${assetOn ? "border-primary ring-1 ring-primary" : "border-border"}`}
    >
      <div className={`relative bg-muted overflow-hidden shrink-0 ${list ? "w-full sm:w-48 aspect-video sm:rounded" : "w-full aspect-video"}`}>
        {g.thumbnail_url
          ? <img src={`/api/thumbnails/${g.thumbnail_url}`} alt="" loading="lazy" className="w-full h-full object-cover" />
          : <div className="absolute inset-0 flex items-center justify-center"><Film className="h-7 w-7 text-muted-foreground/50" /></div>}
        {best && (
          <button type="button" onClick={() => p.onPlay(best)} aria-label={`Play ${g.filename} from ${formatTC(best.start_time, 25, false)}`}
            data-testid="button-search-play"
            className="absolute inset-0 flex items-center justify-center group/play focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
            <span className="h-10 w-10 rounded-full bg-background/85 text-foreground flex items-center justify-center shadow-sm transition-transform group-hover/play:scale-110">
              <Play className="h-4 w-4 translate-x-px" />
            </span>
          </button>
        )}
        <div className="absolute top-2 left-2 z-10">
          <Checkbox on={assetOn} label={assetOn ? `Deselect ${g.filename}` : `Select ${g.filename}`} onClick={() => p.onToggleAsset(g.media_id)} testId="checkbox-search-asset" />
        </div>
        <span className="absolute top-2 right-2 text-[10px] font-mono tabular-nums px-1.5 py-0.5 rounded bg-background/85 text-foreground pointer-events-none">#{g.rank + 1}</span>
        {best && (
          <span className="absolute bottom-2 left-2 text-[11px] font-mono tabular-nums px-1.5 py-0.5 rounded bg-background/90 text-foreground pointer-events-none">
            {formatTC(best.start_time, 25, false)}
          </span>
        )}
      </div>

      <div className={`min-w-0 flex-1 flex flex-col gap-1.5 ${list ? "p-3 sm:p-1" : "p-3"}`}>
        <div className="flex items-center gap-2 min-w-0">
          <Link href={`/library/${g.media_id}`} className="font-medium text-sm truncate flex-1 min-w-0 hover:underline underline-offset-2" title={g.filename} data-testid="link-search-asset">
            {g.filename}
          </Link>
          <Button asChild size="sm" variant="outline" className="h-7 px-2 gap-1 shrink-0 text-xs">
            <Link href={best ? `/library/${g.media_id}?t=${Math.floor(best.start_time)}` : `/library/${g.media_id}`} aria-label={`Open ${g.filename}`} data-testid="button-search-open">
              <ExternalLink className="h-3.5 w-3.5" /> Open
            </Link>
          </Button>
        </div>

        {best ? (
          <div className={`flex items-start gap-2 rounded-md text-xs ${p.selectedMoments[bestKey] ? "bg-primary/10 -mx-1 px-1 py-1" : ""}`} data-testid="search-best-match">
            <Checkbox on={!!p.selectedMoments[bestKey]} label={p.selectedMoments[bestKey] ? "Deselect best moment" : "Select best moment"}
              onClick={() => p.onToggleMoment(best)} className="mt-0.5 h-4 w-4" testId="checkbox-search-moment" />
            <div className="min-w-0 flex-1 space-y-0.5">
              <div className="flex items-center gap-1.5 flex-wrap">
                <TimeLink r={best} />
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{MATCH_LABEL[best.match_type] ?? best.match_type}</span>
              </div>
              {best.snippet ? <Snippet text={best.snippet} lines={3} /> : null}
            </div>
          </div>
        ) : (
          g.filenameMatch && <p className="text-xs text-muted-foreground">Filename match</p>
        )}

        <div className="flex items-center gap-2 flex-wrap text-[11px] text-muted-foreground mt-auto pt-1">
          {count > 0 && <span className="tabular-nums font-medium text-foreground/80" data-testid="text-moment-count">{count} matching moment{count === 1 ? "" : "s"}</span>}
          {g.matchTypes.map((t) => <span key={t} className="px-1.5 py-px rounded border border-border uppercase tracking-wider text-[10px]">{MATCH_LABEL[t] ?? t}</span>)}
          {rest.length > 0 && (
            <button type="button" className="ml-auto inline-flex items-center gap-1 text-primary hover:underline underline-offset-2"
              aria-expanded={expanded} aria-controls={`moments-${g.media_id}`} data-testid="button-toggle-moments"
              onClick={() => setShown((s) => (s ? 0 : MOMENT_PAGE))}>
              {expanded ? <>Hide moments <ChevronUp className="h-3 w-3" /></> : <>{rest.length} more <ChevronDown className="h-3 w-3" /></>}
            </button>
          )}
        </div>

        {expanded && (
          <div id={`moments-${g.media_id}`} className="border-t border-border pt-1.5">
            <ul className="space-y-0.5" aria-label={`More matching moments in ${g.filename}`}>
              {visibleRest.map((m) => {
                const k = momentKey(m);
                return <MomentRow key={k} r={m} selected={!!p.selectedMoments[k]} onToggle={() => p.onToggleMoment(m)} onPlay={() => p.onPlay(m)} />;
              })}
            </ul>
            {rest.length > visibleRest.length && (
              <button type="button" className="mt-1 text-xs text-muted-foreground hover:text-foreground px-1.5" data-testid="button-more-moments"
                onClick={() => setShown((s) => s + MOMENT_PAGE)}>
                Show {Math.min(MOMENT_PAGE, rest.length - visibleRest.length)} more of {rest.length - visibleRest.length}
              </button>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

export function LibrarySearchResults(p: Props) {
  const grid = p.view === "grid" ? SEARCH_GRID_CLASS : "space-y-2";
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
      <div className={grid} data-testid="search-loading" aria-busy="true">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="rounded-lg border border-border overflow-hidden">
            <div className="aspect-video animate-pulse bg-muted" />
            <div className="p-3 space-y-2"><div className="h-3 w-2/3 bg-muted animate-pulse rounded" /><div className="h-3 w-full bg-muted animate-pulse rounded" /></div>
          </div>
        ))}
      </div>
    );
  }
  if (!p.data) return null;
  const groups = groupSearchResults(p.data.results);
  if (!groups.length) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center gap-3 py-16 text-muted-foreground" data-testid="search-empty">
        <SearchX className="h-10 w-10 opacity-50" />
        <p className="text-sm max-w-sm">Nothing in this scope matched &ldquo;{p.data.query}&rdquo;. Try other wording, switch to Everything, or clear active filters.</p>
        <Button variant="outline" size="sm" onClick={p.onClearSearch}>Back to browsing</Button>
      </div>
    );
  }
  const capped = p.data.results.length >= SEARCH_LIMIT;
  return (
    <div className={p.loading ? "opacity-60 transition-opacity" : "transition-opacity"}>
      <div className="flex items-baseline gap-x-2 gap-y-0.5 flex-wrap mb-3" data-testid="search-summary">
        <p className="text-sm font-medium tabular-nums">
          {groups.length} asset{groups.length === 1 ? "" : "s"}
          <span className="text-muted-foreground font-normal"> · {p.data.results.length} matching moment{p.data.results.length === 1 ? "" : "s"}, best first</span>
        </p>
        {capped && <p className="text-[11px] text-muted-foreground">Showing the top {SEARCH_LIMIT} matches. Refine to narrow.</p>}
      </div>
      <div className={grid} data-testid="search-results-grid">
        {groups.map((g) => <GroupCard key={g.media_id} g={g} list={p.view === "list"} p={p} />)}
      </div>
    </div>
  );
}
