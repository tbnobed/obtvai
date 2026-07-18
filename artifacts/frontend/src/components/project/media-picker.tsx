import { useEffect, useMemo, useState } from "react";
import { useListMedia, getListMediaQueryKey } from "@workspace/api-client-react";
import type { MediaAsset } from "@workspace/api-client-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Play, Search, X } from "lucide-react";
import { ClipThumb } from "./clip-thumb";

function MediaStatusBadge({ status }: { status: string }) {
  if (status === "ready") return null;
  const cls = status === "error"
    ? "text-red-400 border-red-500/40"
    : "text-blue-400 border-blue-500/40";
  return (
    <Badge variant="outline" className={`shrink-0 text-[10px] px-1.5 py-0 capitalize ${cls}`}>
      {status === "processing" || status === "pending" ? "indexing…" : status}
    </Badge>
  );
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

type MediaPickerProps = {
  selected: string[];
  onToggle: (id: string, checked: boolean) => void;
  onPreview: (asset: MediaAsset) => void;
  /** Only these asset ids are shown at all (e.g. the project's media pool). */
  restrictTo?: string[];
  /** Only "ready" assets can be checked (they can always be unchecked). */
  requireReady?: boolean;
  togglesDisabled?: boolean;
  gridClass?: string;
  emptyText: string;
};

export function MediaPickerGrid({
  selected, onToggle, onPreview, restrictTo, requireReady = false,
  togglesDisabled = false, gridClass = "sm:grid-cols-2 lg:grid-cols-3", emptyText,
}: MediaPickerProps) {
  const [searchText, setSearchText] = useState("");
  const [selectedOnly, setSelectedOnly] = useState(false);
  const search = useDebounced(searchText.trim(), 300);

  const mediaParams = useMemo(
    () => ({ limit: 200, ...(search ? { search } : {}) }),
    [search],
  );
  const { data: media, error, isFetching } = useListMedia(mediaParams, {
    query: { queryKey: getListMediaQueryKey(mediaParams), placeholderData: (p) => p },
  });

  const items = useMemo(() => {
    let list = media?.items ?? [];
    if (restrictTo && restrictTo.length) list = list.filter((a) => restrictTo.includes(a.id));
    if (selectedOnly) list = list.filter((a) => selected.includes(a.id));
    // Selected assets first so the current pool is always visible at the top.
    return [...list].sort(
      (a, b) => Number(selected.includes(b.id)) - Number(selected.includes(a.id)),
    );
  }, [media?.items, restrictTo, selectedOnly, selected]);

  const total = media?.total ?? 0;
  const fetched = media?.items?.length ?? 0;
  const hiddenSelected = selectedOnly
    ? selected.filter((sid) => !(media?.items ?? []).some((a) => a.id === sid)).length
    : 0;
  const truncated =
    !selectedOnly &&
    total > fetched &&
    (!restrictTo || !restrictTo.length ||
      restrictTo.some((rid) => !(media?.items ?? []).some((a) => a.id === rid)));

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="Search by filename or title…"
            className="h-8 pl-8 pr-8 text-sm"
          />
          {searchText && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => setSearchText("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        {selected.length > 0 && (
          <Button
            size="sm"
            variant={selectedOnly ? "default" : "outline"}
            className="h-8 shrink-0"
            onClick={() => setSelectedOnly((v) => !v)}
          >
            Selected ({selected.length})
          </Button>
        )}
      </div>

      <div className={`grid gap-2 max-h-64 overflow-y-auto ${gridClass}`}>
        {items.length ? items.map((a) => {
          const isSelected = selected.includes(a.id);
          const toggleDisabled = togglesDisabled || (requireReady && !isSelected && a.status !== "ready");
          return (
            <label
              key={a.id}
              className={`flex items-center gap-2 text-sm bg-muted/50 rounded p-2 ${toggleDisabled ? "opacity-60" : "cursor-pointer"}`}
            >
              <input
                type="checkbox"
                checked={isSelected}
                disabled={toggleDisabled}
                onChange={(e) => onToggle(a.id, e.target.checked)}
              />
              <ClipThumb url={a.thumbnail_url} className="h-8 w-12" />
              <span className="truncate flex-1">{a.filename}</span>
              <MediaStatusBadge status={a.status} />
              <Button
                size="icon" variant="ghost" className="h-6 w-6 shrink-0" title="Preview this asset"
                disabled={a.status !== "ready"}
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  onPreview(a);
                }}
              >
                <Play className="h-3 w-3" />
              </Button>
            </label>
          );
        }) : (
          <p className="text-sm text-muted-foreground col-span-full">
            {error
              ? `Couldn't load the media library: ${error instanceof Error ? error.message : "unknown error"}`
              : !media
                ? "Loading media library…"
                : search || selectedOnly
                  ? "No assets match this search."
                  : emptyText}
          </p>
        )}
      </div>

      {truncated && (
        <p className="text-xs text-muted-foreground">
          Showing {fetched} of {total} assets{isFetching ? "…" : ""} — type in the search box to find the rest.
        </p>
      )}
      {hiddenSelected > 0 && (
        <p className="text-xs text-muted-foreground">
          {hiddenSelected} selected asset{hiddenSelected === 1 ? " isn't" : "s aren't"} shown here
          {search ? " (outside this search)" : " (outside the first page)"} — search by filename to see {hiddenSelected === 1 ? "it" : "them"}.
        </p>
      )}
    </div>
  );
}
