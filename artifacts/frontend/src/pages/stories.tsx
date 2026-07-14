import { useEffect, useState } from "react";
import {
  useListMedia, getListMediaQueryKey,
  useListStories, getListStoriesQueryKey,
  useCreateStory,
  useDeleteStory,
} from "@workspace/api-client-react";
import type { StoryJob } from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { BookOpen, Loader2, Trash2, ListVideo, Clock } from "lucide-react";
import { Link } from "wouter";

function formatDuration(seconds: number | null | undefined): string {
  if (!seconds) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function StatusBadge({ status }: { status: string }) {
  const variant =
    status === "success" ? "default" :
    status === "error" ? "destructive" : "secondary";
  return <Badge variant={variant} className="uppercase text-[10px]">{status}</Badge>;
}

export default function Stories() {
  const queryClient = useQueryClient();
  const { data: media } = useListMedia({}, { query: { queryKey: getListMediaQueryKey({}) } });
  const { data: stories, isLoading } = useListStories(
    { query: { queryKey: getListStoriesQueryKey() } },
  );
  const createMutation = useCreateStory();
  const deleteMutation = useDeleteStory();

  const [selected, setSelected] = useState<string[]>([]);
  const [prompt, setPrompt] = useState("");

  const hasActive = stories?.some((s) => s.status === "pending" || s.status === "running");
  useEffect(() => {
    if (!hasActive) return;
    const t = setInterval(
      () => queryClient.invalidateQueries({ queryKey: getListStoriesQueryKey() }),
      2500,
    );
    return () => clearInterval(t);
  }, [hasActive, queryClient]);

  const toggle = (id: string) => {
    setSelected((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
  };

  const submit = () => {
    createMutation.mutate(
      { data: { asset_ids: selected, prompt: prompt.trim() || undefined } },
      {
        onSuccess: () => {
          setSelected([]);
          setPrompt("");
          queryClient.invalidateQueries({ queryKey: getListStoriesQueryKey() });
        },
      },
    );
  };

  const remove = (id: string) => {
    deleteMutation.mutate({ id }, {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListStoriesQueryKey() }),
    });
  };

  const eligible = (media?.items ?? []).filter((a) => a.status === "ready" || a.status === "indexed");

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
          <BookOpen className="h-7 w-7" /> Story Builder
        </h1>
        <p className="text-muted-foreground mt-1">
          Pick footage from several videos and the AI assembles one storyline — a titled,
          ordered clip list with a narrative you can render or export.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,26rem)_1fr]">
        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">New story</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
              {eligible.length ? eligible.map((a) => (
                <label
                  key={a.id}
                  className="flex items-center gap-3 rounded border border-border p-2 cursor-pointer hover:bg-muted/50 transition-colors"
                >
                  <Checkbox
                    checked={selected.includes(a.id)}
                    onCheckedChange={() => toggle(a.id)}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm truncate">{a.filename}</div>
                    <div className="text-xs text-muted-foreground flex items-center gap-1">
                      <Clock className="h-3 w-3" /> {formatDuration(a.duration_seconds)}
                    </div>
                  </div>
                </label>
              )) : (
                <p className="text-sm text-muted-foreground">No processed assets yet.</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="story-prompt" className="text-xs">Editorial direction (optional)</Label>
              <Textarea
                id="story-prompt"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="e.g. Open on the conflict, build to the data rebuttal, close on the ballot deadline"
                rows={3}
              />
            </div>
            {createMutation.isError && (
              <p className="text-sm text-red-400">Failed to start the story build.</p>
            )}
            <Button
              className="w-full gap-2"
              onClick={submit}
              disabled={selected.length < 1 || createMutation.isPending}
            >
              {createMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <BookOpen className="h-4 w-4" />}
              Build story from {selected.length || "…"} video{selected.length === 1 ? "" : "s"}
            </Button>
          </CardContent>
        </Card>

        <div className="space-y-4">
          {isLoading ? (
            [...Array(2)].map((_, i) => <Card key={i} className="animate-pulse h-32 bg-muted" />)
          ) : stories?.length ? (
            stories.map((s: StoryJob) => (
              <Card key={s.id}>
                <CardContent className="pt-5">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <StatusBadge status={s.status} />
                        <span className="text-xs text-muted-foreground">
                          {s.asset_ids.length} video{s.asset_ids.length === 1 ? "" : "s"} ·{" "}
                          {new Date(s.created_at).toLocaleString()}
                        </span>
                      </div>
                      <div className="font-medium truncate">
                        {s.title || s.prompt || "Untitled story"}
                      </div>
                      {s.status === "running" && (
                        <Progress value={s.progress} className="mt-2 h-1.5" />
                      )}
                      {s.status === "error" && s.error_message && (
                        <p className="text-xs text-red-400 mt-1">{s.error_message}</p>
                      )}
                      {s.narrative && (
                        <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
                          {s.narrative}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {s.clip_list_id && (
                        <Link href="/clips">
                          <Button size="sm" variant="outline" className="gap-1.5">
                            <ListVideo className="h-4 w-4" /> Clip List
                          </Button>
                        </Link>
                      )}
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-8 w-8 text-muted-foreground hover:text-destructive"
                        onClick={() => remove(s.id)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))
          ) : (
            <div className="text-center text-muted-foreground py-20 border border-dashed border-border rounded-lg">
              No stories yet — pick a few videos and build your first one.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
