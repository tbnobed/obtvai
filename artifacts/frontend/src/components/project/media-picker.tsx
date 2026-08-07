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
  /** Batch select/deselect (e.g. "Select all" on search results) in one update. */
  onToggleMany?: (ids: string[], checked: boolean) => void;
  onPreview: (asset: MediaAsset) => void;
  /** Only these asset ids are shown at all (e.g. the project's media pool). */
  restrictTo?: string[];
  /** Only "ready" assets can be checked (they can always be unchecked). */
  requireReady?: boolean;
  togglesDisabled?: boolean;
  gridClass?: string;
  emptyText: string;
  /** Show selected assets as a prominent thumbnail strip above the library list. */
  selectedStrip?: boolean;
};

export function MediaPickerGrid({
  selected, onToggle, onToggleMany, onPreview, restrictTo, requireReady = false,
  togglesDisabled = false, gridClass = "sm:grid-cols-2 lg:grid-cols-3", emptyText,
  selectedStrip = false,
}: MediaPickerProps) {
  const [searchText, setSearchText] = useState("");
  const [selectedOnly, setSelectedOnly] = useState(false);
  const search = useDebounced(searchText.trim(), 300);

  // When the grid is restricted to a fixed pool (e.g. a project's source
  // assets), resolve those exact ids — paging through the newest 200 library
  // assets can miss pool members and silently hide them from the picker.
  const restrictKey = restrictTo && restrictTo.length ? [...restrictTo].sort().join(",") : "";
  const mediaParams = useMemo(
    () =>
      restrictKey
        ? { ids: restrictKey, limit: Math.min(Math.max(restrictKey.split(",").length, 1), 200) }
        : { limit: 200, ...(search ? { search } : {}) },
    [search, restrictKey],
  );
  const { data: media, error, isFetching } = useListMedia(mediaParams, {
    query: { queryKey: getListMediaQueryKey(mediaParams), placeholderData: (p) => p },
  });

  const items = useMemo(() => {
    let list = media?.items ?? [];
    if (restrictTo && restrictTo.length) list = list.filter((a) => restrictTo.includes(a.id));
    if (selectedOnly) list = list.filter((a) => selected.includes(a.id));
    // Also filter client-side so typing always visibly narrows the list, even
    // if the server returns unfiltered results (stale API) or while the
    // debounced request is still showing placeholder data.
    const needle = search.toLowerCase();
    if (needle) {
      list = list.filter((a) =>
        [a.filename, needle.includes("/") ? a.original_path : null].some(
          (v) => typeof v === "string" && v.toLowerCase().includes(needle),
        ),
      );
    }
    // Selected assets first so the current pool is always visible at the top.
    return [...list].sort(
      (a, b) => Number(selected.includes(b.id)) - Number(selected.includes(a.id)),
    );
  }, [media?.items, restrictTo, selectedOnly, selected, search]);

  const selectedAssets = useMemo(
    () => (selectedStrip ? items.filter((a) => selected.includes(a.id)) : []),
    [items, selected, selectedStrip],
  );
  // With the strip shown, the list below only offers what's NOT yet selected.
  const listItems = useMemo(
    () => (selectedStrip ? items.filter((a) => !selected.includes(a.id)) : items),
    [items, selected, selectedStrip],
  );

  const selectableIds = useMemo(
    () => items
      .filter((a) => !selected.includes(a.id) && !(requireReady && a.status !== "ready"))
      .map((a) => a.id),
    [items, selected, requireReady],
  );
  const visibleSelectedIds = useMemo(
    () => items.filter((a) => selected.includes(a.id)).map((a) => a.id),
    [items, selected],
  );

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
        {onToggleMany && selectableIds.length > 0 && (
          <Button
            size="sm"
            variant="outline"
            className="h-8 shrink-0"
            disabled={togglesDisabled}
            onClick={() => onToggleMany(selectableIds, true)}
          >
            Select all ({selectableIds.length})
          </Button>
        )}
        {onToggleMany && selectableIds.length === 0 && visibleSelectedIds.length > 0 && (
          <Button
            size="sm"
            variant="outline"
            className="h-8 shrink-0"
            disabled={togglesDisabled}
            onClick={() => onToggleMany(visibleSelectedIds, false)}
          >
            Deselect all ({visibleSelectedIds.length})
          </Button>
        )}
        {!selectedStrip && selected.length > 0 && (
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

      {selectedStrip && selectedAssets.length > 0 && (
        <div className="rounded-lg border border-primary/25 bg-primary/[0.04] p-3 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-primary">
              In this project — {selected.length} asset{selected.length === 1 ? "" : "s"}
            </p>
            {onToggleMany && visibleSelectedIds.length > 1 && (
              <Button
                size="sm" variant="ghost" className="h-7 text-xs text-muted-foreground"
                disabled={togglesDisabled}
                onClick={() => onToggleMany(visibleSelectedIds, false)}
              >
                Remove all
              </Button>
            )}
          </div>
          <div className="grid gap-2 grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
            {selectedAssets.map((a) => (
              <div
                key={a.id}
                className="group relative rounded-md overflow-hidden border border-border/60 bg-muted/40"
              >
                <button
                  type="button"
                  className="block w-full text-left"
                  title={a.status === "ready" ? "Preview this asset" : a.filename}
                  disabled={a.status !== "ready"}
                  onClick={() => onPreview(a)}
                >
                  <div className="relative">
                    <ClipThumb url={a.thumbnail_url} className="aspect-video w-full" />
                    {a.status === "ready" && (
                      <span className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/35 transition-colors">
                        <Play className="h-5 w-5 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1 px-1.5 py-1">
                    <span className="truncate text-[11px] leading-tight flex-1">{a.filename}</span>
                    <MediaStatusBadge status={a.status} />
                  </div>
                </button>
                <button
                  type="button"
                  aria-label={`Remove ${a.filename} from this project`}
                  title="Remove from this project"
                  disabled={togglesDisabled}
                  onClick={() => onToggle(a.id, false)}
                  className="absolute top-1 right-1 rounded-full bg-black/60 p-1 text-white/80 hover:text-white hover:bg-black/80 opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className={`grid gap-2 max-h-64 overflow-y-auto ${gridClass}`}>
        {listItems.length ? listItems.map((a) => {
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
                : selectedStrip && selectedAssets.length > 0
                  ? search
                    ? "No other assets match this search."
                    : "Every other library asset is already in this project."
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
