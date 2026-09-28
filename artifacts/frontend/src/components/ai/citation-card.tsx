import { useState } from "react";
import { Link } from "wouter";
import { useGetMedia, getGetMediaQueryKey } from "@workspace/api-client-react";
import { Film, Play, AlertTriangle, RefreshCw } from "lucide-react";
import { citationHref, formatTimecode, isAssetLevelCitation, mediaLookupState, type CitationGroup } from "@/lib/ai-citations";

function Thumb({ src, alt }: { src: string | null; alt: string }) {
  const [broken, setBroken] = useState(false);
  if (!src || broken) {
    return (
      <div className="absolute inset-0 flex items-center justify-center bg-muted/60" data-testid="img-citation-fallback">
        <Film className="h-5 w-5 text-muted-foreground/60" />
      </div>
    );
  }
  return <img src={src} alt={alt} onError={() => setBroken(true)} className="absolute inset-0 h-full w-full object-cover" draggable={false} />;
}

/** One cited asset: real thumbnail resolved from the library, plus its timestamped moments. */
export function CitationCard({ group }: { group: CitationGroup }) {
  const { data: asset, isLoading, isError, error, refetch, isFetching } = useGetMedia(group.mediaId, {
    query: { queryKey: getGetMediaQueryKey(group.mediaId), retry: false, staleTime: 60_000 },
  });
  const unavailable = isError ? mediaLookupState(error) === "missing" : (!isLoading && !asset);
  const transient = isError && !unavailable;
  const name = asset?.filename ?? group.filename ?? "Untitled asset";
  const first = group.moments[0];

  return (
    <div
      className={`rounded-lg border overflow-hidden ${unavailable ? "border-dashed border-border/70 bg-background/30" : "border-border/70 bg-background/60"}`}
      data-testid={`card-citation-${group.mediaId}`}
    >
      <div className="flex gap-3 p-2">
        {unavailable ? (
          <div className="relative w-24 aspect-video shrink-0 rounded bg-muted/40 flex items-center justify-center">
            <AlertTriangle className="h-4 w-4 text-muted-foreground" />
          </div>
        ) : (
          <Link href={first ? citationHref(group.mediaId, first) : `/library/${encodeURIComponent(group.mediaId)}`} className="group relative w-24 aspect-video shrink-0 rounded overflow-hidden bg-muted" data-testid={`link-citation-thumb-${group.mediaId}`}>
            {isLoading ? <div className="absolute inset-0 animate-pulse bg-muted" /> : <Thumb src={asset?.thumbnail_url ? `/api/thumbnails/${asset.thumbnail_url}` : null} alt={name} />}
            <span className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/40 transition-colors">
              <Play className="h-4 w-4 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
            </span>
          </Link>
        )}
        <div className="min-w-0 flex-1">
          <div className="text-xs font-medium truncate" title={name}>{isLoading ? <span className="inline-block h-3 w-32 rounded bg-muted animate-pulse" /> : name}</div>
          <div className="text-[11px] text-muted-foreground mt-0.5">
            {transient ? (
              <span className="inline-flex items-center gap-1.5">
                Couldn't load asset details.
                <button type="button" onClick={() => refetch()} disabled={isFetching} className="inline-flex items-center gap-1 text-primary hover:underline disabled:opacity-50" data-testid={`button-retry-citation-${group.mediaId}`}>
                  <RefreshCw className={`h-3 w-3 ${isFetching ? "animate-spin" : ""}`} /> Retry
                </button>
              </span>
            ) : unavailable
              ? "No longer in the library — it may have been deleted or you lack access."
              : `${group.moments.length} moment${group.moments.length === 1 ? "" : "s"}${asset?.duration_seconds ? ` · ${formatTimecode(asset.duration_seconds)} total` : ""}`}
          </div>
        </div>
      </div>
      <ul className="border-t border-border/50 divide-y divide-border/40">
        {group.moments.map(m => {
          const body = (
            <>
              <span className="font-mono text-[10px] text-muted-foreground w-6 shrink-0">[{m.index}]</span>
              <span className={`font-mono text-[11px] shrink-0 ${unavailable ? "text-muted-foreground" : "text-primary"}`}>{isAssetLevelCitation(m) ? "Asset" : formatTimecode(m.start_time)}</span>
              <span className="text-[11px] text-muted-foreground line-clamp-2 min-w-0">{m.snippet ? `“${m.snippet}”` : isAssetLevelCitation(m) ? "Open asset details" : `to ${formatTimecode(m.end_time)}`}</span>
            </>
          );
          return (
            <li key={`${m.index}`}>
              {unavailable ? (
                <div className="flex items-start gap-2 px-2 py-1.5 opacity-70">{body}</div>
              ) : (
                <Link href={citationHref(group.mediaId, m)} className="flex items-start gap-2 px-2 py-1.5 hover:bg-muted/50 transition-colors" data-testid={`link-moment-${group.mediaId}-${m.index}`}>
                  {body}
                </Link>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
