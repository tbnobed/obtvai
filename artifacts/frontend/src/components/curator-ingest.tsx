import { useState } from "react";
import {
  useListCuratorFolders, getListCuratorFoldersQueryKey, useSelectCuratorFolder,
} from "@workspace/api-client-react";
import type { CuratorFolderOut } from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { useIsAdmin } from "@/lib/auth";
import { useToast } from "@/hooks/use-toast";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Folder, ChevronDown, ChevronRight, HardDrive, Loader2, RefreshCw, Maximize2, Search,
} from "lucide-react";

/** Curator selective-ingest selector (admins only): check a share folder to
 * ingest it — existing clips import within a minute and new files keep
 * importing automatically. Lives in the app sidebar. */
export function CuratorIngest() {
  const isAdmin = useIsAdmin();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { data: curatorTree, isLoading: curatorLoading, isError: curatorError, refetch: refetchCurator, isFetching: curatorFetching } =
    useListCuratorFolders({ query: { queryKey: getListCuratorFoldersQueryKey(), enabled: isAdmin, staleTime: 60_000, retry: false } });
  const selectCuratorFolder = useSelectCuratorFolder();
  const [curatorExpanded, setCuratorExpanded] = useState<Set<string>>(new Set());
  const [curatorBrowseOpen, setCuratorBrowseOpen] = useState(false);
  const [curatorSearch, setCuratorSearch] = useState("");

  if (!isAdmin) return null;

  const curatorChildren = (parent: string | null) =>
    (curatorTree?.items ?? []).filter(c => (c.parent ?? null) === parent);
  const toggleCuratorIngest = (c: CuratorFolderOut) => {
    selectCuratorFolder.mutate(
      { data: { path: c.path, selected: !c.selected } },
      {
        onSuccess: () => queryClient.invalidateQueries({ queryKey: getListCuratorFoldersQueryKey() }),
        onError: () => toast({ title: "Could not update Curator folder", variant: "destructive" }),
      }
    );
  };
  const renderCuratorNode = (c: CuratorFolderOut, depth: number): React.ReactElement => {
    const kids = curatorChildren(c.path);
    const isOpen = curatorExpanded.has(c.path);
    return (
      <div key={c.path}>
        <div
          className="flex items-center gap-1 h-7 px-1.5 rounded-md text-sm select-none text-muted-foreground hover:text-foreground hover:bg-muted/50"
          style={{ paddingLeft: `${6 + depth * 14}px` }}
          title={c.path}
        >
          {kids.length ? (
            <button
              type="button"
              className="h-4 w-4 flex items-center justify-center shrink-0"
              onClick={() =>
                setCuratorExpanded(prev => {
                  const next = new Set(prev);
                  if (next.has(c.path)) next.delete(c.path); else next.add(c.path);
                  return next;
                })
              }
            >
              {isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            </button>
          ) : (
            <span className="h-4 w-4 shrink-0" />
          )}
          <Folder className="h-3.5 w-3.5 shrink-0" />
          <span className="flex-1 truncate">{c.name}</span>
          {c.clip_count > 0 && (
            <span className="text-[11px] tabular-nums">{c.clip_count}</span>
          )}
          <input
            type="checkbox"
            className="h-3.5 w-3.5 accent-primary cursor-pointer shrink-0"
            checked={c.selected}
            disabled={selectCuratorFolder.isPending}
            onChange={() => toggleCuratorIngest(c)}
            title={c.selected ? "Stop ingesting this folder (existing media stays)" : "Ingest this folder — existing clips import within a minute and new ones auto-import"}
          />
        </div>
        {isOpen && kids.map(k => renderCuratorNode(k, depth + 1))}
      </div>
    );
  };

  // Large browse dialog: full names, no truncation, optional filter. The
  // whole tree is rendered expanded so nothing hides behind chevrons.
  const renderCuratorBrowseNode = (c: CuratorFolderOut, depth: number): React.ReactElement | null => {
    const kids = curatorChildren(c.path);
    const q = curatorSearch.trim().toLowerCase();
    const selfMatch = !q || c.path.toLowerCase().includes(q);
    const renderedKids = kids.map(k => renderCuratorBrowseNode(k, depth + 1)).filter(Boolean);
    if (!selfMatch && !renderedKids.length) return null;
    return (
      <div key={c.path}>
        <div
          className="flex items-center gap-2 h-9 px-2 rounded-md text-sm select-none hover:bg-muted/50 border-b border-border/40"
          style={{ paddingLeft: `${8 + depth * 20}px` }}
        >
          <Folder className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="flex-1 min-w-0 break-all">{c.name}</span>
          <span className="text-xs text-muted-foreground tabular-nums shrink-0">
            {c.clip_count > 0 ? `${c.clip_count} clip${c.clip_count === 1 ? "" : "s"}` : ""}
          </span>
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer shrink-0">
            {c.selected ? "Ingesting" : "Ingest"}
            <input
              type="checkbox"
              className="h-4 w-4 accent-primary cursor-pointer"
              checked={c.selected}
              disabled={selectCuratorFolder.isPending}
              onChange={() => toggleCuratorIngest(c)}
            />
          </label>
        </div>
        {renderedKids}
      </div>
    );
  };

  return (
    <div className="pt-2 mt-1 border-t border-border/60">
      <div className="flex items-center gap-1.5 px-1.5 py-1">
        <HardDrive className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex-1">Curator</span>
        <button
          type="button"
          className="h-5 w-5 flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted"
          title="Browse in a larger window"
          onClick={() => setCuratorBrowseOpen(true)}
        >
          <Maximize2 className="h-3 w-3" />
        </button>
        <button
          type="button"
          className="h-5 w-5 flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted"
          title="Rescan the Curator share"
          onClick={() => refetchCurator()}
        >
          <RefreshCw className={`h-3 w-3 ${curatorFetching ? "animate-spin" : ""}`} />
        </button>
      </div>
      {curatorLoading ? (
        <p className="text-xs text-muted-foreground px-1.5 py-1 flex items-center gap-1.5">
          <Loader2 className="h-3 w-3 animate-spin" /> Scanning share...
        </p>
      ) : curatorError ? (
        <p className="text-xs text-muted-foreground px-1.5 py-1">Curator share not available.</p>
      ) : curatorChildren(null).length ? (
        <>
          <p className="text-[11px] text-muted-foreground px-1.5 pb-1">Check a folder to ingest it — new files keep importing automatically.</p>
          {curatorChildren(null).map(c => renderCuratorNode(c, 0))}
          {curatorTree?.truncated && (
            <p className="text-[11px] text-muted-foreground px-1.5 py-1">Share is large — some folders not shown.</p>
          )}
        </>
      ) : (
        <p className="text-xs text-muted-foreground px-1.5 py-1">No folders found on the Curator share.</p>
      )}
      <Dialog open={curatorBrowseOpen} onOpenChange={setCuratorBrowseOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <HardDrive className="h-4 w-4" /> Curator Share
              <button
                type="button"
                className="h-6 w-6 flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted"
                title="Rescan the Curator share"
                onClick={() => refetchCurator()}
              >
                <RefreshCw className={`h-3.5 w-3.5 ${curatorFetching ? "animate-spin" : ""}`} />
              </button>
            </DialogTitle>
          </DialogHeader>
          <p className="text-xs text-muted-foreground -mt-2">
            Check a folder to ingest it — existing clips import within a minute and new files keep importing automatically. Unchecking stops future imports; already-imported media stays.
          </p>
          <div className="relative">
            <Search className="h-4 w-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Filter folders..."
              value={curatorSearch}
              onChange={e => setCuratorSearch(e.target.value)}
              className="pl-8 h-9"
            />
          </div>
          <div className="max-h-[60vh] overflow-y-auto -mx-1 px-1">
            {curatorLoading ? (
              <p className="text-sm text-muted-foreground py-4 flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" /> Scanning share...
              </p>
            ) : curatorError ? (
              <p className="text-sm text-muted-foreground py-4">Curator share not available.</p>
            ) : (
              <>
                {curatorChildren(null).map(c => renderCuratorBrowseNode(c, 0))}
                {!curatorChildren(null).length && (
                  <p className="text-sm text-muted-foreground py-4">No folders found on the Curator share.</p>
                )}
                {curatorTree?.truncated && (
                  <p className="text-xs text-muted-foreground py-2">Share is large — some folders not shown.</p>
                )}
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
