import { useState } from "react";
import {
  useListReels,
  getListReelsQueryKey,
  useCreateReel,
  useDeleteReel,
} from "@workspace/api-client-react";
import type { ReelJob } from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Download, Trash2, Wand2, Loader2, Smartphone, Monitor, Captions, Film } from "lucide-react";
import { Link } from "wouter";

function statusBadge(status: string) {
  const map: Record<string, string> = {
    pending: "bg-yellow-500/15 text-yellow-400",
    running: "bg-blue-500/15 text-blue-400",
    success: "bg-green-500/15 text-green-400",
    error: "bg-red-500/15 text-red-400",
  };
  return map[status] || "bg-muted text-muted-foreground";
}

function fmtTime(s: number) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
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
        <div className="space-y-3">
          {[...Array(2)].map((_, i) => <Card key={i} className="animate-pulse h-28 bg-muted" />)}
        </div>
      ) : reels?.length ? (
        <div className="space-y-3">
          {reels.map((r: ReelJob) => (
            <Card key={r.id}>
              <CardContent className="py-4">
                <div className="flex items-start gap-4">
                  <div className="shrink-0 text-muted-foreground mt-1">
                    {r.preset === "vertical" ? <Smartphone className="h-5 w-5" /> : <Monitor className="h-5 w-5" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium">“{r.prompt}”</span>
                      <Badge variant="outline" className={statusBadge(r.status)}>{r.status}</Badge>
                      <Badge variant="outline">{r.clips.length} clip{r.clips.length === 1 ? "" : "s"}</Badge>
                      {r.preset === "vertical" && <Badge variant="outline">9:16 vertical</Badge>}
                      {r.burn_captions && (
                        <Badge variant="outline" className="gap-1"><Captions className="h-3 w-3" /> captions</Badge>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground mt-1.5 space-y-0.5 font-mono">
                      {r.clips.map((c, i) => (
                        <div key={i} className="truncate">
                          {c.filename} · {fmtTime(c.start_time)} – {fmtTime(c.end_time)}
                          {c.snippet ? <span className="text-muted-foreground/60"> — {c.snippet}</span> : null}
                        </div>
                      ))}
                    </div>
                    {(r.status === "running" || r.status === "pending") && (
                      <div className="mt-2 flex items-center gap-3">
                        <Progress value={r.progress} className="h-1.5 flex-1 max-w-md" />
                        <span className="text-xs text-muted-foreground font-mono">{Math.round(r.progress)}%</span>
                      </div>
                    )}
                    {r.status === "error" && r.error_message && (
                      <p className="text-xs text-red-400 mt-1 truncate">{r.error_message}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {r.status === "success" && (
                      <Button size="sm" variant="outline" asChild>
                        <a href={`/api/reels/${r.id}/download`} download>
                          <Download className="h-4 w-4 mr-2" /> MP4
                        </a>
                      </Button>
                    )}
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-8 w-8 text-muted-foreground hover:text-red-400"
                      onClick={() => deleteMutation.mutate({ id: r.id }, { onSuccess: invalidate })}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
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
