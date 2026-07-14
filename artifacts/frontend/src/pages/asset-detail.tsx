import { useEffect, useRef, useState } from "react";
import { useParams, useSearch, useLocation } from "wouter";
import { 
  useGetMedia, getGetMediaQueryKey,
  useGetMediaScenes, getGetMediaScenesQueryKey,
  useGetMediaTranscript, getGetMediaTranscriptQueryKey,
  useListJobs, getListJobsQueryKey,
  useDeleteMedia, getListMediaQueryKey,
  useCreateHighlight,
  useCreateSocialAnalysis,
  useCreateSocialCuts,
  useCreateTranslation,
  useCreateDub,
  useListReels, getListReelsQueryKey,
  useCreateReel,
  useDeleteReel
} from "@workspace/api-client-react";
import type { SocialScore, SocialCutsRequestPlatform, ReelJob } from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Trash2, Sparkles, Film, Loader2, Download, Share2, Youtube, Instagram, Facebook, Twitter, Music2, TrendingUp, ThumbsUp, ThumbsDown, Clapperboard, Hash, Languages, Volume2, AudioLines, Scissors, Wand2, Smartphone, Monitor, Captions } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Progress } from "@/components/ui/progress";
import AssetChat from "@/components/asset-chat";

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
  const langAvailable = transcriptLang !== "original" && (asset?.translated_languages ?? []).includes(transcriptLang);
  const transcriptParams = langAvailable ? { lang: transcriptLang } : undefined;
  const { data: transcript } = useGetMediaTranscript(id!, transcriptParams, { query: { enabled: !!id, queryKey: getGetMediaTranscriptQueryKey(id!, transcriptParams) } });
  const { data: jobs } = useListJobs({ media_id: id! }, { query: { enabled: !!id, queryKey: getListJobsQueryKey({ media_id: id! }), refetchInterval: 3000 } });

  const highlightMutation = useCreateHighlight();
  const highlightJob = jobs?.find(j => j.job_type === "highlight" && (j.status === "pending" || j.status === "running"));
  const highlightBusy = highlightMutation.isPending || Boolean(highlightJob);

  const startHighlight = () => {
    if (!id) return;
    highlightMutation.mutate({ id }, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListJobsQueryKey({ media_id: id }) });
      }
    });
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

  const cutsMutation = useCreateSocialCuts();
  const [cutsPlatform, setCutsPlatform] = useState<string | null>(null);

  const startCuts = (platform: SocialCutsRequestPlatform | null) => {
    if (!id) return;
    setCutsPlatform(platform ?? "all");
    cutsMutation.mutate(
      { id, data: platform ? { platform } : {} },
      {
        onSuccess: () => navigate("/exports"),
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

  const startDub = (lang: string) => {
    if (!id) return;
    dubMutation.mutate({ id, data: { target_language: lang } }, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListJobsQueryKey({ media_id: id }) });
      }
    });
  };

  const dubSupported = DUB_LANGUAGES.includes(transcriptLang);
  const dubAvailable = dubSupported && (asset?.dubbed_languages ?? []).includes(transcriptLang);
  const [dubOn, setDubOn] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);

  // Turn dubbed audio off whenever it stops being applicable.
  useEffect(() => {
    if (!dubAvailable && dubOn) setDubOn(false);
  }, [dubAvailable, dubOn]);

  // Keep the dubbed audio track in lockstep with the video element.
  useEffect(() => {
    const video = videoRef.current;
    const audio = audioRef.current;
    if (!video || !audio || !dubOn) return;
    video.muted = true;
    const syncPlay = () => { audio.currentTime = video.currentTime; audio.play().catch(() => {}); };
    const syncPause = () => audio.pause();
    const syncSeek = () => { audio.currentTime = video.currentTime; };
    const syncRate = () => { audio.playbackRate = video.playbackRate; };
    const fixDrift = () => {
      if (!video.paused && Math.abs(audio.currentTime - video.currentTime) > 0.35) {
        audio.currentTime = video.currentTime;
      }
    };
    video.addEventListener("play", syncPlay);
    video.addEventListener("pause", syncPause);
    video.addEventListener("seeked", syncSeek);
    video.addEventListener("ratechange", syncRate);
    video.addEventListener("timeupdate", fixDrift);
    syncRate();
    if (!video.paused) syncPlay();
    return () => {
      video.removeEventListener("play", syncPlay);
      video.removeEventListener("pause", syncPause);
      video.removeEventListener("seeked", syncSeek);
      video.removeEventListener("ratechange", syncRate);
      video.removeEventListener("timeupdate", fixDrift);
      audio.pause();
      video.muted = false;
    };
  }, [dubOn, transcriptLang, id]);

  // When a highlight/social/translate job finishes, refresh the asset so results appear.
  const lastHighlightStatus = jobs?.filter(j => j.job_type === "highlight")
    .sort((a, b) => (b.created_at > a.created_at ? 1 : -1))[0]?.status;
  const lastSocialStatus = jobs?.filter(j => j.job_type === "social")
    .sort((a, b) => (b.created_at > a.created_at ? 1 : -1))[0]?.status;
  const lastTranslateJob = jobs?.filter(j => j.job_type === "translate")
    .sort((a, b) => (b.created_at > a.created_at ? 1 : -1))[0];
  const lastTranslateStatus = lastTranslateJob?.status;
  const lastDubJob = jobs?.filter(j => j.job_type === "dub")
    .sort((a, b) => (b.created_at > a.created_at ? 1 : -1))[0];
  const lastDubStatus = lastDubJob?.status;
  useEffect(() => {
    if ((lastHighlightStatus === "success" || lastSocialStatus === "success" || lastTranslateStatus === "success" || lastDubStatus === "success") && id) {
      queryClient.invalidateQueries({ queryKey: getGetMediaQueryKey(id) });
    }
  }, [lastHighlightStatus, lastSocialStatus, lastTranslateStatus, lastDubStatus, id, queryClient]);

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
        {/* Main Content Area */}
        <div className="flex-1 flex flex-col overflow-y-auto">
          <div className="p-6 bg-black flex-shrink-0 relative">
            {asset.status === 'ready' ? (
              <video 
                ref={videoRef}
                src={`/api/media/${id}/stream`} 
                controls 
                className="w-full max-h-[60vh] object-contain bg-black"
              />
            ) : (
              undefined
            )}
            {asset.status === 'ready' && dubAvailable && (
              <audio
                ref={audioRef}
                src={`/api/media/${id}/dub/${transcriptLang}/stream`}
                preload="auto"
                className="hidden"
              />
            )}
            {asset.status !== 'ready' && (
              <div className="w-full h-64 bg-muted flex flex-col items-center justify-center">
                <p className="text-muted-foreground mb-2">Media is {asset.status}</p>
                {asset.processing_stage && (
                  <Badge variant="outline">{asset.processing_stage} {asset.processing_progress}%</Badge>
                )}
              </div>
            )}
          </div>
          
          <div className="p-6">
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
            <div className="flex gap-4 text-sm text-muted-foreground mb-6">
              <span>{asset.codec}</span>
              <span>{asset.width}x{asset.height}</span>
              <span>{asset.fps} fps</span>
            </div>

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

            <Tabs defaultValue={hasAnalysis ? "analysis" : "scenes"}>
              <TabsList>
                <TabsTrigger value="analysis" className="gap-1.5">
                  <Sparkles className="h-3.5 w-3.5" />
                  AI Analysis
                </TabsTrigger>
                <TabsTrigger value="highlight" className="gap-1.5">
                  <Film className="h-3.5 w-3.5" />
                  Highlight Reel
                </TabsTrigger>
                <TabsTrigger value="socials" className="gap-1.5">
                  <Share2 className="h-3.5 w-3.5" />
                  Socials
                </TabsTrigger>
                <TabsTrigger value="scenes">Scenes</TabsTrigger>
                <TabsTrigger value="jobs">Pipeline Jobs</TabsTrigger>
              </TabsList>
              <TabsContent value="analysis" className="mt-4">
                {hasAnalysis ? (
                  <div className="space-y-6 max-w-3xl">
                    {asset.synopsis && (
                      <div>
                        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">Synopsis</h3>
                        <p className="text-sm text-muted-foreground leading-relaxed">{asset.synopsis}</p>
                      </div>
                    )}
                    {asset.key_moments && asset.key_moments.length > 0 && (
                      <div>
                        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">Key Moments</h3>
                        <div className="space-y-1">
                          {asset.key_moments.map((moment, i) => (
                            <div
                              key={i}
                              className="flex gap-3 items-baseline p-2 -mx-2 rounded cursor-pointer hover:bg-muted transition-colors"
                              onClick={() => seekTo(moment.time)}
                            >
                              <span className="text-xs font-mono text-primary shrink-0 w-12 text-right">
                                {formatTimecode(moment.time)}
                              </span>
                              <div>
                                <div className="text-sm font-medium">{moment.title}</div>
                                {moment.description && (
                                  <div className="text-xs text-muted-foreground">{moment.description}</div>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {asset.topics && asset.topics.length > 0 && (
                      <div>
                        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">Topics</h3>
                        <div className="flex flex-wrap gap-1.5">
                          {asset.topics.map(topic => (
                            <Badge key={topic} variant="secondary" className="text-xs">{topic}</Badge>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground py-8 text-center">
                    No AI analysis yet. It is generated automatically after indexing completes —
                    or re-run the index job from the Pipeline Jobs tab.
                  </div>
                )}
              </TabsContent>
              <TabsContent value="highlight" className="mt-4 space-y-6">
                {asset.key_moments && asset.key_moments.length > 0 ? (
                  asset.highlight_url && !highlightBusy ? (
                    <div className="space-y-3 max-w-5xl">
                      <video
                        src={`/api/media/${id}/highlight/stream`}
                        controls
                        className="w-full max-h-[55vh] rounded border border-border bg-black"
                      />
                      <div className="flex gap-2">
                        <Button asChild variant="outline" size="sm" className="gap-2">
                          <a href={`/api/media/${id}/highlight/stream`} download={`highlight_${asset.filename}`}>
                            <Download className="h-4 w-4" />
                            Download
                          </a>
                        </Button>
                        <Button variant="outline" size="sm" className="gap-2" onClick={startHighlight}>
                          <Film className="h-4 w-4" />
                          Regenerate
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="py-10 flex flex-col items-center text-center gap-3">
                      <Clapperboard className="h-10 w-10 text-muted-foreground" />
                      <Button className="gap-2" onClick={startHighlight} disabled={highlightBusy}>
                        {highlightBusy ? (
                          <>
                            <Loader2 className="h-4 w-4 animate-spin" />
                            Building reel{highlightJob?.progress ? ` — ${Math.round(highlightJob.progress)}%` : "..."}
                          </>
                        ) : (
                          <>
                            <Film className="h-4 w-4" />
                            Generate Highlight Reel
                          </>
                        )}
                      </Button>
                      <p className="text-xs text-muted-foreground max-w-sm">
                        Cuts short clips at each AI-detected key moment and stitches them into one video.
                      </p>
                      {highlightMutation.isError && (
                        <p className="text-xs text-destructive">Failed to start highlight job. Check Pipeline Jobs.</p>
                      )}
                    </div>
                  )
                ) : (
                  <div className="text-sm text-muted-foreground py-8 text-center">
                    A highlight reel needs AI-detected key moments. Run AI analysis first.
                  </div>
                )}
                <AssetReelSection mediaId={id!} />
              </TabsContent>
              <TabsContent value="socials" className="mt-4">
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
                    {cutsMutation.isError && (
                      <p className="text-xs text-destructive">Failed to create cuts. Check that key moments exist and the pipeline is running.</p>
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
                              Create cuts
                            </Button>
                          </div>
                        );
                      })}
                    </div>
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
              <TabsContent value="scenes" className="mt-4">
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
                          {Math.floor(scene.start_time)}s
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </TabsContent>
              <TabsContent value="jobs" className="mt-4">
                <div className="space-y-2">
                  {jobs?.map(job => (
                    <div key={job.id} className="p-3 border border-border rounded flex justify-between items-center">
                      <div>
                        <div className="font-medium">{job.job_type}</div>
                        <div className="text-xs text-muted-foreground">{new Date(job.created_at).toLocaleString()}</div>
                      </div>
                      <Badge variant={job.status === 'success' ? 'default' : job.status === 'error' ? 'destructive' : 'secondary'}>
                        {job.status}
                      </Badge>
                    </div>
                  ))}
                </div>
              </TabsContent>
            </Tabs>
          </div>
        </div>

        {/* Right Sidebar - Transcript / AI Chat */}
        <div className="w-[26rem] border-l border-border flex flex-col bg-card shrink-0 overflow-hidden">
          <Tabs defaultValue="transcript" className="flex flex-col h-full overflow-hidden">
            <div className="p-3 border-b border-border shrink-0">
              <TabsList className="w-full">
                <TabsTrigger value="transcript" className="flex-1">Transcript</TabsTrigger>
                <TabsTrigger value="chat" className="flex-1 gap-1.5">
                  <Sparkles className="h-3.5 w-3.5" />
                  AI Chat
                </TabsTrigger>
              </TabsList>
            </div>
            <TabsContent value="transcript" className="flex-1 overflow-hidden mt-0 flex flex-col">
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
              {transcriptLang !== "original" && langAvailable && (
                <div className="px-3 pt-2 shrink-0">
                  {dubAvailable ? (
                    <Button
                      size="sm"
                      variant={dubOn ? "default" : "outline"}
                      className="w-full gap-2"
                      onClick={() => setDubOn(v => !v)}
                    >
                      <Volume2 className="h-4 w-4" />
                      {dubOn ? "Dubbed audio on — click to switch off" : "Play dubbed audio"}
                    </Button>
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
              <ScrollArea className="flex-1 p-4">
                <div className="space-y-4">
                  {transcript?.map(segment => (
                    <div 
                      key={segment.id} 
                      className="group cursor-pointer hover:bg-muted p-2 -mx-2 rounded transition-colors"
                      onClick={() => seekTo(segment.start_time)}
                    >
                      <div className="flex gap-2 items-baseline mb-1">
                        <span className="text-xs font-medium text-primary">{segment.speaker || 'Unknown'}</span>
                        <span className="text-[10px] text-muted-foreground">{Math.floor(segment.start_time)}s</span>
                      </div>
                      <p className="text-sm">{segment.text}</p>
                    </div>
                  ))}
                  {!transcript?.length && (
                    <div className="text-sm text-muted-foreground text-center mt-10">No transcript available</div>
                  )}
                </div>
              </ScrollArea>
              )}
            </TabsContent>
            <TabsContent value="chat" className="flex-1 overflow-hidden mt-0">
              <AssetChat key={id} mediaId={id!} onSeek={seekTo} />
            </TabsContent>
          </Tabs>
        </div>
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

function AssetReelSection({ mediaId }: { mediaId: string }) {
  const queryClient = useQueryClient();
  const listParams = { media_id: mediaId };
  const { data: reels } = useListReels(listParams, {
    query: { queryKey: getListReelsQueryKey(listParams), refetchInterval: 3000 },
  });
  const createMutation = useCreateReel();
  const deleteMutation = useDeleteReel();

  const [prompt, setPrompt] = useState("");
  const [preset, setPreset] = useState<"original" | "vertical">("original");
  const [burnCaptions, setBurnCaptions] = useState(false);
  const [maxClips, setMaxClips] = useState(6);

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: getListReelsQueryKey(listParams) });

  const submit = () => {
    if (prompt.trim().length < 3) return;
    createMutation.mutate(
      {
        data: {
          prompt: prompt.trim(),
          media_id: mediaId,
          preset,
          burn_captions: burnCaptions,
          max_clips: maxClips,
        },
      },
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
    <div className="border-t border-border pt-5 space-y-4 max-w-5xl">
      <div>
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Wand2 className="h-4 w-4" />
          Prompt Reel
        </h3>
        <p className="text-xs text-muted-foreground mt-1">
          Describe what to highlight — the best matching moments from this video get stitched into one reel.
        </p>
      </div>
      <div className="space-y-3">
        <Textarea
          placeholder='e.g. "every moment about his family" or "the story about the book"'
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={2}
        />
        <div className="flex flex-wrap items-end gap-4">
          <div className="space-y-1.5">
            <Label className="text-xs">Format</Label>
            <Select value={preset} onValueChange={(v) => setPreset(v as typeof preset)}>
              <SelectTrigger className="w-40 h-9"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="original">Original</SelectItem>
                <SelectItem value="vertical">Vertical 9:16</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Max clips</Label>
            <Select value={String(maxClips)} onValueChange={(v) => setMaxClips(Number(v))}>
              <SelectTrigger className="w-20 h-9"><SelectValue /></SelectTrigger>
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
              ? "No moments in this video match that prompt — try different wording."
              : "Failed to start the reel. Check that the pipeline is running."}
          </p>
        )}
      </div>

      {reels && reels.length > 0 && (
        <div className="space-y-3">
          {reels.map((r: ReelJob) => (
            <div key={r.id} className="border border-border rounded-lg p-4">
              <div className="flex items-start gap-4">
                <div className="shrink-0 text-muted-foreground mt-1">
                  {r.preset === "vertical" ? <Smartphone className="h-5 w-5" /> : <Monitor className="h-5 w-5" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-sm">&ldquo;{r.prompt}&rdquo;</span>
                    <Badge variant="outline" className={reelStatusBadge(r.status)}>{r.status}</Badge>
                    <Badge variant="outline">{r.clips.length} clip{r.clips.length === 1 ? "" : "s"}</Badge>
                    {r.preset === "vertical" && <Badge variant="outline">9:16 vertical</Badge>}
                    {r.burn_captions && (
                      <Badge variant="outline" className="gap-1"><Captions className="h-3 w-3" /> captions</Badge>
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground mt-1.5 space-y-0.5 font-mono">
                    {r.clips.map((c, i) => (
                      <div key={i} className="truncate">
                        {formatTimecode(c.start_time)} – {formatTimecode(c.end_time)}
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
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
