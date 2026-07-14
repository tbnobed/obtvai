import { useState } from "react";
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
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Download, Trash2, Wand2, Loader2, Smartphone, Captions, Film, Clock,
  ChevronDown, ChevronUp, Play, AlertCircle,
} from "lucide-react";
import { Link } from "wouter";

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

function ClipThumb({ clip, vertical }: { clip: ReelClip; vertical: boolean }) {
  return (
    <Link
      href={`/library/${clip.media_id}?t=${Math.floor(clip.start_time)}`}
      className={`group relative shrink-0 overflow-hidden rounded-md bg-muted/60 border border-border/60 ${
        vertical ? "w-[76px] h-[124px]" : "w-[136px] h-[76px]"
      }`}
      title={`${clip.filename} · ${fmtTime(clip.start_time)} – ${fmtTime(clip.end_time)}`}
    >
      {clip.thumbnail_url ? (
        <img
          src={`/api/thumbnails/${clip.thumbnail_url}`}
          className="w-full h-full object-cover group-hover:scale-105 transition-transform"
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center">
          <Film className="h-5 w-5 text-muted-foreground/40" />
        </div>
      )}
      <div className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/40 transition-colors">
        <Play className="h-5 w-5 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
      </div>
      <span className="absolute bottom-1 right-1 rounded bg-black/70 px-1 py-px text-[10px] font-mono text-white/90">
        {fmtTime(clip.end_time - clip.start_time)}
      </span>
    </Link>
  );
}

function ReelCard({
  reel,
  onDelete,
  deleting,
}: {
  reel: ReelJob;
  onDelete: () => void;
  deleting: boolean;
}) {
  const [showClips, setShowClips] = useState(false);
  const vertical = reel.preset === "vertical";
  const inProgress = reel.status === "running" || reel.status === "pending";
  const runtime = totalDuration(reel.clips);
  const sourceCount = new Set(reel.clips.map((c) => c.media_id)).size;

  return (
    <Card className="overflow-hidden">
      <CardContent className="p-0">
        <div className="p-4 pb-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <p className="font-medium leading-snug truncate" title={reel.prompt}>
                “{reel.prompt}”
              </p>
              <div className="mt-1.5 flex items-center gap-2 flex-wrap text-xs text-muted-foreground">
                {inProgress ? (
                  <span className="inline-flex items-center gap-1.5 text-blue-400">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    {reel.status === "pending" ? "Queued" : "Rendering"}
                  </span>
                ) : reel.status === "error" ? (
                  <span className="inline-flex items-center gap-1.5 text-red-400">
                    <AlertCircle className="h-3 w-3" /> Failed
                  </span>
                ) : null}
                <span className="inline-flex items-center gap-1">
                  <Clock className="h-3 w-3" /> {fmtTime(runtime)}
                </span>
                <span>
                  {reel.clips.length} clip{reel.clips.length === 1 ? "" : "s"}
                  {sourceCount > 1 ? ` · ${sourceCount} sources` : ""}
                </span>
                {vertical && (
                  <span className="inline-flex items-center gap-1">
                    <Smartphone className="h-3 w-3" /> 9:16
                  </span>
                )}
                {reel.burn_captions && (
                  <span className="inline-flex items-center gap-1">
                    <Captions className="h-3 w-3" /> captions
                  </span>
                )}
                <span className="text-muted-foreground/60">{relativeTime(reel.created_at)}</span>
              </div>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
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
            </div>
          </div>

          {inProgress && (
            <div className="mt-3 flex items-center gap-3">
              <Progress value={reel.progress} className="h-1.5 flex-1" />
              <span className="text-xs text-muted-foreground font-mono w-9 text-right">
                {Math.round(reel.progress)}%
              </span>
            </div>
          )}
          {reel.status === "error" && reel.error_message && (
            <p className="text-xs text-red-400 mt-2">{reel.error_message}</p>
          )}
        </div>

        {reel.status === "success" && reel.output_url && (
          <div className="px-4 pb-3">
            <video
              controls
              preload="metadata"
              playsInline
              poster={
                reel.clips.find((c) => c.thumbnail_url)?.thumbnail_url
                  ? `/api/thumbnails/${reel.clips.find((c) => c.thumbnail_url)!.thumbnail_url}`
                  : undefined
              }
              src={reel.output_url}
              className={`w-full rounded-md bg-black border border-border/60 ${
                vertical ? "max-h-[420px]" : "aspect-video"
              }`}
            />
          </div>
        )}

        {reel.clips.length > 0 && (
          <div className="px-4 pb-3">
            <div className="flex gap-2 overflow-x-auto pb-1">
              {reel.clips.map((c, i) => (
                <ClipThumb key={i} clip={c} vertical={vertical} />
              ))}
            </div>
          </div>
        )}

        {reel.clips.length > 0 && (
          <div className="border-t border-border/60">
            <button
              className="w-full flex items-center justify-center gap-1.5 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
              onClick={() => setShowClips((v) => !v)}
            >
              {showClips ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
              {showClips ? "Hide clip details" : "Clip details"}
            </button>
            {showClips && (
              <div className="px-4 pb-4 pt-1 space-y-2.5">
                {reel.clips.map((c, i) => (
                  <div key={i} className="flex gap-3 text-sm">
                    <span className="shrink-0 w-6 text-right font-mono text-xs text-muted-foreground/60 pt-0.5">
                      {i + 1}
                    </span>
                    <div className="min-w-0">
                      <Link
                        href={`/library/${c.media_id}?t=${Math.floor(c.start_time)}`}
                        className="font-mono text-xs text-primary hover:underline"
                      >
                        {fmtTime(c.start_time)} – {fmtTime(c.end_time)}
                      </Link>
                      <span className="font-mono text-xs text-muted-foreground ml-2 break-all">
                        {c.filename}
                      </span>
                      {c.snippet && (
                        <p className="text-xs text-muted-foreground/80 mt-0.5 line-clamp-2">
                          “{c.snippet}”
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
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

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: getListReelsQueryKey() });

  const submit = () => {
    if (prompt.trim().length < 3) return;
    createMutation.mutate(
      { data: { prompt: prompt.trim(), preset, burn_captions: burnCaptions, max_clips: maxClips } },
      {
        onSuccess: () => {
          setPrompt("");
          invalidate();
        },
      },
    );
  };

  const createError = createMutation.error as { status?: number } | null;

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
        <div className="grid gap-4 md:grid-cols-2">
          {[...Array(2)].map((_, i) => <Card key={i} className="animate-pulse h-44 bg-muted" />)}
        </div>
      ) : reels?.length ? (
        <div className="grid gap-4 md:grid-cols-2">
          {reels.map((r: ReelJob) => (
            <ReelCard
              key={r.id}
              reel={r}
              deleting={deleteMutation.isPending}
              onDelete={() => deleteMutation.mutate({ id: r.id }, { onSuccess: invalidate })}
            />
          ))}
        </div>
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
    </div>
  );
}
