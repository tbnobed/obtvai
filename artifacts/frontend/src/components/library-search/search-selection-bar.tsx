import { useState } from "react";
import { useLocation } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  useListProjects, getListProjectsQueryKey, useCreateProject, useUpdateProject, getGetProjectQueryKey,
} from "@workspace/api-client-react";
import type { SearchResult } from "@workspace/api-client-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { FolderKanban, Loader2, Plus } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

type Range = { in: number; out: number };

/** Span of selected moments per file (earliest in to latest out). */
function momentRanges(moments: SearchResult[]): Record<string, Range> {
  const out: Record<string, Range> = {};
  for (const r of moments) {
    const cur = out[r.media_id];
    out[r.media_id] = { in: cur ? Math.min(cur.in, r.start_time) : r.start_time, out: cur ? Math.max(cur.out, r.end_time) : r.end_time };
  }
  return out;
}

/**
 * Floating action bar for search selections: whole assets (library selection)
 * plus individual moments. "Clips only" trims each file's usable region to
 * the selected moments.
 */
export function SearchSelectionBar({
  assetIds, moments, defaultProjectName, onClear,
}: {
  assetIds: string[];
  moments: SearchResult[];
  defaultProjectName: string;
  onClear: () => void;
}) {
  const [, navigate] = useLocation();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { data: projects } = useListProjects();
  const createProject = useCreateProject();
  const updateProject = useUpdateProject();
  const [addMode, setAddMode] = useState<"asset" | "clips">("asset");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [name, setName] = useState("");
  const mediaIds = [...new Set([...assetIds, ...moments.map((m) => m.media_id)])];
  const activeProjects = (projects ?? []).filter((p) => p.status === "active");
  const busy = createProject.isPending || updateProject.isPending;
  const clipsAvailable = moments.length > 0;
  const mode = clipsAvailable ? addMode : "asset";

  if (!mediaIds.length) return null;

  const addToProject = (projectId: string, projectName: string) => {
    const existing = (projects ?? []).find((p) => p.id === projectId);
    const merged = [...new Set([...(existing?.media_ids ?? []), ...mediaIds])];
    let mediaRanges: Record<string, Range> | undefined;
    if (mode === "clips") {
      mediaRanges = { ...((existing?.media_ranges ?? {}) as Record<string, Range>) };
      for (const [mid, r] of Object.entries(momentRanges(moments))) {
        const cur = mediaRanges[mid];
        mediaRanges[mid] = cur ? { in: Math.min(cur.in, r.in), out: Math.max(cur.out, r.out) } : r;
      }
    }
    updateProject.mutate(
      { id: projectId, data: { media_ids: merged, ...(mediaRanges ? { media_ranges: mediaRanges } : {}) } },
      {
        onSuccess: () => {
          queryClient.invalidateQueries({ queryKey: getListProjectsQueryKey() });
          queryClient.invalidateQueries({ queryKey: getGetProjectQueryKey(projectId) });
          onClear();
          toast({ description: `Added ${mediaIds.length} file${mediaIds.length === 1 ? "" : "s"} to ${projectName}` });
        },
        onError: () => toast({ variant: "destructive", description: "Could not add to project" }),
      },
    );
  };

  const create = () => {
    if (!name.trim()) return;
    createProject.mutate(
      { data: { name: name.trim(), media_ids: mediaIds, ...(mode === "clips" ? { media_ranges: momentRanges(moments) } : {}) } },
      {
        onSuccess: (p) => {
          queryClient.invalidateQueries({ queryKey: getListProjectsQueryKey() });
          onClear();
          setDialogOpen(false);
          navigate(`/studio/${p.id}`);
        },
      },
    );
  };

  return (
    <>
      <div className="sticky bottom-4 z-20 mt-4 flex justify-center pointer-events-none" data-testid="search-selection-bar">
        <div className="pointer-events-auto flex flex-wrap items-center gap-2 rounded-xl border border-border bg-card/95 backdrop-blur px-3 py-2 shadow-xl">
          <span className="text-sm tabular-nums px-1">
            <span className="font-semibold">{mediaIds.length}</span> file{mediaIds.length === 1 ? "" : "s"}
            {clipsAvailable && <> · <span className="font-semibold">{moments.length}</span> moment{moments.length === 1 ? "" : "s"}</>}
          </span>
          {clipsAvailable && (
            <div className="flex items-center rounded-lg border border-border p-0.5" title="Whole files adds complete assets; Clips only trims each file to the selected moments">
              <Button size="sm" variant={mode === "asset" ? "secondary" : "ghost"} className="h-7 px-2.5 text-xs" onClick={() => setAddMode("asset")}>Whole files</Button>
              <Button size="sm" variant={mode === "clips" ? "secondary" : "ghost"} className="h-7 px-2.5 text-xs" onClick={() => setAddMode("clips")}>Clips only</Button>
            </div>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="outline" disabled={busy || !activeProjects.length}>
                {updateProject.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <FolderKanban className="h-4 w-4 mr-2" />}
                Add to project
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="center" className="max-h-72 overflow-y-auto">
              {activeProjects.map((p) => (
                <DropdownMenuItem key={p.id} onClick={() => addToProject(p.id, p.name)}>{p.name}</DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
          <Button size="sm" disabled={busy} onClick={() => { setName(defaultProjectName); setDialogOpen(true); }}>
            <Plus className="h-4 w-4 mr-2" /> New project
          </Button>
          <Button size="sm" variant="ghost" onClick={onClear}>Clear</Button>
        </div>
      </div>
      <Dialog open={dialogOpen} onOpenChange={(o) => !busy && setDialogOpen(o)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader><DialogTitle>New project from selection</DialogTitle></DialogHeader>
          <div className="space-y-2">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Project name" autoFocus onKeyDown={(e) => e.key === "Enter" && create()} />
            <p className="text-xs text-muted-foreground">
              {mode === "clips"
                ? `Starts with ${mediaIds.length} source file${mediaIds.length === 1 ? "" : "s"}, trimmed to span your selected moments.`
                : `Starts with ${mediaIds.length} whole source file${mediaIds.length === 1 ? "" : "s"}.`}
            </p>
            {createProject.isError && <p className="text-xs text-destructive">Couldn't create the project. Try again.</p>}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDialogOpen(false)} disabled={busy}>Cancel</Button>
            <Button onClick={create} disabled={!name.trim() || busy}>
              {createProject.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}Create project
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
