import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  useGetProject,
  getGetProjectQueryKey,
  getListProjectsQueryKey,
  useUpdateProject,
  useListClipLists,
  getListClipListsQueryKey,
  useCreateClipList,
  useUpdateClipList,
  useListStories,
  getListStoriesQueryKey,
  useCreateStory,
  useDeleteStory,
  useListReels,
  getListReelsQueryKey,
  useCreateReel,
  useDeleteReel,
  useDeleteRender,
  useCreateClipListRoughCut,
  useListRenders,
  getListRendersQueryKey,
  useRenderClipList,
  useExportClipList,
  usePublishRender,
  useGetPublishPlatforms,
  getGetPublishPlatformsQueryKey,
  useSemanticSearch,
  useScriptMatch,
  useListMedia,
  getListMediaQueryKey,
} from "@workspace/api-client-react";
import type {
  ClipList,
  ClipListUpdateClipsItem,
  SearchResult,
  RenderJob,
  ReelJob,
  ReelClip,
} from "@workspace/api-client-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ReelRatingButtons } from "@/components/reel-rating";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  ArrowLeft, Search, FileText, Scissors, BookOpen, Wand2, Clapperboard,
  Play, Download, Loader2, Save, Plus, Trash2, ArrowUp, ArrowDown,
  Monitor, Smartphone, ChevronDown, Upload, Archive, ArchiveRestore,
  ExternalLink, Lock, LockOpen, SlidersHorizontal, CheckCircle2, AlertTriangle,
} from "lucide-react";
import { RefineTab } from "@/components/project/refine-tab";
import { ClipThumb } from "@/components/project/clip-thumb";
import { MediaPickerGrid } from "@/components/project/media-picker";
import { ClipPlayerDialog, type PlayerClip } from "@/components/project/clip-player-dialog";
import { TimecodeInput } from "@/components/project/timecode-input";
import { formatTC } from "@/lib/timecode";
import { useToast } from "@/hooks/use-toast";

const EXPORT_FORMATS: { format: string; label: string; hint: string }[] = [
  { format: "edl", label: "EDL", hint: "CMX3600 edit decision list" },
  { format: "fcpxml", label: "FCPXML", hint: "Final Cut Pro / DaVinci Resolve" },
  { format: "otio", label: "OTIO", hint: "OpenTimelineIO timeline" },
  { format: "csv", label: "CSV", hint: "Spreadsheet" },
  { format: "json", label: "JSON", hint: "Raw clip data" },
];

function fmtTime(s: number) {
  return formatTC(s, 25, false);
}

const EDL_COLORS = [
  "bg-sky-500/70", "bg-emerald-500/70", "bg-amber-500/70", "bg-fuchsia-500/70",
  "bg-rose-500/70", "bg-indigo-500/70", "bg-teal-500/70", "bg-orange-500/70",
];

function ReelEdlTimeline({ clips, onSeek }: { clips: ReelClip[]; onSeek: (t: number) => void }) {
  const events = useMemo(() => {
    let rec = 0;
    const mediaIds: string[] = [];
    return clips.map((c, i) => {
      if (!mediaIds.includes(c.media_id)) mediaIds.push(c.media_id);
      const dur = Math.max(0, c.end_time - c.start_time);
      const ev = {
        n: i + 1,
        clip: c,
        dur,
        recIn: rec,
        recOut: rec + dur,
        color: EDL_COLORS[mediaIds.indexOf(c.media_id) % EDL_COLORS.length],
      };
      rec += dur;
      return ev;
    });
  }, [clips]);
  const total = events.length ? events[events.length - 1].recOut : 0;
  if (!events.length || total <= 0) return null;

  return (
    <div className="space-y-2">
      <div className="flex h-8 w-full rounded overflow-hidden border border-border bg-black/40">
        {events.map((ev) => (
          <button
            key={ev.n}
            type="button"
            onClick={() => onSeek(ev.recIn)}
            className={`${ev.color} relative h-full border-r border-black/50 last:border-r-0 hover:brightness-125 transition-[filter] cursor-pointer`}
            style={{ width: `${(ev.dur / total) * 100}%`, minWidth: 14 }}
            title={`${ev.n}. ${ev.clip.filename}\nSRC ${fmtTime(ev.clip.start_time)}–${fmtTime(ev.clip.end_time)}\nREC ${fmtTime(ev.recIn)}–${fmtTime(ev.recOut)}`}
          >
            <span className="absolute inset-0 flex items-center justify-center text-[10px] font-semibold text-black/80 tabular-nums">
              {ev.n}
            </span>
          </button>
        ))}
      </div>
      <div className="max-h-40 overflow-y-auto rounded border border-border">
        <table className="w-full text-[11px] tabular-nums">
          <thead className="sticky top-0 bg-muted/80 text-muted-foreground">
            <tr className="[&>th]:px-2 [&>th]:py-1 [&>th]:text-left [&>th]:font-medium">
              <th className="w-8">#</th>
              <th>Source</th>
              <th>Src In–Out</th>
              <th>Rec In–Out</th>
              <th className="text-right">Dur</th>
            </tr>
          </thead>
          <tbody>
            {events.map((ev) => (
              <tr
                key={ev.n}
                className="border-t border-border/60 hover:bg-muted/40 cursor-pointer"
                onClick={() => onSeek(ev.recIn)}
              >
                <td className="px-2 py-1">
                  <span className={`inline-block h-2.5 w-2.5 rounded-sm mr-1 align-middle ${ev.color}`} />
                  {ev.n}
                </td>
                <td className="px-2 py-1 truncate max-w-[160px]" title={ev.clip.snippet ?? undefined}>{ev.clip.filename}</td>
                <td className="px-2 py-1">{fmtTime(ev.clip.start_time)}–{fmtTime(ev.clip.end_time)}</td>
                <td className="px-2 py-1">{fmtTime(ev.recIn)}–{fmtTime(ev.recOut)}</td>
                <td className="px-2 py-1 text-right">{fmtTime(ev.dur)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function JobStatusBadge({ status }: { status: string }) {
  const variant =
    status === "success" ? "default" :
    status === "error" ? "destructive" : "secondary";
  return <Badge variant={variant} className="capitalize">{status}</Badge>;
}

function ApprovalBadge({ list }: { list: ClipList }) {
  if (!list.clips.length) return null;
  if (list.locked) {
    return (
      <Badge
        variant="outline"
        className="shrink-0 text-[10px] px-1.5 py-0 font-normal text-emerald-400 border-emerald-500/40"
        title="Story locked — beats are final"
      >
        Locked ✓
      </Badge>
    );
  }
  const n = list.clips.filter((c) => c.approved).length;
  const all = n === list.clips.length;
  return (
    <Badge
      variant="outline"
      className={`shrink-0 text-[10px] px-1.5 py-0 font-normal ${all ? "text-emerald-400 border-emerald-500/40" : "text-amber-500 border-amber-500/40"}`}
      title={all ? "All beats approved in Refine" : "Review and approve the remaining beats in the Refine tab"}
    >
      {n}/{list.clips.length} approved
    </Badge>
  );
}

function UnreviewedBadge({ show }: { show: boolean | null | undefined }) {
  if (!show) return null;
  return (
    <Badge
      variant="outline"
      className="shrink-0 text-[10px] px-1.5 py-0 font-normal text-amber-500 border-amber-500/40"
      title="Rendered before all beats were approved in Refine"
    >
      Unreviewed
    </Badge>
  );
}

export default function ProjectDetail() {
  const { id = "" } = useParams<{ id: string }>();
  const [, navigate] = useLocation();
  const queryClient = useQueryClient();

  const [tab, setTab] = useState<string>(() => {
    const t = new URLSearchParams(window.location.search).get("tab") ?? "";
    return ["find", "assemble", "refine", "cut", "deliver"].includes(t) ? t : "find";
  });
  const [refineFocus, setRefineFocus] = useState<{ id: string } | null>(null);
  const [approvalGate, setApprovalGate] = useState<{ list: ClipList; action: "roughcut" | "render" } | null>(null);

  const { data: project, isLoading } = useGetProject(id);
  const updateMutation = useUpdateProject();

  const listParams = { project_id: id };
  const { data: clipLists } = useListClipLists(listParams, {
    query: { queryKey: getListClipListsQueryKey(listParams) },
  });
  const { data: stories } = useListStories(listParams, {
    query: { queryKey: getListStoriesQueryKey(listParams) },
  });
  const { data: reels } = useListReels(listParams, {
    query: { queryKey: getListReelsQueryKey(listParams), refetchInterval: 5000 },
  });
  const { data: renders } = useListRenders(listParams, {
    query: { queryKey: getListRendersQueryKey(listParams), refetchInterval: 5000 },
  });
  const mediaParams = { limit: 200 };
  const { data: media } = useListMedia(mediaParams, {
    query: { queryKey: getListMediaQueryKey(mediaParams) },
  });
  const [playerClip, setPlayerClip] = useState<PlayerClip | null>(null);

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: getGetProjectQueryKey(id) });
    queryClient.invalidateQueries({ queryKey: getListProjectsQueryKey() });
    queryClient.invalidateQueries({ queryKey: getListClipListsQueryKey(listParams) });
    queryClient.invalidateQueries({ queryKey: getListStoriesQueryKey(listParams) });
    queryClient.invalidateQueries({ queryKey: getListReelsQueryKey(listParams) });
    queryClient.invalidateQueries({ queryKey: getListRendersQueryKey(listParams) });
  };

  // ---- Script ----
  const [script, setScript] = useState("");
  const [scriptDirty, setScriptDirty] = useState(false);
  useEffect(() => {
    if (project && !scriptDirty) setScript(project.script ?? "");
  }, [project, scriptDirty]);

  const saveScript = () => {
    updateMutation.mutate(
      { id, data: { script } },
      { onSuccess: () => { setScriptDirty(false); invalidateAll(); } },
    );
  };

  const toggleArchive = () => {
    if (!project) return;
    updateMutation.mutate(
      { id, data: { status: project.status === "archived" ? "active" : "archived" } },
      { onSuccess: invalidateAll },
    );
  };

  // ---- Media pool: restrict Find to selected assets ----
  const mediaPool = useMemo(() => project?.media_ids ?? [], [project?.media_ids]);
  const toggleMediaPool = (assetId: string, checked: boolean) => {
    const next = checked ? [...mediaPool, assetId] : mediaPool.filter((x) => x !== assetId);
    updateMutation.mutate({ id, data: { media_ids: next } }, { onSuccess: invalidateAll });
  };

  const toggleMediaPoolMany = (assetIds: string[], checked: boolean) => {
    const next = checked
      ? [...mediaPool, ...assetIds.filter((x) => !mediaPool.includes(x))]
      : mediaPool.filter((x) => !assetIds.includes(x));
    updateMutation.mutate({ id, data: { media_ids: next } }, { onSuccess: invalidateAll });
  };

  const clearMediaPool = () => {
    updateMutation.mutate({ id, data: { media_ids: [] } }, { onSuccess: invalidateAll });
  };

  // ---- Find: search + script match + add-to-list ----
  const searchMutation = useSemanticSearch();
  const matchMutation = useScriptMatch();
  const createListMutation = useCreateClipList();
  const updateListMutation = useUpdateClipList();

  const [query, setQuery] = useState("");
  const [searchAllMedia, setSearchAllMedia] = useState(false);
  const [targetListId, setTargetListId] = useState<string>("");
  const [lastAdded, setLastAdded] = useState<string | null>(null);
  // Rapid "Add" clicks race the clip-list refetch: each click would rebuild the
  // list from stale cache and overwrite the previous add. Track the latest
  // known clips per list synchronously so consecutive adds accumulate.
  const pendingClipsRef = useRef<Record<string, ClipListUpdateClipsItem[]>>({});
  const reelVideoRefs = useRef<Record<string, HTMLVideoElement | null>>({});
  // Multi-select of search / script-match results, keyed by row key.
  const [selectedResults, setSelectedResults] = useState<Record<string, SearchResult>>({});

  useEffect(() => {
    if (!targetListId && clipLists?.length) setTargetListId(clipLists[0].id);
  }, [clipLists, targetListId]);

  const searchScope = searchAllMedia || !mediaPool.length ? {} : { media_ids: mediaPool };

  const runSearch = () => {
    if (query.trim().length < 2) return;
    setSelectedResults({});
    searchMutation.mutate({
      data: { query: query.trim(), ...searchScope },
    });
  };

  const runScriptMatch = () => {
    if (!script.trim()) return;
    setSelectedResults({});
    matchMutation.mutate({
      data: {
        script: script.trim(),
        matches_per_line: 3,
        ...searchScope,
      },
    });
  };

  const addResultsToList = (results: SearchResult[]) => {
    if (!results.length) return;
    const newClips: ClipListUpdateClipsItem[] = results.map((r) => ({
      media_id: r.media_id,
      start_time: r.start_time,
      end_time: r.end_time,
      label: r.snippet?.slice(0, 80) || r.filename,
      approved: false,
      match_reason: `${r.match_type === "visual" ? "Visual" : "Transcript"} match · ${(r.score * 100).toFixed(0)}%${r.snippet ? ` — “${r.snippet}”` : ""}`,
    }));
    const target = clipLists?.find((l) => l.id === targetListId);
    const done = () => {
      setLastAdded(
        results.length === 1
          ? `${results[0].filename} ${fmtTime(results[0].start_time)}`
          : `${results.length} clips`,
      );
      setSelectedResults({});
      invalidateAll();
    };
    if (target) {
      const base: ClipListUpdateClipsItem[] =
        pendingClipsRef.current[target.id] ??
        target.clips.map((c) => ({
          media_id: c.media_id,
          start_time: c.start_time,
          end_time: c.end_time,
          label: c.label ?? undefined,
          notes: c.notes ?? null,
          approved: c.approved ?? false,
          match_reason: c.match_reason ?? null,
        }));
      const clips = [...base, ...newClips];
      pendingClipsRef.current[target.id] = clips;
      updateListMutation.mutate(
        { id: target.id, data: { clips } },
        {
          onSuccess: done,
          onError: () => {
            // Drop the optimistic state so the next add rebuilds from the server.
            delete pendingClipsRef.current[target.id];
          },
        },
      );
    } else {
      createListMutation.mutate(
        {
          data: {
            name: `${project?.name ?? "Project"} — selects`,
            project_id: id,
            clips: newClips,
          },
        },
        {
          onSuccess: (created) => {
            pendingClipsRef.current[created.id] = newClips;
            setTargetListId(created.id);
            done();
          },
        },
      );
    }
  };

  const addResultToList = (r: SearchResult) => addResultsToList([r]);

  const newEmptyList = () => {
    const name = window.prompt("New clip list name", `${project?.name ?? "Project"} — selects`);
    if (!name?.trim()) return;
    createListMutation.mutate(
      { data: { name: name.trim(), project_id: id } },
      {
        onSuccess: (created) => {
          setTargetListId(created.id);
          invalidateAll();
        },
      },
    );
  };

  // ---- Assemble: inline clip editing ----
  const [editing, setEditing] = useState<Record<string, ClipListUpdateClipsItem[]>>({});

  const startEdit = (list: ClipList) => {
    setEditing((e) => ({
      ...e,
      [list.id]: list.clips.map((c) => ({
        media_id: c.media_id,
        start_time: c.start_time,
        end_time: c.end_time,
        label: c.label ?? undefined,
        notes: c.notes ?? null,
        approved: c.approved ?? false,
        match_reason: c.match_reason ?? null,
      })),
    }));
  };

  const editClips = (listId: string, fn: (clips: ClipListUpdateClipsItem[]) => ClipListUpdateClipsItem[]) =>
    setEditing((e) => ({ ...e, [listId]: fn(e[listId] ?? []) }));

  const [toggleLockPending, setToggleLockPending] = useState<string | null>(null);
  const toggleLock = (list: ClipList) => {
    setToggleLockPending(list.id);
    updateListMutation.mutate(
      { id: list.id, data: { locked: !list.locked } },
      {
        onSuccess: () => invalidateAll(),
        onSettled: () => setToggleLockPending(null),
      },
    );
  };

  const saveEdit = (listId: string) => {
    const clips = editing[listId];
    if (!clips) return;
    updateListMutation.mutate(
      { id: listId, data: { clips } },
      {
        onSuccess: () => {
          setEditing((e) => {
            const { [listId]: _drop, ...rest } = e;
            return rest;
          });
          invalidateAll();
        },
      },
    );
  };

  // ---- Assemble: story builder ----
  const createStoryMutation = useCreateStory();
  const [storyAssets, setStoryAssets] = useState<string[]>([]);
  const [storyPrompt, setStoryPrompt] = useState("");
  // The project's media pool (chosen in Find) is the default story source —
  // pre-select it so the editor isn't asked to pick media twice. Once they
  // touch the selection, respect their choice.
  const storyTouchedRef = useRef(false);
  useEffect(() => {
    if (!storyTouchedRef.current && mediaPool.length) setStoryAssets(mediaPool);
  }, [mediaPool]);

  const submitStory = () => {
    if (!storyAssets.length) return;
    createStoryMutation.mutate(
      { data: { asset_ids: storyAssets, prompt: storyPrompt.trim() || null, project_id: id } },
      {
        onSuccess: () => {
          storyTouchedRef.current = false;
          setStoryAssets(mediaPool.length ? mediaPool : []);
          setStoryPrompt("");
          invalidateAll();
        },
      },
    );
  };

  // ---- Cut: reels + rough cuts ----
  const createReelMutation = useCreateReel();
  const roughCutMutation = useCreateClipListRoughCut();
  const [reelPrompt, setReelPrompt] = useState("");
  const [reelPreset, setReelPreset] = useState<"original" | "vertical">("vertical");
  const [reelMinutes, setReelMinutes] = useState("");
  const [reelPace, setReelPace] = useState<"fast" | "normal" | "cinematic">("normal");

  const submitReel = () => {
    if (reelPrompt.trim().length < 3) return;
    const mins = parseFloat(reelMinutes);
    const targetSeconds = Number.isFinite(mins) && mins > 0
      ? Math.min(Math.max(Math.round(mins * 60), 30), 14400)
      : null;
    createReelMutation.mutate(
      {
        data: {
          prompt: reelPrompt.trim(),
          preset: reelPreset,
          pace: reelPace,
          project_id: id,
          ...(targetSeconds ? { target_duration_seconds: targetSeconds } : {}),
          ...(mediaPool.length ? { media_ids: mediaPool } : {}),
        },
      },
      { onSuccess: () => { setReelPrompt(""); invalidateAll(); } },
    );
  };

  const startRoughCut = (listId: string) => {
    roughCutMutation.mutate(
      { id: listId, data: { preset: "original", burn_captions: false } },
      { onSuccess: invalidateAll },
    );
  };

  // ---- Deliver: render / export / publish ----
  const renderListMutation = useRenderClipList();
  const exportMutation = useExportClipList();
  const publishMutation = usePublishRender();
  const { data: platforms } = useGetPublishPlatforms({
    query: { queryKey: getGetPublishPlatformsQueryKey() },
  });

  const [renderTarget, setRenderTarget] = useState<ClipList | null>(null);
  const [preset, setPreset] = useState<"original" | "vertical">("original");
  const [burnCaptions, setBurnCaptions] = useState(false);
  const [exportData, setExportData] = useState<string | null>(null);
  const [exportFilename, setExportFilename] = useState<string | null>(null);
  const [publishTarget, setPublishTarget] = useState<RenderJob | null>(null);
  const [pubTitle, setPubTitle] = useState("");
  const [pubDescription, setPubDescription] = useState("");
  const [pubPrivacy, setPubPrivacy] = useState<"public" | "unlisted" | "private">("unlisted");
  const { toast } = useToast();
  const deleteError = (what: string) => (err: unknown) =>
    toast({
      variant: "destructive",
      title: `Couldn't delete the ${what}`,
      description: err instanceof Error ? err.message : "Unknown error — check the API logs.",
    });
  const deleteStoryMutation = useDeleteStory({ mutation: { onError: deleteError("story") } });
  const deleteReelMutation = useDeleteReel({ mutation: { onError: deleteError("reel") } });
  const deleteRenderMutation = useDeleteRender({ mutation: { onError: deleteError("render") } });

  const submitRender = () => {
    if (!renderTarget) return;
    renderListMutation.mutate(
      { id: renderTarget.id, data: { preset, burn_captions: burnCaptions } },
      { onSuccess: () => { setRenderTarget(null); invalidateAll(); } },
    );
  };

  const handleExport = (listId: string, format: string) => {
    exportMutation.mutate({ id: listId, data: { format } }, {
      onSuccess: (res) => {
        setExportData(res.content);
        setExportFilename(res.filename ?? `export.${format}`);
      },
    });
  };

  const downloadExport = () => {
    if (!exportData) return;
    const blob = new Blob([exportData], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = exportFilename || "export.txt";
    a.click();
    URL.revokeObjectURL(url);
  };

  const submitPublish = () => {
    if (!publishTarget || !pubTitle.trim()) return;
    publishMutation.mutate(
      { id: publishTarget.id, data: { platform: "youtube", title: pubTitle.trim(), description: pubDescription.trim() || null, privacy: pubPrivacy } },
      { onSuccess: () => { setPublishTarget(null); invalidateAll(); } },
    );
  };

  const stageCounts = useMemo(() => ({
    lists: clipLists?.length ?? 0,
    clips: clipLists?.reduce((n, l) => n + l.clips.length, 0) ?? 0,
    stories: stories?.length ?? 0,
    reels: reels?.length ?? 0,
    renders: renders?.length ?? 0,
    delivered: renders?.filter((r) => r.status === "success").length ?? 0,
  }), [clipLists, stories, reels, renders]);

  if (isLoading) {
    return (
      <div className="flex-1 p-8">
        <div className="animate-pulse h-8 w-64 bg-muted rounded mb-6" />
        <div className="animate-pulse h-64 bg-muted rounded" />
      </div>
    );
  }

  if (!project) {
    return (
      <div className="flex-1 p-8 text-center text-muted-foreground py-20">
        Project not found.
        <div className="mt-4">
          <Button variant="outline" onClick={() => navigate("/projects")}>
            <ArrowLeft className="h-4 w-4 mr-2" /> Back to Projects
          </Button>
        </div>
      </div>
    );
  }

  const addTargetPicker = (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground shrink-0">Add results to</span>
      <select
        className="bg-muted border border-border rounded-md px-2 py-1.5 text-sm max-w-[220px]"
        value={targetListId}
        onChange={(e) => setTargetListId(e.target.value)}
      >
        {!clipLists?.length && <option value="">New list (auto-created)</option>}
        {clipLists?.map((l) => (
          <option key={l.id} value={l.id}>{l.name}</option>
        ))}
      </select>
      <Button size="sm" variant="outline" onClick={newEmptyList}>
        <Plus className="h-3.5 w-3.5 mr-1" /> New list
      </Button>
    </div>
  );

  const toggleResult = (key: string, r: SearchResult) => {
    setSelectedResults((prev) => {
      const next = { ...prev };
      if (next[key]) delete next[key];
      else next[key] = r;
      return next;
    });
  };

  const selectedCount = Object.keys(selectedResults).length;

  const addSelectedButton = selectedCount > 0 && (
    <Button
      size="sm"
      onClick={() => addResultsToList(Object.values(selectedResults))}
      disabled={updateListMutation.isPending || createListMutation.isPending}
    >
      {updateListMutation.isPending || createListMutation.isPending
        ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
        : <Plus className="h-3.5 w-3.5 mr-1" />}
      Add {selectedCount} selected
    </Button>
  );

  const resultRow = (r: SearchResult, key: string) => (
    <div key={key} className="flex items-center justify-between bg-muted/50 p-2.5 rounded text-sm gap-3">
      <input
        type="checkbox"
        className="h-4 w-4 shrink-0 accent-primary cursor-pointer"
        checked={!!selectedResults[key]}
        onChange={() => toggleResult(key, r)}
      />
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{r.filename}</div>
        <div className="text-xs text-muted-foreground truncate">
          {fmtTime(r.start_time)}–{fmtTime(r.end_time)} · {r.match_type} · {(r.score * 100).toFixed(0)}%
          {r.snippet ? ` · “${r.snippet}”` : ""}
        </div>
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        <Button
          size="icon" variant="ghost" className="h-7 w-7" title="Play this clip"
          onClick={() => setPlayerClip({
            media_id: r.media_id,
            start_time: r.start_time,
            end_time: r.end_time,
            label: r.snippet || undefined,
            filename: r.filename,
          })}
        >
          <Play className="h-3.5 w-3.5" />
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => addResultToList(r)}
          disabled={updateListMutation.isPending || createListMutation.isPending}
        >
          <Plus className="h-3.5 w-3.5 mr-1" /> Add
        </Button>
      </div>
    </div>
  );

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <div className="flex items-start justify-between mb-4 gap-4">
        <div className="min-w-0">
          <Button variant="ghost" size="sm" className="mb-2 -ml-2 text-muted-foreground" onClick={() => navigate("/projects")}>
            <ArrowLeft className="h-4 w-4 mr-1" /> Projects
          </Button>
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight truncate">{project.name}</h1>
            {project.status === "archived" && <Badge variant="secondary">Archived</Badge>}
          </div>
          {project.description && (
            <p className="text-sm text-muted-foreground mt-1">{project.description}</p>
          )}
        </div>
        <Button variant="outline" size="sm" onClick={toggleArchive} disabled={updateMutation.isPending}>
          {project.status === "archived"
            ? <><ArchiveRestore className="h-4 w-4 mr-2" /> Unarchive</>
            : <><Archive className="h-4 w-4 mr-2" /> Archive</>}
        </Button>
      </div>

      <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted-foreground mb-6">
        <span className="flex items-center gap-1.5"><Scissors className="h-3.5 w-3.5" /> {stageCounts.clips} clips in {stageCounts.lists} lists</span>
        <span className="flex items-center gap-1.5"><BookOpen className="h-3.5 w-3.5" /> {stageCounts.stories} stories</span>
        <span className="flex items-center gap-1.5"><Wand2 className="h-3.5 w-3.5" /> {stageCounts.reels} reels</span>
        <span className="flex items-center gap-1.5"><Clapperboard className="h-3.5 w-3.5" /> {stageCounts.delivered}/{stageCounts.renders} renders done</span>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="mb-6">
          <TabsTrigger value="find"><Search className="h-4 w-4 mr-2" /> Find</TabsTrigger>
          <TabsTrigger value="assemble"><Scissors className="h-4 w-4 mr-2" /> Assemble</TabsTrigger>
          <TabsTrigger value="refine"><SlidersHorizontal className="h-4 w-4 mr-2" /> Refine</TabsTrigger>
          <TabsTrigger value="cut"><Wand2 className="h-4 w-4 mr-2" /> Cut</TabsTrigger>
          <TabsTrigger value="deliver"><Clapperboard className="h-4 w-4 mr-2" /> Deliver</TabsTrigger>
        </TabsList>

        {/* ------------------------------ FIND ------------------------------ */}
        <TabsContent value="find" className="space-y-6">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 flex-wrap gap-2">
              <CardTitle className="flex items-center gap-2 text-base">
                <Clapperboard className="h-4 w-4" /> Project Media
              </CardTitle>
              <div className="flex items-center gap-2">
                <Badge variant="secondary">
                  {mediaPool.length ? `${mediaPool.length} selected` : "Whole library"}
                </Badge>
                {mediaPool.length > 0 && (
                  <Button size="sm" variant="ghost" onClick={clearMediaPool} disabled={updateMutation.isPending}>
                    Use whole library
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground mb-3">
                Pick the assets this project works with — search and script matching stay within this media.
              </p>
              <MediaPickerGrid
                selected={mediaPool}
                onToggle={toggleMediaPool}
                onToggleMany={toggleMediaPoolMany}
                togglesDisabled={updateMutation.isPending}
                onPreview={(a) => setPlayerClip({ media_id: a.id, start_time: 0, end_time: null, filename: a.filename })}
                emptyText="The library is empty — drop files in the watch folder or upload from the Library page. They'll appear here once ingested."
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <CardTitle className="flex items-center gap-2 text-base">
                <FileText className="h-4 w-4" /> Working Script
              </CardTitle>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={runScriptMatch}
                  disabled={!script.trim() || matchMutation.isPending}>
                  {matchMutation.isPending
                    ? <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    : <Wand2 className="h-4 w-4 mr-2" />}
                  Match script to footage
                </Button>
                <Button size="sm" onClick={saveScript} disabled={!scriptDirty || updateMutation.isPending}>
                  {updateMutation.isPending
                    ? <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    : <Save className="h-4 w-4 mr-2" />}
                  Save
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <Textarea
                value={script}
                onChange={(e) => { setScript(e.target.value); setScriptDirty(true); }}
                placeholder="Paste the script or rundown — every line can be matched against the footage."
                rows={6}
                className="font-mono text-sm"
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 flex-wrap gap-2">
              <CardTitle className="flex items-center gap-2 text-base">
                <Search className="h-4 w-4" /> Search Footage
              </CardTitle>
              <div className="flex items-center gap-3 flex-wrap">
                {mediaPool.length > 0 && (
                  <div className="flex items-center gap-2" title="Search every indexed asset in the library instead of only this project's media pool">
                    <Switch id="search-all-media" checked={searchAllMedia} onCheckedChange={setSearchAllMedia} />
                    <Label htmlFor="search-all-media" className="text-xs text-muted-foreground cursor-pointer">
                      Whole library
                    </Label>
                  </div>
                )}
                {addSelectedButton}
                {addTargetPicker}
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex gap-2">
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder='e.g. "mayor talks about the housing vote"'
                  onKeyDown={(e) => e.key === "Enter" && runSearch()}
                />
                <Button onClick={runSearch} disabled={query.trim().length < 2 || searchMutation.isPending}>
                  {searchMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                </Button>
              </div>
              {lastAdded && (
                <p className="text-xs text-emerald-400">Added {lastAdded} to the clip list.</p>
              )}
              {searchMutation.isError && (
                <p className="text-sm text-red-400">Search failed — try again.</p>
              )}
              {searchMutation.data && (
                <div className="space-y-2">
                  {searchMutation.data.results.length ? (
                    searchMutation.data.results.map((r, i) => resultRow(r, `s-${i}`))
                  ) : (
                    <p className="text-sm text-muted-foreground">No matches for “{searchMutation.data.query}”.</p>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          {matchMutation.data && (
            <Card>
              <CardHeader>
                <div className="flex flex-row items-center justify-between flex-wrap gap-2">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Wand2 className="h-4 w-4" /> Script Matches
                  </CardTitle>
                  {addSelectedButton}
                </div>
              </CardHeader>
              <CardContent className="space-y-5">
                {matchMutation.data.lines.map((line, li) => (
                  <div key={li}>
                    <p className="text-sm font-medium mb-2 text-muted-foreground">“{line.line}”</p>
                    <div className="space-y-2">
                      {line.matches.length
                        ? line.matches.map((r, mi) => resultRow(r, `m-${li}-${mi}`))
                        : <p className="text-xs text-muted-foreground">No footage matches this line.</p>}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* ---------------------------- ASSEMBLE ---------------------------- */}
        <TabsContent value="assemble" className="space-y-6">
          <div className="flex justify-between items-center">
            <p className="text-sm text-muted-foreground">Arrange the story — order and label clips, or build an AI story from selected assets. Nothing is rendered here; review each beat in Refine, then render in Cut.</p>
            <Button size="sm" variant="outline" onClick={newEmptyList}>
              <Plus className="h-4 w-4 mr-2" /> New clip list
            </Button>
          </div>

          {clipLists?.length ? clipLists.map((list) => {
            const draft = editing[list.id];
            return (
              <Card key={list.id}>
                <CardHeader className="flex flex-row items-center justify-between space-y-0">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Scissors className="h-4 w-4" /> {list.name}
                    <span className="text-xs font-normal text-muted-foreground">
                      {(draft ?? list.clips).length} clips
                    </span>
                    <ApprovalBadge list={list} />
                    {list.locked && (
                      <Badge variant="outline" className="gap-1 text-amber-500 border-amber-500/40 font-normal">
                        <Lock className="h-3 w-3" /> Picture locked
                      </Badge>
                    )}
                  </CardTitle>
                  {draft ? (
                    <div className="flex gap-2">
                      <Button size="sm" variant="outline" onClick={() =>
                        setEditing((e) => { const { [list.id]: _d, ...rest } = e; return rest; })
                      }>Cancel</Button>
                      <Button size="sm" onClick={() => saveEdit(list.id)} disabled={updateListMutation.isPending}>
                        {updateListMutation.isPending
                          ? <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          : <Save className="h-4 w-4 mr-2" />}
                        Save changes
                      </Button>
                    </div>
                  ) : (
                    <div className="flex gap-2">
                      <Button
                        size="sm" variant="outline"
                        className={list.locked ? "text-amber-500" : "text-muted-foreground"}
                        title={list.locked ? "Unlock to allow edits" : "Freeze this cut — no more changes until unlocked"}
                        disabled={toggleLockPending === list.id}
                        onClick={() => toggleLock(list)}
                      >
                        {toggleLockPending === list.id
                          ? <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          : list.locked ? <Lock className="h-4 w-4 mr-2" /> : <LockOpen className="h-4 w-4 mr-2" />}
                        {list.locked ? "Unlock" : "Lock story"}
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => startEdit(list)} disabled={!list.clips.length || list.locked}
                        title={list.locked ? "Picture locked — unlock to edit" : undefined}>
                        Edit clips
                      </Button>
                    </div>
                  )}
                </CardHeader>
                <CardContent className="space-y-2">
                  {draft ? draft.map((c, i) => (
                    <div key={i} className="flex items-center gap-2 bg-muted/50 p-2 rounded text-sm">
                      <div className="flex flex-col">
                        <Button size="icon" variant="ghost" className="h-5 w-5" disabled={i === 0}
                          onClick={() => editClips(list.id, (cs) => {
                            const next = [...cs];
                            [next[i - 1], next[i]] = [next[i], next[i - 1]];
                            return next;
                          })}>
                          <ArrowUp className="h-3 w-3" />
                        </Button>
                        <Button size="icon" variant="ghost" className="h-5 w-5" disabled={i === draft.length - 1}
                          onClick={() => editClips(list.id, (cs) => {
                            const next = [...cs];
                            [next[i], next[i + 1]] = [next[i + 1], next[i]];
                            return next;
                          })}>
                          <ArrowDown className="h-3 w-3" />
                        </Button>
                      </div>
                      <Input
                        className="h-8 flex-1 min-w-0"
                        value={c.label ?? ""}
                        placeholder="Clip label"
                        onChange={(e) => editClips(list.id, (cs) =>
                          cs.map((x, xi) => xi === i ? { ...x, label: e.target.value } : x))}
                      />
                      <div className="flex items-center gap-1 shrink-0">
                        <TimecodeInput
                          className="h-8 w-20 font-mono text-xs"
                          value={c.start_time}
                          title="Start (mm:ss.ff)"
                          onCommit={(v) => editClips(list.id, (cs) =>
                            cs.map((x, xi) => xi === i ? { ...x, start_time: v } : x))}
                        />
                        <span className="text-muted-foreground text-xs">→</span>
                        <TimecodeInput
                          className="h-8 w-20 font-mono text-xs"
                          value={c.end_time}
                          title="End (mm:ss.ff)"
                          onCommit={(v) => editClips(list.id, (cs) =>
                            cs.map((x, xi) => xi === i ? { ...x, end_time: v } : x))}
                        />
                      </div>
                      <Button size="icon" variant="ghost" className="h-7 w-7 text-muted-foreground hover:text-red-400 shrink-0"
                        onClick={() => editClips(list.id, (cs) => cs.filter((_, xi) => xi !== i))}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  )) : list.clips.length ? list.clips.map((clip, i) => (
                    <div key={clip.id} className="flex items-center gap-2 bg-muted/50 p-2 rounded text-sm">
                      <ClipThumb url={clip.thumbnail_url} mediaId={clip.media_id} time={clip.start_time} className="h-9 w-14" />
                      <div className="truncate pr-2 flex-1 min-w-0">
                        <div className="truncate">
                          <span className="text-muted-foreground mr-2">{i + 1}.</span>
                          {clip.label || clip.filename || clip.media_id}
                        </div>
                        {clip.match_reason && (
                          <div className="truncate text-xs text-muted-foreground">{clip.match_reason}</div>
                        )}
                      </div>
                      <div className="flex items-center gap-3 shrink-0">
                        {clip.approved && <CheckCircle2 className="h-4 w-4 text-emerald-400" aria-label="Approved" />}
                        <span className="font-mono text-xs">{fmtTime(clip.start_time)} – {fmtTime(clip.end_time)}</span>
                        <Button
                          size="icon" variant="ghost" className="h-6 w-6" title="Play this clip"
                          onClick={() => setPlayerClip({
                            media_id: clip.media_id,
                            start_time: clip.start_time,
                            end_time: clip.end_time,
                            label: clip.label,
                            filename: clip.filename,
                          })}
                        >
                          <Play className="h-3 w-3" />
                        </Button>
                      </div>
                    </div>
                  )) : (
                    <p className="text-sm text-muted-foreground">Empty — add clips from the Find tab.</p>
                  )}
                </CardContent>
              </Card>
            );
          }) : (
            <div className="text-center text-muted-foreground py-10 border border-dashed border-border rounded-lg">
              No clip lists yet — search footage in the Find tab and add clips.
            </div>
          )}

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <BookOpen className="h-4 w-4" /> Build a Story
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label className="mb-2 block">Source assets</Label>
                {mediaPool.length > 0 && (
                  <p className="text-xs text-muted-foreground mb-2">
                    Your project media (from Find) is pre-selected — narrow it down here if you only want some of it in the story.
                  </p>
                )}
                <MediaPickerGrid
                  selected={storyAssets}
                  onToggle={(assetId, checked) => {
                    storyTouchedRef.current = true;
                    setStoryAssets((s) =>
                      checked ? [...s, assetId] : s.filter((x) => x !== assetId));
                  }}
                  onToggleMany={(assetIds, checked) => {
                    storyTouchedRef.current = true;
                    setStoryAssets((s) =>
                      checked
                        ? [...s, ...assetIds.filter((x) => !s.includes(x))]
                        : s.filter((x) => !assetIds.includes(x)));
                  }}
                  restrictTo={mediaPool.length ? mediaPool : undefined}
                  requireReady
                  gridClass="sm:grid-cols-2"
                  onPreview={(a) => setPlayerClip({ media_id: a.id, start_time: 0, end_time: null, filename: a.filename })}
                  emptyText="The library is empty — add or upload footage first, then build a story from it here."
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="story-prompt">Editorial direction (optional)</Label>
                <Input
                  id="story-prompt"
                  value={storyPrompt}
                  onChange={(e) => setStoryPrompt(e.target.value)}
                  placeholder='e.g. "focus on the community reaction"'
                />
              </div>
              {createStoryMutation.isError && (
                <p className="text-sm text-red-400">Could not start the story — try again.</p>
              )}
              <Button onClick={submitStory} disabled={!storyAssets.length || createStoryMutation.isPending}>
                {createStoryMutation.isPending
                  ? <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  : <BookOpen className="h-4 w-4 mr-2" />}
                Build story from {storyAssets.length || "selected"} asset{storyAssets.length === 1 ? "" : "s"}
              </Button>

              {stories?.length ? (
                <div className="space-y-2 pt-2">
                  {stories.map((s) => (
                    <div key={s.id} className="bg-muted/50 p-2.5 rounded text-sm space-y-1">
                      <div className="flex items-center justify-between gap-3">
                        <span className="truncate font-medium">{s.title || s.prompt || `${s.asset_ids.length} assets`}</span>
                        <div className="flex items-center gap-1 shrink-0">
                          <JobStatusBadge status={s.status} />
                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-7 w-7 text-muted-foreground hover:text-red-400"
                            onClick={() => deleteStoryMutation.mutate({ id: s.id }, { onSuccess: invalidateAll })}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </div>
                      {s.status === "running" && (
                        <p className="text-xs text-muted-foreground">Building… {Math.round(s.progress ?? 0)}%</p>
                      )}
                      {s.status === "error" && s.error_message && (
                        <p className="text-xs text-red-400">{s.error_message}</p>
                      )}
                      {s.narrative && (
                        <p className="text-xs text-muted-foreground leading-relaxed">{s.narrative}</p>
                      )}
                    </div>
                  ))}
                </div>
              ) : null}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ----------------------------- REFINE ----------------------------- */}
        <TabsContent value="refine" className="space-y-6">
          <p className="text-sm text-muted-foreground">
            Review and trim each beat right here — play it, drag the in/out points, see why it was picked, and approve it. Lock the story when the cut is final.
          </p>
          <RefineTab projectId={id} clipLists={clipLists} assets={media?.items} onChanged={invalidateAll} focusList={refineFocus} />
        </TabsContent>

        {/* ------------------------------ CUT ------------------------------ */}
        <TabsContent value="cut" className="space-y-6">
          <p className="text-sm text-muted-foreground">
            Cut renders actual video files — build a reel from a prompt, or turn a clip list into a rough-cut video.
          </p>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Wand2 className="h-4 w-4" /> Build from Prompt
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex gap-2">
                <Input
                  value={reelPrompt}
                  onChange={(e) => setReelPrompt(e.target.value)}
                  placeholder='Describe what to build, e.g. "a highlight reel of the strongest soundbites about the vote"'
                  onKeyDown={(e) => e.key === "Enter" && submitReel()}
                />
                <Input
                  value={reelMinutes}
                  onChange={(e) => setReelMinutes(e.target.value.replace(/[^0-9.]/g, ""))}
                  placeholder="Auto"
                  inputMode="decimal"
                  title="Target run time in minutes (blank = short highlight reel, up to 240 for feature length)"
                  className="w-24 shrink-0"
                />
                <Select value={reelPace} onValueChange={(v) => setReelPace(v as typeof reelPace)}>
                  <SelectTrigger className="w-32 shrink-0" title="Cutting pace — hard max clip length">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="fast">Fast (2–6 s)</SelectItem>
                    <SelectItem value="normal">Normal (≤15 s)</SelectItem>
                    <SelectItem value="cinematic">Cinematic (≤40 s)</SelectItem>
                  </SelectContent>
                </Select>
                <Button variant={reelPreset === "original" ? "default" : "outline"} size="icon"
                  onClick={() => setReelPreset("original")} title="Original framing">
                  <Monitor className="h-4 w-4" />
                </Button>
                <Button variant={reelPreset === "vertical" ? "default" : "outline"} size="icon"
                  onClick={() => setReelPreset("vertical")} title="Vertical 9:16">
                  <Smartphone className="h-4 w-4" />
                </Button>
                <Button onClick={submitReel} disabled={reelPrompt.trim().length < 3 || createReelMutation.isPending}>
                  {createReelMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create"}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Target run time in minutes (optional) — leave blank for a short highlight reel, or set up to 240 for feature-length builds.
                {mediaPool.length ? " Uses this project's media pool." : " Uses the whole library."}
              </p>
              {createReelMutation.isError && (
                <p className="text-sm text-red-400">Could not start the reel — try different wording.</p>
              )}
            </CardContent>
          </Card>

          {clipLists?.length ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <Scissors className="h-4 w-4" /> Rough Cuts from Clip Lists
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {clipLists.map((l) => (
                  <div key={l.id} className="flex items-center justify-between gap-3 bg-muted/50 p-2.5 rounded text-sm">
                    <span className="truncate">{l.name} · {l.clips.length} clips</span>
                    <div className="flex items-center gap-2 shrink-0">
                      <ApprovalBadge list={l} />
                      <Button size="sm" variant="outline"
                        onClick={() => {
                          if (!l.locked && !l.clips.every((c) => c.approved)) setApprovalGate({ list: l, action: "roughcut" });
                          else startRoughCut(l.id);
                        }}
                        disabled={!l.clips.length || roughCutMutation.isPending}
                        title={l.clips.length && !l.clips.every((c) => c.approved) ? "Some beats aren't approved yet — review them in Refine first" : undefined}>
                        {roughCutMutation.isPending
                          ? <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          : <Wand2 className="h-4 w-4 mr-2" />}
                        Rough cut
                      </Button>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}

          {reels?.length ? (
            <div className="grid gap-6 md:grid-cols-2">
              {reels.map((reel: ReelJob) => (
                <Card key={reel.id}>
                  <CardHeader className="flex flex-row items-center justify-between space-y-0">
                    <CardTitle className="text-base truncate pr-3">{reel.prompt}</CardTitle>
                    <div className="flex items-center gap-1 shrink-0">
                      <UnreviewedBadge show={reel.unreviewed} />
                      <JobStatusBadge status={reel.status} />
                      <ReelRatingButtons reel={reel} onRated={invalidateAll} />
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7 text-muted-foreground hover:text-red-400"
                        onClick={() => deleteReelMutation.mutate({ id: reel.id }, { onSuccess: invalidateAll })}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {reel.status === "success" && reel.output_url ? (
                      <>
                        <video controls preload="metadata" src={reel.output_url}
                          ref={(el) => { reelVideoRefs.current[reel.id] = el; }}
                          className={`w-full rounded bg-black ${reel.preset === "vertical" ? "max-h-[40vh]" : "aspect-video"}`} />
                        {reel.clips?.length ? (
                          <ReelEdlTimeline
                            clips={reel.clips}
                            onSeek={(t) => {
                              const v = reelVideoRefs.current[reel.id];
                              if (v) { v.currentTime = t; v.play().catch(() => {}); }
                            }}
                          />
                        ) : null}
                      </>
                    ) : reel.status === "error" ? (
                      <p className="text-sm text-red-400">{reel.error_message || "Reel failed."}</p>
                    ) : (
                      <p className="text-sm text-muted-foreground">Rendering… {Math.round(reel.progress ?? 0)}%</p>
                    )}
                    <div className="flex justify-between items-center">
                      <span className="text-xs text-muted-foreground">{reel.clips?.length ?? 0} clips · {reel.preset}</span>
                      {reel.status === "success" && (
                        <a href={`/api/reels/${reel.id}/download`} download>
                          <Button size="sm" variant="outline"><Download className="h-3.5 w-3.5 mr-2" /> Download</Button>
                        </a>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <div className="text-center text-muted-foreground py-10 border border-dashed border-border rounded-lg">
              No reels yet — describe a highlight above or rough-cut a clip list.
            </div>
          )}
        </TabsContent>

        {/* ----------------------------- DELIVER ---------------------------- */}
        <TabsContent value="deliver" className="space-y-6">
          {clipLists?.length ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <Clapperboard className="h-4 w-4" /> Render & Export Clip Lists
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {clipLists.map((l) => (
                  <div key={l.id} className="flex items-center justify-between bg-muted/50 p-2.5 rounded text-sm gap-3">
                    <span className="truncate flex-1">{l.name} · {l.clips.length} clips</span>
                    <ApprovalBadge list={l} />
                    <div className="flex gap-2 shrink-0">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button size="sm" variant="outline">
                            <Download className="h-3.5 w-3.5 mr-2" /> Export <ChevronDown className="h-3 w-3 ml-1" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {EXPORT_FORMATS.map((f) => (
                            <DropdownMenuItem key={f.format} onClick={() => handleExport(l.id, f.format)}>
                              <div>
                                <div className="font-medium">{f.label}</div>
                                <div className="text-xs text-muted-foreground">{f.hint}</div>
                              </div>
                            </DropdownMenuItem>
                          ))}
                        </DropdownMenuContent>
                      </DropdownMenu>
                      <Button size="sm"
                        onClick={() => {
                          if (!l.locked && !l.clips.every((c) => c.approved)) setApprovalGate({ list: l, action: "render" });
                          else { setPreset("original"); setBurnCaptions(false); setRenderTarget(l); }
                        }}
                        disabled={!l.clips.length}>
                        <Clapperboard className="h-3.5 w-3.5 mr-2" /> Render
                      </Button>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : (
            <div className="text-center text-muted-foreground py-10 border border-dashed border-border rounded-lg">
              Nothing to deliver yet — assemble a clip list first.
            </div>
          )}

          {renders?.length ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Renders</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {renders.map((r) => (
                  <div key={r.id} className="flex items-center justify-between bg-muted/50 p-2.5 rounded text-sm gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="truncate">{r.label || r.filename || r.media_id}</div>
                      <div className="text-xs text-muted-foreground">
                        {fmtTime(r.start_time)}–{fmtTime(r.end_time)} · {r.preset}
                        {r.status === "running" ? ` · ${Math.round(r.progress ?? 0)}%` : ""}
                      </div>
                      {r.publish_status === "error" && r.publish_error && (
                        <p className="text-xs text-red-400 mt-0.5 truncate">Publish failed: {r.publish_error}</p>
                      )}
                      {r.publish_stats && (
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {(r.publish_stats.views ?? 0).toLocaleString()} views · {(r.publish_stats.likes ?? 0).toLocaleString()} likes · {(r.publish_stats.comments ?? 0).toLocaleString()} comments
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {r.publish_status && (
                        <Badge variant="outline" className={r.publish_status === "success" ? "bg-green-500/15 text-green-400" : r.publish_status === "error" ? "bg-red-500/15 text-red-400" : "bg-blue-500/15 text-blue-400"}>
                          {r.publish_status === "success" ? "published" : `publish: ${r.publish_status}`}
                        </Badge>
                      )}
                      <UnreviewedBadge show={r.unreviewed} />
                      <JobStatusBadge status={r.status} />
                      {r.publish_url && (
                        <a href={r.publish_url} target="_blank" rel="noreferrer">
                          <Button size="sm" variant="outline"><ExternalLink className="h-3.5 w-3.5 mr-2" /> Watch</Button>
                        </a>
                      )}
                      {r.status === "success" && (
                        <>
                          <a href={`/api/renders/${r.id}/download`} download>
                            <Button size="icon" variant="ghost" className="h-7 w-7"><Download className="h-3.5 w-3.5" /></Button>
                          </a>
                          {platforms?.youtube && !r.publish_url && (
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={r.publish_status === "pending" || r.publish_status === "running"}
                              onClick={() => {
                                setPublishTarget(r);
                                setPubTitle(r.label || project.name);
                                setPubDescription("");
                                setPubPrivacy("unlisted");
                              }}
                            >
                              <Upload className="h-3.5 w-3.5 mr-2" />
                              {r.publish_status === "pending" || r.publish_status === "running" ? "Publishing..." : "Publish"}
                            </Button>
                          )}
                        </>
                      )}
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7 text-muted-foreground hover:text-red-400"
                        onClick={() => deleteRenderMutation.mutate({ id: r.id }, { onSuccess: invalidateAll })}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}
        </TabsContent>
      </Tabs>

      {/* Render dialog */}
      <Dialog open={!!renderTarget} onOpenChange={(open) => !open && setRenderTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Clapperboard className="h-5 w-5" /> Render "{renderTarget?.name}"
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-3">
              <button type="button" onClick={() => setPreset("original")}
                className={`flex flex-col items-center gap-2 rounded-lg border p-4 text-sm transition-colors ${
                  preset === "original" ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:bg-muted"}`}>
                <Monitor className="h-6 w-6" />
                <span className="font-medium">Original</span>
              </button>
              <button type="button" onClick={() => setPreset("vertical")}
                className={`flex flex-col items-center gap-2 rounded-lg border p-4 text-sm transition-colors ${
                  preset === "vertical" ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:bg-muted"}`}>
                <Smartphone className="h-6 w-6" />
                <span className="font-medium">Vertical 9:16</span>
              </button>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-border p-4">
              <Label htmlFor="proj-burn-captions">Burn in captions</Label>
              <Switch id="proj-burn-captions" checked={burnCaptions} onCheckedChange={setBurnCaptions} />
            </div>
            {renderListMutation.isError && (
              <p className="text-sm text-red-400">Render request failed — is the list empty?</p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenderTarget(null)}>Cancel</Button>
            <Button onClick={submitRender} disabled={renderListMutation.isPending}>
              {renderListMutation.isPending ? "Starting..." : "Start Render"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Approval gate dialog */}
      <Dialog open={!!approvalGate} onOpenChange={(open) => !open && setApprovalGate(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-500" /> Render unreviewed beats?
            </DialogTitle>
          </DialogHeader>
          {approvalGate && (
            <p className="text-sm text-muted-foreground">
              {approvalGate.list.clips.filter((c) => c.approved).length} of {approvalGate.list.clips.length} beats approved. Render anyway?
            </p>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                if (approvalGate) {
                  setRefineFocus({ id: approvalGate.list.id });
                  setTab("refine");
                }
                setApprovalGate(null);
              }}
            >
              <SlidersHorizontal className="h-3.5 w-3.5 mr-2" /> Review in Refine
            </Button>
            <Button
              onClick={() => {
                if (approvalGate) {
                  if (approvalGate.action === "roughcut") startRoughCut(approvalGate.list.id);
                  else { setPreset("original"); setBurnCaptions(false); setRenderTarget(approvalGate.list); }
                }
                setApprovalGate(null);
              }}
            >
              Render unreviewed
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Export dialog */}
      <Dialog open={!!exportData} onOpenChange={(open) => !open && setExportData(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Export Result</DialogTitle>
          </DialogHeader>
          <pre className="bg-muted p-4 rounded-md overflow-x-auto text-xs font-mono max-h-96">{exportData}</pre>
          <div className="flex gap-2">
            <Button onClick={downloadExport}>
              <Download className="h-4 w-4 mr-2" /> Download {exportFilename}
            </Button>
            <Button variant="outline" onClick={() => navigator.clipboard.writeText(exportData || "")}>
              Copy to Clipboard
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Publish dialog */}
      <Dialog open={!!publishTarget} onOpenChange={(open) => !open && setPublishTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Upload className="h-5 w-5" /> Publish to YouTube
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="pub-title">Title</Label>
              <Input id="pub-title" value={pubTitle} onChange={(e) => setPubTitle(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="pub-desc">Description (optional)</Label>
              <Textarea id="pub-desc" rows={3} value={pubDescription} onChange={(e) => setPubDescription(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Visibility</Label>
              <Select value={pubPrivacy} onValueChange={(v) => setPubPrivacy(v as typeof pubPrivacy)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="unlisted">Unlisted</SelectItem>
                  <SelectItem value="private">Private</SelectItem>
                  <SelectItem value="public">Public</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {publishMutation.isError && (
              <p className="text-sm text-red-400">Publish failed — check the YouTube connection.</p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPublishTarget(null)}>Cancel</Button>
            <Button onClick={submitPublish} disabled={!pubTitle.trim() || publishMutation.isPending}>
              {publishMutation.isPending ? "Publishing..." : "Publish"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ClipPlayerDialog clip={playerClip} onClose={() => setPlayerClip(null)} />
    </div>
  );
}
