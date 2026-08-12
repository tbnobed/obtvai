import { useEffect, useMemo, useRef, useState } from "react";
import { useRoute, Link } from "wouter";
import {
  useGetPerson,
  getGetPersonQueryKey,
  getListPeopleQueryKey,
  useUpdatePerson,
  useMergePerson,
  useSplitPerson,
  useUnmergePerson,
  useListPeople,
  useGetVoiceProfile,
  getGetVoiceProfileQueryKey,
  useAddVoiceSample,
  useUploadVoiceSample,
  useDeleteVoiceSample,
  useCreateVoiceGeneration,
  useListVoiceGenerations,
  getListVoiceGenerationsQueryKey,
  useDeleteVoiceGeneration,
  useCreateLipsyncVideo,
  useUploadLipsyncReference,
  useDeleteLipsyncReference,
  useTuneVoice,
  useSetVoicePreset,
  useSetVoiceSettings,
  useReprofilePerson,
  useFaceSearchPerson,
  useUpdatePersonPhoto,
  useDeletePersonPhoto,
} from "@workspace/api-client-react";
import type { FaceSearchResult, PersonAppearance, VoiceGeneration, VoiceSettings } from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  ArrowLeft, User, Pencil, Merge, Film, Mic, MessageSquareQuote, Scissors,
  AudioWaveform, Upload, Trash2, Loader2, Play, Download, Plus, Sparkles,
  SlidersHorizontal, ChevronDown, ChevronUp, Eye, Undo2, Check, Search,
  RefreshCw, Globe, ScanSearch, ExternalLink, AlertTriangle,
  LayoutGrid, List, ChevronLeft, ChevronRight, Clapperboard,
  Settings2, MoreHorizontal, Maximize2,
  X
} from "lucide-react";
import { useLocation } from "wouter";

const XTTS_LANGUAGES: { code: string; label: string }[] = [
  { code: "en", label: "English" },
  { code: "es", label: "Spanish" },
  { code: "fr", label: "French" },
  { code: "de", label: "German" },
  { code: "it", label: "Italian" },
  { code: "pt", label: "Portuguese" },
  { code: "pl", label: "Polish" },
  { code: "tr", label: "Turkish" },
  { code: "ru", label: "Russian" },
  { code: "nl", label: "Dutch" },
  { code: "cs", label: "Czech" },
  { code: "ar", label: "Arabic" },
  { code: "zh-cn", label: "Chinese" },
  { code: "ja", label: "Japanese" },
  { code: "hu", label: "Hungarian" },
  { code: "ko", label: "Korean" },
  { code: "hi", label: "Hindi" },
];

function faceSearchActive(fs?: FaceSearchResult | null): boolean {
  if (fs?.status !== "pending") return false;
  if (!fs.queued_at) return true;
  return Date.now() - Date.parse(fs.queued_at) <= 10 * 60 * 1000;
}

function parseTimecode(v: string): number | null {
  const t = v.trim();
  if (!t) return null;
  if (/^\d+(\.\d+)?$/.test(t)) return parseFloat(t);
  const parts = t.split(":").map((p) => p.trim());
  if (parts.some((p) => p === "" || !/^\d+(\.\d+)?$/.test(p))) return null;
  const nums = parts.map(parseFloat);
  if (nums.length === 2) return nums[0] * 60 + nums[1];
  if (nums.length === 3) return nums[0] * 3600 + nums[1] * 60 + nums[2];
  return null;
}

function formatTimecode(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);
  if (h > 0) return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

const PRESET_LABELS: Record<string, string> = {
  natural: "Natural",
  expressive: "Expressive",
  steady: "Steady",
  warm: "Warm",
};

const DEFAULT_TUNE = { speed: 1.0, temperature: 0.65, top_p: 0.85, repetition_penalty: 2.0 };

const TUNE_SLIDERS: {
  key: keyof typeof DEFAULT_TUNE;
  label: string;
  hint: string;
  min: number;
  max: number;
  step: number;
}[] = [
  { key: "speed", label: "Speed", hint: "pace of delivery", min: 0.7, max: 1.3, step: 0.05 },
  { key: "temperature", label: "Expressiveness", hint: "higher = livelier, less stable", min: 0.2, max: 1.2, step: 0.05 },
  { key: "top_p", label: "Stability", hint: "lower = safer, flatter", min: 0.3, max: 1.0, step: 0.05 },
  { key: "repetition_penalty", label: "Clarity", hint: "higher = crisper, can clip words", min: 1.5, max: 12, step: 0.5 },
];

function VoiceSection({
  personId,
  personName,
  appearances,
  voicePreset,
  voiceSettings,
}: {
  personId: string;
  personName: string;
  appearances: PersonAppearance[];
  voicePreset: string | null | undefined;
  voiceSettings: VoiceSettings | null | undefined;
}) {
  const queryClient = useQueryClient();
  const { data: profile } = useGetVoiceProfile(personId, {
    query: {
      queryKey: getGetVoiceProfileQueryKey(personId),
      enabled: !!personId,
      refetchInterval: (q) =>
        q.state.data?.samples?.some((s) => s.status === "pending") ? 2500 : false,
    },
  });
  const { data: generations } = useListVoiceGenerations(personId, {
    query: {
      queryKey: getListVoiceGenerationsQueryKey(personId),
      enabled: !!personId,
      refetchInterval: (q) =>
        q.state.data?.some((g) =>
          g.status === "pending" || g.status === "running" ||
          g.video_status === "pending" || g.video_status === "running") ? 2000 : false,
    },
  });

  const addSample = useAddVoiceSample();
  const uploadSample = useUploadVoiceSample();
  const deleteSample = useDeleteVoiceSample();
  const createGen = useCreateVoiceGeneration();
  const deleteGen = useDeleteVoiceGeneration();
  const lipsync = useCreateLipsyncVideo();
  const uploadRef = useUploadLipsyncReference();
  const deleteRef = useDeleteLipsyncReference();
  const tuneVoice = useTuneVoice();
  const setPreset = useSetVoicePreset();
  const saveSettings = useSetVoiceSettings();

  const invalidateProfile = () =>
    queryClient.invalidateQueries({ queryKey: getGetVoiceProfileQueryKey(personId) });
  const invalidateGens = () =>
    queryClient.invalidateQueries({ queryKey: getListVoiceGenerationsQueryKey(personId) });

  const [addOpen, setAddOpen] = useState(false);
  const [sampleMedia, setSampleMedia] = useState("");
  const [sampleStart, setSampleStart] = useState("");
  const [sampleEnd, setSampleEnd] = useState("");
  const [rangeError, setRangeError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const refVideoInputRef = useRef<HTMLInputElement>(null);

  const handleReferenceUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    uploadRef.mutate({ id: personId, data: { file } }, { onSuccess: invalidateProfile });
    e.target.value = "";
  };

  const [genText, setGenText] = useState("");
  const [genLang, setGenLang] = useState("en");
  const [genSpeed, setGenSpeed] = useState(1.0);
  const [genTarget, setGenTarget] = useState("");
  const [tuneOpen, setTuneOpen] = useState(false);
  const [tune, setTune] = useState<typeof DEFAULT_TUNE>({
    ...DEFAULT_TUNE,
    ...(voiceSettings
      ? Object.fromEntries(Object.entries(voiceSettings).filter(([, v]) => typeof v === "number"))
      : {}),
  });

  const speakingAppearances = appearances.filter((a) => a.speaker_label);

  const submitSample = () => {
    setRangeError(null);
    const start = parseTimecode(sampleStart);
    const end = parseTimecode(sampleEnd);
    if (!sampleMedia || start == null || end == null) {
      setRangeError("Enter start and end as seconds or hh:mm:ss.");
      return;
    }
    if (end <= start) { setRangeError("End must be after start."); return; }
    if (end - start > 60) { setRangeError("Keep samples under 60 seconds."); return; }
    addSample.mutate(
      { id: personId, data: { media_id: sampleMedia, start_time: start, end_time: end } },
      {
        onSuccess: () => {
          setAddOpen(false);
          setSampleStart("");
          setSampleEnd("");
          invalidateProfile();
        },
        onError: () => setRangeError("Could not add the sample — check the time range."),
      },
    );
  };

  const handleUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    uploadSample.mutate(
      { id: personId, data: { file } },
      { onSuccess: invalidateProfile },
    );
    e.target.value = "";
  };

  const tuneChanged = TUNE_SLIDERS.some((s) => tune[s.key] !== DEFAULT_TUNE[s.key]);

  const submitGeneration = () => {
    if (!genText.trim()) return;
    const target = parseFloat(genTarget);
    createGen.mutate(
      {
        id: personId,
        data: {
          text: genText.trim(),
          language: genLang,
          ...(tuneOpen && tuneChanged ? { settings: tune } : {}),
          ...(genSpeed !== 1.0 ? { speed: genSpeed } : {}),
          ...(Number.isFinite(target) && target >= 1 ? { target_seconds: target } : {}),
        },
      },
      { onSuccess: () => { setGenText(""); invalidateGens(); } },
    );
  };

  const saveTuneAsDefault = () => {
    saveSettings.mutate(
      { id: personId, data: tuneChanged ? tune : {} },
      {
        onSuccess: () =>
          queryClient.invalidateQueries({ queryKey: getGetPersonQueryKey(personId) }),
      },
    );
  };

  const submitTune = () => {
    const text = genText.trim();
    if (!text) return;
    tuneVoice.mutate(
      { id: personId, data: { text: text.slice(0, 400), language: genLang } },
      { onSuccess: () => { setGenText(""); invalidateGens(); } },
    );
  };

  const choosePreset = (preset: string) => {
    setPreset.mutate(
      { id: personId, data: { preset } },
      {
        onSuccess: () =>
          queryClient.invalidateQueries({ queryKey: getGetPersonQueryKey(personId) }),
      },
    );
  };

  const readySeconds = profile?.total_sample_seconds ?? 0;
  const minSeconds = profile?.min_sample_seconds ?? 10;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/5 pb-4">
        <h2 className="text-xl font-medium flex items-center gap-3 text-foreground tracking-tight">
          <AudioWaveform className="h-5 w-5 text-primary" /> Voice Studio
        </h2>
        <div className="flex items-center gap-2">
          {voiceSettings ? (
            <Badge className="bg-background text-primary border-primary/30 font-mono text-[10px]">
              STYLE: CUSTOM
            </Badge>
          ) : voicePreset ? (
            <Badge className="bg-background text-primary border-primary/30 font-mono text-[10px] uppercase">
              STYLE: {PRESET_LABELS[voicePreset] ?? voicePreset}
            </Badge>
          ) : null}
          {profile?.ready ? (
            <Badge className="bg-primary/20 text-primary border-primary/40 font-mono text-[10px]">READY</Badge>
          ) : (
            <Badge variant="outline" className="font-mono text-[10px] bg-background">
              {Math.round(readySeconds)}s / {minSeconds}s CLEAN AUDIO
            </Badge>
          )}
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-2 items-start">
        {/* Synthesis & Tuning Panel */}
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground tracking-tight">
             <Sparkles className="h-4 w-4 text-primary/70" /> Synthesis Generator
          </div>
          
          <div className="bg-card/40 border border-white/5 rounded-xl p-5 space-y-5">
            {profile?.ready ? (
              <>
                <div className="space-y-3 relative">
                  <div className="flex items-center justify-between">
                    <Label className="text-xs text-muted-foreground uppercase tracking-wider font-mono">Script</Label>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-6 px-2 gap-1.5 text-[10px] text-muted-foreground hover:text-primary transition-colors"
                      onClick={() => setTuneOpen((v) => !v)}
                    >
                      <Settings2 className="h-3 w-3" /> {tuneOpen ? "Hide Settings" : "Tuning Settings"}
                    </Button>
                  </div>
                  
                  <Textarea
                    rows={4}
                    value={genText}
                    onChange={(e) => setGenText(e.target.value)}
                    placeholder={`Type anything — hear it in ${personName}'s voice...`}
                    maxLength={2000}
                    className="resize-none bg-background/50 border-white/10 focus-visible:ring-primary/50 text-sm leading-relaxed"
                  />
                </div>

                {tuneOpen && (
                  <div className="rounded-lg border border-white/5 bg-background/50 p-4 space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                      {TUNE_SLIDERS.map((s) => (
                        <div key={s.key} className="space-y-2">
                          <div className="flex items-center justify-between text-[10px] font-mono">
                            <span className="text-muted-foreground uppercase">{s.label}</span>
                            <span className="text-primary">{tune[s.key].toFixed(2)}</span>
                          </div>
                          <Slider
                            min={s.min}
                            max={s.max}
                            step={s.step}
                            value={[tune[s.key]]}
                            onValueChange={([v]) => setTune((t) => ({ ...t, [s.key]: v }))}
                            className="[&_[role=slider]]:h-3 [&_[role=slider]]:w-3"
                          />
                        </div>
                      ))}
                    </div>
                    <div className="flex items-center gap-2 pt-2 border-t border-white/5">
                      <p className="text-[10px] text-muted-foreground flex-1 font-mono">
                        Generate to preview these settings.
                      </p>
                      <Button size="sm" variant="ghost" className="h-6 text-[10px] uppercase font-mono px-2"
                        onClick={() => setTune({ ...DEFAULT_TUNE })}>
                        Reset
                      </Button>
                      <Button size="sm" variant="outline" className="h-6 text-[10px] uppercase font-mono px-2 border-white/10 bg-card"
                        disabled={saveSettings.isPending}
                        onClick={saveTuneAsDefault}>
                        {saveSettings.isPending ? "Saving…" : "Set Default"}
                      </Button>
                    </div>
                  </div>
                )}

                <div className="flex items-center gap-4 flex-wrap bg-background/30 p-2 rounded-lg border border-white/5">
                  <div className="flex items-center gap-3 min-w-[200px] flex-1 px-2">
                    <span className="text-[10px] uppercase font-mono text-muted-foreground shrink-0">Speed</span>
                    <Slider
                      min={0.5}
                      max={2.0}
                      step={0.05}
                      value={[genSpeed]}
                      onValueChange={([v]) => setGenSpeed(v)}
                      className="flex-1 [&_[role=slider]]:h-3 [&_[role=slider]]:w-3"
                    />
                    <span className="text-[10px] font-mono w-8 text-right text-primary">{genSpeed.toFixed(2)}x</span>
                  </div>
                  <div className="w-px h-6 bg-white/10" />
                  <div className="flex items-center gap-2 pr-2">
                    <span className="text-[10px] uppercase font-mono text-muted-foreground shrink-0" title="Time-stretches audio to exact runtime">Match Secs</span>
                    <Input
                      type="number"
                      min={1}
                      max={3600}
                      step="any"
                      value={genTarget}
                      onChange={(e) => setGenTarget(e.target.value)}
                      placeholder="0.0"
                      className="w-16 h-7 text-xs bg-background/50 border-white/10 px-2"
                    />
                  </div>
                </div>

                <div className="flex items-center gap-2 pt-2">
                  <Select value={genLang} onValueChange={setGenLang}>
                    <SelectTrigger className="w-32 h-9 bg-background/50 border-white/10 text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {XTTS_LANGUAGES.map((l) => (
                        <SelectItem key={l.code} value={l.code} className="text-xs">{l.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button variant="outline" className="ml-auto gap-2 h-9 text-xs border-white/10 bg-card hover:bg-card/80 hover:text-primary transition-colors" onClick={submitTune}
                    disabled={!genText.trim() || tuneVoice.isPending}
                    title="Generate the same line in 4 synthesis styles">
                    {tuneVoice.isPending
                      ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Queuing...</>
                      : <><Sparkles className="h-3.5 w-3.5" /> Compare Styles</>}
                  </Button>
                  <Button className="gap-2 h-9 text-xs bg-primary text-primary-foreground hover:bg-primary/90" onClick={submitGeneration}
                    disabled={!genText.trim() || createGen.isPending}>
                    {createGen.isPending
                      ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Queuing...</>
                      : <><Play className="h-3.5 w-3.5 fill-current" /> Generate</>}
                  </Button>
                </div>
                {(createGen.isError || tuneVoice.isError) && (
                  <p className="text-xs text-destructive flex items-center gap-1.5 mt-2 bg-destructive/10 p-2 rounded-md border border-destructive/20"><AlertTriangle className="h-3.5 w-3.5" /> Generation failed to start.</p>
                )}
              </>
            ) : (
              <div className="flex flex-col items-center justify-center py-10 text-center space-y-3">
                <div className="h-12 w-12 rounded-full bg-background border border-white/10 flex items-center justify-center">
                  <Mic className="h-5 w-5 text-muted-foreground/50" />
                </div>
                <div>
                  <p className="text-sm font-medium text-foreground">Synthesis Locked</p>
                  <p className="text-xs text-muted-foreground mt-1 max-w-[250px] mx-auto">
                    Add {Math.max(0, Math.ceil(minSeconds - readySeconds))} more seconds of clean audio samples to unlock cloning.
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* Generations List */}
          {generations?.length ? (
            <div className="space-y-2 mt-4">
              <div className="flex items-center justify-between px-1">
                <span className="text-[10px] uppercase font-mono text-muted-foreground">Recent Generations</span>
              </div>
              <div className="space-y-2 max-h-[400px] overflow-y-auto pr-2 custom-scrollbar">
                {generations.map((g: VoiceGeneration) => (
                  <div key={g.id} className="bg-card/40 border border-white/5 rounded-lg p-3 space-y-3 group hover:border-primary/20 transition-colors">
                    <div className="flex items-start justify-between gap-4">
                      <p className="flex-1 text-sm leading-relaxed text-foreground/90 italic line-clamp-2" title={g.text}>"{g.text}"</p>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-6 w-6 text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100 transition-opacity -mt-1 -mr-1"
                        onClick={() => deleteGen.mutate({ id: g.id }, { onSuccess: invalidateGens })}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                    
                    <div className="flex items-center gap-2 bg-background/50 rounded-md p-1.5 border border-white/5">
                      {g.status === "success" ? (
                        <>
                          <audio controls preload="none" src={`/api/voice/generations/${g.id}/audio`} className="h-8 flex-1 min-w-[150px] hue-rotate-[180deg] invert sepia saturate-200" />
                          <div className="flex flex-col gap-1 items-end pr-1 shrink-0">
                            <div className="flex items-center gap-1.5">
                              <Badge variant="outline" className="text-[9px] h-4 px-1 rounded-sm bg-background">
                                {XTTS_LANGUAGES.find((l) => l.code === g.language)?.label ?? g.language}
                              </Badge>
                              {g.preset && (
                                <Badge className="bg-primary/10 text-primary border-primary/20 text-[9px] h-4 px-1 rounded-sm uppercase">
                                  {PRESET_LABELS[g.preset] ?? g.preset}
                                </Badge>
                              )}
                            </div>
                            <div className="flex items-center gap-1">
                              {g.preset && g.preset !== voicePreset && (
                                <Button size="sm" variant="ghost" className="h-5 text-[9px] px-1.5 text-primary hover:bg-primary/10 transition-colors"
                                  disabled={setPreset.isPending}
                                  onClick={() => choosePreset(g.preset!)}>
                                  Set Style
                                </Button>
                              )}
                              <a href={`/api/voice/generations/${g.id}/audio`} download>
                                <Button size="icon" variant="ghost" className="h-5 w-5 text-muted-foreground hover:text-foreground"><Download className="h-3 w-3" /></Button>
                              </a>
                            </div>
                          </div>
                        </>
                      ) : g.status === "error" ? (
                        <p className="text-xs text-destructive flex-1 py-1 px-2">{g.error_message || "Generation failed"}</p>
                      ) : (
                        <div className="flex items-center gap-2 py-1 px-2 flex-1">
                          <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                          <p className="text-xs text-muted-foreground">Synthesizing audio...</p>
                        </div>
                      )}
                    </div>

                    {g.status === "success" && (
                      <div className="flex items-center justify-between pt-1">
                         {!g.video_status || g.video_status === "error" ? (
                          <Button size="sm" variant="outline" className="h-7 text-[10px] uppercase font-mono px-3 border-white/10 bg-card/50 hover:bg-card hover:text-primary transition-colors gap-1.5"
                            disabled={lipsync.isPending}
                            title="Render a lipsynced video of this person speaking this audio"
                            onClick={() => lipsync.mutate({ id: g.id }, { onSuccess: invalidateGens })}>
                            <Clapperboard className="h-3 w-3" /> {lipsync.isPending ? "Queuing..." : "Render Lipsync Video"}
                          </Button>
                        ) : g.video_status === "success" ? (
                          <div className="flex items-center gap-2 w-full">
                            <Badge className="bg-green-500/10 text-green-400 border-green-500/20 text-[9px] uppercase">Video Ready</Badge>
                            <a href={`/api/voice/generations/${g.id}/video`} download className="ml-auto">
                              <Button size="sm" variant="secondary" className="h-7 text-[10px] uppercase font-mono px-3 gap-1.5">
                                <Download className="h-3 w-3" /> Download Video
                              </Button>
                            </a>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2 px-2">
                            <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                            <span className="text-[10px] uppercase font-mono text-muted-foreground">Rendering video...</span>
                          </div>
                        )}
                        {g.video_status === "error" && (
                          <span className="text-[10px] text-destructive flex items-center gap-1"><AlertTriangle className="h-3 w-3" /> Render failed</span>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>

        {/* Source Material & Lipsync Panel */}
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground tracking-tight">
             <Clapperboard className="h-4 w-4 text-primary/70" /> Source & Lipsync
          </div>
          
          <div className="bg-card/40 border border-white/5 rounded-xl p-5 space-y-6">
            
            {/* Lipsync Reference */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <Label className="text-xs text-muted-foreground uppercase tracking-wider font-mono">Lipsync Reference Video</Label>
              </div>
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-background/50 border border-white/5 rounded-lg p-3">
                <div className="flex items-center gap-3">
                  <div className={`h-8 w-8 rounded-md flex items-center justify-center border ${profile?.has_lipsync_reference ? 'bg-primary/10 border-primary/30' : 'bg-card border-white/10'}`}>
                    <Maximize2 className={`h-4 w-4 ${profile?.has_lipsync_reference ? 'text-primary' : 'text-muted-foreground/50'}`} />
                  </div>
                  <div className="flex flex-col">
                    <span className="text-xs font-medium text-foreground">
                      {profile?.has_lipsync_reference ? "Custom reference active" : "Library footage fallback"}
                    </span>
                    <span className="text-[10px] text-muted-foreground">
                      {profile?.has_lipsync_reference ? "Using uploaded front-facing video" : "No custom video provided"}
                    </span>
                  </div>
                </div>
                
                <div className="flex items-center gap-2 shrink-0">
                  <input
                    ref={refVideoInputRef}
                    type="file"
                    accept=".mp4,.mov,.m4v,.webm,.mkv,video/*"
                    className="hidden"
                    onChange={handleReferenceUpload}
                  />
                  {profile?.has_lipsync_reference && (
                    <>
                      <a href={`/api/people/${personId}/lipsync/reference`} target="_blank" rel="noreferrer">
                        <Button size="icon" variant="ghost" className="h-7 w-7 text-muted-foreground hover:text-primary transition-colors"><Eye className="h-3.5 w-3.5" /></Button>
                      </a>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7 text-muted-foreground hover:text-destructive transition-colors"
                        disabled={deleteRef.isPending}
                        onClick={() => deleteRef.mutate({ id: personId }, { onSuccess: invalidateProfile })}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 text-[10px] uppercase font-mono px-3 gap-1.5 border-white/10 bg-card hover:bg-card/80"
                    disabled={uploadRef.isPending}
                    onClick={() => refVideoInputRef.current?.click()}
                  >
                    {uploadRef.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Upload className="h-3 w-3" />}
                    {profile?.has_lipsync_reference ? "Replace" : "Upload"}
                  </Button>
                </div>
              </div>
              {uploadRef.isError && (
                <p className="text-[10px] text-destructive mt-1 px-1">Upload failed — use mp4/mov (max 500MB).</p>
              )}
            </div>

            {/* Clean Samples */}
            <div className="space-y-3 pt-3 border-t border-white/5">
              <div className="flex items-center justify-between">
                <Label className="text-xs text-muted-foreground uppercase tracking-wider font-mono">Clean Audio Samples</Label>
                <div className="flex gap-2">
                  <Dialog open={addOpen} onOpenChange={setAddOpen}>
                    <DialogTrigger asChild>
                      <Button size="sm" variant="ghost" className="h-6 px-2 gap-1.5 text-[10px] uppercase font-mono text-muted-foreground hover:text-primary transition-colors" disabled={!speakingAppearances.length}>
                        <Scissors className="h-3 w-3" /> From Footage
                      </Button>
                    </DialogTrigger>
                    <DialogContent className="overflow-hidden bg-card/95 backdrop-blur-xl border-white/10">
                      <DialogHeader>
                         <DialogTitle className="text-lg">Extract Voice Sample</DialogTitle>
                      </DialogHeader>
                      <div className="space-y-4 pt-2">
                        <p className="text-sm text-muted-foreground">
                          Pick a stretch where only {personName} speaks — no music, no crosstalk. 10–30 seconds is ideal.
                        </p>
                        <div className="space-y-2 min-w-0">
                          <Label className="text-xs text-muted-foreground uppercase tracking-wider font-mono">Source Asset</Label>
                          <Select value={sampleMedia} onValueChange={setSampleMedia}>
                            <SelectTrigger className="bg-background/50 border-white/10">
                              <SelectValue placeholder="Choose an asset they speak in" />
                            </SelectTrigger>
                            <SelectContent>
                              {speakingAppearances.map((a) => (
                                <SelectItem key={a.media_id} value={a.media_id} className="text-xs">
                                  {a.filename} {a.first_spoken_at != null ? `(speaks @ ${formatTimecode(a.first_spoken_at)})` : ""}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="grid grid-cols-2 gap-4">
                          <div className="space-y-2">
                            <Label className="text-xs text-muted-foreground uppercase tracking-wider font-mono">Start Time</Label>
                            <Input value={sampleStart} onChange={(e) => setSampleStart(e.target.value)} placeholder="e.g. 2:05 or 125" className="bg-background/50 border-white/10" />
                          </div>
                          <div className="space-y-2">
                            <Label className="text-xs text-muted-foreground uppercase tracking-wider font-mono">End Time</Label>
                            <Input value={sampleEnd} onChange={(e) => setSampleEnd(e.target.value)} placeholder="e.g. 2:28 or 148" className="bg-background/50 border-white/10" />
                          </div>
                        </div>
                        {rangeError && <p className="text-[10px] text-destructive">{rangeError}</p>}
                      </div>
                      <DialogFooter className="border-t border-white/10 pt-4 mt-4">
                        <Button variant="ghost" onClick={() => setAddOpen(false)} className="text-xs">Cancel</Button>
                        <Button onClick={submitSample} disabled={addSample.isPending} className="text-xs">
                          {addSample.isPending ? "Extracting..." : "Extract Sample"}
                        </Button>
                      </DialogFooter>
                    </DialogContent>
                  </Dialog>
                  
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".wav,.mp3,.m4a,.flac,.ogg,audio/*"
                    className="hidden"
                    onChange={handleUpload}
                  />
                  <Button size="sm" variant="ghost" className="h-6 px-2 gap-1.5 text-[10px] uppercase font-mono text-muted-foreground hover:text-primary transition-colors"
                    onClick={() => fileInputRef.current?.click()} disabled={uploadSample.isPending}>
                    {uploadSample.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Upload className="h-3 w-3" />}
                    Upload File
                  </Button>
                </div>
              </div>

              {uploadSample.isError && (
                <p className="text-[10px] text-destructive px-1">
                  Upload failed — {(uploadSample.error as { data?: { detail?: string } } | null)?.data?.detail ?? "use wav, mp3, m4a, flac, or ogg."}
                </p>
              )}
              
              <div className="space-y-2">
                {profile?.samples?.length ? (
                  profile.samples.map((s) => (
                    <div key={s.id} className="flex items-center gap-3 bg-background/50 border border-white/5 rounded-lg p-2 group transition-colors hover:bg-background/80">
                      <div className="flex-1 min-w-0 flex flex-col justify-center">
                        <p className="text-xs font-medium text-foreground truncate flex items-center gap-1.5">
                          {s.source === "upload" ? <Upload className="h-3 w-3 text-primary/70" /> : <Scissors className="h-3 w-3 text-primary/70" />}
                          {s.filename || (s.source === "upload" ? "Uploaded audio" : "Extracted clip")}
                        </p>
                        <div className="flex items-center gap-2 mt-0.5">
                          {s.status === "ready" ? (
                            <span className="text-[10px] font-mono text-primary">{(s.duration_seconds ?? 0).toFixed(1)}s</span>
                          ) : s.status === "error" ? (
                            <span className="text-[10px] font-mono text-destructive">Failed</span>
                          ) : (
                            <span className="text-[10px] font-mono text-muted-foreground">Processing...</span>
                          )}
                          {s.start_time != null && s.end_time != null && (
                             <span className="text-[9px] text-muted-foreground">({formatTimecode(s.start_time)} – {formatTimecode(s.end_time)})</span>
                          )}
                        </div>
                      </div>
                      
                      {s.status === "pending" && <Loader2 className="h-4 w-4 animate-spin text-primary shrink-0 mr-2" />}
                      {s.status === "error" && (
                        <div title={s.error_message || "Error"}>
                          <AlertTriangle className="h-4 w-4 text-destructive shrink-0 mr-2" />
                        </div>
                      )}
                      {s.status === "ready" && (
                        <audio controls preload="none" src={`/api/voice/samples/${s.id}/audio`} className="h-6 w-32 shrink-0 hue-rotate-[180deg] invert sepia saturate-200 opacity-60 group-hover:opacity-100 transition-opacity" />
                      )}
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-6 w-6 text-muted-foreground hover:text-destructive shrink-0 transition-colors opacity-0 group-hover:opacity-100"
                        onClick={() => deleteSample.mutate({ id: s.id }, { onSuccess: invalidateProfile })}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ))
                ) : (
                  <div className="py-6 text-center border border-dashed border-white/10 rounded-lg bg-background/20">
                    <p className="text-xs text-muted-foreground">No audio samples yet.</p>
                  </div>
                )}
              </div>
            </div>
            
          </div>
        </div>
      </div>
    </div>
  );
}

export default function PersonDetail() {
  const [, params] = useRoute("/people/:id");
  const [, setLocation] = useLocation();
  const id = params?.id;

  const queryClient = useQueryClient();
  const { data: person, isLoading, error } = useGetPerson(id!, {
    query: {
      queryKey: getGetPersonQueryKey(id!),
      enabled: !!id,
    },
  });

  const { data: peopleList } = useListPeople({ limit: 100 }, { query: { enabled: !!id, queryKey: getListPeopleQueryKey({ limit: 100 }) } });

  const updatePerson = useUpdatePerson();
  const mergePerson = useMergePerson();
  const splitPerson = useSplitPerson();
  const unmergePerson = useUnmergePerson();
  const reprofile = useReprofilePerson();
  const faceSearch = useFaceSearchPerson();
  const updatePhoto = useUpdatePersonPhoto();
  const deletePhoto = useDeletePersonPhoto();

  const invalidatePerson = () => {
    queryClient.invalidateQueries({ queryKey: getGetPersonQueryKey(id!) });
    queryClient.invalidateQueries({ queryKey: getListPeopleQueryKey() });
  };

  const [editName, setEditName] = useState("");
  const [editing, setEditing] = useState(false);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [mergeTarget, setMergeTarget] = useState("");

  const startEdit = () => {
    if (!person) return;
    setEditName(
      person.display_name.startsWith("Person ") || person.display_name.startsWith("SPEAKER_")
        ? ""
        : person.display_name,
    );
    setEditing(true);
  };

  const saveEdit = () => {
    const name = editName.trim();
    if (!name || !id || updatePerson.isPending) return;
    updatePerson.mutate(
      { id, data: { display_name: name } },
      {
        onSuccess: () => {
          setEditing(false);
          invalidatePerson();
        },
      },
    );
  };

  const executeMerge = () => {
    if (!id || !mergeTarget) return;
    mergePerson.mutate(
      { id: mergeTarget, data: { source_person_id: id } },
      {
        onSuccess: () => {
          setMergeOpen(false);
          queryClient.invalidateQueries({ queryKey: getListPeopleQueryKey() });
          setLocation(`/people/${mergeTarget}`);
        },
      },
    );
  };

  const handleUnmerge = (app: PersonAppearance) => {
    if (!id || unmergePerson.isPending || !app.merged_from) return;
    if (!window.confirm(`Remove all appearances originally from "${app.merged_from.display_name}"? They will be restored as a separate profile.`)) return;
    unmergePerson.mutate({ id, data: { merged_from_person_id: app.merged_from.person_id } }, { onSuccess: invalidatePerson });
  };

  const handleSplit = (app: PersonAppearance) => {
    if (!id || splitPerson.isPending) return;
    if (!window.confirm(`Split this specific appearance in "${app.filename}" into a new profile?`)) return;
    splitPerson.mutate({ id, data: { media_id: app.media_id, speaker_label: app.speaker_label, face_cluster_id: app.face_cluster_id } }, { onSuccess: invalidatePerson });
  };

  const handleReprofile = () => {
    if (!id || reprofile.isPending) return;
    reprofile.mutate(
      { id },
      {
        onSuccess: () => {
          alert("Reprofiling queued. Face and voice processing will run in the background.");
          invalidatePerson();
        },
      },
    );
  };

  const handleFaceSearch = () => {
    if (!id || faceSearch.isPending) return;
    faceSearch.mutate({ id }, { onSuccess: invalidatePerson });
  };

  const fileInputRef = useRef<HTMLInputElement>(null);
  const handlePhotoUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !id) return;
    updatePhoto.mutate({ id, data: { photo: file } }, { onSuccess: invalidatePerson });
    e.target.value = "";
  };

  useEffect(() => {
    if (person?.face_search && person.face_search.status === "pending") {
      const interval = setInterval(invalidatePerson, 3000);
      return () => clearInterval(interval);
    }
    return undefined;
  }, [person?.face_search?.status, invalidatePerson]);

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-primary/50" />
      </div>
    );
  }

  if (error || !person) {
    return (
      <div className="flex-1 flex items-center justify-center flex-col bg-background">
        <div className="h-16 w-16 rounded-2xl bg-card border border-white/5 flex items-center justify-center mb-4">
          <AlertTriangle className="h-6 w-6 text-destructive/70" />
        </div>
        <h2 className="text-lg font-medium text-foreground">Person not found</h2>
        <p className="text-muted-foreground text-sm mt-1">This profile may have been deleted or merged.</p>
        <Link href="/people" className="mt-6 text-primary hover:underline text-sm font-medium">
          Back to Directory
        </Link>
      </div>
    );
  }

  const appearances = person.appearances || [];
  const speakingAppearances = appearances.filter((a) => a.speaker_label);
  const visualAppearances = appearances.filter((a) => a.face_cluster_id);
  const isUnnamed = person.name_source !== "manual" && (person.display_name.startsWith("Person ") || person.display_name.startsWith("SPEAKER_"));
  const fsActive = faceSearchActive(person.face_search);

  return (
    <div className="flex-1 overflow-y-auto flex flex-col bg-background">
      {/* Sticky Header */}
      <div className="sticky top-0 z-50 border-b border-white/5 bg-background/80 backdrop-blur-xl px-6 py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <Link href="/people">
            <Button size="icon" variant="ghost" className="h-8 w-8 rounded-md text-muted-foreground hover:text-foreground bg-card/30 border border-white/5">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div className="flex items-center gap-2">
            <h1 className="text-sm font-medium text-foreground tracking-tight">{person.display_name}</h1>
            {isUnnamed && <div className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse ml-1" title="Unnamed" />}
          </div>
        </div>
        
        <div className="flex items-center gap-2 self-end sm:self-auto">
          <Dialog open={mergeOpen} onOpenChange={setMergeOpen}>
            <DialogTrigger asChild>
              <Button size="sm" variant="outline" className="h-8 text-xs bg-card/30 border-white/5 hover:bg-card gap-1.5">
                <Merge className="h-3.5 w-3.5" /> Merge Profile
              </Button>
            </DialogTrigger>
            <DialogContent className="bg-card/95 backdrop-blur-xl border-white/10">
              <DialogHeader>
                <DialogTitle className="text-lg">Merge {person.display_name} into another profile</DialogTitle>
              </DialogHeader>
              <div className="space-y-4 pt-2">
                <p className="text-sm text-muted-foreground">
                  This will move all appearances, assets, and voice data to the target profile and delete this one.
                </p>
                <div className="space-y-2 min-w-0">
                  <Label className="text-xs text-muted-foreground uppercase tracking-wider font-mono">Target Profile</Label>
                  <Select value={mergeTarget} onValueChange={setMergeTarget}>
                    <SelectTrigger className="bg-background/50 border-white/10">
                      <SelectValue placeholder="Select target person..." />
                    </SelectTrigger>
                    <SelectContent>
                      {peopleList?.items
                        ?.filter((p) => p.id !== id)
                        .map((p) => (
                          <SelectItem key={p.id} value={p.id} className="text-xs">
                            {p.display_name}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <DialogFooter className="mt-6 border-t border-white/10 pt-4">
                <Button variant="ghost" onClick={() => setMergeOpen(false)} className="text-xs">Cancel</Button>
                <Button onClick={executeMerge} disabled={!mergeTarget || mergePerson.isPending} variant="destructive" className="text-xs">
                  {mergePerson.isPending ? "Merging..." : "Confirm Merge"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <Button
            size="sm"
            variant="outline"
            className="h-8 text-xs bg-card/30 border-white/5 hover:bg-card gap-1.5"
            onClick={handleReprofile}
            disabled={reprofile.isPending}
            title="Re-run face clustering and voice profiling using current assets"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${reprofile.isPending ? "animate-spin" : ""}`} />
            {reprofile.isPending ? "Reprofiling..." : "Reprofile"}
          </Button>
        </div>
      </div>

      <div className="flex-1 p-6 w-full max-w-[1600px] mx-auto">
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-8 items-start">
          
          {/* LEFT COLUMN: Identity & Data (Wider on XL for balance) */}
          <div className="xl:col-span-4 space-y-6">
            
            {/* Identity Card */}
            <div className="bg-card/40 border border-white/5 rounded-2xl overflow-hidden relative">
              {/* Cover background */}
              <div className="absolute inset-x-0 top-0 h-24 overflow-hidden pointer-events-none opacity-40">
                {person.thumbnail_url ? (
                  <img src={`/api/thumbnails/${person.thumbnail_url}`} className="w-full h-full object-cover blur-md scale-110 saturate-50" />
                ) : (
                  <div className="w-full h-full bg-gradient-to-br from-primary/20 to-background" />
                )}
                <div className="absolute inset-0 bg-gradient-to-t from-card/40 to-transparent" />
              </div>
              
              <div className="relative pt-12 px-6 pb-6 flex flex-col items-center text-center space-y-4">
                <div className="relative group">
                  <div className="h-24 w-24 rounded-2xl overflow-hidden border-4 border-card/40 shadow-xl bg-background relative z-10">
                    {person.thumbnail_url ? (
                      <img src={`/api/thumbnails/${person.thumbnail_url}`} className="w-full h-full object-cover" />
                    ) : (
                      <User className="h-10 w-10 text-muted-foreground/30 m-auto mt-6" />
                    )}
                  </div>
                  
                  {/* Photo Edit actions on hover */}
                  <div className="absolute inset-0 z-20 flex items-center justify-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity bg-background/60 backdrop-blur-sm rounded-xl m-1">
                    <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handlePhotoUpload} />
                    <Button size="icon" variant="ghost" className="h-8 w-8 text-foreground hover:text-primary bg-card/80 border border-white/10" title="Upload Photo" onClick={() => fileInputRef.current?.click()} disabled={updatePhoto.isPending}>
                      {updatePhoto.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                    </Button>
                    {person.thumbnail_url && (
                      <Button size="icon" variant="ghost" className="h-8 w-8 text-foreground hover:text-destructive bg-card/80 border border-white/10" title="Remove Photo" onClick={() => deletePhoto.mutate({ id: id! }, { onSuccess: invalidatePerson })} disabled={deletePhoto.isPending}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    )}
                  </div>
                </div>
                
                <div className="space-y-1 w-full flex flex-col items-center">
                  {editing ? (
                    <div className="flex items-center gap-1 max-w-[280px] bg-background p-1 rounded-md border border-primary/40 shadow-sm w-full">
                      <Input
                        autoFocus
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") saveEdit();
                          if (e.key === "Escape") setEditing(false);
                        }}
                        placeholder="Enter name..."
                        className="h-8 text-sm px-2 bg-transparent border-0 focus-visible:ring-0 text-center"
                      />
                      <Button size="icon" variant="ghost" className="h-8 w-8 shrink-0 text-primary hover:bg-primary/20" onClick={saveEdit} disabled={!editName.trim() || updatePerson.isPending}><Check className="h-4 w-4" /></Button>
                      <Button size="icon" variant="ghost" className="h-8 w-8 shrink-0 text-destructive hover:bg-destructive/20" onClick={() => setEditing(false)}><X className="h-4 w-4" /></Button>
                    </div>
                  ) : (
                    <div className="flex items-center justify-center gap-2 group w-full px-2">
                      <h2 className="text-xl font-semibold text-foreground tracking-tight truncate">{person.display_name}</h2>
                      <Button size="icon" variant="ghost" className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity shrink-0 text-muted-foreground hover:text-foreground" onClick={startEdit}>
                        <Pencil className="h-3 w-3" />
                      </Button>
                    </div>
                  )}
                  {isUnnamed && <Badge variant="outline" className="text-[9px] uppercase font-mono mt-1 text-amber-500 border-amber-500/30 bg-amber-500/10">Unidentified Profile</Badge>}
                </div>

                <div className="flex items-center justify-center gap-6 w-full pt-4 border-t border-white/5">
                  <div className="flex flex-col items-center">
                    <span className="text-xs font-semibold text-foreground">{person.asset_count ?? 0}</span>
                    <span className="text-[10px] uppercase font-mono text-muted-foreground">Assets</span>
                  </div>
                  <div className="h-8 w-px bg-white/10" />
                  <div className="flex flex-col items-center">
                    <span className="text-xs font-semibold text-foreground">{formatTimecode(person.total_speaking_seconds ?? 0)}</span>
                    <span className="text-[10px] uppercase font-mono text-muted-foreground">Speech</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Attributes & Data */}
            <div className="bg-card/20 border border-white/5 rounded-2xl p-5 space-y-5">
              <div className="flex items-center gap-2 text-sm font-medium text-foreground tracking-tight">
                 <MoreHorizontal className="h-4 w-4 text-primary/70" /> Attributes
              </div>
              
              <div className="space-y-4">
                <div className="flex flex-col gap-1.5">
                  <span className="text-[10px] uppercase font-mono text-muted-foreground">Name Source</span>
                  <Badge variant="outline" className="w-fit text-xs bg-background/50">{person.name_source}</Badge>
                </div>
                
                {person.key_topics && person.key_topics.length > 0 && (
                  <div className="flex flex-col gap-2">
                    <span className="text-[10px] uppercase font-mono text-muted-foreground">Detected Tags</span>
                    <div className="flex flex-wrap gap-1.5">
                      {person.key_topics.map((attr, i) => (
                        <Badge key={i} variant="secondary" className="bg-card/50 border-white/10 text-xs font-normal">
                          {attr}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Search Everywhere Action */}
            <div className="bg-card/20 border border-white/5 rounded-2xl p-5 space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground tracking-tight">
                   <Globe className="h-4 w-4 text-primary/70" /> Global Search
                </div>
                {person.face_search?.status === "done" && person.face_search.searched_at && (
                  <span className="text-[9px] uppercase font-mono text-muted-foreground">
                    Last: {new Date(person.face_search.searched_at).toLocaleDateString()}
                  </span>
                )}
              </div>
              
              <p className="text-xs text-muted-foreground leading-relaxed">
                Scan the entire library for matching faces to link unassigned appearances to this profile.
              </p>
              
              <div className="pt-2">
                {fsActive ? (
                  <div className="flex items-center gap-3 bg-primary/10 border border-primary/20 p-3 rounded-lg text-primary text-xs font-medium">
                    <Loader2 className="h-4 w-4 animate-spin shrink-0" />
                    <span>Search in progress...</span>
                  </div>
                ) : person.face_search?.status === "error" ? (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-xs text-destructive bg-destructive/10 p-2.5 rounded-lg border border-destructive/20">
                      <AlertTriangle className="h-3.5 w-3.5 shrink-0" /> {person.face_search.error || "Search failed."}
                    </div>
                    <Button size="sm" variant="outline" className="w-full h-8 text-xs bg-card hover:bg-card/80 border-white/10 gap-2" onClick={handleFaceSearch}>
                      <RefreshCw className="h-3.5 w-3.5" /> Retry Search
                    </Button>
                  </div>
                ) : (
                  <Button size="sm" variant="outline" className="w-full h-9 text-xs font-medium bg-card hover:bg-card/80 hover:text-primary transition-colors border-white/10 gap-2" onClick={handleFaceSearch}>
                    <ScanSearch className="h-4 w-4 text-primary/70" /> Scan Library for Matches
                  </Button>
                )}
                {person.face_search?.status === "done" && (
                  <p className="text-[10px] text-green-400 mt-3 flex items-center justify-center gap-1.5 bg-green-500/10 p-2 rounded-lg border border-green-500/20">
                    <Check className="h-3 w-3" /> Search completed
                  </p>
                )}
              </div>
            </div>
            
          </div>

          {/* RIGHT COLUMN: Production Suite (Wider on XL) */}
          <div className="xl:col-span-8 space-y-6">
            
            <Tabs defaultValue="voice" className="w-full">
              <TabsList className="bg-card/40 border border-white/5 mb-4 inline-flex h-9 items-center justify-center rounded-lg p-1 text-muted-foreground w-full sm:w-auto">
                <TabsTrigger value="voice" className="inline-flex items-center justify-center whitespace-nowrap rounded-md px-3 py-1.5 text-xs font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm">
                  <Mic className="h-3.5 w-3.5 mr-2" /> Voice Studio
                </TabsTrigger>
                <TabsTrigger value="appearances" className="inline-flex items-center justify-center whitespace-nowrap rounded-md px-3 py-1.5 text-xs font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm">
                  <Film className="h-3.5 w-3.5 mr-2" /> Appearances <Badge className="ml-2 h-4 px-1 text-[9px] bg-background border-white/10">{appearances.length}</Badge>
                </TabsTrigger>
              </TabsList>

              <TabsContent value="voice" className="focus-visible:outline-none focus-visible:ring-0 mt-0">
                <div className="bg-card/20 border border-white/5 rounded-2xl p-6 relative overflow-hidden">
                  <VoiceSection
                    personId={id!}
                    personName={person.display_name}
                    appearances={appearances}
                    voicePreset={person.voice_preset}
                    voiceSettings={person.voice_settings}
                  />
                </div>
              </TabsContent>

              <TabsContent value="appearances" className="focus-visible:outline-none focus-visible:ring-0 mt-0">
                <div className="bg-card/20 border border-white/5 rounded-2xl p-6 space-y-5">
                  <div className="flex items-center justify-between border-b border-white/5 pb-4">
                    <h2 className="text-xl font-medium flex items-center gap-3 text-foreground tracking-tight">
                      <Film className="h-5 w-5 text-primary" /> Appearances
                    </h2>
                  </div>

                  {appearances.length > 0 ? (
                    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                      {appearances.map((app, index) => {
                        const isVis = !!app.face_cluster_id;
                        const isSpk = !!app.speaker_label;
                        const thumb = app.thumbnail_url;

                        return (
                          <div key={`${app.media_id}-${index}`} className="bg-card/40 border border-white/5 rounded-xl overflow-hidden group hover:border-primary/30 transition-colors flex flex-col h-[280px]">
                            <div className="relative h-32 w-full bg-background overflow-hidden border-b border-white/5">
                              {thumb ? (
                                <img src={`/api/thumbnails/${thumb}`} className="w-full h-full object-cover transition-transform duration-700 group-hover:scale-105 opacity-80 group-hover:opacity-100" />
                              ) : app.face_cluster_id ? (
                                <div className="w-full h-full flex items-center justify-center bg-card">
                                   <User className="h-8 w-8 text-muted-foreground/30" />
                                </div>
                              ) : (
                                <div className="w-full h-full flex items-center justify-center bg-card">
                                   <Mic className="h-8 w-8 text-muted-foreground/30" />
                                </div>
                              )}
                              <div className="absolute inset-0 bg-gradient-to-t from-background/90 to-transparent" />
                              
                              <div className="absolute top-2 left-2 flex gap-1">
                                {isVis && <Badge className="bg-background/80 backdrop-blur text-foreground border-white/10 text-[9px] uppercase px-1.5 h-4">Visual</Badge>}
                                {isSpk && <Badge className="bg-primary/20 backdrop-blur text-primary border-primary/30 text-[9px] uppercase px-1.5 h-4">Audio</Badge>}
                              </div>
                            </div>

                            <div className="p-3 flex-1 flex flex-col">
                              <Link href={`/library/${app.media_id}`} className="text-xs font-medium text-foreground hover:text-primary transition-colors line-clamp-2 leading-relaxed mb-2 flex-1" title={app.filename}>
                                {app.filename}
                              </Link>
                              
                              <div className="flex flex-col gap-2 mt-auto">
                                <div className="flex items-center justify-between text-[10px] font-mono text-muted-foreground">
                                  <span></span>
                                  {app.first_spoken_at != null ? (
                                    <span className="flex items-center gap-1"><MessageSquareQuote className="h-3 w-3" /> {formatTimecode(app.first_spoken_at)}</span>
                                  ) : <span />}
                                </div>
                                
                                <div className="flex items-center gap-1 pt-2 border-t border-white/5 opacity-0 group-hover:opacity-100 transition-opacity">
                                  {app.merged_from && (
                                    <>
                                      <Button
                                        size="sm"
                                        variant="ghost"
                                        className="flex-1 h-7 text-[9px] uppercase font-mono px-2 text-muted-foreground hover:text-foreground hover:bg-card transition-colors"
                                        onClick={() => handleUnmerge(app)}
                                        title="Remove all of this person's appearances from this asset and create a new profile for them"
                                      >
                                        <Undo2 className="h-3 w-3 mr-1" /> Remove
                                      </Button>
                                      <div className="w-px h-4 bg-white/10" />
                                    </>
                                  )}
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    className="flex-1 h-7 text-[9px] uppercase font-mono px-2 text-muted-foreground hover:text-foreground hover:bg-card transition-colors"
                                    onClick={() => handleSplit(app)}
                                    title="Split this specific appearance into a new profile"
                                  >
                                    <Scissors className="h-3 w-3 mr-1" /> Split
                                  </Button>
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center py-16 text-center bg-card/20 rounded-xl border border-dashed border-white/10">
                      <Film className="h-8 w-8 text-muted-foreground/50 mb-3" />
                      <p className="text-sm font-medium text-foreground">No appearances recorded</p>
                      <p className="text-xs text-muted-foreground mt-1 max-w-[300px]">This profile isn't linked to any media in the library yet.</p>
                    </div>
                  )}
                </div>
              </TabsContent>
            </Tabs>
            
          </div>
        </div>
      </div>
    </div>
  );
}
