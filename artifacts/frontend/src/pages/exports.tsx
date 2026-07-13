import { useState } from "react";
import {
  useListRenders,
  getListRendersQueryKey,
  useDeleteRender,
  usePublishRender,
  useGetPublishPlatforms,
  getGetPublishPlatformsQueryKey,
} from "@workspace/api-client-react";
import type { RenderJob } from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Download, Trash2, Youtube, ExternalLink, Captions, Smartphone, Monitor } from "lucide-react";
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

export default function Exports() {
  const queryClient = useQueryClient();
  const { data: renders, isLoading } = useListRenders(undefined, {
    query: { queryKey: getListRendersQueryKey(), refetchInterval: 3000 },
  });
  const { data: platforms } = useGetPublishPlatforms({
    query: { queryKey: getGetPublishPlatformsQueryKey() },
  });
  const deleteMutation = useDeleteRender();
  const publishMutation = usePublishRender();

  const [publishTarget, setPublishTarget] = useState<RenderJob | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [privacy, setPrivacy] = useState<"public" | "unlisted" | "private">("unlisted");

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: getListRendersQueryKey() });

  const openPublish = (r: RenderJob) => {
    setPublishTarget(r);
    setTitle(r.label || r.filename || "Clip");
    setDescription("");
    setPrivacy("unlisted");
  };

  const submitPublish = () => {
    if (!publishTarget) return;
    publishMutation.mutate(
      { id: publishTarget.id, data: { platform: "youtube", title, description, privacy } },
      {
        onSuccess: () => {
          setPublishTarget(null);
          invalidate();
        },
      },
    );
  };

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">Exports</h1>
        <p className="text-muted-foreground mt-1">
          Rendered clips ready for download and publishing
        </p>
      </div>

      <Dialog open={!!publishTarget} onOpenChange={(open) => !open && setPublishTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Youtube className="h-5 w-5 text-red-500" /> Publish to YouTube
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="pub-title">Title</Label>
              <Input id="pub-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={100} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="pub-desc">Description</Label>
              <Textarea id="pub-desc" value={description} onChange={(e) => setDescription(e.target.value)} rows={3} />
            </div>
            <div className="space-y-2">
              <Label>Privacy</Label>
              <Select value={privacy} onValueChange={(v) => setPrivacy(v as typeof privacy)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="unlisted">Unlisted</SelectItem>
                  <SelectItem value="private">Private</SelectItem>
                  <SelectItem value="public">Public</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {publishMutation.isError && (
              <p className="text-sm text-red-400">Publish failed — check server logs and YouTube credentials.</p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPublishTarget(null)}>Cancel</Button>
            <Button onClick={submitPublish} disabled={!title.trim() || publishMutation.isPending}>
              {publishMutation.isPending ? "Publishing..." : "Publish"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {isLoading ? (
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => <Card key={i} className="animate-pulse h-24 bg-muted" />)}
        </div>
      ) : renders?.length ? (
        <div className="space-y-3">
          {renders.map((r) => (
            <Card key={r.id}>
              <CardContent className="py-4">
                <div className="flex items-center gap-4">
                  <div className="shrink-0 text-muted-foreground">
                    {r.preset === "vertical" ? <Smartphone className="h-5 w-5" /> : <Monitor className="h-5 w-5" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium truncate">{r.label || r.filename || r.media_id}</span>
                      <Badge variant="outline" className={statusBadge(r.status)}>{r.status}</Badge>
                      <Badge variant="outline">{r.preset === "vertical" ? "9:16 vertical" : "original"}</Badge>
                      {r.burn_captions && (
                        <Badge variant="outline" className="gap-1"><Captions className="h-3 w-3" /> captions</Badge>
                      )}
                      {r.publish_status && (
                        <Badge variant="outline" className={statusBadge(r.publish_status)}>
                          <Youtube className="h-3 w-3 mr-1" /> {r.publish_status === "success" ? "published" : `publish: ${r.publish_status}`}
                        </Badge>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground mt-1 font-mono">
                      {r.filename} · {fmtTime(r.start_time)} – {fmtTime(r.end_time)} ({Math.round(r.end_time - r.start_time)}s)
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
                    {r.publish_status === "error" && r.publish_error && (
                      <p className="text-xs text-red-400 mt-1 truncate">Publish failed: {r.publish_error}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {r.publish_url && (
                      <Button size="sm" variant="outline" asChild>
                        <a href={r.publish_url} target="_blank" rel="noreferrer">
                          <ExternalLink className="h-4 w-4 mr-2" /> Watch
                        </a>
                      </Button>
                    )}
                    {r.status === "success" && (
                      <>
                        <Button size="sm" variant="outline" asChild>
                          <a href={`/api/renders/${r.id}/download`} download>
                            <Download className="h-4 w-4 mr-2" /> MP4
                          </a>
                        </Button>
                        {platforms?.youtube && !r.publish_url && (
                          <Button
                            size="sm"
                            onClick={() => openPublish(r)}
                            disabled={r.publish_status === "pending" || r.publish_status === "running"}
                          >
                            <Youtube className="h-4 w-4 mr-2" />
                            {r.publish_status === "pending" || r.publish_status === "running" ? "Publishing..." : "Publish"}
                          </Button>
                        )}
                      </>
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
          <p>No renders yet.</p>
          <p className="text-sm mt-2">
            Render clips from a <Link href="/clips" className="text-primary hover:underline">clip list</Link> to see them here.
          </p>
        </div>
      )}
    </div>
  );
}
