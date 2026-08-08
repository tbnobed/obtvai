import { Fragment, cloneElement, isValidElement, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  useListProjectChatMessages, getListProjectChatMessagesQueryKey,
  usePostProjectChatMessage,
  useGetProjectCut, getGetProjectCutQueryKey,
  useUpdateProjectCut, useRevertProjectCut, useRenderProjectCut,
  useExportProjectCut,
  useGetProjectCutFeedback, getGetProjectCutFeedbackQueryKey,
  usePostProjectCutFeedback,
} from "@workspace/api-client-react";
import type { ProjectChatMessage, ProjectCut, CutClip, Project } from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Loader2, Lock, LockOpen, Send, Sparkles, Trash2, Clapperboard, History, Film, Play, Scissors, Download, ThumbsUp, ThumbsDown, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { TrimPlayer } from "./trim-player";
import { ClipThumb } from "./clip-thumb";
import { CutPreviewPlayer } from "./cut-preview-dialog";
import { CutStrips } from "./cut-strips";
import { useToast } from "@/hooks/use-toast";
import { formatTC } from "@/lib/timecode";

const fmtTime = (s: number) => formatTC(s, 25, false);

function parseTC(tc: string): number {
  const p = tc.split(":").map(Number);
  return p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1];
}

// Matches "1:22", "01:07:43" and ranges like "1:22-1:43" / "1:22–1:43".
const TC_RE = /\b(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[-–]\s*\d{1,2}:\d{2}(?::\d{2})?)?)\b/g;

function linkifyTimecodes(node: React.ReactNode, onSeek: (t: number) => void): React.ReactNode {
  if (typeof node === "string") {
    const out: React.ReactNode[] = [];
    let last = 0;
    let i = 0;
    for (const m of node.matchAll(TC_RE)) {
      const idx = m.index ?? 0;
      if (idx > last) out.push(node.slice(last, idx));
      const label = m[1];
      const start = parseTC(label.split(/\s*[-–]\s*/)[0]);
      out.push(
        <button
          key={`tc-${idx}-${i++}`}
          type="button"
          onClick={() => onSeek(start)}
          className="text-primary underline underline-offset-2 hover:opacity-80 font-mono"
        >
          {label}
        </button>,
      );
      last = idx + label.length;
    }
    if (!out.length) return node;
    if (last < node.length) out.push(node.slice(last));
    return out;
  }
  if (Array.isArray(node)) return node.map((n, i) => <Fragment key={i}>{linkifyTimecodes(n, onSeek)}</Fragment>);
  if (isValidElement(node)) {
    const children = (node.props as { children?: React.ReactNode }).children;
    if (children == null) return node;
    return cloneElement(node, undefined, linkifyTimecodes(children, onSeek));
  }
  return node;
}

function ChatMarkdown({ text, onSeek }: { text: string; onSeek?: (t: number) => void }) {
  const wrap = (Tag: "p" | "li" | "td" | "th") =>
    function Wrapped({ children }: { children?: React.ReactNode }) {
      return <Tag>{onSeek ? linkifyTimecodes(children, onSeek) : children}</Tag>;
    };
  return (
    <div className="min-w-0 break-words text-sm leading-relaxed space-y-2 [&_table]:block [&_table]:overflow-x-auto [&_p]:my-0 [&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-4 [&_li]:my-0.5 [&_strong]:font-semibold [&_h1]:text-sm [&_h1]:font-semibold [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:text-sm [&_h3]:font-semibold [&_code]:rounded [&_code]:bg-black/30 [&_code]:px-1 [&_table]:w-full [&_table]:border-collapse [&_table]:text-xs [&_th]:border [&_th]:border-border [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1 [&_td]:align-top">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={onSeek ? { p: wrap("p"), li: wrap("li"), td: wrap("td"), th: wrap("th") } : undefined}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

const EDL_COLORS = [
  "bg-sky-500/70", "bg-emerald-500/70", "bg-amber-500/70", "bg-fuchsia-500/70",
  "bg-rose-500/70", "bg-indigo-500/70", "bg-teal-500/70", "bg-orange-500/70",
];

function cutDuration(clips: CutClip[]) {
  return clips.reduce((s, c) => s + Math.max(0, c.end_time - c.start_time), 0);
}

function fmtRuntime(s: number) {
  const t = Math.round(s);
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
}

export function StudioTab({ project, onOpenPool, focusVersion, fill, onSeekSource, onCutChange, cutHost }: { project: Project; onOpenPool?: () => void; focusVersion?: number | null; fill?: boolean; onSeekSource?: (t: number) => void; onCutChange?: (clips: CutClip[]) => void; cutHost?: HTMLElement | null }) {
  // Fill the viewport: measure where the panels actually start and stretch
  // them to the bottom of the window instead of guessing a fixed offset.
  const gridRef = useRef<HTMLDivElement>(null);
  const [panelPx, setPanelPx] = useState<number | null>(null);
  useEffect(() => {
    const update = () => {
      const r = gridRef.current?.getBoundingClientRect();
      if (r) setPanelPx(Math.max(420, window.innerHeight - r.top - 24));
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  const panelStyle = panelPx != null ? { height: panelPx } : undefined;
  const panelH = panelPx != null ? "" : "h-[calc(100vh-260px)]";
  void fill;
  const projectId = project.id;
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [input, setInput] = useState("");
  // Assistant pane collapses to a slim rail so laptops keep room for the cut.
  const [chatOpen, setChatOpen] = useState<boolean>(
    () => typeof window === "undefined" || window.innerWidth >= 1440,
  );
  const [viewVersion, setViewVersion] = useState<number | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewIndex, setPreviewIndex] = useState(0);
  const [previewLarge, setPreviewLarge] = useState(false);
  // Per-clip trim editor: index into `clips` plus a draft in/out.
  const [editIdx, setEditIdx] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<{ in: number; out: number } | null>(null);
  // Deliver's "Studio cut vN" badge jumps here with a specific version.
  useEffect(() => {
    if (focusVersion != null) setViewVersion(focusVersion);
  }, [focusVersion]);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Which assets the assistant may draw from — managed in the Media Pool tab.
  const mediaPool = project.media_ids ?? [];


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
  const exportMutation = useExportProjectCut();

  const exportCut = (format: "fcpxml" | "otio" | "edl") =>
    exportMutation.mutate(
      { id: projectId, data: { format } },
      {
        onSuccess: (r) => {
          const blob = new Blob([r.content ?? ""], { type: "text/plain" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = r.filename ?? "cut-export.txt";
          a.click();
          URL.revokeObjectURL(url);
        },
        onError: () => toast({ title: "Export failed", variant: "destructive" }),
      },
    );
  const renderMutation = useRenderProjectCut();

  // Thumbs up/down on clips — downvotes teach the assistant what footage to
  // avoid in future searches (visual negative exemplars).
  const { data: feedback } = useGetProjectCutFeedback(projectId, {
    query: { queryKey: getGetProjectCutFeedbackQueryKey(projectId) },
  });
  const feedbackMutation = usePostProjectCutFeedback();
  const ratingFor = (c: CutClip): number => {
    for (const fb of feedback?.items ?? []) {
      if (
        fb.media_id === c.media_id &&
        Math.abs(fb.start_time - c.start_time) < 0.5 &&
        Math.abs(fb.end_time - c.end_time) < 0.5
      ) return fb.rating;
    }
    return 0;
  };
  const rateClip = (c: CutClip, rating: 1 | -1) =>
    feedbackMutation.mutate(
      {
        id: projectId,
        data: {
          media_id: c.media_id,
          start_time: c.start_time,
          end_time: c.end_time,
          rating,
          snippet: c.snippet ?? null,
        },
      },
      {
        onSuccess: (r) =>
          queryClient.setQueryData(getGetProjectCutFeedbackQueryKey(projectId), r),
        onError: () => toast({ title: "Couldn't save rating", variant: "destructive" }),
      },
    );

  const refreshCut = () => {
    queryClient.invalidateQueries({ queryKey: getGetProjectCutQueryKey(projectId) });
    setViewVersion(null);
  };

  const send = (textOverride?: string) => {
    const text = (textOverride ?? input).trim();
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

  // Floating prompt bars elsewhere on the page (e.g. over the asset viewport)
  // submit into this chat via a window event.
  useEffect(() => {
    const onPrompt = (e: Event) => {
      const text = (e as CustomEvent<string>).detail;
      // The dispatcher also queues the prompt for not-yet-mounted chats; we
      // consumed it here, so clear the queue to avoid a double send.
      (window as unknown as { __obtvPendingPrompt?: string }).__obtvPendingPrompt = undefined;
      if (typeof text === "string" && text.trim()) send(text);
    };
    // Consume a prompt queued before this chat was mounted (e.g. the floating
    // bar fired while the Studio session was still opening).
    const pending = (window as unknown as { __obtvPendingPrompt?: string }).__obtvPendingPrompt;
    if (typeof pending === "string" && pending.trim() && !assistantBusy) {
      (window as unknown as { __obtvPendingPrompt?: string }).__obtvPendingPrompt = undefined;
      send(pending);
    }
    window.addEventListener("obtv:studio-prompt", onPrompt);
    return () => window.removeEventListener("obtv:studio-prompt", onPrompt);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assistantBusy, projectId]);

  const clips = cut?.clips ?? [];
  const latestVersion = cut?.versions?.length ? Math.max(...cut.versions) : 0;

  // Surface the current cut to the host page (asset viewport PREVIEW mode).
  useEffect(() => {
    onCutChange?.(clips);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clips]);
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
  const openClipEditor = (i: number) => {
    const c = clips[i];
    setEditDraft({ in: c.start_time, out: c.end_time });
    setEditIdx(i);
  };
  const closeClipEditor = () => { setEditIdx(null); setEditDraft(null); };
  const saveClipTrim = () => {
    if (editIdx == null || !editDraft) return;
    patchClips(clips.map((c, j) => (j === editIdx ? { ...c, start_time: editDraft.in, end_time: editDraft.out } : c)));
    closeClipEditor();
  };

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
    <div
      ref={gridRef}
      className={
        cutHost
          ? "flex flex-col gap-4 h-full min-h-0"
          : chatOpen
            ? // Project studio page: 2 columns — chat left, cut/player right (larger)
              "grid gap-4 items-start lg:grid-cols-[minmax(260px,1fr)_minmax(0,4fr)]"
            : "flex flex-col gap-4"
      }
    >
      {/* ── Chat pane (collapsible; left column on the project studio page) ── */}
      {!chatOpen && !cutHost && (
        <button
          type="button"
          onClick={() => setChatOpen(true)}
          title="Show the editorial assistant"
          className="h-9 border border-border rounded-lg bg-card/50 flex items-center gap-2 px-3 text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
        >
          <Sparkles className="w-4 h-4 text-primary" />
          <span className="text-[11px] font-medium tracking-wide">Editorial assistant</span>
          <PanelLeftOpen className="w-3.5 h-3.5 ml-auto" />
        </button>
      )}
      <div
        className={`min-w-0 ${chatOpen || cutHost ? "flex" : "hidden"} flex-col ${cutHost ? "flex-1 min-h-0" : `border border-border rounded-lg bg-card/50 ${panelH} min-h-[420px]`}`}
        style={cutHost ? undefined : panelStyle}
      >
        {!cutHost && (
        <div className="px-4 py-3 border-b border-border flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-primary" />
          <span className="text-sm font-medium">Editorial assistant</span>
          <Button
            size="sm" variant="outline" className="ml-auto h-7 text-xs"
            onClick={() => onOpenPool?.()}
            data-testid="button-media-pool"
          >
            <Film className="w-3.5 h-3.5 mr-1.5" />
            {mediaPool.length ? `Media pool: ${mediaPool.length}` : "Media pool: all"}
          </Button>
          <button
            type="button"
            onClick={() => setChatOpen(false)}
            title="Hide the assistant"
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <PanelLeftClose className="w-4 h-4" />
          </button>
        </div>
        )}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
          {!(messages ?? []).length && (
            <div className="text-sm text-muted-foreground space-y-3 pt-4">
              <p>Tell me what to build — I'll assemble a cut from this footage and revise it as we talk. You can also just ask questions about what's in it.</p>
              <div className="flex flex-wrap gap-2">
                {[
                  "What are the main topics covered?",
                  "Cut a 30 second clip of the key moments",
                  "Build a 2 minute highlight reel",
                  "Find the strongest soundbites",
                ].map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setInput(s)}
                    className="text-xs rounded-full border border-border px-3 py-1.5 hover:bg-muted hover:text-foreground transition-colors"
                  >
                    {s}
                  </button>
                ))}
              </div>
              <p className="text-xs">Then refine: "make it shorter", "less of the host", "drop clip 2", "render it".</p>
            </div>
          )}
          {(messages ?? []).map((m) => (
            <div key={m.id} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
              <div
                className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                  m.role === "user"
                    ? "bg-primary text-primary-foreground whitespace-pre-wrap"
                    : "bg-muted/60"
                }`}
                data-testid={`chat-msg-${m.id}`}
              >
                {m.status === "running" ? (
                  <span className="inline-flex items-center gap-2 text-muted-foreground">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> Working on the cut…
                  </span>
                ) : (
                  <>
                    {m.role === "user" ? m.content : <ChatMarkdown text={m.content ?? ""} onSeek={onSeekSource} />}
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
          <Button size="icon" onClick={() => send()} disabled={assistantBusy || !input.trim()} data-testid="button-send-chat">
            <Send className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {/* ── Living cut pane — portalled into cutHost (e.g. the asset page's bottom bar) when provided ── */}
      {(() => {
      const cutPane = (
      <div
        className={
          cutHost
            ? "min-w-0 border border-border rounded-lg bg-card/50 flex flex-col max-h-[46vh]"
            : `min-w-0 border border-border rounded-lg bg-card/50 flex flex-col ${panelH} min-h-[420px]`
        }
        style={cutHost ? undefined : panelStyle}
      >
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
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  size="sm" variant="outline"
                  disabled={!clips.length || viewingOld || exportMutation.isPending}
                  data-testid="button-export-cut"
                >
                  <Download className="w-4 h-4 mr-1.5" /> Export
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => exportCut("fcpxml")} data-testid="menu-export-fcpxml">
                  Premiere (FCPXML)
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => exportCut("otio")} data-testid="menu-export-otio">
                  Resolve (OTIO)
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => exportCut("edl")} data-testid="menu-export-edl">
                  EDL (CMX 3600)
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button
              size="sm"
              variant="outline"
              onClick={() => { setPreviewIndex(0); setPreviewOpen(true); }}
              disabled={!clips.length}
              data-testid="button-preview-cut"
            >
              <Play className="w-4 h-4 mr-1.5" /> Preview
            </Button>
            <Button
              size="sm"
              onClick={() =>
                renderMutation.mutate(
                  { id: projectId, data: { preset: "original" } },
                  {
                    onSuccess: () => toast({ title: "Render started", description: "Track progress in the Deliver tab." }),
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
          {viewingOld && (
            <div className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200 flex items-center justify-between gap-3">
              <span>
                You're viewing v{viewVersion} — the chat still edits the latest version (v{latestVersion}).
                Restore v{viewVersion} to keep working from it.
              </span>
              <Button
                size="sm" variant="outline" className="h-7 shrink-0 border-amber-500/50"
                onClick={() =>
                  revertMutation.mutate(
                    { id: projectId, data: { version: viewVersion! } },
                    { onSuccess: refreshCut },
                  )
                }
                disabled={revertMutation.isPending}
                data-testid="button-restore-version-banner"
              >
                Restore v{viewVersion}
              </Button>
            </div>
          )}
          {(previewOpen || !cutHost) && clips.length > 0 && !previewLarge && (
            // Sticky: the player stays pinned while the clip list scrolls under it.
            <div className="sticky -top-4 z-20 -mx-4 -mt-3 bg-background px-4 pt-3 pb-3 shadow-lg shadow-black/40">
              <CutPreviewPlayer
                clips={clips}
                open={previewOpen || !cutHost}
                initialIndex={previewIndex}
                compact
                onToggleExpand={() => setPreviewLarge(true)}
                onClose={() => setPreviewOpen(false)}
              />
            </div>
          )}
          {previewOpen && clips.length > 0 && previewLarge && (
            <Dialog open onOpenChange={(o) => { if (!o) setPreviewLarge(false); }}>
              <DialogContent className="max-w-[92vw] w-[92vw] sm:max-w-6xl p-4" aria-describedby={undefined}>
                <DialogHeader className="sr-only">
                  <DialogTitle>Preview draft cut</DialogTitle>
                </DialogHeader>
                <CutPreviewPlayer
                  clips={clips}
                  open={previewOpen}
                  initialIndex={previewIndex}
                  expanded
                  onToggleExpand={() => setPreviewLarge(false)}
                  onClose={() => { setPreviewLarge(false); setPreviewOpen(false); }}
                />
              </DialogContent>
            </Dialog>
          )}
          {!clips.length ? (
            <p className="text-sm text-muted-foreground pt-6 text-center">
              No cut yet — describe what you want in the chat and I'll build the first draft.
            </p>
          ) : (
            <>
              {/* Proportional EDL strip only in the standalone pane — in the bottom bar the
                  numbered bar sits on each card so widths always match the cards. */}
              {!cutHost && (
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
              )}
              <div className="flex gap-1.5 overflow-x-auto pb-1">
                  {events.map((ev, i) => (
                    <div key={ev.n} className="w-44 shrink-0 rounded border border-border bg-black/30 overflow-hidden" data-testid={`cut-block-${i}`}>
                      {cutHost && (
                        <div
                          className={`${ev.color} h-6 flex items-center justify-center text-[10px] font-semibold text-black/80 tabular-nums cursor-pointer`}
                          title={`${ev.n}. ${ev.clip.filename} — click to play in the player`}
                          onClick={() => onSeekSource?.(ev.clip.start_time)}
                        >
                          {ev.n}
                        </div>
                      )}
                      <div
                        className="relative cursor-pointer"
                        title={`${ev.clip.filename}\n${fmtTime(ev.clip.start_time)}–${fmtTime(ev.clip.end_time)} — click to play`}
                        onClick={() => {
                          if (cutHost && onSeekSource) {
                            // On the asset page the main player IS the preview — jump it there.
                            onSeekSource(ev.clip.start_time);
                          } else {
                            setPreviewIndex(i); setPreviewOpen(true);
                          }
                        }}
                      >
                        <ClipThumb url={ev.clip.thumbnail_url} mediaId={ev.clip.media_id} time={ev.clip.start_time} className="aspect-video w-full rounded-none border-0" />
                        <span className={`absolute top-1 left-1 ${ev.color} text-black/80 text-[10px] font-semibold rounded px-1 tabular-nums`}>{ev.n}</span>
                        <span className="absolute bottom-1 right-1 bg-black/70 text-white text-[10px] rounded px-1 tabular-nums">{Math.round(ev.dur)}s</span>
                        {ev.clip.locked && (
                          <span className="absolute top-1 right-1 bg-black/70 rounded p-0.5">
                            <Lock className="w-3 h-3 text-amber-400" />
                          </span>
                        )}
                      </div>
                      <div className="px-1.5 py-1">
                        <p className="text-[11px] font-medium truncate" title={ev.clip.filename}>{ev.clip.filename}</p>
                        {ev.clip.snippet ? (
                          <p className="text-[10px] text-muted-foreground truncate" title={ev.clip.snippet}>{ev.clip.snippet}</p>
                        ) : null}
                        <div className="flex items-center pt-0.5 -ml-1">
                          <Button size="icon" variant="ghost" className="h-5 w-5" title="Good clip — more like this"
                            onClick={() => rateClip(ev.clip, 1)} disabled={feedbackMutation.isPending}>
                            <ThumbsUp className={`w-3 h-3 ${ratingFor(ev.clip) === 1 ? "text-emerald-400" : "text-muted-foreground"}`} />
                          </Button>
                          <Button size="icon" variant="ghost" className="h-5 w-5" title="Bad clip — avoid footage like this"
                            onClick={() => rateClip(ev.clip, -1)} disabled={feedbackMutation.isPending}>
                            <ThumbsDown className={`w-3 h-3 ${ratingFor(ev.clip) === -1 ? "text-rose-400" : "text-muted-foreground"}`} />
                          </Button>
                          <Button size="icon" variant="ghost" className="h-5 w-5" title="Preview & trim this clip"
                            onClick={() => openClipEditor(i)} disabled={viewingOld || updateMutation.isPending}>
                            <Scissors className="w-3 h-3 text-muted-foreground" />
                          </Button>
                          <Button size="icon" variant="ghost" className="h-5 w-5"
                            title={ev.clip.locked ? "Unlock — allow the assistant to change this clip" : "Lock — the assistant will keep this clip"}
                            onClick={() => toggleLock(i)} disabled={viewingOld || updateMutation.isPending}>
                            {ev.clip.locked
                              ? <Lock className="w-3 h-3 text-amber-400" />
                              : <LockOpen className="w-3 h-3 text-muted-foreground" />}
                          </Button>
                          <Button size="icon" variant="ghost" className="h-5 w-5" title="Remove clip"
                            onClick={() => removeClip(i)} disabled={viewingOld || updateMutation.isPending}>
                            <Trash2 className="w-3 h-3 text-muted-foreground" />
                          </Button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              <CutStrips clips={events.map((ev) => ev.clip)} />
            </>
          )}
        </div>
      </div>
      );
      return cutHost ? createPortal(cutPane, cutHost) : cutPane;
      })()}

      <Dialog open={editIdx != null} onOpenChange={(o) => { if (!o) closeClipEditor(); }}>
        <DialogContent className="max-w-3xl">
          {editIdx != null && editDraft && clips[editIdx] && (
            <>
              <DialogHeader>
                <DialogTitle className="text-base">
                  Clip {editIdx + 1} — {clips[editIdx].filename}
                </DialogTitle>
              </DialogHeader>
              <TrimPlayer
                mediaId={clips[editIdx].media_id}
                clipKey={`${clips[editIdx].media_id}-${editIdx}`}
                inPoint={editDraft.in}
                outPoint={editDraft.out}
                onChange={(inPoint, outPoint) => setEditDraft({ in: inPoint, out: outPoint })}
              />
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-muted-foreground">
                  {fmtTime(editDraft.in)}–{fmtTime(editDraft.out)} · {Math.round(editDraft.out - editDraft.in)}s
                </span>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={closeClipEditor}>Cancel</Button>
                  <Button
                    size="sm"
                    disabled={updateMutation.isPending || editDraft.out - editDraft.in < 0.5}
                    onClick={saveClipTrim}
                    data-testid="button-save-clip-trim"
                  >
                    {updateMutation.isPending && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
                    Save trim
                  </Button>
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
