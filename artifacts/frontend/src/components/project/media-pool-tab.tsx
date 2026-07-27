import { useMemo, useState } from "react";
import {
  useListMedia, getListMediaQueryKey, useUpdateProject, getGetProjectQueryKey,
} from "@workspace/api-client-react";
import type { Project, MediaAsset } from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Loader2, Film, Scissors, RotateCcw, ChevronDown, ChevronUp } from "lucide-react";
import { MediaPickerGrid } from "@/components/project/media-picker";
import { ClipPlayerDialog, type PlayerClip } from "@/components/project/clip-player-dialog";
import { TrimPlayer } from "@/components/project/trim-player";
import { ClipThumb } from "@/components/project/clip-thumb";
import { formatTC } from "@/lib/timecode";
import { useToast } from "@/hooks/use-toast";

type Range = { in: number; out: number };

export function MediaPoolTab({ project }: { project: Project }) {
  const projectId = project.id;
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const updateMutation = useUpdateProject();

  const pool = useMemo(() => project.media_ids ?? [], [project.media_ids]);
  const ranges: Record<string, Range> = (project.media_ranges ?? {}) as Record<string, Range>;

  const [playerClip, setPlayerClip] = useState<PlayerClip | null>(null);
  const [openTrim, setOpenTrim] = useState<string | null>(null);
  // Draft in/out while the trim player is open for an asset.
  const [draft, setDraft] = useState<Range | null>(null);

  // Resolve the pool assets' metadata (filename, duration, fps).
  const poolKey = pool.length ? [...pool].sort().join(",") : "";
  const mediaParams = poolKey
    ? { ids: poolKey, limit: Math.min(Math.max(pool.length, 1), 200) }
    : undefined;
  const { data: media } = useListMedia(mediaParams ?? {}, {
    query: { queryKey: getListMediaQueryKey(mediaParams ?? {}), enabled: !!poolKey },
  });
  const assets = useMemo(() => {
    const byId = new Map((media?.items ?? []).map((a) => [a.id, a]));
    return pool.map((mid) => byId.get(mid)).filter((a): a is MediaAsset => !!a);
  }, [media?.items, pool]);

  const patchProject = (data: Record<string, unknown>, onDone?: () => void) => {
    updateMutation.mutate(
      { id: projectId, data },
      {
        onSuccess: () => {
          queryClient.invalidateQueries({ queryKey: getGetProjectQueryKey(projectId) });
          onDone?.();
        },
        onError: () => toast({ title: "Couldn't save the media pool", variant: "destructive" }),
      },
    );
  };

  const togglePool = (assetId: string, checked: boolean) =>
    patchProject({ media_ids: checked ? [...pool, assetId] : pool.filter((x) => x !== assetId) });
  const togglePoolMany = (assetIds: string[], checked: boolean) =>
    patchProject({
      media_ids: checked
        ? [...pool, ...assetIds.filter((x) => !pool.includes(x))]
        : pool.filter((x) => !assetIds.includes(x)),
    });

  const saveRange = (assetId: string, r: Range | null) => {
    const next: Record<string, Range> = { ...ranges };
    if (r) next[assetId] = r;
    else delete next[assetId];
    patchProject({ media_ranges: Object.keys(next).length ? next : null }, () => {
      setOpenTrim(null);
      setDraft(null);
    });
  };

  const startTrim = (a: MediaAsset) => {
    const r = ranges[a.id];
    setDraft(r ? { ...r } : { in: 0, out: a.duration_seconds ?? 0 });
    setOpenTrim(a.id);
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 flex-wrap gap-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Film className="h-4 w-4" /> Media Pool
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="secondary">
              {pool.length ? `${pool.length} selected` : "Whole library"}
            </Badge>
            {pool.length > 0 && (
              <Button size="sm" variant="ghost" onClick={() => patchProject({ media_ids: [], media_ranges: null })} disabled={updateMutation.isPending}>
                Use whole library
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground mb-3">
            Everything in this project works from these assets — Studio, search, and script matching stay within this pool.
          </p>
          <MediaPickerGrid
            selected={pool}
            onToggle={togglePool}
            onToggleMany={togglePoolMany}
            togglesDisabled={updateMutation.isPending}
            onPreview={(a) => setPlayerClip({ media_id: a.id, start_time: 0, end_time: null, filename: a.filename })}
            emptyText="The library is empty — drop files in the watch folder or upload from the Library page. They'll appear here once ingested."
          />
        </CardContent>
      </Card>

      {pool.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Scissors className="h-4 w-4" /> Usable Regions
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-xs text-muted-foreground mb-2">
              Set in/out points per asset — the Studio assistant only pulls moments from inside these regions. Untrimmed assets are usable end to end.
            </p>
            {assets.map((a) => {
              const r = ranges[a.id];
              const isOpen = openTrim === a.id;
              const dur = a.duration_seconds ?? 0;
              return (
                <div key={a.id} className="rounded border border-border bg-muted/40">
                  <div className="flex items-center gap-2 p-2 text-sm">
                    <ClipThumb url={a.thumbnail_url} mediaId={a.id} time={r?.in ?? 0} className="h-9 w-14" />
                    <div className="flex-1 min-w-0">
                      <div className="truncate">{a.filename}</div>
                      <div className="text-xs text-muted-foreground font-mono">
                        {r
                          ? <span className="text-primary">{formatTC(r.in)} – {formatTC(r.out)} of {formatTC(dur)}</span>
                          : <span>full asset · {formatTC(dur)}</span>}
                      </div>
                    </div>
                    {r && !isOpen && (
                      <Button
                        size="sm" variant="ghost" className="h-7 text-xs text-muted-foreground"
                        title="Clear the trim — use the full asset"
                        disabled={updateMutation.isPending}
                        onClick={() => saveRange(a.id, null)}
                      >
                        <RotateCcw className="h-3.5 w-3.5 mr-1" /> Clear
                      </Button>
                    )}
                    <Button
                      size="sm" variant="outline" className="h-7 text-xs"
                      onClick={() => (isOpen ? (setOpenTrim(null), setDraft(null)) : startTrim(a))}
                      data-testid={`button-trim-${a.id}`}
                    >
                      {isOpen ? <ChevronUp className="h-3.5 w-3.5 mr-1" /> : <ChevronDown className="h-3.5 w-3.5 mr-1" />}
                      {isOpen ? "Close" : r ? "Adjust" : "Trim"}
                    </Button>
                  </div>
                  {isOpen && draft && (
                    <div className="border-t border-border p-3 space-y-3">
                      <TrimPlayer
                        mediaId={a.id}
                        clipKey={a.id}
                        inPoint={draft.in}
                        outPoint={draft.out}
                        fps={a.fps}
                        onChange={(inPoint, outPoint) => setDraft({ in: inPoint, out: outPoint })}
                      />
                      <div className="flex justify-end gap-2">
                        <Button size="sm" variant="outline" onClick={() => { setOpenTrim(null); setDraft(null); }}>
                          Cancel
                        </Button>
                        <Button
                          size="sm"
                          disabled={updateMutation.isPending || draft.out - draft.in < 2}
                          onClick={() => saveRange(a.id, draft)}
                          data-testid={`button-save-trim-${a.id}`}
                        >
                          {updateMutation.isPending && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
                          Save region
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      <ClipPlayerDialog clip={playerClip} onClose={() => setPlayerClip(null)} />
    </div>
  );
}
