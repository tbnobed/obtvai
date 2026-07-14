import { useMemo, useState } from "react";
import {
  useListReels,
  getListReelsQueryKey,
  useCreateReel,
  useDeleteReel,
} from "@workspace/api-client-react";
import type { ReelJob, ReelClip } from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  Pagination, PaginationContent, PaginationItem, PaginationLink,
  PaginationNext, PaginationPrevious,
} from "@/components/ui/pagination";
import {
  Download, Trash2, Wand2, Loader2, Smartphone, Captions, Film, Clock,
  Play, AlertCircle,
} from "lucide-react";
import { Link } from "wouter";

const PAGE_SIZE = 12;

function fmtTime(s: number) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

function totalDuration(clips: ReelClip[]) {
  return clips.reduce((sum, c) => sum + Math.max(0, c.end_time - c.start_time), 0);
}

function relativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function coverThumb(reel: ReelJob): string | null {
  const c = reel.clips.find((c) => c.thumbnail_url);
  return c?.thumbnail_url ?? null;
}

function StatusLine({ reel }: { reel: ReelJob }) {
  const inProgress = reel.status === "running" || reel.status === "pending";
  if (inProgress)
    return (
      <span className="inline-flex items-center gap-1.5 text-blue-400">
        <Loader2 className="h-3 w-3 animate-spin" />
        {reel.status === "pending" ? "Queued" : "Rendering"}
      </span>
    );
  if (reel.status === "error")
    return (
      <span className="inline-flex items-center gap-1.5 text-red-400">
        <AlertCircle className="h-3 w-3" /> Failed
      </span>
    );
  return null;
}

function ReelTile({ reel, onOpen }: { reel: ReelJob; onOpen: () => void }) {
  const inProgress = reel.status === "running" || reel.status === "pending";
  const cover = coverThumb(reel);
  return (
    <Card
      className="overflow-hidden cursor-pointer hover:border-primary/40 transition-colors group"
      onClick={onOpen}
    >
      <div className="relative aspect-video bg-muted/50">
        {cover ? (
          <img
            src={`/api/thumbnails/${cover}`}
            className="w-full h-full object-cover group-hover:scale-[1.02] transition-transform"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <Film className="h-7 w-7 text-muted-foreground/30" />
          </div>
        )}
        {reel.status === "success" && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/30 transition-colors">
            <span className="rounded-full bg-black/60 p-2.5 opacity-0 group-hover:opacity-100 transition-opacity">
              <Play className="h-5 w-5 text-white" />
            </span>
          </div>
        )}
        <span className="absolute bottom-1.5 right-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-mono text-white/90">
          {fmtTime(totalDuration(reel.clips))}
        </span>
        {reel.preset === "vertical" && (
          <span className="absolute top-1.5 right-1.5 rounded bg-black/70 p-1">
            <Smartphone className="h-3 w-3 text-white/80" />
          </span>
        )}
        {inProgress && (
          <div className="absolute bottom-0 left-0 right-0">
            <Progress value={reel.progress} className="h-1 rounded-none" />
          </div>
        )}
      </div>
      <CardContent className="p-3">
        <p className="text-sm font-medium leading-snug line-clamp-2" title={reel.prompt}>
          “{reel.prompt}”
        </p>
        <div className="mt-1.5 flex items-center gap-2 flex-wrap text-xs text-muted-foreground">
          <StatusLine reel={reel} />
          <span>{reel.clips.length} clip{reel.clips.length === 1 ? "" : "s"}</span>
          {reel.burn_captions && <Captions className="h-3 w-3" />}
          <span className="text-muted-foreground/60 ml-auto">{relativeTime(reel.created_at)}</span>
        </div>
      </CardContent>
    </Card>
  );
}

function ReelDetail({
  reel,
  onDelete,
  deleting,
}: {
  reel: ReelJob;
  onDelete: () => void;
  deleting: boolean;
}) {
  const vertical = reel.preset === "vertical";
  const inProgress = reel.status === "running" || reel.status === "pending";
  const runtime = totalDuration(reel.clips);
  const sourceCount = new Set(reel.clips.map((c) => c.media_id)).size;
  const cover = coverThumb(reel);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap text-sm text-muted-foreground">
        <StatusLine reel={reel} />
        <span className="inline-flex items-center gap-1">
          <Clock className="h-3.5 w-3.5" /> {fmtTime(runtime)}
        </span>
        <span>
          {reel.clips.length} clip{reel.clips.length === 1 ? "" : "s"}
          {sourceCount > 1 ? ` · ${sourceCount} sources` : ""}
        </span>
        {vertical && (
          <span className="inline-flex items-center gap-1">
            <Smartphone className="h-3.5 w-3.5" /> 9:16
          </span>
        )}
        {reel.burn_captions && (
          <span className="inline-flex items-center gap-1">
            <Captions className="h-3.5 w-3.5" /> captions
          </span>
        )}
        <span className="text-muted-foreground/60">{relativeTime(reel.created_at)}</span>
        <span className="ml-auto flex items-center gap-1.5">
          {reel.status === "success" && (
            <Button size="sm" variant="outline" asChild>
              <a href={`/api/reels/${reel.id}/download`} download>
                <Download className="h-4 w-4 mr-1.5" /> MP4
              </a>
            </Button>
          )}
          <Button
            size="icon"
            variant="ghost"
            className="h-8 w-8 text-muted-foreground hover:text-red-400"
            onClick={onDelete}
            disabled={deleting}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </span>
      </div>

      {inProgress && (
        <div className="flex items-center gap-3">
          <Progress value={reel.progress} className="h-1.5 flex-1" />
          <span className="text-xs text-muted-foreground font-mono w-9 text-right">
            {Math.round(reel.progress)}%
          </span>
        </div>
      )}
      {reel.status === "error" && reel.error_message && (
        <p className="text-sm text-red-400">{reel.error_message}</p>
      )}

      {reel.status === "success" && reel.output_url && (
        <video
          controls
          preload="metadata"
          playsInline
          poster={cover ? `/api/thumbnails/${cover}` : undefined}
          src={reel.output_url}
          className={`w-full rounded-md bg-black border border-border/60 ${
            vertical ? "max-h-[50vh]" : "aspect-video"
          }`}
        />
      )}

      {reel.clips.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
            Clips in this reel
          </p>
          <div className="space-y-2 max-h-[40vh] overflow-y-auto pr-1">
            {reel.clips.map((c, i) => (
              <div key={i} className="flex gap-3 rounded-md border border-border/60 p-2">
                <Link
                  href={`/library/${c.media_id}?t=${Math.floor(c.start_time)}`}
                  className={`group relative shrink-0 overflow-hidden rounded bg-muted/60 ${
                    vertical ? "w-[52px] h-[86px]" : "w-[104px] h-[58px]"
                  }`}
                  title={`Open in player at ${fmtTime(c.start_time)}`}
                >
                  {c.thumbnail_url ? (
                    <img
                      src={`/api/thumbnails/${c.thumbnail_url}`}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <Film className="h-4 w-4 text-muted-foreground/40" />
                    </div>
                  )}
                  <div className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/40 transition-colors">
                    <Play className="h-4 w-4 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
                  </div>
                </Link>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2 flex-wrap">
                    <span className="font-mono text-xs text-muted-foreground/60">#{i + 1}</span>
                    <Link
                      href={`/library/${c.media_id}?t=${Math.floor(c.start_time)}`}
                      className="font-mono text-xs text-primary hover:underline"
                    >
                      {fmtTime(c.start_time)} – {fmtTime(c.end_time)}
                    </Link>
                    <span className="font-mono text-[11px] text-muted-foreground truncate">
                      {c.filename}
                    </span>
                    <span className="font-mono text-[11px] text-muted-foreground/60 ml-auto">
                      {fmtTime(c.end_time - c.start_time)}
                    </span>
                  </div>
                  {c.snippet && (
                    <p className="text-xs text-muted-foreground/80 mt-1 line-clamp-2">
                      “{c.snippet}”
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Reels() {
  const queryClient = useQueryClient();
  const { data: reels, isLoading } = useListReels(undefined, {
    query: { queryKey: getListReelsQueryKey(), refetchInterval: 3000 },
  });
  const createMutation = useCreateReel();
  const deleteMutation = useDeleteReel();

  const [prompt, setPrompt] = useState("");
  const [preset, setPreset] = useState<"original" | "vertical">("original");
  const [burnCaptions, setBurnCaptions] = useState(false);
  const [maxClips, setMaxClips] = useState(6);
  const [page, setPage] = useState(1);
  const [openId, setOpenId] = useState<string | null>(null);

  const totalPages = Math.max(1, Math.ceil((reels?.length ?? 0) / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageItems = useMemo(
    () => (reels ?? []).slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE),
    [reels, safePage],
  );
  const openReel = reels?.find((r) => r.id === openId) ?? null;

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: getListReelsQueryKey() });

  const submit = () => {
    if (prompt.trim().length < 3) return;
    createMutation.mutate(
      { data: { prompt: prompt.trim(), preset, burn_captions: burnCaptions, max_clips: maxClips } },
      {
        onSuccess: () => {
          setPrompt("");
          setPage(1);
          invalidate();
        },
      },
    );
  };

  const createError = createMutation.error as { status?: number } | null;

  const pageNumbers = useMemo(() => {
    const nums: number[] = [];
    for (let p = 1; p <= totalPages; p++) {
      if (p === 1 || p === totalPages || Math.abs(p - safePage) <= 1) nums.push(p);
    }
    return nums.filter((p, i) => nums.indexOf(p) === i);
  }, [totalPages, safePage]);

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">Highlight Reels</h1>
        <p className="text-muted-foreground mt-1">
          Describe what to highlight — the best matching moments across the whole library get stitched into one video
        </p>
      </div>

      <Card className="mb-8">
        <CardContent className="py-5 space-y-4">
          <div className="space-y-2">
            <Label htmlFor="reel-prompt">What should the reel highlight?</Label>
            <Textarea
              id="reel-prompt"
              placeholder='e.g. "highlight the fact about faith" or "every moment about affordable housing"'
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={2}
            />
          </div>
          <div className="flex flex-wrap items-end gap-6">
            <div className="space-y-2">
              <Label>Format</Label>
              <Select value={preset} onValueChange={(v) => setPreset(v as typeof preset)}>
                <SelectTrigger className="w-44"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="original">Original</SelectItem>
                  <SelectItem value="vertical">Vertical 9:16</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Max clips</Label>
              <Select value={String(maxClips)} onValueChange={(v) => setMaxClips(Number(v))}>
                <SelectTrigger className="w-24"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {[3, 4, 6, 8, 10, 12].map((n) => (
                    <SelectItem key={n} value={String(n)}>{n}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <label className="flex items-center gap-2 pb-2 cursor-pointer text-sm">
              <Checkbox checked={burnCaptions} onCheckedChange={(v) => setBurnCaptions(v === true)} />
              Burn in captions
            </label>
            <Button
              className="gap-2 ml-auto"
              onClick={submit}
              disabled={prompt.trim().length < 3 || createMutation.isPending}
            >
              {createMutation.isPending ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> Finding moments...</>
              ) : (
                <><Wand2 className="h-4 w-4" /> Build Reel</>
              )}
            </Button>
          </div>
          {createMutation.isError && (
            <p className="text-sm text-red-400">
              {createError?.status === 404
                ? "No moments in the library match that prompt — try different wording."
                : "Failed to start the reel. Check that the pipeline is running."}
            </p>
          )}
        </CardContent>
      </Card>

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[...Array(3)].map((_, i) => <Card key={i} className="animate-pulse h-56 bg-muted" />)}
        </div>
      ) : reels?.length ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {pageItems.map((r: ReelJob) => (
              <ReelTile key={r.id} reel={r} onOpen={() => setOpenId(r.id)} />
            ))}
          </div>

          {totalPages > 1 && (
            <Pagination className="mt-6">
              <PaginationContent>
                <PaginationItem>
                  <PaginationPrevious
                    href="#"
                    aria-disabled={safePage === 1}
                    className={safePage === 1 ? "pointer-events-none opacity-50" : ""}
                    onClick={(e) => { e.preventDefault(); setPage((p) => Math.max(1, p - 1)); }}
                  />
                </PaginationItem>
                {pageNumbers.map((p, i) => (
                  <PaginationItem key={p}>
                    {i > 0 && pageNumbers[i - 1] !== p - 1 && (
                      <span className="px-1 text-muted-foreground">…</span>
                    )}
                    <PaginationLink
                      href="#"
                      isActive={p === safePage}
                      onClick={(e) => { e.preventDefault(); setPage(p); }}
                    >
                      {p}
                    </PaginationLink>
                  </PaginationItem>
                ))}
                <PaginationItem>
                  <PaginationNext
                    href="#"
                    aria-disabled={safePage === totalPages}
                    className={safePage === totalPages ? "pointer-events-none opacity-50" : ""}
                    onClick={(e) => { e.preventDefault(); setPage((p) => Math.min(totalPages, p + 1)); }}
                  />
                </PaginationItem>
              </PaginationContent>
            </Pagination>
          )}
        </>
      ) : (
        <div className="text-center text-muted-foreground py-20 border border-dashed border-border rounded-lg">
          <Film className="h-8 w-8 mx-auto mb-3 opacity-50" />
          <p>No reels yet.</p>
          <p className="text-sm mt-2">
            Type a prompt above, or explore the library with{" "}
            <Link href="/search" className="text-primary hover:underline">semantic search</Link> first.
          </p>
        </div>
      )}

      <Dialog open={!!openReel} onOpenChange={(o) => { if (!o) setOpenId(null); }}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          {openReel && (
            <>
              <DialogHeader>
                <DialogTitle className="pr-8 leading-snug">“{openReel.prompt}”</DialogTitle>
              </DialogHeader>
              <ReelDetail
                reel={openReel}
                deleting={deleteMutation.isPending}
                onDelete={() =>
                  deleteMutation.mutate(
                    { id: openReel.id },
                    { onSuccess: () => { setOpenId(null); invalidate(); } },
                  )
                }
              />
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
