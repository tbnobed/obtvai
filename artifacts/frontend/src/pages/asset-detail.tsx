import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearch, useLocation, Link } from "wouter";
import { 
  useGetMedia, getGetMediaQueryKey,
  useGetAssetPeople,
  useGetMediaScenes, getGetMediaScenesQueryKey,
  useGetMediaTranscript, getGetMediaTranscriptQueryKey,
  useListJobs, getListJobsQueryKey,
  useDeleteMedia, getListMediaQueryKey,
  useRetryJob,
  useRunStage,
  useCreateCreativePass,
  useCreateSocialAnalysis,
  useCreateSocialCuts,
  useCreateTranslation,
  useCreateDub,
  useUpdateTranscriptSegment,
  useListRenders, getListRendersQueryKey, useDeleteRender,
  useTightenMedia,
  getCaptions,
  useListMarkers, getListMarkersQueryKey,
  useCreateMarker,
  useDeleteMarker,
  useListClipLists, getListClipListsQueryKey,
  useCreateClipList,
  useUpdateClipList, getGetClipListQueryKey,
  useListRatings, getListRatingsQueryKey,
  useGetMediaStudioSession
} from "@workspace/api-client-react";
import type { SocialScore, SocialCutsRequestPlatform, RenderJob, CreativeAnalysis, TightenResult, Marker, TranscriptSegment, Project, SearchResult, CutClip } from "@workspace/api-client-react";
import { useSemanticSearch, useFindSimilarMoments } from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Trash2, Sparkles, Film, Loader2, Download, Share2, Youtube, Instagram, Facebook, Twitter, Music2, TrendingUp, ThumbsUp, ThumbsDown, Clapperboard, Hash, Languages, Volume2, AudioLines, Scissors, Wand2, Smartphone, Monitor, Captions, Star, Flag, XCircle, ListPlus, AlertTriangle, Users, BarChart3, RefreshCw, Search, Pencil, Check, X, ChevronUp, ChevronDown, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Progress } from "@/components/ui/progress";
import { StudioTab } from "@/components/project/studio-tab";
import { ReelRatingButtons } from "@/components/reel-rating";

const PLATFORM_META: Record<string, { label: string; Icon: typeof Youtube; color: string }> = {
  youtube: { label: "YouTube", Icon: Youtube, color: "text-red-500" },
  instagram: { label: "Instagram", Icon: Instagram, color: "text-pink-500" },
  x: { label: "X", Icon: Twitter, color: "text-foreground" },
  facebook: { label: "Facebook", Icon: Facebook, color: "text-blue-500" },
  tiktok: { label: "TikTok", Icon: Music2, color: "text-cyan-400" },
};

const TRANSLATION_LANGUAGES: { code: string; label: string }[] = [
  { code: "es", label: "Spanish" },
  { code: "fr", label: "French" },
  { code: "de", label: "German" },
  { code: "pt", label: "Portuguese" },
  { code: "it", label: "Italian" },
  { code: "nl", label: "Dutch" },
  { code: "ru", label: "Russian" },
  { code: "ja", label: "Japanese" },
  { code: "ko", label: "Korean" },
  { code: "zh", label: "Chinese" },
  { code: "ar", label: "Arabic" },
  { code: "hi", label: "Hindi" },
];

// Languages with a local MMS-TTS voice (Italian, Japanese, Chinese have none).
const DUB_LANGUAGES = ["es", "fr", "de", "pt", "nl", "ru", "ko", "ar", "hi"];

function scoreColor(score: number): string {
  if (score >= 70) return "text-green-500";
  if (score >= 45) return "text-yellow-500";
  return "text-red-500";
}

function scoreBarColor(score: number): string {
  if (score >= 70) return "bg-green-500";
  if (score >= 45) return "bg-yellow-500";
  return "bg-red-500";
}

function formatTimecode(seconds: number): string {
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

export default function AssetDetail() {
  const { id } = useParams<{ id: string }>();
  const searchString = useSearch();
  const searchParams = new URLSearchParams(searchString);
  const timeParam = searchParams.get('t');
  
  const videoRef = useRef<HTMLVideoElement>(null);
  const [, navigate] = useLocation();
  const queryClient = useQueryClient();
  const deleteMutation = useDeleteMedia();
  const [confirmDelete, setConfirmDelete] = useState(false);

  const handleDelete = () => {
    if (!id) return;
    deleteMutation.mutate({ id }, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListMediaQueryKey() });
        navigate("/library");
      }
    });
  };

  const { data: asset, isLoading } = useGetMedia(id!, { 
    query: { 
      enabled: !!id, 
      queryKey: getGetMediaQueryKey(id!),
      refetchInterval: (data) => data?.state?.data?.status === 'processing' ? 3000 : false
    } 
  });

  const { data: scenes } = useGetMediaScenes(id!, { query: { enabled: !!id, queryKey: getGetMediaScenesQueryKey(id!) } });
  const [transcriptLang, setTranscriptLang] = useState<string>("original");
  // Collapsible transcript: open by default on wide screens, closed on laptops
  // so the player and analysis panels get the width.
  const [transcriptOpen, setTranscriptOpen] = useState<boolean>(
    () => typeof window === "undefined" || window.innerWidth >= 1440,
  );
  // Sidebar tabs: transcript or the asset's insights (synopsis + key moments).
  const [sideTab, setSideTab] = useState<"transcript" | "insights">("transcript");
  // Floating Cmd-K style prompt bar over the viewport — routes into the Studio chat.
  const [floatPrompt, setFloatPrompt] = useState("");
  // Single-viewport PREVIEW mode: the main player plays the draft cut in place.
  const [viewMode, setViewMode] = useState<"original" | "preview">("original");
  const [cutClips, setCutClips] = useState<CutClip[]>([]);
  const previewClips = useMemo(() => cutClips.filter((c) => c.media_id === id), [cutClips, id]);

  // Preview playback engine: sequence the draft cut's clips in the main player.
  useEffect(() => {
    if (viewMode !== "preview") return;
    const v = videoRef.current;
    if (!v || !previewClips.length) return;
    let idx = 0;
    v.currentTime = previewClips[0].start_time;
    v.play().catch(() => {});
    const onTime = () => {
      const c = previewClips[idx];
      if (!c) return;
      if (v.currentTime >= c.end_time - 0.05) {
        idx += 1;
        if (idx >= previewClips.length) {
          idx = 0;
          v.pause();
          v.currentTime = previewClips[0].start_time;
        } else {
          v.currentTime = previewClips[idx].start_time;
        }
      }
    };
    v.addEventListener("timeupdate", onTime);
    return () => v.removeEventListener("timeupdate", onTime);
  }, [viewMode, previewClips]);

  // If the cut disappears (cleared/reset), fall back to the original.
  useEffect(() => {
    if (viewMode === "preview" && !previewClips.length) setViewMode("original");
  }, [viewMode, previewClips]);
  const langAvailable = transcriptLang !== "original" && (asset?.translated_languages ?? []).includes(transcriptLang);
  const transcriptParams = langAvailable ? { lang: transcriptLang } : undefined;
  const { data: transcript } = useGetMediaTranscript(id!, transcriptParams, { query: { enabled: !!id, queryKey: getGetMediaTranscriptQueryKey(id!, transcriptParams) } });

  // ── Transcript follows playback ────────────────────────────────────────
  const [activeSegmentId, setActiveSegmentId] = useState<string | null>(null);
  const activeSegmentRef = useRef<HTMLDivElement | null>(null);
  const transcriptUserScrollRef = useRef(0);
  const handleTimeUpdate = () => {
    const t = videoRef.current?.currentTime ?? 0;
    if (!transcript?.length) return;
    let active: TranscriptSegment | null = null;
    for (const seg of transcript) {
      if (seg.start_time <= t) active = seg;
      else break;
    }
    const nextId = active ? String(active.id) : null;
    setActiveSegmentId(prev => (prev === nextId ? prev : nextId));
  };
  useEffect(() => {
    if (!activeSegmentId) return;
    // Don't fight the user: pause auto-follow for a few seconds after they scroll.
    if (Date.now() - transcriptUserScrollRef.current < 4000) return;
    const el = activeSegmentRef.current;
    const viewport = el?.closest('[data-radix-scroll-area-viewport]') as HTMLElement | null;
    if (el && viewport) {
      const elRect = el.getBoundingClientRect();
      const vpRect = viewport.getBoundingClientRect();
      const top = viewport.scrollTop + (elRect.top - vpRect.top) - vpRect.height / 2 + elRect.height / 2;
      viewport.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    }
  }, [activeSegmentId]);
  const markTranscriptUserScroll = () => { transcriptUserScrollRef.current = Date.now(); };

  // ── Markers / selects ──────────────────────────────────────────────────
  const { data: markers } = useListMarkers(id!, { query: { enabled: !!id, queryKey: getListMarkersQueryKey(id!) } });
  const createMarkerMutation = useCreateMarker();
  const deleteMarkerMutation = useDeleteMarker();
  const [markerNote, setMarkerNote] = useState("");
  const invalidateMarkers = () => queryClient.invalidateQueries({ queryKey: getListMarkersQueryKey(id!) });
  const addMarkerAtPlayhead = (kind: "select" | "reject" | "marker") => {
    const t = videoRef.current?.currentTime ?? 0;
    createMarkerMutation.mutate(
      { id: id!, data: { time: t, kind, note: markerNote.trim() || undefined } },
      { onSuccess: () => { setMarkerNote(""); invalidateMarkers(); } },
    );
  };
  const promoteMoment = (time: number, kind: "select" | "reject", note: string) => {
    createMarkerMutation.mutate(
      { id: id!, data: { time, kind, note } },
      { onSuccess: invalidateMarkers },
    );
  };

  // ── Add transcript segment to clip list ────────────────────────────────
  const [clipListSegment, setClipListSegment] = useState<TranscriptSegment | null>(null);
  const { data: jobs } = useListJobs({ media_id: id! }, { query: { enabled: !!id, queryKey: getListJobsQueryKey({ media_id: id! }), refetchInterval: 3000 } });
  const { data: assetRatings } = useListRatings({ asset_id: id!, limit: 100 }, { query: { enabled: !!id, queryKey: getListRatingsQueryKey({ asset_id: id!, limit: 100 }) } });

  const retryJobMutation = useRetryJob();
  const [retryingJobId, setRetryingJobId] = useState<string | null>(null);
  const runStageMutation = useRunStage();
  const [runStageType, setRunStageType] = useState<string>("");

  const creativeMutation = useCreateCreativePass();
  const creativeJob = jobs?.find(j => j.job_type === "creative" && (j.status === "pending" || j.status === "running"));
  const creativeBusy = creativeMutation.isPending || Boolean(creativeJob);

  const startCreative = () => {
    if (!id) return;
    creativeMutation.mutate({ id }, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListJobsQueryKey({ media_id: id }) });
      }
    });
  };

  const tightenMutation = useTightenMedia();
  const [tightenResult, setTightenResult] = useState<TightenResult | null>(null);
  const startTighten = () => {
    if (!id) return;
    tightenMutation.mutate(
      { id, data: { silence_threshold: 1.25, remove_fillers: true } },
      { onSuccess: (res) => setTightenResult(res) },
    );
  };

  const [captionsBusy, setCaptionsBusy] = useState<string | null>(null);
  const downloadCaptions = async (format: "srt" | "vtt") => {
    if (!id) return;
    setCaptionsBusy(format);
    try {
      const lang = transcriptLang !== "original" && langAvailable ? transcriptLang : undefined;
      const res = await getCaptions(id, lang ? { format, lang } : { format });
      const blob = new Blob([res.content], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = res.filename ?? `captions.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setCaptionsBusy(null);
    }
  };

  const socialMutation = useCreateSocialAnalysis();
  const socialJob = jobs?.find(j => j.job_type === "social" && (j.status === "pending" || j.status === "running"));
  const socialBusy = socialMutation.isPending || Boolean(socialJob);

  const startSocial = () => {
    if (!id) return;
    socialMutation.mutate({ id }, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListJobsQueryKey({ media_id: id }) });
      }
    });
  };

  // Tab selection lives in the URL (?tab=) so browser back/forward walks
  // through the views you visited instead of leaving the page.
  const activeTab = searchParams.get("tab");
  const setActiveTab = (v: string) => {
    const p = new URLSearchParams(searchString);
    p.set("tab", v);
    p.delete("t");
    navigate(`/library/${id}?${p.toString()}`);
  };
  // Editorial Assistant lives in an overlay drawer, never a permanent column.
  const [chatDrawerOpen, setChatDrawerOpen] = useState(false);
  const cutsMutation = useCreateSocialCuts();
  const [cutsPlatform, setCutsPlatform] = useState<string | null>(null);
  const [cutsCreated, setCutsCreated] = useState<number | null>(null);
  const [cutsError, setCutsError] = useState<string | null>(null);

  const startCuts = (platform: SocialCutsRequestPlatform | null) => {
    if (!id) return;
    setCutsPlatform(platform ?? "all");
    setCutsCreated(null);
    setCutsError(null);
    cutsMutation.mutate(
      { id, data: platform ? { platform } : {} },
      {
        onSuccess: (created) => {
          setCutsCreated(Array.isArray(created) ? created.length : 0);
          queryClient.invalidateQueries({ queryKey: getListRendersQueryKey({ media_id: id }) });
        },
        onError: (err: any) => {
          const detail = err?.detail || err?.error || err?.message;
          setCutsError(
            typeof detail === "string" && detail
              ? detail
              : "Failed to create cuts. Check that key moments exist and the pipeline is running."
          );
        },
        onSettled: () => setCutsPlatform(null),
      },
    );
  };

  const translateMutation = useCreateTranslation();
  const translateJob = jobs?.find(j => j.job_type === "translate" && (j.status === "pending" || j.status === "running") && (j.logs ?? []).includes(`Target language: ${transcriptLang}`));
  const translateBusy = translateMutation.isPending || Boolean(translateJob);

  const startTranslate = (lang: string) => {
    if (!id) return;
    translateMutation.mutate({ id, data: { target_language: lang } }, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListJobsQueryKey({ media_id: id }) });
      }
    });
  };

  const dubMutation = useCreateDub();
  const dubJob = jobs?.find(j => j.job_type === "dub" && (j.status === "pending" || j.status === "running") && (j.logs ?? []).includes(`Target language: ${transcriptLang}`));
  const dubBusy = dubMutation.isPending || Boolean(dubJob);

  const [dubClonedVoices, setDubClonedVoices] = useState(true);
  const [dubLipSync, setDubLipSync] = useState(false);

  // ── Inline transcript/translation editing ──────────────────────────────
  const segmentUpdateMutation = useUpdateTranscriptSegment();
  const [editingSegId, setEditingSegId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const saveSegmentEdit = (segmentId: string) => {
    if (!id || !editText.trim()) return;
    const lang = transcriptLang !== "original" && langAvailable ? transcriptLang : null;
    segmentUpdateMutation.mutate(
      { id, segmentId, data: { text: editText.trim(), lang } },
      {
        onSuccess: () => {
          setEditingSegId(null);
          queryClient.invalidateQueries({ queryKey: getGetMediaTranscriptQueryKey(id, transcriptParams) });
        },
      },
    );
  };
  const startDub = (lang: string) => {
    if (!id) return;
    dubMutation.mutate({ id, data: { target_language: lang, use_cloned_voices: dubClonedVoices, lip_sync: dubLipSync } }, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListJobsQueryKey({ media_id: id }) });
      }
    });
  };

  const dubSupported = DUB_LANGUAGES.includes(transcriptLang);
  const dubAvailable = dubSupported && (asset?.dubbed_languages ?? []).includes(transcriptLang);
  const [dubOn, setDubOn] = useState(false);

  // Turn dubbed playback off whenever it stops being applicable.
  useEffect(() => {
    if (!dubAvailable && dubOn) setDubOn(false);
  }, [dubAvailable, dubOn]);

  // Toggling dub switches the player's SOURCE to the muxed dubbed video —
  // preserve position and play state across the swap.
  const toggleDub = () => {
    const video = videoRef.current;
    const t = video?.currentTime ?? 0;
    const wasPlaying = video ? !video.paused : false;
    setDubOn(v => !v);
    requestAnimationFrame(() => {
      const v = videoRef.current;
      if (!v) return;
      const restore = () => {
        v.currentTime = t;
        if (wasPlaying) v.play().catch(() => {});
        v.removeEventListener("loadedmetadata", restore);
      };
      v.addEventListener("loadedmetadata", restore);
    });
  };

  // When a highlight/social/translate job finishes, refresh the asset so results appear.
  const lastHighlightStatus = jobs?.filter(j => j.job_type === "highlight")
    .sort((a, b) => (b.created_at > a.created_at ? 1 : -1))[0]?.status;
  const lastSocialStatus = jobs?.filter(j => j.job_type === "social")
    .sort((a, b) => (b.created_at > a.created_at ? 1 : -1))[0]?.status;
  const lastCreativeStatus = jobs?.filter(j => j.job_type === "creative")
    .sort((a, b) => (b.created_at > a.created_at ? 1 : -1))[0]?.status;
  const lastTranslateJob = jobs?.filter(j => j.job_type === "translate")
    .sort((a, b) => (b.created_at > a.created_at ? 1 : -1))[0];
  const lastTranslateStatus = lastTranslateJob?.status;
  const lastDubJob = jobs?.filter(j => j.job_type === "dub")
    .sort((a, b) => (b.created_at > a.created_at ? 1 : -1))[0];
  const lastDubStatus = lastDubJob?.status;
  const lastSentimentStatus = jobs?.filter(j => j.job_type === "sentiment")
    .sort((a, b) => (b.created_at > a.created_at ? 1 : -1))[0]?.status;
  useEffect(() => {
    if ((lastHighlightStatus === "success" || lastSocialStatus === "success" || lastCreativeStatus === "success" || lastTranslateStatus === "success" || lastDubStatus === "success") && id) {
      queryClient.invalidateQueries({ queryKey: getGetMediaQueryKey(id) });
    }
  }, [lastHighlightStatus, lastSocialStatus, lastCreativeStatus, lastTranslateStatus, lastDubStatus, id, queryClient]);
  // When a sentiment pass finishes, refresh the transcript so emotion
  // chips and the timeline emotion lane appear without a reload.
  useEffect(() => {
    if (lastSentimentStatus === "success" && id) {
      queryClient.invalidateQueries({ queryKey: getGetMediaTranscriptQueryKey(id, transcriptParams) });
    }
  }, [lastSentimentStatus, id, queryClient]);

  useEffect(() => {
    if (timeParam && videoRef.current && asset?.status === 'ready') {
      const t = parseFloat(timeParam);
      if (!isNaN(t)) {
        videoRef.current.currentTime = t;
        // Optionally auto-play
        // videoRef.current.play().catch(() => {});
      }
    }
  }, [timeParam, asset?.status]);

  const similarMoments = useFindSimilarMoments();
  const [similarOpen, setSimilarOpen] = useState(false);
  const [similarAt, setSimilarAt] = useState(0);
  const findSimilar = (at?: number) => {
    const t = at ?? videoRef.current?.currentTime ?? 0;
    setSimilarAt(t);
    setSimilarOpen(true);
    similarMoments.mutate({ data: { media_id: id!, time: t, limit: 10 } });
  };

  const seekTo = (time: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = time;
      videoRef.current.play();
      videoRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  if (isLoading) {
    return <div className="p-8">Loading asset...</div>;
  }

  if (!asset) {
    return <div className="p-8">Asset not found.</div>;
  }

  const hasAnalysis = Boolean(
    asset.synopsis ||
    (asset.key_moments && asset.key_moments.length > 0) ||
    (asset.topics && asset.topics.length > 0)
  );

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      <div className="flex-1 flex overflow-hidden">
        {/* Transcript Panel — collapsible so laptops keep room for the player */}
        {!transcriptOpen && (
          <button
            type="button"
            onClick={() => setTranscriptOpen(true)}
            title="Show transcript"
            className={`w-9 shrink-0 border-r border-border bg-card flex-col items-center gap-2 pt-3 text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors ${(activeTab ?? "studio") === "studio" ? "flex" : "hidden"}`}
          >
            <PanelLeftOpen className="h-4 w-4" />
            <span className="text-[11px] font-medium tracking-wide" style={{ writingMode: "vertical-rl" }}>
              Transcript
            </span>
          </button>
        )}
        <div className={`${transcriptOpen && (activeTab ?? "studio") === "studio" ? "w-[320px] flex" : "hidden"} shrink-0 border-r border-border bg-card flex-col overflow-hidden`}>
          <div className="px-3 py-2 border-b border-border shrink-0 flex items-center gap-1 text-sm font-medium">
            <button
              type="button"
              onClick={() => setSideTab("transcript")}
              className={`flex items-center gap-1.5 rounded px-2 py-1 text-xs font-medium transition-colors ${sideTab === "transcript" ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"}`}
            >
              <Captions className="h-3.5 w-3.5" />
              Transcript
            </button>
            <button
              type="button"
              onClick={() => setSideTab("insights")}
              className={`flex items-center gap-1.5 rounded px-2 py-1 text-xs font-medium transition-colors ${sideTab === "insights" ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"}`}
            >
              <Sparkles className="h-3.5 w-3.5" />
              Insights
            </button>
            <button
              type="button"
              onClick={() => setTranscriptOpen(false)}
              title="Hide panel"
              className="ml-auto text-muted-foreground hover:text-foreground transition-colors"
            >
              <PanelLeftClose className="h-4 w-4" />
            </button>
          </div>
              {sideTab === "insights" ? (
              <ScrollArea className="flex-1 p-4">
                <div className="space-y-5">
                  {asset.synopsis ? (
                    <div>
                      <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">Synopsis</h3>
                      <p className="text-sm text-muted-foreground leading-relaxed">{asset.synopsis}</p>
                    </div>
                  ) : null}
                  {asset.topics && asset.topics.length > 0 ? (
                    <div>
                      <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">Topics</h3>
                      <div className="flex flex-wrap gap-1.5">
                        {asset.topics.map(topic => (
                          <Badge key={topic} variant="secondary" className="text-xs">{topic}</Badge>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {asset.key_moments && asset.key_moments.length > 0 ? (
                    <div>
                      <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">Key Moments</h3>
                      <div className="space-y-2">
                        {(asset.key_moments as { time: number; title: string; description?: string }[]).map((m, i) => (
                          <div
                            key={i}
                            className="flex gap-2 items-baseline cursor-pointer hover:bg-muted p-1.5 -mx-1.5 rounded transition-colors"
                            onClick={() => seekTo(m.time)}
                          >
                            <span className="text-xs font-mono text-primary shrink-0">{formatTimecode(m.time)}</span>
                            <div className="min-w-0">
                              <p className="text-sm font-medium leading-snug">{m.title}</p>
                              {m.description ? <p className="text-xs text-muted-foreground leading-snug">{m.description}</p> : null}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {!hasAnalysis && (
                    <p className="text-sm text-muted-foreground text-center mt-10">
                      No AI analysis yet. It is generated automatically after indexing completes —
                      or re-run the index job from the Pipeline Jobs tab.
                    </p>
                  )}
                </div>
              </ScrollArea>
              ) : (
              <div className="flex-1 overflow-hidden flex flex-col">
              <div className="px-3 pt-3 shrink-0 flex items-center gap-2">
                <Languages className="h-4 w-4 text-muted-foreground shrink-0" />
                <Select value={transcriptLang} onValueChange={setTranscriptLang}>
                  <SelectTrigger className="h-8 text-xs flex-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="original">Original</SelectItem>
                    {TRANSLATION_LANGUAGES.map(l => (
                      <SelectItem key={l.code} value={l.code}>
                        {l.label}{(asset?.translated_languages ?? []).includes(l.code) ? " ✓" : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="px-3 pt-2 shrink-0 flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="flex-1 gap-1.5 h-8 text-xs"
                  onClick={() => downloadCaptions("srt")}
                  disabled={captionsBusy !== null}
                >
                  {captionsBusy === "srt" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Captions className="h-3.5 w-3.5" />}
                  SRT
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="flex-1 gap-1.5 h-8 text-xs"
                  onClick={() => downloadCaptions("vtt")}
                  disabled={captionsBusy !== null}
                >
                  {captionsBusy === "vtt" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Captions className="h-3.5 w-3.5" />}
                  VTT
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="flex-1 gap-1.5 h-8 text-xs"
                  onClick={startTighten}
                  disabled={tightenMutation.isPending}
                >
                  {tightenMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Scissors className="h-3.5 w-3.5" />}
                  Tighten
                </Button>
              </div>
              {transcriptLang !== "original" && langAvailable && (
                <div className="px-3 pt-2 shrink-0">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="w-full gap-2 mb-1.5 text-muted-foreground"
                    onClick={() => startTranslate(transcriptLang)}
                    disabled={translateBusy}
                  >
                    {translateBusy ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Retranslating{translateJob?.progress ? ` — ${Math.round(translateJob.progress)}%` : "..."}
                      </>
                    ) : (
                      <>
                        <Languages className="h-3.5 w-3.5" />
                        Retranslate
                      </>
                    )}
                  </Button>
                  {dubAvailable ? (
                    <>
                      <div className="flex gap-1.5">
                        <Button
                          size="sm"
                          variant={dubOn ? "default" : "outline"}
                          className="flex-1 min-w-0 gap-2"
                          onClick={toggleDub}
                        >
                          <Volume2 className="h-4 w-4 shrink-0" />
                          <span className="truncate">
                            {dubOn ? "Dubbed version playing — click for original" : "Play dubbed version"}
                          </span>
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="flex-1 min-w-0 gap-2"
                          asChild
                          data-testid="button-download-dub-audio"
                        >
                          <a href={`/api/media/${id}/dub/${transcriptLang}/stream?download=true`} download>
                            <Download className="h-4 w-4 shrink-0" />
                            <span className="truncate">
                              Download audio only (
                              {TRANSLATION_LANGUAGES.find(l => l.code === transcriptLang)?.label ?? transcriptLang.toUpperCase()}
                              {" "}dub, M4A)
                            </span>
                          </a>
                        </Button>
                      </div>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="w-full gap-2 mt-1.5 text-muted-foreground"
                        onClick={() => startDub(transcriptLang)}
                        disabled={dubBusy}
                      >
                        {dubBusy ? (
                          <>
                            <Loader2 className="h-4 w-4 animate-spin" />
                            Regenerating dub{dubJob?.progress ? ` — ${Math.round(dubJob.progress)}%` : "..."}
                          </>
                        ) : (
                          <>
                            <RefreshCw className="h-3.5 w-3.5" />
                            Regenerate dub
                          </>
                        )}
                      </Button>
                      {!dubBusy && (
                        <label className="flex items-center gap-2 mt-1.5 cursor-pointer text-[11px] text-muted-foreground">
                          <Checkbox
                            checked={dubClonedVoices}
                            onCheckedChange={(v) => setDubClonedVoices(v === true)}
                          />
                          Use cloned voices — speakers with a ready voice profile keep their own voice
                        </label>
                      )}
                      {!dubBusy && (
                        <label className="flex items-center gap-2 mt-1.5 cursor-pointer text-[11px] text-muted-foreground">
                          <Checkbox
                            checked={dubLipSync}
                            onCheckedChange={(v) => setDubLipSync(v === true)}
                          />
                          Lip sync (experimental) — re-render mouths to match the dub where the speaker's face is visible
                        </label>
                      )}
                    </>
                  ) : dubSupported ? (
                    <>
                      <Button
                        size="sm"
                        variant="outline"
                        className="w-full gap-2"
                        onClick={() => startDub(transcriptLang)}
                        disabled={dubBusy}
                      >
                        {dubBusy ? (
                          <>
                            <Loader2 className="h-4 w-4 animate-spin" />
                            Generating dub{dubJob?.progress ? ` — ${Math.round(dubJob.progress)}%` : "..."}
                          </>
                        ) : (
                          <>
                            <AudioLines className="h-4 w-4" />
                            Generate dubbed audio
                          </>
                        )}
                      </Button>
                      <label className="flex items-center gap-2 mt-1.5 cursor-pointer text-[11px] text-muted-foreground">
                        <Checkbox
                          checked={dubClonedVoices}
                          onCheckedChange={(v) => setDubClonedVoices(v === true)}
                          disabled={dubBusy}
                        />
                        Use cloned voices — speakers with a ready voice profile keep their own voice
                      </label>
                      <label className="flex items-center gap-2 mt-1.5 cursor-pointer text-[11px] text-muted-foreground">
                        <Checkbox
                          checked={dubLipSync}
                          onCheckedChange={(v) => setDubLipSync(v === true)}
                          disabled={dubBusy}
                        />
                        Lip sync (experimental) — re-render mouths to match the dub where the speaker's face is visible
                      </label>
                      {dubMutation.isError && (
                        <p className="text-xs text-destructive mt-1.5">Failed to start dubbing. Check Pipeline Jobs.</p>
                      )}
                      {!dubBusy && !dubMutation.isError && lastDubStatus === "error" && (
                        <p className="text-xs text-destructive mt-1.5 break-words">
                          Last dub failed{lastDubJob?.error_message ? `: ${lastDubJob.error_message}` : ""}. See Pipeline Jobs for details.
                        </p>
                      )}
                    </>
                  ) : (
                    <p className="text-[11px] text-muted-foreground">
                      Dubbed audio isn't available for this language — no local TTS voice exists for it.
                    </p>
                  )}
                </div>
              )}
              {transcriptLang !== "original" && !langAvailable ? (
                <div className="flex-1 flex flex-col items-center justify-center gap-3 p-6 text-center">
                  <Languages className="h-8 w-8 text-muted-foreground" />
                  <Button size="sm" className="gap-2" onClick={() => startTranslate(transcriptLang)} disabled={translateBusy}>
                    {translateBusy ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Translating{translateJob?.progress ? ` — ${Math.round(translateJob.progress)}%` : "..."}
                      </>
                    ) : (
                      <>
                        <Languages className="h-4 w-4" />
                        Translate to {TRANSLATION_LANGUAGES.find(l => l.code === transcriptLang)?.label}
                      </>
                    )}
                  </Button>
                  <p className="text-xs text-muted-foreground">
                    Translates the full transcript locally on the GPU worker. Timecodes and speakers stay aligned.
                  </p>
                  {translateMutation.isError && (
                    <p className="text-xs text-destructive">Failed to start translation. Check Pipeline Jobs.</p>
                  )}
                  {!translateBusy && !translateMutation.isError && lastTranslateStatus === "error" && (
                    <p className="text-xs text-destructive max-w-xs break-words">
                      Last translation failed{lastTranslateJob?.error_message ? `: ${lastTranslateJob.error_message}` : ""}. See Pipeline Jobs for details.
                    </p>
                  )}
                </div>
              ) : (
              <ScrollArea className="flex-1 p-4" onWheel={markTranscriptUserScroll} onTouchMove={markTranscriptUserScroll}>
                <div className="space-y-4">
                  {transcript?.map(segment => (
                    <div 
                      key={segment.id} 
                      ref={el => { if (String(segment.id) === activeSegmentId) activeSegmentRef.current = el; }}
                      className={`group cursor-pointer hover:bg-muted p-2 -mx-2 rounded transition-colors relative ${String(segment.id) === activeSegmentId ? "bg-primary/10 ring-1 ring-primary/30" : ""}`}
                      onClick={() => seekTo(segment.start_time)}
                    >
                      <div className="flex gap-2 items-baseline mb-1">
                        <span className="text-xs font-medium text-primary">{segment.speaker || 'Unknown'}</span>
                        <span className="text-[10px] text-muted-foreground font-mono">{formatTimecode(segment.start_time)}</span>
                        {segment.emotion && segment.emotion !== "neutral" && (
                          <span
                            className="text-[10px] px-1.5 py-0 rounded-full border"
                            style={{ color: emotionColor(segment.emotion), borderColor: `${emotionColor(segment.emotion)}55` }}
                            title={segment.sentiment != null ? `sentiment ${segment.sentiment > 0 ? "+" : ""}${segment.sentiment.toFixed(2)}` : undefined}
                          >
                            {segment.emotion}
                          </span>
                        )}
                      </div>
                      {editingSegId === String(segment.id) ? (
                        <div onClick={(e) => e.stopPropagation()}>
                          <Textarea
                            value={editText}
                            onChange={(e) => setEditText(e.target.value)}
                            className="text-sm min-h-[60px]"
                            autoFocus
                            onKeyDown={(e) => {
                              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) saveSegmentEdit(String(segment.id));
                              if (e.key === "Escape") setEditingSegId(null);
                            }}
                          />
                          <div className="flex gap-1.5 mt-1.5">
                            <Button
                              size="sm" className="h-6 px-2 gap-1 text-[11px]"
                              disabled={segmentUpdateMutation.isPending || !editText.trim()}
                              onClick={() => saveSegmentEdit(String(segment.id))}
                            >
                              {segmentUpdateMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />} Save
                            </Button>
                            <Button
                              size="sm" variant="outline" className="h-6 px-2 gap-1 text-[11px]"
                              onClick={() => setEditingSegId(null)}
                            >
                              <X className="h-3 w-3" /> Cancel
                            </Button>
                            {segmentUpdateMutation.isError && editingSegId === String(segment.id) && (
                              <span className="text-[11px] text-destructive self-center">Save failed</span>
                            )}
                          </div>
                        </div>
                      ) : (
                        <p className="text-sm">{segment.text}</p>
                      )}
                      {editingSegId !== String(segment.id) && (
                        <div className="absolute top-1 right-1 flex gap-1 opacity-0 group-hover:opacity-100">
                          <Button
                            size="sm" variant="secondary"
                            className="h-6 px-2 gap-1 text-[11px]"
                            title={transcriptLang !== "original" && langAvailable ? "Edit this translation" : "Edit this segment"}
                            onClick={(e) => { e.stopPropagation(); setEditingSegId(String(segment.id)); setEditText(segment.text); }}
                          >
                            <Pencil className="h-3 w-3" /> Edit
                          </Button>
                          <Button
                            size="sm" variant="secondary"
                            className="h-6 px-2 gap-1 text-[11px]"
                            title="Add this segment to a clip list"
                            onClick={(e) => { e.stopPropagation(); setClipListSegment(segment); }}
                          >
                            <ListPlus className="h-3 w-3" /> Clip
                          </Button>
                        </div>
                      )}
                    </div>
                  ))}
                  {!transcript?.length && (
                    <div className="text-sm text-muted-foreground text-center mt-10">No transcript available</div>
                  )}
                </div>
              </ScrollArea>
              )}
            </div>
              )}
        </div>

        {/* Main Content Area — tabs on top, viewport fills the rest */}
        <Tabs
          value={activeTab ?? "studio"}
          onValueChange={setActiveTab}
          className="flex-1 min-w-0 flex flex-col overflow-hidden"
        >
          <div className="px-3 py-2 border-b border-border shrink-0 flex items-center gap-2">
            <TabsList className="flex flex-wrap h-auto gap-1 justify-start">
              <TabsTrigger
                value="studio"
                className="gap-1.5 text-primary data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
              >
                <Clapperboard className="h-3.5 w-3.5" />
                Studio
              </TabsTrigger>
              <TabsTrigger value="search" className="gap-1.5">
                <Search className="h-3.5 w-3.5" />
                Search
              </TabsTrigger>
              <TabsTrigger value="creative" className="gap-1.5">
                <Clapperboard className="h-3.5 w-3.5" />
                Creative
              </TabsTrigger>
              <TabsTrigger value="socials" className="gap-1.5">
                <Share2 className="h-3.5 w-3.5" />
                Socials
              </TabsTrigger>
              <TabsTrigger value="selects" className="gap-1.5">
                <Star className="h-3.5 w-3.5" />
                Selects
              </TabsTrigger>
              <TabsTrigger value="scenes">Scenes</TabsTrigger>
              <TabsTrigger value="jobs">Pipeline Jobs</TabsTrigger>
              {(assetRatings?.total ?? 0) > 0 && (
                <TabsTrigger value="ratings" className="gap-1.5">
                  <BarChart3 className="h-3.5 w-3.5" />
                  Ratings
                </TabsTrigger>
              )}
            </TabsList>
            <Button
              size="sm"
              variant={chatDrawerOpen ? "default" : "outline"}
              className="ml-auto gap-1.5 shrink-0"
              onClick={() => setChatDrawerOpen((v) => !v)}
              data-testid="button-toggle-assistant"
            >
              <Sparkles className="h-3.5 w-3.5" />
              Assistant
            </Button>
          </div>
          <div className="flex-1 flex flex-col overflow-y-auto">
          <div className={`p-6 bg-black flex-shrink-0 sticky top-0 z-20 shadow-lg shadow-black/50 ${(activeTab ?? "studio") === "studio" ? "" : "hidden"}`}>
            {asset.status === 'ready' ? (
              <video 
                ref={videoRef}
                src={dubOn && dubAvailable
                  ? `/api/media/${id}/dub/${transcriptLang}/video`
                  : `/api/media/${id}/stream`} 
                controls 
                className="w-full max-h-[60vh] object-contain bg-black"
                onTimeUpdate={handleTimeUpdate}
              />
            ) : (
              undefined
            )}
            {asset.status === 'ready' && (
              <button
                type="button"
                className="absolute top-8 right-8 z-10 flex items-center gap-1.5 rounded-md bg-black/70 hover:bg-primary/80 px-2.5 py-1.5 text-xs font-medium text-white backdrop-blur-sm transition-colors"
                title="Find visually and verbally similar moments across the library at the current playback position"
                onClick={() => findSimilar()}
              >
                <Sparkles className="h-3.5 w-3.5" />
                Find similar moments
              </button>
            )}
            {asset.status === 'ready' && (
              <div
                className="absolute top-8 left-8 z-10 flex rounded-md overflow-hidden border border-zinc-700 text-[11px] font-bold tracking-wider backdrop-blur-sm"
                data-testid="badge-active-version"
              >
                <button
                  type="button"
                  onClick={() => { setViewMode("original"); if (dubOn) setDubOn(false); }}
                  className={`px-2.5 py-1 transition-colors ${viewMode === "original" && !dubOn ? "bg-white text-black" : "bg-black/60 text-zinc-400 hover:text-white"}`}
                  data-testid="toggle-original"
                >
                  ORIGINAL
                </button>
                {dubAvailable && (
                  <button
                    type="button"
                    title={`Switch to the ${TRANSLATION_LANGUAGES.find(l => l.code === transcriptLang)?.label ?? transcriptLang.toUpperCase()} dub`}
                    onClick={() => { setViewMode("original"); setDubOn(true); }}
                    className={`px-2.5 py-1 transition-colors ${viewMode === "original" && dubOn ? "bg-white text-black" : "bg-black/60 text-zinc-400 hover:text-white"}`}
                    data-testid="toggle-dub"
                  >
                    DUB
                  </button>
                )}
                <button
                  type="button"
                  disabled={!previewClips.length}
                  title={previewClips.length ? "Play the current draft cut in this player" : "No draft cut yet — build one in the Studio chat"}
                  onClick={() => previewClips.length && setViewMode("preview")}
                  className={`px-2.5 py-1 transition-colors ${viewMode === "preview" ? "bg-white text-black" : "bg-black/60 text-zinc-400 hover:text-white disabled:opacity-40 disabled:hover:text-zinc-400"}`}
                  data-testid="toggle-preview"
                >
                  PREVIEW
                </button>
              </div>
            )}
            {asset.status !== 'ready' && (
              <div className="w-full h-64 bg-muted flex flex-col items-center justify-center">
                <p className="text-muted-foreground mb-2">Media is {asset.status}</p>
                {asset.processing_stage && (
                  <Badge variant="outline">{asset.processing_stage} {asset.processing_progress}%</Badge>
                )}
              </div>
            )}
            {asset.status === 'ready' && (
              <div className="absolute bottom-9 left-1/2 -translate-x-1/2 z-10 w-[min(560px,72%)] flex items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900/95 backdrop-blur px-3 py-2 shadow-2xl shadow-black/60">
                <Sparkles className="h-4 w-4 text-primary shrink-0" />
                <Input
                  value={floatPrompt}
                  onChange={(e) => setFloatPrompt(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && floatPrompt.trim()) {
                      const text = floatPrompt.trim();
                      setFloatPrompt("");
                      setChatDrawerOpen(true);
                      (window as unknown as { __obtvPendingPrompt?: string }).__obtvPendingPrompt = text;
                      window.dispatchEvent(new CustomEvent("obtv:studio-prompt", { detail: text }));
                    }
                  }}
                  placeholder="Ask AI — build or change a cut from this footage…"
                  className="h-8 border-0 bg-transparent focus-visible:ring-0 text-sm text-zinc-200 placeholder:text-zinc-500 px-0"
                  data-testid="input-ask-ai-floating"
                />
              </div>
            )}
          </div>
          
          <div className={`p-6 ${(activeTab ?? "studio") === "studio" ? "" : "hidden"}`}>
            <div className="flex items-start justify-between gap-4 mb-2">
              <h1 className="text-2xl font-bold">{asset.filename}</h1>
              <Button 
                variant="outline" 
                size="sm" 
                className="gap-2 text-destructive hover:text-destructive shrink-0"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 className="h-4 w-4" />
                Remove from Library
              </Button>
            </div>
            <div className={`flex gap-4 items-center text-sm text-muted-foreground ${asset.curator_id ? "mb-2" : "mb-6"} flex-wrap`}>
              <span>{asset.codec}</span>
              <span>{asset.width}x{asset.height}</span>
              <span>{asset.fps} fps</span>
              {((asset.qc_flags as { flags?: string[] } | null)?.flags ?? []).map(flag => (
                <Badge key={flag} variant="outline" className="gap-1 text-amber-500 border-amber-500/40" title={QC_FLAG_HINTS[flag] ?? flag}>
                  <AlertTriangle className="h-3 w-3" />
                  {QC_FLAG_LABELS[flag] ?? flag}
                </Badge>
              ))}
            </div>
            {asset.curator_id && (
              <div className="flex gap-x-4 gap-y-1 items-center text-sm mb-6 flex-wrap">
                <Badge variant="outline" className="gap-1 text-sky-400 border-sky-400/40">Curator</Badge>
                <span className="text-muted-foreground">
                  ID: <span className="font-mono text-foreground">{asset.curator_id}</span>
                </span>
                {asset.source_path && (
                  <span className="text-muted-foreground" title="Hi-res source path — NLE exports relink to this file">
                    Source: <span className="font-mono text-foreground break-all">{asset.source_path}</span>
                  </span>
                )}
              </div>
            )}

            <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Remove from library?</DialogTitle>
                </DialogHeader>
                <p className="text-sm text-muted-foreground">
                  This removes <span className="font-medium text-foreground">{asset.filename}</span> from 
                  the index — its transcript, scenes, and search entries. The source video file on disk 
                  is never touched and can be re-ingested later.
                </p>
                <div className="flex justify-end gap-2 pt-2">
                  <Button variant="outline" onClick={() => setConfirmDelete(false)}>Cancel</Button>
                  <Button variant="destructive" onClick={handleDelete} disabled={deleteMutation.isPending}>
                    {deleteMutation.isPending ? "Removing..." : "Remove"}
                  </Button>
                </div>
              </DialogContent>
            </Dialog>

            <Dialog open={!!tightenResult} onOpenChange={(open) => !open && setTightenResult(null)}>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle className="flex items-center gap-2">
                    <Scissors className="h-5 w-5" /> Tightened cut ready
                  </DialogTitle>
                </DialogHeader>
                {tightenResult && (
                  <div className="space-y-3 text-sm">
                    <p className="text-muted-foreground">
                      Removed <span className="font-medium text-foreground">{tightenResult.removed_seconds}s</span> of
                      silence and filler across {tightenResult.cuts.length} cuts —{" "}
                      {tightenResult.kept_segments} keep-segments saved as a clip list.
                    </p>
                    <div className="max-h-48 overflow-y-auto space-y-1">
                      {tightenResult.cuts.slice(0, 40).map((c, i) => (
                        <div key={i} className="flex items-center justify-between bg-muted/50 rounded px-2 py-1 text-xs font-mono">
                          <span>{formatTimecode(c.start)} → {formatTimecode(c.end)}</span>
                          <Badge variant="outline" className="text-[10px] uppercase">{c.reason}</Badge>
                        </div>
                      ))}
                    </div>
                    <div className="flex justify-end gap-2 pt-1">
                      <Button onClick={() => setTightenResult(null)}>Done</Button>
                    </div>
                  </div>
                )}
              </DialogContent>
            </Dialog>

          </div>
              <TabsContent value="selects" className="flex-1 overflow-y-auto mt-0 p-4">
                <div className="space-y-4">
                  <div className="flex items-end gap-2 flex-wrap max-w-3xl">
                    <div className="flex-1 min-w-48">
                      <Label htmlFor="marker-note" className="text-xs text-muted-foreground">Note (optional)</Label>
                      <Input
                        id="marker-note"
                        value={markerNote}
                        onChange={(e) => setMarkerNote(e.target.value)}
                        placeholder="Why this moment matters..."
                        className="mt-1"
                      />
                    </div>
                    <Button size="sm" variant="outline" className="gap-1.5 text-green-500" disabled={createMarkerMutation.isPending} onClick={() => addMarkerAtPlayhead("select")}>
                      <Star className="h-3.5 w-3.5" /> Select
                    </Button>
                    <Button size="sm" variant="outline" className="gap-1.5 text-red-500" disabled={createMarkerMutation.isPending} onClick={() => addMarkerAtPlayhead("reject")}>
                      <XCircle className="h-3.5 w-3.5" /> Reject
                    </Button>
                    <Button size="sm" variant="outline" className="gap-1.5 text-sky-400" disabled={createMarkerMutation.isPending} onClick={() => addMarkerAtPlayhead("marker")}>
                      <Flag className="h-3.5 w-3.5" /> Marker
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Marks are placed at the current playhead position. AI-suggested beats appear on the heat strip under the player — promote the good ones to selects here or from the AI Analysis tab.
                  </p>
                  <div className="grid gap-8 lg:grid-cols-2">
                  {asset.key_moments && asset.key_moments.length > 0 && (
                    <div>
                      <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">AI Suggestions</h3>
                      <div className="space-y-1">
                        {(asset.key_moments as { time: number; title: string; description?: string }[]).map((moment, i) => {
                          const already = (markers ?? []).some(m => m.source === "editor" && Math.abs(m.time - moment.time) < 2);
                          return (
                            <div key={i} className="flex items-center gap-2 p-2 -mx-2 rounded hover:bg-muted transition-colors">
                              <span className="text-xs font-mono text-primary shrink-0 w-14 text-right cursor-pointer" onClick={() => seekTo(moment.time)}>
                                {formatTimecode(moment.time)}
                              </span>
                              <div className="flex-1 min-w-0 cursor-pointer" onClick={() => seekTo(moment.time)}>
                                <div className="text-sm font-medium truncate">{moment.title}</div>
                                {moment.description && <div className="text-xs text-muted-foreground truncate">{moment.description}</div>}
                              </div>
                              {already ? (
                                <Badge variant="secondary" className="text-[10px]">marked</Badge>
                              ) : (
                                <>
                                  <Button size="sm" variant="ghost" className="h-7 px-2 text-green-500" title="Promote to select" onClick={() => promoteMoment(moment.time, "select", moment.title)}>
                                    <ThumbsUp className="h-3.5 w-3.5" />
                                  </Button>
                                  <Button size="sm" variant="ghost" className="h-7 px-2 text-red-500" title="Reject this beat" onClick={() => promoteMoment(moment.time, "reject", moment.title)}>
                                    <ThumbsDown className="h-3.5 w-3.5" />
                                  </Button>
                                </>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  <div>
                    <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">Editor Marks</h3>
                    {(markers ?? []).length === 0 ? (
                      <p className="text-sm text-muted-foreground py-4 text-center">No marks yet. Play the video and mark selects, rejects, and notes at the playhead.</p>
                    ) : (
                      <div className="space-y-1">
                        {(markers ?? []).map(m => (
                          <div key={m.id} className="flex items-center gap-2 p-2 -mx-2 rounded hover:bg-muted transition-colors group">
                            {m.kind === "select" ? <Star className="h-3.5 w-3.5 text-green-500 shrink-0" />
                              : m.kind === "reject" ? <XCircle className="h-3.5 w-3.5 text-red-500 shrink-0" />
                              : <Flag className="h-3.5 w-3.5 text-sky-400 shrink-0" />}
                            <span className="text-xs font-mono text-primary shrink-0 w-14 text-right cursor-pointer" onClick={() => seekTo(m.time)}>
                              {formatTimecode(m.time)}
                            </span>
                            <span className="flex-1 text-sm truncate cursor-pointer" onClick={() => seekTo(m.time)}>
                              {m.note || <span className="text-muted-foreground italic">{m.kind}</span>}
                            </span>
                            <Button
                              size="sm" variant="ghost"
                              className="h-7 px-2 opacity-0 group-hover:opacity-100 text-destructive"
                              disabled={deleteMarkerMutation.isPending}
                              onClick={() => deleteMarkerMutation.mutate({ id: id!, markerId: m.id }, { onSuccess: invalidateMarkers })}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  </div>
                </div>
              </TabsContent>
              <TabsContent value="creative" className="flex-1 overflow-y-auto mt-0 p-4">
                <CreativeSection
                  creative={asset.creative as CreativeAnalysis | null | undefined}
                  busy={creativeBusy}
                  progress={creativeJob?.progress ?? null}
                  error={creativeMutation.isError}
                  onRun={startCreative}
                  seekTo={seekTo}
                />
              </TabsContent>
              <TabsContent value="socials" className="flex-1 overflow-y-auto mt-0 p-4">
                {(asset.social_scores && asset.social_scores.length > 0 && !socialBusy) ? (
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <p className="text-sm text-muted-foreground flex items-center gap-2">
                        <TrendingUp className="h-4 w-4" />
                        Predicted performance if posted (or clipped) per platform
                      </p>
                      <div className="flex items-center gap-2">
                        <Button
                          size="sm"
                          className="gap-2"
                          onClick={() => startCuts(null)}
                          disabled={cutsMutation.isPending || !asset.key_moments?.length}
                        >
                          {cutsMutation.isPending && cutsPlatform === "all" ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Scissors className="h-4 w-4" />
                          )}
                          Create all cuts
                        </Button>
                        <Button variant="outline" size="sm" className="gap-2" onClick={startSocial}>
                          <Share2 className="h-4 w-4" />
                          Re-analyze
                        </Button>
                      </div>
                    </div>
                    {!asset.key_moments?.length && (
                      <p className="text-xs text-muted-foreground">
                        Cuts use AI-detected key moments — run AI analysis on the Highlights tab first.
                      </p>
                    )}
                    {cutsError && (
                      <p className="text-xs text-destructive">{cutsError}</p>
                    )}
                    {cutsCreated !== null && (
                      <div className="border border-green-500/30 bg-green-500/10 rounded-md px-3 py-2">
                        <p className="text-xs text-green-500">
                          {cutsCreated} cut{cutsCreated === 1 ? "" : "s"} queued — rendering below, download when ready.
                        </p>
                      </div>
                    )}
                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                      {(asset.social_scores as SocialScore[]).map((s) => {
                        const meta = PLATFORM_META[s.platform] ?? { label: s.platform, Icon: Share2, color: "text-foreground" };
                        const score = Math.round(s.score);
                        return (
                          <div key={s.platform} className="border border-border rounded-lg p-4 space-y-3">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <meta.Icon className={`h-5 w-5 ${meta.color}`} />
                                <span className="font-medium">{meta.label}</span>
                              </div>
                              <span className={`text-2xl font-bold font-mono ${scoreColor(score)}`}>{score}</span>
                            </div>
                            <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                              <div className={`h-full ${scoreBarColor(score)}`} style={{ width: `${score}%` }} />
                            </div>
                            {s.verdict && (
                              <p className="text-sm text-muted-foreground">{s.verdict}</p>
                            )}
                            {s.strengths && s.strengths.length > 0 && (
                              <div className="space-y-1">
                                {s.strengths.map((str, i) => (
                                  <div key={i} className="flex gap-2 text-xs text-muted-foreground">
                                    <ThumbsUp className="h-3.5 w-3.5 text-green-500 shrink-0 mt-0.5" />
                                    <span>{str}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                            {s.weaknesses && s.weaknesses.length > 0 && (
                              <div className="space-y-1">
                                {s.weaknesses.map((str, i) => (
                                  <div key={i} className="flex gap-2 text-xs text-muted-foreground">
                                    <ThumbsDown className="h-3.5 w-3.5 text-red-500 shrink-0 mt-0.5" />
                                    <span>{str}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                            {s.best_format && (
                              <div className="flex gap-2 text-xs text-muted-foreground">
                                <Clapperboard className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                                <span>{s.best_format}</span>
                              </div>
                            )}
                            {s.suggested_caption && (
                              <div className="bg-muted/50 rounded p-2 text-xs">
                                {s.suggested_caption}
                              </div>
                            )}
                            {s.hashtags && s.hashtags.length > 0 && (
                              <div className="flex flex-wrap gap-1.5 items-center">
                                <Hash className="h-3 w-3 text-muted-foreground" />
                                {s.hashtags.map((h) => (
                                  <Badge key={h} variant="secondary" className="text-[10px]">{h}</Badge>
                                ))}
                              </div>
                            )}
                            <Button
                              variant="outline"
                              size="sm"
                              className="w-full gap-2"
                              onClick={() => startCuts(s.platform as SocialCutsRequestPlatform)}
                              disabled={cutsMutation.isPending || !asset.key_moments?.length}
                            >
                              {cutsMutation.isPending && cutsPlatform === s.platform ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Scissors className="h-4 w-4" />
                              )}
                              {asset.key_moments?.length ? "Create cuts" : "Run AI analysis first"}
                            </Button>
                          </div>
                        );
                      })}
                    </div>
                    <AssetRendersSection mediaId={id!} socialOnly />
                  </div>
                ) : (
                  <div className="py-10 flex flex-col items-center text-center gap-3">
                    <TrendingUp className="h-10 w-10 text-muted-foreground" />
                    <Button className="gap-2" onClick={startSocial} disabled={socialBusy}>
                      {socialBusy ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Analyzing{socialJob?.progress ? ` — ${Math.round(socialJob.progress)}%` : "..."}
                        </>
                      ) : (
                        <>
                          <Share2 className="h-4 w-4" />
                          Analyze Social Potential
                        </>
                      )}
                    </Button>
                    <p className="text-xs text-muted-foreground max-w-sm">
                      Scores how this content would perform on YouTube, Instagram, X, Facebook, and
                      TikTok — with strengths, weaknesses, captions, and hashtags per platform.
                    </p>
                    {socialMutation.isError && (
                      <p className="text-xs text-destructive">Failed to start social analysis. Check Pipeline Jobs.</p>
                    )}
                  </div>
                )}
              </TabsContent>
              <TabsContent value="scenes" className="flex-1 overflow-y-auto mt-0 p-4">
                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
                  {scenes?.map(scene => (
                    <div 
                      key={scene.id} 
                      className="cursor-pointer group"
                      onClick={() => seekTo(scene.start_time)}
                    >
                      <div className="aspect-video bg-muted rounded overflow-hidden mb-2 relative">
                        {scene.thumbnail_url && (
                          <img src={`/api/thumbnails/${scene.thumbnail_url}`} className="w-full h-full object-cover group-hover:scale-105 transition-transform" />
                        )}
                        <div className="absolute bottom-1 right-1 bg-black/80 px-1 py-0.5 rounded text-[10px] text-white">
                          {formatTimecode(scene.start_time)}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </TabsContent>
              <TabsContent value="jobs" className="flex-1 overflow-y-auto mt-0 p-4">
                <div className="flex items-center gap-2 mb-3">
                  <Select value={runStageType} onValueChange={setRunStageType}>
                    <SelectTrigger className="h-8 text-xs w-48">
                      <SelectValue placeholder="Run a pipeline stage…" />
                    </SelectTrigger>
                    <SelectContent>
                      {["proxy", "audio_extract", "transcribe", "diarize", "scene_detect", "qc", "visual_embed", "face_detect", "index", "analyze", "creative", "identify"].map(s => (
                        <SelectItem key={s} value={s}>{s}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!runStageType || runStageMutation.isPending}
                    onClick={() => {
                      runStageMutation.mutate({ id: id!, data: { job_type: runStageType as any } }, {
                        onSuccess: () => queryClient.invalidateQueries({ queryKey: getListJobsQueryKey({ media_id: id! }) }),
                      });
                    }}
                  >
                    {runStageMutation.isPending
                      ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      : <RefreshCw className="w-3.5 h-3.5" />}
                    <span className="ml-1">Run stage</span>
                  </Button>
                  {runStageMutation.isError && (
                    <span className="text-xs text-destructive">
                      {(runStageMutation.error as any)?.data?.detail || "Failed to queue stage"}
                    </span>
                  )}
                </div>
                {(!jobs || jobs.length === 0) && (
                  <p className="text-xs text-muted-foreground mb-2">
                    No job history for this asset — pick a stage above to reprocess it.
                  </p>
                )}
                <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                  {jobs?.map(job => (
                    <div key={job.id} className="p-3 border border-border rounded flex justify-between items-center gap-2">
                      <div className="min-w-0">
                        <div className="font-medium">{job.job_type}</div>
                        <div className="text-xs text-muted-foreground">{new Date(job.created_at).toLocaleString()}</div>
                        {job.status === 'error' && job.error_message && (
                          <div className="text-xs text-destructive truncate" title={job.error_message}>{job.error_message}</div>
                        )}
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <Badge variant={job.status === 'success' ? 'default' : job.status === 'error' ? 'destructive' : 'secondary'}>
                          {job.status}
                        </Badge>
                        {(job.status === 'success' || job.status === 'error' || job.status === 'cancelled') && (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={retryJobMutation.isPending && retryingJobId === job.id}
                            onClick={() => {
                              setRetryingJobId(job.id);
                              retryJobMutation.mutate({ id: job.id }, {
                                onSuccess: () => queryClient.invalidateQueries({ queryKey: getListJobsQueryKey({ media_id: id! }) }),
                                onSettled: () => setRetryingJobId(null),
                              });
                            }}
                          >
                            {retryJobMutation.isPending && retryingJobId === job.id
                              ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              : <RefreshCw className="w-3.5 h-3.5" />}
                            <span className="ml-1">Rerun</span>
                          </Button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </TabsContent>
              <TabsContent value="ratings" className="flex-1 overflow-y-auto mt-0 p-4">
                <div className="space-y-2">
                  <p className="text-xs text-muted-foreground mb-2">
                    Audience measurement records linked to this asset —{" "}
                    <Link href="/ratings" className="text-primary hover:underline">open the Ratings dashboard</Link>
                  </p>
                  {assetRatings?.items?.map(r => (
                    <div key={r.id} className="p-3 border border-border rounded flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                      <Badge variant={r.is_own ? "default" : "outline"} className="text-xs">{r.station}</Badge>
                      <span className="font-medium">{r.program_title}</span>
                      <span className="text-xs text-muted-foreground">
                        {r.air_date}{r.start_time ? ` · ${r.start_time}${r.end_time ? `–${r.end_time}` : ""}` : ""}
                      </span>
                      <span className="ml-auto flex items-center gap-4 text-xs">
                        <span>Rating <span className="font-semibold">{r.rating ?? "—"}</span></span>
                        <span>Share <span className="font-semibold">{r.share ?? "—"}</span></span>
                        <span>Viewers <span className="font-semibold">{r.viewers != null ? r.viewers.toLocaleString() : "—"}</span></span>
                      </span>
                    </div>
                  ))}
                </div>
              </TabsContent>
            <TabsContent value="search" className="flex-1 overflow-y-auto mt-0 p-4">
                <AssetSearchTab mediaId={id!} seekTo={seekTo} />
              </TabsContent>
          </div>
        </Tabs>
      </div>

      {/* Editorial Assistant — overlay drawer, always mounted so the cut/preview stays wired */}
      <div
        className={`${chatDrawerOpen ? "flex" : "hidden"} fixed right-0 top-0 bottom-0 z-40 w-[440px] max-w-[92vw] flex-col border-l border-border bg-card shadow-2xl shadow-black/60`}
        data-testid="drawer-assistant"
      >
        <div className="px-4 py-2.5 border-b border-border flex items-center gap-2 shrink-0">
          <Sparkles className="h-4 w-4 text-primary" />
          <span className="text-sm font-medium">Editorial assistant</span>
          <Button variant="ghost" size="icon" className="ml-auto h-7 w-7" onClick={() => setChatDrawerOpen(false)} data-testid="button-close-assistant">
            <XCircle className="h-4 w-4" />
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          <AssetStudioSection mediaId={id!} onSeek={seekTo} onCutChange={setCutClips} />
          <AssetRendersSection mediaId={id!} />
        </div>
      </div>

      {/* ── Full-width NLE timeline band — Studio tab only ── */}
      {asset.status === 'ready' && (asset.duration_seconds ?? 0) > 0 && (
        <div className={`shrink-0 border-t border-zinc-800 bg-zinc-950 px-3 pt-1.5 pb-2 max-h-[38vh] overflow-y-auto ${(activeTab ?? "studio") === "studio" ? "" : "hidden"}`}>
          <div className="grid grid-cols-[92px_1fr] items-start gap-x-2">
            <div className="pt-2.5 text-[9px] font-bold tracking-widest text-zinc-600 select-none">[TIMELINE]</div>
            <div className="min-w-0">
              <MomentsTimeline
                duration={asset.duration_seconds!}
                keyMoments={(asset.key_moments as { time: number; title: string; description?: string }[] | null) ?? []}
                clipSuggestions={((asset.creative as CreativeAnalysis | null)?.clip_suggestions as { start: number; end: number; title: string; reason?: string; strength: number }[] | undefined) ?? []}
                markers={markers ?? []}
                seekTo={seekTo}
                onFindSimilar={findSimilar}
                spriteUrl={asset.sprite_url ?? undefined}
                spriteMeta={(asset.sprite_meta as SpriteMeta | null) ?? undefined}
                videoRef={videoRef}
                segments={transcript ?? []}
              />
            </div>
            <div className="pt-2 text-[9px] font-bold tracking-widest text-zinc-600 select-none">[PEOPLE]</div>
            <div className="min-w-0">
              <PeopleTracks
                mediaId={id!}
                duration={asset.duration_seconds!}
                seekTo={seekTo}
              />
            </div>

            {(transcript?.length ?? 0) > 0 && (
              <>
                <div className="pt-1.5 text-[9px] font-bold tracking-widest text-zinc-600 select-none">[DIALOGUE]</div>
                <div className="relative h-4 mt-1 rounded-sm bg-sky-950/40 overflow-hidden">
                  {transcript!.map((s, i) => (
                    <div
                      key={i}
                      className="absolute bottom-0 h-full bg-sky-500/70 hover:bg-sky-400 cursor-pointer rounded-[1px] transition-colors"
                      style={{
                        left: `${Math.min(100, Math.max(0, (s.start_time / asset.duration_seconds!) * 100))}%`,
                        width: `${Math.max(0.3, Math.min(100, ((s.end_time - s.start_time) / asset.duration_seconds!) * 100))}%`,
                      }}
                      title={`${formatTimecode(s.start_time)} — ${s.text ?? ""}`}
                      onClick={() => seekTo(s.start_time)}
                    />
                  ))}
                </div>
              </>
            )}

            {((asset.key_moments as { time: number; title: string }[] | null)?.length ?? 0) > 0 && (
              <>
                <div className="pt-1.5 text-[9px] font-bold tracking-widest text-zinc-600 select-none">[AI TAGS]</div>
                <div className="relative h-6 mt-0.5">
                  {(asset.key_moments as { time: number; title: string }[]).map((m, i) => (
                    <button
                      key={i}
                      type="button"
                      className="absolute top-1/2 -translate-y-1/2 max-w-[180px] truncate rounded-full bg-emerald-500/80 hover:bg-emerald-400 text-emerald-950 px-2 py-0.5 text-[9px] font-semibold whitespace-nowrap transition-colors"
                      style={{ left: `${Math.min(94, Math.max(0, (m.time / asset.duration_seconds!) * 100))}%` }}
                      title={`${formatTimecode(m.time)} — ${m.title}`}
                      onClick={() => seekTo(m.time)}
                    >
                      ● {m.title}
                    </button>
                  ))}
                </div>
              </>
            )}

          </div>
        </div>
      )}
      <Dialog open={similarOpen} onOpenChange={setSimilarOpen}>
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              Moments like {formatTimecode(similarAt)}
            </DialogTitle>
          </DialogHeader>
          <div className="flex-1 overflow-y-auto -mx-1 px-1">
            {similarMoments.isPending ? (
              <div className="flex items-center justify-center h-40 text-muted-foreground gap-2">
                <Loader2 className="h-5 w-5 animate-spin" /> Searching the library…
              </div>
            ) : similarMoments.data?.results.length ? (
              <div className="space-y-5">
                {(["visual", "transcript"] as const).map((kind) => {
                  const items = (similarMoments.data?.results ?? []).filter((r) => r.match_type === kind);
                  if (!items.length) return null;
                  return (
                    <div key={kind}>
                      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                        {kind === "visual" ? "Looks similar" : "Similar things said"}
                      </p>
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                        {items.map((r, i) => (
                          <Link
                            key={`${kind}-${i}`}
                            href={`/library/${r.media_id}?t=${Math.floor(r.start_time)}`}
                            onClick={() => setSimilarOpen(false)}
                            className="rounded-lg overflow-hidden bg-muted/50 hover:bg-muted transition-colors group"
                          >
                            <div className="relative aspect-video bg-black/40">
                              {r.thumbnail_url && (
                                <img src={`/api/thumbnails/${r.thumbnail_url}`} className="w-full h-full object-cover" loading="lazy" />
                              )}
                              <span className="absolute bottom-1 right-1 text-[10px] px-1 py-0.5 rounded bg-black/70 text-white tabular-nums">
                                {formatTimecode(r.start_time)}
                              </span>
                            </div>
                            <div className="p-2">
                              <p className="text-xs font-medium truncate">{r.filename}</p>
                              {r.snippet && <p className="text-[11px] text-muted-foreground line-clamp-2 mt-0.5">{r.snippet}</p>}
                            </div>
                          </Link>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground py-10 text-center">
                Nothing similar found elsewhere in the library for this moment.
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>
      <AddToClipListDialog
        mediaId={id!}
        segment={clipListSegment}
        onClose={() => setClipListSegment(null)}
      />
    </div>
  );
}

const QC_FLAG_LABELS: Record<string, string> = {
  audio_clipping: "Audio clipping",
  audio_silent: "Silent audio",
  audio_low: "Low audio",
  no_audio: "No audio",
  black_frames: "Black frames",
  mostly_black: "Mostly black",
};

/** Compact NLE-style people tracks rendered directly under the player timeline. */
const TRACK_COLORS = ["bg-emerald-500", "bg-sky-500", "bg-amber-500", "bg-fuchsia-500", "bg-rose-500", "bg-violet-500"];

function PeopleTracks({
  mediaId,
  duration,
  seekTo,
}: {
  mediaId: string;
  duration: number;
  seekTo: (time: number) => void;
}) {
  const { data: people } = useGetAssetPeople(mediaId);
  if (!people?.length || duration <= 0) return null;
  const pct = (t: number) => `${Math.min(100, Math.max(0, (t / duration) * 100))}%`;
  const widthPct = (a: number, b: number) =>
    `${Math.max(0.5, Math.min(100, ((b - a) / duration) * 100))}%`;
  return (
    <div className="mt-2 space-y-1" data-testid="people-tracks">
      {people.slice(0, 6).map((p, i) => (
        <div key={p.person_id} className="flex items-center gap-2">
          <Link
            href={`/people/${p.person_id}`}
            className="w-32 shrink-0 flex items-center justify-end gap-1.5 group"
            title={p.display_name}
          >
            <span className="text-[10px] font-medium text-zinc-400 group-hover:text-zinc-200 truncate transition-colors">
              {p.display_name}
            </span>
            {p.thumbnail_url ? (
              <img
                src={`/api/thumbnails/${p.thumbnail_url}`}
                alt=""
                className="h-4 w-4 rounded-full object-cover shrink-0"
              />
            ) : null}
          </Link>
          <div className="relative h-3.5 flex-1 rounded-sm bg-white/5 overflow-hidden">
            {(p.on_camera ?? []).map((r, j) => (
              <div
                key={`cam-${j}`}
                className={`absolute top-0 h-full ${TRACK_COLORS[i % TRACK_COLORS.length]} opacity-25 hover:opacity-40 cursor-pointer transition-opacity`}
                style={{ left: pct(r.start_time), width: widthPct(r.start_time, r.end_time) }}
                title={`${p.display_name} on camera ${formatTimecode(r.start_time)} – ${formatTimecode(r.end_time)}`}
                onClick={() => seekTo(r.start_time)}
              />
            ))}
            {(p.speaking ?? []).map((s, j) => (
              <div
                key={`spk-${j}`}
                className={`absolute bottom-0 h-full ${TRACK_COLORS[i % TRACK_COLORS.length]} opacity-80 hover:opacity-100 cursor-pointer rounded-[1px] transition-opacity`}
                style={{ left: pct(s.start_time), width: widthPct(s.start_time, s.end_time) }}
                title={`${p.display_name} — ${formatTimecode(s.start_time)}${s.text ? `\n${s.text}` : ""}`}
                onClick={() => seekTo(s.start_time)}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

const QC_FLAG_HINTS: Record<string, string> = {
  audio_clipping: "Audio peaks at or above 0 dBFS — likely distorted",
  audio_silent: "Mean audio level below -50 dB — effectively silent",
  audio_low: "Mean audio level below -35 dB — may need a gain boost",
  no_audio: "No audio stream detected",
  black_frames: "One or more black segments of 1s+ detected",
  mostly_black: "Over 90% of the video is black frames",
};

function AssetPeople({
  mediaId,
  duration,
  seekTo,
}: {
  mediaId: string;
  duration: number;
  seekTo: (time: number) => void;
}) {
  const { data: people } = useGetAssetPeople(mediaId);
  const [isolatedId, setIsolatedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  if (!people?.length || duration <= 0) {
    return (
      <div className="text-sm text-muted-foreground py-8 text-center">
        No people identified in this video yet. People appear here after
        diarization and face analysis complete.
      </div>
    );
  }
  const pct = (t: number) => `${Math.min(100, Math.max(0, (t / duration) * 100))}%`;
  const widthPct = (a: number, b: number) =>
    `${Math.max(0.5, Math.min(100, ((b - a) / duration) * 100))}%`;
  const shown = isolatedId ? people.filter((p) => p.person_id === isolatedId) : people;
  const q = query.trim().toLowerCase();
  const matches = q
    ? shown.flatMap((p) =>
        (p.speaking ?? [])
          .filter((s) => (s.text ?? "").toLowerCase().includes(q))
          .map((s) => ({ person: p, moment: s }))
      )
    : [];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setIsolatedId(null)}
          className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${
            isolatedId === null
              ? "bg-primary text-primary-foreground border-primary"
              : "border-border text-muted-foreground hover:text-foreground"
          }`}
        >
          All people
        </button>
        {people.map((p) => (
          <button
            key={p.person_id}
            type="button"
            onClick={() => setIsolatedId(isolatedId === p.person_id ? null : p.person_id)}
            className={`flex items-center gap-2 pl-1 pr-3 py-1 rounded-full text-xs font-medium border transition-colors ${
              isolatedId === p.person_id
                ? "bg-primary text-primary-foreground border-primary"
                : "border-border text-muted-foreground hover:text-foreground"
            }`}
          >
            {p.thumbnail_url ? (
              <img
                src={`/api/thumbnails/${p.thumbnail_url}`}
                alt={p.display_name}
                className="h-6 w-6 rounded-full object-cover"
              />
            ) : (
              <span className="h-6 w-6 rounded-full bg-muted flex items-center justify-center text-[10px] font-semibold">
                {p.display_name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase()}
              </span>
            )}
            {p.display_name}
          </button>
        ))}
      </div>
      <div className="relative max-w-2xl">
        <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={
            isolatedId
              ? `Search what ${shown[0]?.display_name ?? "this person"} says in this video…`
              : "Search what anyone says in this video…"
          }
          className="pl-9"
        />
      </div>
      <div className="space-y-3">
        {shown.map((p) => (
          <div key={p.person_id} className="flex items-center gap-3">
            <Link href={`/people/${p.person_id}`} className="flex items-center gap-2.5 w-48 shrink-0 group">
              {p.thumbnail_url ? (
                <img
                  src={`/api/thumbnails/${p.thumbnail_url}`}
                  alt={p.display_name}
                  className="h-10 w-10 rounded-full object-cover border border-border shrink-0"
                />
              ) : (
                <div className="h-10 w-10 rounded-full bg-muted flex items-center justify-center text-xs font-semibold text-muted-foreground border border-border shrink-0">
                  {p.display_name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase()}
                </div>
              )}
              <div className="min-w-0">
                <p className="text-sm font-medium truncate group-hover:text-primary transition-colors">
                  {p.display_name}
                </p>
                {p.speaking_seconds ? (
                  <p className="text-[11px] text-muted-foreground">
                    {Math.round(p.speaking_seconds / 60)}m speaking
                  </p>
                ) : null}
              </div>
            </Link>
            <div className="relative flex-1 h-7 bg-muted/50 rounded overflow-hidden">
              {(p.on_camera ?? []).map((r, i) => (
                <div
                  key={`cam-${i}`}
                  className="absolute top-0 h-full bg-primary/25 hover:bg-primary/40 cursor-pointer transition-colors"
                  style={{ left: pct(r.start_time), width: widthPct(r.start_time, r.end_time) }}
                  title={`On camera ${formatTimecode(r.start_time)} – ${formatTimecode(r.end_time)}`}
                  onClick={() => seekTo(r.start_time)}
                />
              ))}
              {(p.speaking ?? []).map((s, i) => {
                const isMatch = q && (s.text ?? "").toLowerCase().includes(q);
                return (
                  <div
                    key={`spk-${i}`}
                    className={`absolute bottom-0 h-2.5 cursor-pointer rounded-sm ${
                      q
                        ? isMatch
                          ? "bg-amber-400 hover:bg-amber-300"
                          : "bg-primary/30"
                        : "bg-primary hover:bg-primary/80"
                    }`}
                    style={{ left: pct(s.start_time), width: widthPct(s.start_time, s.end_time) }}
                    title={`${formatTimecode(s.start_time)} — ${s.text}`}
                    onClick={() => seekTo(s.start_time)}
                  />
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <p className="text-[11px] text-muted-foreground">
        Solid marks = speaking · shaded blocks = on camera{q ? " · amber = search match" : ""} · click any mark to jump the player there.
      </p>
      {q ? (
        matches.length ? (
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3 max-h-96 overflow-y-auto">
            {matches.map(({ person, moment }, i) => (
              <div
                key={i}
                className="flex gap-3 items-baseline p-2.5 border border-border rounded-md cursor-pointer hover:bg-muted transition-colors"
                onClick={() => seekTo(moment.start_time)}
              >
                <span className="text-xs font-mono text-primary shrink-0 w-16 text-right">
                  {formatTimecode(moment.start_time)}
                </span>
                <div className="min-w-0">
                  {!isolatedId && (
                    <span className="text-xs font-medium text-muted-foreground mr-2">
                      {person.display_name}:
                    </span>
                  )}
                  <span className="text-sm">{moment.text}</span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground py-2">
            No spoken lines match "{query}"{isolatedId && shown[0] ? ` for ${shown[0].display_name}` : ""}.
          </p>
        )
      ) : null}
    </div>
  );
}

const EMOTION_COLORS: Record<string, string> = {
  joy: "#facc15",
  humor: "#fb923c",
  excitement: "#f97316",
  warmth: "#4ade80",
  pride: "#34d399",
  surprise: "#a78bfa",
  sadness: "#60a5fa",
  anger: "#f87171",
  tension: "#ef4444",
  fear: "#c084fc",
  neutral: "#71717a",
};

function emotionColor(emotion?: string | null): string {
  return EMOTION_COLORS[emotion ?? ""] ?? "#71717a";
}

function MomentsTimeline({
  duration,
  keyMoments,
  clipSuggestions,
  markers,
  seekTo,
  onFindSimilar,
  spriteUrl,
  spriteMeta,
  videoRef,
  segments,
}: {
  duration: number;
  keyMoments: { time: number; title: string; description?: string }[];
  clipSuggestions: { start: number; end: number; title: string; reason?: string; strength: number }[];
  markers: Marker[];
  seekTo: (time: number) => void;
  onFindSimilar?: (time: number) => void;
  spriteUrl?: string;
  spriteMeta?: SpriteMeta;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  segments?: TranscriptSegment[];
}) {
  const barRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; t: number } | null>(null);
  const [playhead, setPlayhead] = useState(0);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onTime = () => setPlayhead(v.currentTime);
    onTime();
    v.addEventListener("timeupdate", onTime);
    v.addEventListener("seeked", onTime);
    return () => {
      v.removeEventListener("timeupdate", onTime);
      v.removeEventListener("seeked", onTime);
    };
  }, [videoRef, duration]);

  const PREVIEW_W = 160;
  const scale = spriteMeta ? PREVIEW_W / spriteMeta.tile_width : 1;
  const previewH = spriteMeta ? Math.round(spriteMeta.tile_height * scale) : 0;
  const idx = spriteMeta && hover ? Math.min(spriteMeta.count - 1, Math.max(0, Math.floor(hover.t / spriteMeta.interval))) : 0;
  const bgX = spriteMeta ? -(idx % spriteMeta.cols) * spriteMeta.tile_width * scale : 0;
  const bgY = spriteMeta ? -Math.floor(idx / spriteMeta.cols) * spriteMeta.tile_height * scale : 0;

  const pct = (t: number) => `${Math.min(100, Math.max(0, (t / duration) * 100))}%`;
  const widthPct = (a: number, b: number) => `${Math.max(0.4, Math.min(100, ((b - a) / duration) * 100))}%`;

  // Continuous heat field: clip strength spread over its span, key moments as
  // gaussian bumps, so the strip reads like a heat map instead of tick marks.
  const gradient = useMemo(() => {
    const N = 160;
    const heat = new Array<number>(N).fill(0);
    const bucket = (t: number) => Math.min(N - 1, Math.max(0, Math.floor((t / duration) * N)));
    for (const c of clipSuggestions) {
      const b0 = bucket(c.start), b1 = Math.max(bucket(c.end), b0);
      const v = 0.25 + 0.75 * (c.strength / 100);
      for (let b = b0; b <= b1; b++) heat[b] = Math.max(heat[b], v);
      // soft falloff at the edges
      for (let d = 1; d <= 3; d++) {
        const f = v * (1 - d / 4);
        if (b0 - d >= 0) heat[b0 - d] = Math.max(heat[b0 - d], f);
        if (b1 + d < N) heat[b1 + d] = Math.max(heat[b1 + d], f);
      }
    }
    for (const m of keyMoments) {
      const b = bucket(m.time);
      for (let d = -2; d <= 2; d++) {
        const i = b + d;
        if (i < 0 || i >= N) continue;
        heat[i] = Math.max(heat[i], 0.85 * (1 - Math.abs(d) / 3));
      }
    }
    const color = (raw: number) => {
      // Baseline "cold" floor so quiet stretches read as deep blue instead of
      // empty black — the whole strip is part of the heat field.
      const v = Math.max(0.06, Math.min(1, raw));
      const hue = 225 - 200 * v; // deep blue -> teal -> green -> amber -> red
      const sat = 55 + 40 * v;
      const light = 16 + 38 * v;
      return `hsl(${hue.toFixed(0)},${sat.toFixed(0)}%,${light.toFixed(0)}%)`;
    };
    const stops = heat.map((v, i) => `${color(v)} ${((i / (N - 1)) * 100).toFixed(2)}%`);
    const heatGradient = `linear-gradient(to right, ${stops.join(",")})`;
    // Emotion gradient replaces the heat strip when the transcript carries emotions.
    const emo = (segments ?? []).filter((s) => s.emotion && s.emotion !== "neutral");
    if (emo.length === 0) return heatGradient;
    const emoStops = (segments ?? [])
      .map(
        (s) =>
          `${emotionColor(s.emotion)} ${Math.min(100, Math.max(0, ((s.start_time + s.end_time) / 2 / duration) * 100)).toFixed(1)}%`,
      )
      .join(", ");
    return `linear-gradient(90deg, ${emoStops})`;
  }, [clipSuggestions, keyMoments, duration, segments]);

  const timeFromEvent = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = Math.min(rect.width, Math.max(0, e.clientX - rect.left));
    return { x, t: (x / rect.width) * duration };
  };

  return (
    <div className="relative mt-2 select-none px-0" data-testid="moments-timeline">
      {hover && spriteUrl && spriteMeta && barRef.current && (
        <div
          className="fixed z-50 pointer-events-none rounded border border-border shadow-lg overflow-hidden bg-black"
          style={{
            left:
              barRef.current.getBoundingClientRect().left +
              Math.min(Math.max(hover.x - PREVIEW_W / 2, 0), barRef.current.clientWidth - PREVIEW_W),
            top: barRef.current.getBoundingClientRect().top - previewH - 20,
            width: PREVIEW_W,
          }}
        >
          <div
            style={{
              width: PREVIEW_W,
              height: previewH,
              backgroundImage: `url(/api/thumbnails/${spriteUrl})`,
              backgroundPosition: `${bgX}px ${bgY}px`,
              backgroundSize: `${spriteMeta.cols * spriteMeta.tile_width * scale}px ${spriteMeta.rows * spriteMeta.tile_height * scale}px`,
            }}
          />
          <div className="text-center text-[10px] font-mono text-white bg-black/80 py-0.5">
            {formatTimecode(hover.t)}
          </div>
        </div>
      )}
      {hover && (!spriteUrl || !spriteMeta) && barRef.current && (
        <div
          className="fixed z-50 pointer-events-none rounded bg-black/85 px-1.5 py-0.5 text-[10px] font-mono text-white"
          style={{
            left: barRef.current.getBoundingClientRect().left + Math.max(0, hover.x - 24),
            top: barRef.current.getBoundingClientRect().top - 22,
          }}
        >
          {formatTimecode(hover.t)}
        </div>
      )}
      <div
        ref={barRef}
        className="relative h-9 rounded bg-zinc-900 overflow-hidden cursor-pointer"
        title="Hover to preview · click to jump · right-click to find similar moments"
        onMouseMove={(e) => setHover(timeFromEvent(e))}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => seekTo(timeFromEvent(e).t)}
        onContextMenu={(e) => {
          if (!onFindSimilar) return;
          e.preventDefault();
          onFindSimilar(timeFromEvent(e).t);
        }}
      >
        <div className="absolute inset-0" style={{ background: gradient }} />
        {clipSuggestions.map((c, i) => (
          <div
            key={`cs-${i}`}
            className="absolute top-0 h-full"
            style={{ left: pct(c.start), width: widthPct(c.start, c.end) }}
            title={`${c.title} (${c.strength}) — ${c.reason ?? ""}`}
          />
        ))}
        {keyMoments.map((m, i) => (
          <div
            key={`km-${i}`}
            className="absolute top-0 h-full w-px bg-white/50"
            style={{ left: pct(m.time) }}
            title={`${m.title}${m.description ? ` — ${m.description}` : ""}`}
          />
        ))}
        {markers.map(m => (
          <div
            key={m.id}
            className={`absolute top-0 h-full ${
              m.kind === "select" ? "bg-green-500" : m.kind === "reject" ? "bg-red-500" : "bg-white/80"
            }`}
            style={m.end_time != null
              ? { left: pct(m.time), width: widthPct(m.time, m.end_time), opacity: 0.55 }
              : { left: pct(m.time), width: "3px" }}
            title={`${m.kind}${m.note ? `: ${m.note}` : ""}`}
          />
        ))}
        {hover && (
          <div className="absolute top-0 bottom-0 w-px bg-white/70 pointer-events-none" style={{ left: hover.x }} />
        )}
        <div
          className="absolute top-0 bottom-0 pointer-events-none"
          style={{ left: pct(playhead) }}
        >
          <div className="absolute top-0 bottom-0 w-[2px] -ml-[1px] bg-white shadow-[0_0_4px_rgba(0,0,0,0.9)]" />
          <div className="absolute -top-0.5 -ml-[5px] w-0 h-0 border-l-[5px] border-r-[5px] border-t-[6px] border-l-transparent border-r-transparent border-t-white" />
        </div>
      </div>
      {(segments ?? []).some((s) => s.emotion && s.emotion !== "neutral") && (
        <div className="relative h-2.5 mt-0.5 rounded-sm bg-zinc-900 overflow-hidden pointer-events-none">
          {(segments ?? []).map((s) =>
            s.emotion && s.emotion !== "neutral" ? (
              <div
                key={`em-${s.id}`}
                className="absolute top-0 h-full pointer-events-auto"
                style={{
                  left: pct(s.start_time),
                  width: widthPct(s.start_time, s.end_time),
                  background: emotionColor(s.emotion),
                  opacity: 0.35 + 0.6 * Math.min(1, Math.abs(s.sentiment ?? 0.4)),
                }}
                title={`${s.emotion}${s.sentiment != null ? ` (${s.sentiment > 0 ? "+" : ""}${s.sentiment.toFixed(2)})` : ""} — ${s.text.slice(0, 120)}`}
              />
            ) : null
          )}
          <div className="absolute top-0 bottom-0 w-[2px] -ml-[1px] bg-white/80" style={{ left: pct(playhead) }} />
        </div>
      )}
      <div className="flex gap-4 mt-1 text-[10px] text-zinc-500">
        <span className="font-mono text-zinc-300">{formatTimecode(playhead)}</span>
        <span className="flex items-center gap-1"><span className="inline-block w-6 h-2 rounded-sm" style={{ background: "linear-gradient(to right, #60a5fa, #ef4444, #facc15, #4ade80)" }} /> emotion heatmap</span>
        <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 bg-green-500 rounded-sm" /> Select</span>
        <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 bg-red-500 rounded-sm" /> Reject</span>
        <span className="ml-auto text-zinc-600">right-click anywhere to find similar moments</span>
      </div>
    </div>
  );
}

function AddToClipListDialog({
  mediaId,
  segment,
  onClose,
}: {
  mediaId: string;
  segment: TranscriptSegment | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { data: clipLists } = useListClipLists(undefined, { query: { enabled: !!segment, queryKey: getListClipListsQueryKey() } });
  const createMutation = useCreateClipList();
  const updateMutation = useUpdateClipList();
  const [target, setTarget] = useState<string>("__new__");
  const [newName, setNewName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const busy = createMutation.isPending || updateMutation.isPending;

  const label = segment ? (segment.text.length > 60 ? `${segment.text.slice(0, 57)}...` : segment.text) : "";

  const handleAdd = () => {
    if (!segment) return;
    setError(null);
    const clip = { media_id: mediaId, start_time: segment.start_time, end_time: segment.end_time, label };
    const done = () => {
      queryClient.invalidateQueries({ queryKey: getListClipListsQueryKey() });
      onClose();
    };
    if (target === "__new__") {
      const name = newName.trim() || "Transcript selects";
      createMutation.mutate({ data: { name, clips: [clip] } }, { onSuccess: done, onError: () => setError("Failed to create clip list.") });
    } else {
      const existing = clipLists?.find(c => c.id === target);
      if (!existing) return;
      const clips = [
        ...existing.clips.map(c => ({ media_id: c.media_id, start_time: c.start_time, end_time: c.end_time, label: c.label ?? undefined })),
        clip,
      ];
      updateMutation.mutate({ id: target, data: { clips } }, {
        onSuccess: () => {
          queryClient.invalidateQueries({ queryKey: getGetClipListQueryKey(target) });
          done();
        },
        onError: () => setError("Failed to add — the clip list may be picture-locked."),
      });
    }
  };

  return (
    <Dialog open={!!segment} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ListPlus className="h-5 w-5" /> Add to clip list
          </DialogTitle>
        </DialogHeader>
        {segment && (
          <div className="space-y-3 text-sm">
            <p className="text-muted-foreground">
              <span className="font-mono text-xs">{formatTimecode(segment.start_time)} – {formatTimecode(segment.end_time)}</span>{" "}
              — "{label}"
            </p>
            <Select value={target} onValueChange={setTarget}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="__new__">+ New clip list</SelectItem>
                {clipLists?.map(cl => (
                  <SelectItem key={cl.id} value={cl.id} disabled={cl.locked}>
                    {cl.name}{cl.locked ? " (locked)" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {target === "__new__" && (
              <Input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Clip list name" />
            )}
            {error && <p className="text-xs text-destructive">{error}</p>}
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="outline" onClick={onClose}>Cancel</Button>
              <Button onClick={handleAdd} disabled={busy}>
                {busy ? "Adding..." : "Add clip"}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

const BEAT_COLORS: Record<string, string> = {
  hook: "bg-amber-500",
  setup: "bg-sky-500",
  development: "bg-blue-500",
  turn: "bg-orange-500",
  climax: "bg-red-500",
  resolution: "bg-green-500",
};

const NOTE_LABELS: Record<string, string> = {
  pacing: "Pacing",
  structure: "Structure",
  cuts: "Cuts",
  broll: "B-Roll",
  delivery: "Delivery",
  best_take: "Best Take",
};

function CreativeSection({
  creative,
  busy,
  progress,
  error,
  onRun,
  seekTo,
}: {
  creative: CreativeAnalysis | null | undefined;
  busy: boolean;
  progress: number | null;
  error: boolean;
  onRun: () => void;
  seekTo: (time: number) => void;
}) {
  if (!creative || busy) {
    return (
      <div className="py-10 flex flex-col items-center text-center gap-3">
        <Clapperboard className="h-10 w-10 text-muted-foreground" />
        <Button className="gap-2" onClick={onRun} disabled={busy}>
          {busy ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Reviewing footage{progress ? ` — ${Math.round(progress)}%` : "..."}
            </>
          ) : (
            <>
              <Wand2 className="h-4 w-4" />
              Run Creative Pass
            </>
          )}
        </Button>
        <p className="text-xs text-muted-foreground max-w-sm">
          The AI reviews the footage like a story editor: maps the narrative arc, pulls the
          strongest soundbites as ready-to-cut clips, and writes actionable editing notes.
        </p>
        {error && (
          <p className="text-xs text-destructive">Failed to start creative pass. Check Pipeline Jobs.</p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {creative.logline && (
        <div className="border-l-2 border-primary pl-4">
          <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-1">Logline</h3>
          <p className="text-sm leading-relaxed italic">{creative.logline}</p>
        </div>
      )}

      <div className="grid gap-8 lg:grid-cols-2">
      <div className="space-y-8">
      {creative.story_beats.length > 0 && (
        <div>
          <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-3">Story Arc</h3>
          <div className="space-y-1">
            {creative.story_beats.map((beat, i) => (
              <div
                key={i}
                className="flex gap-3 items-baseline p-2 -mx-2 rounded cursor-pointer hover:bg-muted transition-colors"
                onClick={() => seekTo(beat.time)}
              >
                <span className="text-xs font-mono text-primary shrink-0 w-14 text-right">
                  {formatTimecode(beat.time)}
                </span>
                <span
                  className={`shrink-0 mt-1 h-2 w-2 rounded-full ${BEAT_COLORS[beat.beat] ?? "bg-muted-foreground"}`}
                />
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium">{beat.title}</span>
                    <Badge variant="outline" className="text-[10px] uppercase tracking-wide">{beat.beat}</Badge>
                    {beat.emotion && (
                      <span className="text-[11px] text-muted-foreground">{beat.emotion}</span>
                    )}
                  </div>
                  {beat.description && (
                    <div className="text-xs text-muted-foreground">{beat.description}</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {creative.editorial_notes.length > 0 && (
        <div>
          <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-3">
            Editorial Notes
          </h3>
          <div className="space-y-2">
            {creative.editorial_notes.map((note, i) => (
              <div key={i} className="flex gap-3 items-start">
                <Badge variant="secondary" className="text-[10px] uppercase tracking-wide shrink-0 mt-0.5 w-20 justify-center">
                  {NOTE_LABELS[note.category] ?? note.category}
                </Badge>
                <p className="text-sm text-muted-foreground leading-relaxed">{note.note}</p>
              </div>
            ))}
          </div>
        </div>
      )}
      </div>

      {creative.clip_suggestions.length > 0 && (
        <div>
          <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-3">
            Suggested Clips
          </h3>
          <div className="space-y-3">
            {creative.clip_suggestions.map((clip, i) => (
              <div
                key={i}
                className="border border-border rounded-lg p-3 cursor-pointer hover:bg-muted/50 transition-colors"
                onClick={() => seekTo(clip.start)}
              >
                <div className="flex items-center justify-between gap-3 mb-1.5">
                  <div className="flex items-center gap-2 min-w-0">
                    <Scissors className="h-3.5 w-3.5 text-primary shrink-0" />
                    <span className="text-sm font-medium truncate">{clip.title}</span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-xs font-mono text-muted-foreground">
                      {formatTimecode(clip.start)}–{formatTimecode(clip.end)}
                      <span className="ml-1 text-muted-foreground/70">
                        ({Math.round(clip.end - clip.start)}s)
                      </span>
                    </span>
                    {clip.strength != null && (
                      <span className={`text-xs font-semibold ${scoreColor(clip.strength)}`}>
                        {clip.strength}
                      </span>
                    )}
                  </div>
                </div>
                {clip.quote && (
                  <p className="text-sm text-muted-foreground italic mb-1.5">“{clip.quote}”</p>
                )}
                <p className="text-xs text-muted-foreground">{clip.reason}</p>
                {clip.platforms && clip.platforms.length > 0 && (
                  <div className="flex gap-1.5 mt-2">
                    {clip.platforms.map((p) => {
                      const meta = PLATFORM_META[p];
                      return meta ? (
                        <meta.Icon key={p} className={`h-3.5 w-3.5 ${meta.color}`} />
                      ) : (
                        <Badge key={p} variant="secondary" className="text-[10px]">{p}</Badge>
                      );
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      </div>

      <div className="flex items-center gap-3 pt-2">
        <Button variant="outline" size="sm" className="gap-2" onClick={onRun}>
          <Wand2 className="h-4 w-4" />
          Re-run Creative Pass
        </Button>
        {creative.generated_at && (
          <span className="text-xs text-muted-foreground">
            Generated {new Date(creative.generated_at).toLocaleString()}
          </span>
        )}
      </div>
    </div>
  );
}

function reelStatusBadge(status: string) {
  const map: Record<string, string> = {
    pending: "bg-yellow-500/15 text-yellow-400",
    running: "bg-blue-500/15 text-blue-400",
    success: "bg-green-500/15 text-green-400",
    error: "bg-red-500/15 text-red-400",
  };
  return map[status] || "bg-muted text-muted-foreground";
}

const SOCIAL_CUT_LABEL = /^(youtube|instagram|x|facebook|tiktok): /;

function AssetRendersSection({ mediaId, socialOnly }: { mediaId: string; socialOnly?: boolean }) {
  const queryClient = useQueryClient();
  const listParams = { media_id: mediaId };
  const deleteMutation = useDeleteRender();
  const [previewId, setPreviewId] = useState<string | null>(null);
  const { data: allRenders } = useListRenders(listParams, {
    query: {
      queryKey: getListRendersQueryKey(listParams),
      refetchInterval: (q) =>
        q.state.data?.some((r) => r.status === "pending" || r.status === "running") ? 3000 : false,
    },
  });

  const renders = socialOnly
    ? allRenders?.filter((r) => SOCIAL_CUT_LABEL.test(r.label ?? ""))
    : allRenders;

  if (!renders?.length) return null;

  return (
    <div className="border-t border-border pt-5 space-y-3 max-w-5xl">
      <div>
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Clapperboard className="h-4 w-4" /> {socialOnly ? "Social cuts" : "Renders"}
        </h3>
        <p className="text-xs text-muted-foreground mt-1">
          {socialOnly
            ? "Cuts rendered from this video — download when ready."
            : "Clips and social cuts rendered from this video."}
        </p>
      </div>
      <div className="space-y-2">
        {renders.map((r: RenderJob) => (
          <div key={r.id} className="bg-muted/50 p-2.5 rounded text-sm space-y-2">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="truncate">{r.label || r.filename || r.media_id}</div>
              <div className="text-xs text-muted-foreground">
                {formatTimecode(r.start_time)}–{formatTimecode(r.end_time)} · {r.preset}
                {r.status === "running" ? ` · ${Math.round(r.progress ?? 0)}%` : ""}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <Badge variant="outline" className={reelStatusBadge(r.status)}>{r.status}</Badge>
              {r.status === "success" && (
                <>
                  <Button
                    size="sm" variant="outline"
                    onClick={() => setPreviewId(previewId === r.id ? null : r.id)}
                    data-testid={`button-preview-render-${r.id}`}
                  >
                    {previewId === r.id ? "Close" : "Preview"}
                  </Button>
                  <Button size="sm" variant="outline" asChild>
                    <a href={`/api/renders/${r.id}/download`} download>
                      <Download className="h-4 w-4 mr-2" /> MP4
                    </a>
                  </Button>
                </>
              )}
              <Button
                size="sm" variant="ghost"
                className="text-muted-foreground hover:text-destructive"
                title="Delete this render and its file"
                disabled={deleteMutation.isPending}
                onClick={() =>
                  deleteMutation.mutate(
                    { id: r.id },
                    { onSuccess: () => queryClient.invalidateQueries({ queryKey: getListRendersQueryKey(listParams) }) },
                  )
                }
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </div>
          {previewId === r.id && r.status === "success" && (
            <video
              key={r.id}
              src={`/api/renders/${r.id}/download`}
              controls
              autoPlay
              playsInline
              className={
                r.preset === "vertical"
                  ? "w-auto mx-auto max-h-[70vh] aspect-[9/16] rounded bg-black"
                  : "w-full max-h-[70vh] rounded bg-black"
              }
            />
          )}
          </div>
        ))}
      </div>
    </div>
  );
}

function AssetStudioSection({ mediaId, onSeek, onCutChange }: { mediaId: string; onSeek?: (t: number) => void; onCutChange?: (clips: CutClip[]) => void }) {
  const [project, setProject] = useState<Project | null>(null);
  const sessionMutation = useGetMediaStudioSession();
  const startedFor = useRef<string | null>(null);

  const open = () => {
    sessionMutation.mutate(
      { id: mediaId },
      { onSuccess: (p) => setProject(p) },
    );
  };

  useEffect(() => {
    if (startedFor.current === mediaId) return;
    startedFor.current = mediaId;
    setProject(null);
    open();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mediaId]);

  if (sessionMutation.isError) {
    return (
      <div className="py-10 flex flex-col items-center gap-3 text-sm text-destructive">
        Failed to open the Studio session for this asset.
        <Button size="sm" variant="outline" onClick={open}>Retry</Button>
      </div>
    );
  }
  if (!project) {
    return (
      <div className="py-10 flex items-center justify-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Opening Studio…
      </div>
    );
  }
  return <StudioTab project={project} onSeekSource={onSeek} onCutChange={onCutChange} />;
}

type SpriteMeta = {
  interval: number;
  tile_width: number;
  tile_height: number;
  cols: number;
  rows: number;
  count: number;
};

function AssetSearchTab({ mediaId, seekTo }: { mediaId: string; seekTo: (t: number) => void }) {
  const [q, setQ] = useState("");
  const [scope, setScope] = useState<"combined" | "transcript" | "visual">("combined");
  const search = useSemanticSearch();

  const run = (s?: "combined" | "transcript" | "visual") => {
    const term = q.trim();
    if (term.length < 2) return;
    search.mutate({
      data: { query: term, media_id: mediaId, search_type: s ?? scope, limit: 500 },
    });
  };

  const results = search.data?.results ?? [];

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          placeholder="Search this asset — transcript & visuals…"
          data-testid="input-asset-search"
        />
        <Button onClick={() => run()} disabled={q.trim().length < 2 || search.isPending} data-testid="button-asset-search">
          {search.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
        </Button>
      </div>
      <div className="flex items-center gap-1.5 text-xs">
        <span className="text-muted-foreground mr-1">Search in:</span>
        {([["combined", "All"], ["transcript", "Transcript"], ["visual", "Visuals"]] as const).map(([v, label]) => (
          <Button
            key={v}
            size="sm"
            variant={scope === v ? "default" : "outline"}
            className="h-6 px-2 text-xs"
            onClick={() => { setScope(v); if (q.trim().length >= 2) run(v); }}
          >
            {label}
          </Button>
        ))}
      </div>
      {search.data && (
        <p className="text-xs text-muted-foreground">
          {results.length} result{results.length === 1 ? "" : "s"} for “{search.data.query}”
        </p>
      )}
      <div className="space-y-1.5">
        {results.map((r: SearchResult, i: number) => (
          <button
            key={`${r.start_time}-${i}`}
            type="button"
            onClick={() => seekTo(r.start_time)}
            className="w-full flex items-start gap-3 rounded-md border border-border bg-card/50 hover:bg-muted/40 px-3 py-2 text-left"
            data-testid={`asset-search-result-${i}`}
          >
            {r.thumbnail_url && (
              <img src={`/api/thumbnails/${r.thumbnail_url}`} alt="" loading="lazy" className="h-12 w-20 rounded object-cover shrink-0" />
            )}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-xs">
                <span className="font-mono text-primary">
                  {formatTimecode(r.start_time)}{r.end_time != null ? ` – ${formatTimecode(r.end_time)}` : ""}
                </span>
                <span className="text-muted-foreground">
                  {r.match_type === "visual" ? "Visual" : r.match_type === "person" ? "Person" : "Transcript"}
                  {r.match_type === "person" ? "" : ` · ${(r.score * 100).toFixed(0)}%`}
                </span>
              </div>
              {r.snippet && <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">{r.snippet}</p>}
            </div>
          </button>
        ))}
        {search.data && !results.length && (
          <p className="text-sm text-muted-foreground py-4 text-center">No matches in this asset.</p>
        )}
      </div>
    </div>
  );
}
