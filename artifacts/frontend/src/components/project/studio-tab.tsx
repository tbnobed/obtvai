import { useEffect, useMemo, useRef, useState } from "react";
import {
  useListProjectChatMessages, getListProjectChatMessagesQueryKey,
  usePostProjectChatMessage,
  useGetProjectCut, getGetProjectCutQueryKey,
  useUpdateProjectCut, useRevertProjectCut, useRenderProjectCut,
} from "@workspace/api-client-react";
import type { ProjectChatMessage, ProjectCut, CutClip, Project } from "@workspace/api-client-react";
import { useUpdateProject, getGetProjectQueryKey } from "@workspace/api-client-react";
import type { MediaAsset } from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { MediaPickerGrid } from "@/components/project/media-picker";
import { ClipPlayerDialog, type PlayerClip } from "@/components/project/clip-player-dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Loader2, Lock, LockOpen, Send, Sparkles, Trash2, Clapperboard, History, Film } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { formatTC } from "@/lib/timecode";

const fmtTime = (s: number) => formatTC(s, 25, false);

const EDL_COLORS = [
  "bg-sky-500/70", "bg-emerald-500/70", "bg-amber-500/70", "bg-fuchsia-500/70",
  "bg-rose-500/70", "bg-indigo-500/70", "bg-teal-500/70", "bg-orange-500/70",
];

function cutDuration(clips: CutClip[]) {
  return clips.reduce((s, c) => s + Math.max(0, c.end_time - c.start_time), 0);
}

function fmtRuntime(s: number) {
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.round(s % 60)).padStart(2, "0")}`;
}

export function StudioTab({ project }: { project: Project }) {
  const projectId = project.id;
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [input, setInput] = useState("");
  const [viewVersion, setViewVersion] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Media pool picker — which assets the assistant may draw from.
  const [poolOpen, setPoolOpen] = useState(false);
  const [poolDraft, setPoolDraft] = useState<string[]>([]);
  const [previewAsset, setPreviewAsset] = useState<PlayerClip | null>(null);
  const updateProjectMutation = useUpdateProject();
  const mediaPool = project.media_ids ?? [];

  const openPool = () => {
    setPoolDraft(mediaPool);
    setPoolOpen(true);
  };
  const savePool = () => {
    updateProjectMutation.mutate(
      { id: projectId, data: { media_ids: poolDraft } },
      {
        onSuccess: () => {
          queryClient.invalidateQueries({ queryKey: getGetProjectQueryKey(projectId) });
          setPoolOpen(false);
        },
        onError: () => toast({ title: "Couldn't update the media pool", variant: "destructive" }),
      },
    );
  };

  const { data: messages } = useListProjectChatMessages(projectId, {
    query: {
      queryKey: getListProjectChatMessagesQueryKey(projectId),
      refetchInterval: (q) => {
        const items = (q.state.data as ProjectChatMessage[] | undefined) ?? [];
        return items.some((m) => m.status === "running") ? 2000 : false;
      },
    },
  });

  const assistantBusy = (messages ?? []).some((m) => m.status === "running");
  const prevBusy = useRef(assistantBusy);
  useEffect(() => {
    if (prevBusy.current && !assistantBusy) {
      // Turn just finished — pull the new revision.
      queryClient.invalidateQueries({ queryKey: getGetProjectCutQueryKey(projectId) });
      setViewVersion(null);
    }
    prevBusy.current = assistantBusy;
  }, [assistantBusy, projectId, queryClient]);

  const cutParams = viewVersion != null ? { version: viewVersion } : undefined;
  const { data: cut } = useGetProjectCut(projectId, cutParams, {
    query: { queryKey: getGetProjectCutQueryKey(projectId, cutParams) },
  });

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages?.length, assistantBusy]);

  const postMutation = usePostProjectChatMessage();
  const updateMutation = useUpdateProjectCut();
  const revertMutation = useRevertProjectCut();
  const renderMutation = useRenderProjectCut();

  const refreshCut = () => {
    queryClient.invalidateQueries({ queryKey: getGetProjectCutQueryKey(projectId) });
    setViewVersion(null);
  };

  const send = () => {
    const text = input.trim();
    if (!text || assistantBusy) return;
    setInput("");
    postMutation.mutate(
      { id: projectId, data: { content: text } },
      {
        onSuccess: () =>
          queryClient.invalidateQueries({ queryKey: getListProjectChatMessagesQueryKey(projectId) }),
        onError: () => {
          setInput(text);
          toast({ title: "Couldn't send message", variant: "destructive" });
        },
      },
    );
  };

  const clips = cut?.clips ?? [];
  const latestVersion = cut?.versions?.length ? Math.max(...cut.versions) : 0;
  const viewingOld = viewVersion != null && viewVersion !== latestVersion;

  const patchClips = (next: CutClip[]) => {
    updateMutation.mutate(
      { id: projectId, data: { clips: next } },
      { onSuccess: refreshCut, onError: () => toast({ title: "Couldn't update the cut", variant: "destructive" }) },
    );
  };

  const toggleLock = (i: number) =>
    patchClips(clips.map((c, j) => (j === i ? { ...c, locked: !c.locked } : c)));
  const removeClip = (i: number) => patchClips(clips.filter((_, j) => j !== i));

  const events = useMemo(() => {
    let rec = 0;
    const mediaIds: string[] = [];
    return clips.map((c, i) => {
      if (!mediaIds.includes(c.media_id)) mediaIds.push(c.media_id);
      const dur = Math.max(0, c.end_time - c.start_time);
      const ev = { n: i + 1, clip: c, dur, recIn: rec, color: EDL_COLORS[mediaIds.indexOf(c.media_id) % EDL_COLORS.length] };
      rec += dur;
      return ev;
    });
  }, [clips]);
  const total = cutDuration(clips);

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(320px,1fr)_2fr]">
      {/* ── Chat pane ── */}
      <div className="flex flex-col border border-border rounded-lg bg-card/50 h-[calc(100vh-260px)] min-h-[420px]">
        <div className="px-4 py-3 border-b border-border flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-primary" />
          <span className="text-sm font-medium">Editorial assistant</span>
          <Button
            size="sm" variant="outline" className="ml-auto h-7 text-xs"
            onClick={openPool}
            data-testid="button-media-pool"
          >
            <Film className="w-3.5 h-3.5 mr-1.5" />
            {mediaPool.length ? `Media pool: ${mediaPool.length}` : "Media pool: all"}
          </Button>
        </div>
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
          {!(messages ?? []).length && (
            <div className="text-sm text-muted-foreground space-y-2 pt-4">
              <p>Tell me what to build — I'll assemble a cut from this project's footage and revise it as we talk.</p>
              <p className="text-xs">e.g. "A 10-minute highlight reel focused on the healing testimonies" — then "less of the host, more guest reactions".</p>
            </div>
          )}
          {(messages ?? []).map((m) => (
            <div key={m.id} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
              <div
                className={`max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
                  m.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted/60"
                }`}
                data-testid={`chat-msg-${m.id}`}
              >
                {m.status === "running" ? (
                  <span className="inline-flex items-center gap-2 text-muted-foreground">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> Working on the cut…
                  </span>
                ) : (
                  <>
                    {m.content}
                    {m.cut_version != null && (
                      <button
                        type="button"
                        onClick={() => setViewVersion(m.cut_version!)}
                        className="mt-1 block text-[11px] underline underline-offset-2 opacity-80 hover:opacity-100"
                      >
                        cut v{m.cut_version}
                      </button>
                    )}
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
        <div className="p-3 border-t border-border flex gap-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
            }}
            placeholder={assistantBusy ? "Assistant is working…" : "Describe the cut you want, or how to change it…"}
            className="min-h-[42px] max-h-32 resize-none text-sm"
            disabled={assistantBusy}
            data-testid="input-chat"
          />
          <Button size="icon" onClick={send} disabled={assistantBusy || !input.trim()} data-testid="button-send-chat">
            <Send className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {/* ── Living cut pane ── */}
      <div className="border border-border rounded-lg bg-card/50 flex flex-col h-[calc(100vh-260px)] min-h-[420px]">
        <div className="px-4 py-3 border-b border-border flex items-center gap-3 flex-wrap">
          <span className="text-sm font-medium">Draft cut</span>
          {latestVersion > 0 && (
            <div className="flex items-center gap-1.5">
              <History className="w-3.5 h-3.5 text-muted-foreground" />
              <Select
                value={String(viewVersion ?? latestVersion)}
                onValueChange={(v) => setViewVersion(Number(v) === latestVersion ? null : Number(v))}
              >
                <SelectTrigger className="h-7 w-[86px] text-xs" data-testid="select-cut-version">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(cut?.versions ?? []).slice().reverse().map((v) => (
                    <SelectItem key={v} value={String(v)}>v{v}{v === latestVersion ? " (latest)" : ""}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {clips.length > 0 && (
            <Badge variant="outline" className="text-xs tabular-nums">
              {clips.length} clips · {fmtRuntime(total)}
              {project.target_runtime_seconds ? ` / ${fmtRuntime(project.target_runtime_seconds)}` : ""}
            </Badge>
          )}
          <div className="ml-auto flex gap-2">
            {viewingOld && (
              <Button
                size="sm" variant="outline"
                onClick={() =>
                  revertMutation.mutate(
                    { id: projectId, data: { version: viewVersion! } },
                    { onSuccess: refreshCut },
                  )
                }
                disabled={revertMutation.isPending}
                data-testid="button-restore-version"
              >
                Restore v{viewVersion}
              </Button>
            )}
            <Button
              size="sm"
              onClick={() =>
                renderMutation.mutate(
                  { id: projectId, data: { preset: "original" } },
                  {
                    onSuccess: () => toast({ title: "Render started", description: "Track progress in the Cut tab." }),
                    onError: () => toast({ title: "Render failed to start", variant: "destructive" }),
                  },
                )
              }
              disabled={!clips.length || viewingOld || renderMutation.isPending}
              data-testid="button-render-cut"
            >
              <Clapperboard className="w-4 h-4 mr-1.5" /> Render
            </Button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {!clips.length ? (
            <p className="text-sm text-muted-foreground pt-6 text-center">
              No cut yet — describe what you want in the chat and I'll build the first draft.
            </p>
          ) : (
            <>
              <div className="flex h-8 w-full rounded overflow-hidden border border-border bg-black/40">
                {events.map((ev) => (
                  <div
                    key={ev.n}
                    className={`${ev.color} relative h-full border-r border-black/50 last:border-r-0`}
                    style={{ width: `${total > 0 ? (ev.dur / total) * 100 : 0}%`, minWidth: 14 }}
                    title={`${ev.n}. ${ev.clip.filename}\n${fmtTime(ev.clip.start_time)}–${fmtTime(ev.clip.end_time)}`}
                  >
                    <span className="absolute inset-0 flex items-center justify-center text-[10px] font-semibold text-black/80 tabular-nums">
                      {ev.n}
                    </span>
                  </div>
                ))}
              </div>
              <div className="rounded border border-border divide-y divide-border/60">
                {events.map((ev, i) => (
                  <div key={ev.n} className="flex items-center gap-2 px-2 py-1.5 text-xs hover:bg-muted/30" data-testid={`cut-clip-${i}`}>
                    <span className={`inline-block h-2.5 w-2.5 rounded-sm shrink-0 ${ev.color}`} />
                    <span className="w-6 tabular-nums text-muted-foreground">{ev.n}</span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">{ev.clip.filename}</div>
                      {ev.clip.snippet && <div className="truncate text-muted-foreground">{ev.clip.snippet}</div>}
                    </div>
                    <span className="tabular-nums text-muted-foreground shrink-0">
                      {fmtTime(ev.clip.start_time)}–{fmtTime(ev.clip.end_time)}
                    </span>
                    <span className="tabular-nums shrink-0 w-10 text-right">{Math.round(ev.dur)}s</span>
                    <Button
                      size="icon" variant="ghost" className="h-6 w-6 shrink-0"
                      title={ev.clip.locked ? "Unlock — allow the assistant to change this clip" : "Lock — the assistant will keep this clip"}
                      onClick={() => toggleLock(i)}
                      disabled={viewingOld || updateMutation.isPending}
                      data-testid={`button-lock-clip-${i}`}
                    >
                      {ev.clip.locked
                        ? <Lock className="w-3.5 h-3.5 text-amber-400" />
                        : <LockOpen className="w-3.5 h-3.5 text-muted-foreground" />}
                    </Button>
                    <Button
                      size="icon" variant="ghost" className="h-6 w-6 shrink-0"
                      title="Remove clip"
                      onClick={() => removeClip(i)}
                      disabled={viewingOld || updateMutation.isPending}
                      data-testid={`button-remove-clip-${i}`}
                    >
                      <Trash2 className="w-3.5 h-3.5 text-muted-foreground" />
                    </Button>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── Media pool picker ── */}
      <Dialog open={poolOpen} onOpenChange={setPoolOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Media pool</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground -mt-2">
            The assistant only pulls moments from these assets. Leave all unchecked to search the whole library.
          </p>
          <div className="max-h-[50vh] overflow-y-auto">
            <MediaPickerGrid
              selected={poolDraft}
              onToggle={(mid, checked) =>
                setPoolDraft((prev) => (checked ? [...prev, mid] : prev.filter((x) => x !== mid)))
              }
              onToggleMany={(ids, checked) =>
                setPoolDraft((prev) =>
                  checked ? [...new Set([...prev, ...ids])] : prev.filter((x) => !ids.includes(x))
                )
              }
              onPreview={(asset: MediaAsset) =>
                setPreviewAsset({ media_id: asset.id, filename: asset.filename, start_time: 0, end_time: asset.duration_seconds ?? 0 })
              }
              requireReady
              emptyText="No media in the library yet — upload footage first."
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPoolOpen(false)}>Cancel</Button>
            <Button onClick={savePool} disabled={updateProjectMutation.isPending} data-testid="button-save-media-pool">
              {updateProjectMutation.isPending && <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />}
              Save pool
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ClipPlayerDialog clip={previewAsset} onClose={() => setPreviewAsset(null)} />
    </div>
  );
}
