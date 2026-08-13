import { useState } from "react";
import {
  useListCuratorFolders, getListCuratorFoldersQueryKey, useSelectCuratorFolder,
} from "@workspace/api-client-react";
import type { CuratorFolderOut } from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/hooks/use-toast";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Folder, HardDrive, Loader2, RefreshCw, Search,
} from "lucide-react";

/** Curator ingest page (admins only): browse the Curator share and check
 * folders to ingest — existing clips import within a minute and new files
 * keep importing automatically. */
export default function CuratorPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { data: tree, isLoading, isError, refetch, isFetching } =
    useListCuratorFolders({ query: { queryKey: getListCuratorFoldersQueryKey(), staleTime: 60_000, retry: false } });
  const selectFolder = useSelectCuratorFolder();
  const [search, setSearch] = useState("");
  const [showSelectedOnly, setShowSelectedOnly] = useState(false);

  const childrenOf = (parent: string | null) =>
    (tree?.items ?? []).filter(c => (c.parent ?? null) === parent);

  const selectedCount = (tree?.items ?? []).filter(c => c.selected).length;

  const toggleIngest = (c: CuratorFolderOut) => {
    selectFolder.mutate(
      { data: { path: c.path, selected: !c.selected } },
      {
        onSuccess: () => queryClient.invalidateQueries({ queryKey: getListCuratorFoldersQueryKey() }),
        onError: () => toast({ title: "Could not update Curator folder", variant: "destructive" }),
      }
    );
  };

  // Full tree rendered expanded (nothing hides behind chevrons); filter by
  // path substring and optionally by selection state.
  const renderNode = (c: CuratorFolderOut, depth: number): React.ReactElement | null => {
    const kids = childrenOf(c.path);
    const q = search.trim().toLowerCase();
    const selfMatch = (!q || c.path.toLowerCase().includes(q)) && (!showSelectedOnly || c.selected);
    const renderedKids = kids.map(k => renderNode(k, depth + 1)).filter(Boolean);
    if (!selfMatch && !renderedKids.length) return null;
    return (
      <div key={c.path}>
        <div
          className="flex items-center gap-2 h-10 px-2 rounded-md text-sm select-none hover:bg-muted/50 border-b border-border/40"
          style={{ paddingLeft: `${8 + depth * 24}px` }}
        >
          <Folder className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="flex-1 min-w-0 break-all">{c.name}</span>
          {c.selected && (
            <Badge variant="secondary" className="text-[10px] shrink-0">Ingesting</Badge>
          )}
          <span className="text-xs text-muted-foreground tabular-nums shrink-0 w-16 text-right">
            {c.clip_count > 0 ? `${c.clip_count} clip${c.clip_count === 1 ? "" : "s"}` : ""}
          </span>
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer shrink-0">
            Ingest
            <input
              type="checkbox"
              className="h-4 w-4 accent-primary cursor-pointer"
              checked={c.selected}
              disabled={selectFolder.isPending}
              onChange={() => toggleIngest(c)}
              title={c.selected ? "Stop ingesting this folder (existing media stays)" : "Ingest this folder — existing clips import within a minute and new ones auto-import"}
            />
          </label>
        </div>
        {renderedKids}
      </div>
    );
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="h-14 shrink-0 border-b border-border flex items-center gap-3 px-6">
        <HardDrive className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-lg font-semibold flex-1">Curator</h1>
        {selectedCount > 0 && (
          <span className="text-xs text-muted-foreground">{selectedCount} folder{selectedCount === 1 ? "" : "s"} ingesting</span>
        )}
        <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
          <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${isFetching ? "animate-spin" : ""}`} />
          Rescan share
        </Button>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="max-w-4xl mx-auto p-6 space-y-4">
          <p className="text-sm text-muted-foreground">
            Check a folder to ingest it — existing clips import within a minute and new files keep
            importing automatically. Unchecking stops future imports; already-imported media stays.
          </p>
          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <Search className="h-4 w-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Filter folders..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="pl-8 h-9"
              />
            </div>
            <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer shrink-0">
              <input
                type="checkbox"
                className="h-4 w-4 accent-primary cursor-pointer"
                checked={showSelectedOnly}
                onChange={e => setShowSelectedOnly(e.target.checked)}
              />
              Ingesting only
            </label>
          </div>
          <div className="rounded-lg border border-border">
            {isLoading ? (
              <p className="text-sm text-muted-foreground p-6 flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" /> Scanning share...
              </p>
            ) : isError ? (
              <p className="text-sm text-muted-foreground p-6">Curator share not available.</p>
            ) : (
              <div className="p-2">
                {childrenOf(null).map(c => renderNode(c, 0))}
                {!childrenOf(null).length && (
                  <p className="text-sm text-muted-foreground p-4">No folders found on the Curator share.</p>
                )}
                {tree?.truncated && (
                  <p className="text-xs text-muted-foreground p-2">Share is large — some folders not shown.</p>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
