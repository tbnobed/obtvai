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
  useTuneVoice,
  useSetVoicePreset,
  useSetVoiceSettings,
  useGetPersonAssetMoments,
  getGetPersonAssetMomentsQueryKey,
  useReprofilePerson,
} from "@workspace/api-client-react";
import type { PersonAppearance, VoiceGeneration, VoiceSettings } from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
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
  RefreshCw, Globe,
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

const PRESET_LABELS: Record<string, string> = {
  natural: "Natural",
  expressive: "Expressive",
  steady: "Steady",
  warm: "Warm",
};

// XTTS stock defaults — sliders start here.
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
        q.state.data?.some((g) => g.status === "pending" || g.status === "running") ? 2000 : false,
    },
  });

  const addSample = useAddVoiceSample();
  const uploadSample = useUploadVoiceSample();
  const deleteSample = useDeleteVoiceSample();
  const createGen = useCreateVoiceGeneration();
  const deleteGen = useDeleteVoiceGeneration();
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

  const [genText, setGenText] = useState("");
  const [genLang, setGenLang] = useState("en");
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
    createGen.mutate(
      {
        id: personId,
        data: {
          text: genText.trim(),
          language: genLang,
          ...(tuneOpen && tuneChanged ? { settings: tune } : {}),
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
    <div className="mb-8">
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <AudioWaveform className="h-5 w-5 text-primary" /> Voice Clone
        </h2>
        {profile?.ready ? (
          <Badge className="bg-green-500/15 text-green-400 border-green-500/30">ready</Badge>
        ) : (
          <Badge variant="outline">
            {Math.round(readySeconds)}s / {minSeconds}s of clean audio
          </Badge>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="border border-border bg-card rounded-md p-4 space-y-3">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <h3 className="text-sm font-semibold">Clean Samples</h3>
            <div className="flex gap-2">
              <Dialog open={addOpen} onOpenChange={setAddOpen}>
                <DialogTrigger asChild>
                  <Button size="sm" variant="outline" className="gap-1.5" disabled={!speakingAppearances.length}>
                    <Plus className="h-3.5 w-3.5" /> From footage
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Add a Voice Sample from Footage</DialogTitle>
                  </DialogHeader>
                  <div className="space-y-4 pt-2">
                    <p className="text-sm text-muted-foreground">
                      Pick a stretch where only {personName} speaks — no music, no crosstalk. 10–30 seconds is ideal.
                    </p>
                    <div className="space-y-2">
                      <Label>Asset</Label>
                      <Select value={sampleMedia} onValueChange={setSampleMedia}>
                        <SelectTrigger><SelectValue placeholder="Choose an asset they speak in" /></SelectTrigger>
                        <SelectContent>
                          {speakingAppearances.map((a) => (
                            <SelectItem key={a.media_id} value={a.media_id}>
                              {a.filename}
                              {a.first_spoken_at != null ? ` — first speaks at ${formatTimecode(a.first_spoken_at)}` : ""}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-2">
                        <Label>Start</Label>
                        <Input value={sampleStart} onChange={(e) => setSampleStart(e.target.value)} placeholder="e.g. 2:05 or 125" />
                      </div>
                      <div className="space-y-2">
                        <Label>End</Label>
                        <Input value={sampleEnd} onChange={(e) => setSampleEnd(e.target.value)} placeholder="e.g. 2:28 or 148" />
                      </div>
                    </div>
                    {rangeError && <p className="text-sm text-red-400">{rangeError}</p>}
                  </div>
                  <DialogFooter>
                    <Button variant="outline" onClick={() => setAddOpen(false)}>Cancel</Button>
                    <Button onClick={submitSample} disabled={addSample.isPending}>
                      {addSample.isPending ? "Adding..." : "Add Sample"}
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
              <Button size="sm" variant="outline" className="gap-1.5"
                onClick={() => fileInputRef.current?.click()} disabled={uploadSample.isPending}>
                {uploadSample.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                Upload
              </Button>
            </div>
          </div>
          {uploadSample.isError && (
            <p className="text-xs text-red-400">
              Upload failed —{" "}
              {(uploadSample.error as { data?: { detail?: string } } | null)?.data?.detail ??
                "use wav, mp3, m4a, flac, or ogg."}
            </p>
          )}
          {profile?.samples?.length ? (
            <div className="space-y-2">
              {profile.samples.map((s) => (
                <div key={s.id} className="flex items-center gap-3 bg-muted/50 rounded p-2 text-sm">
                  <div className="flex-1 min-w-0">
                    <p className="truncate">
                      {s.filename || (s.source === "upload" ? "Uploaded audio" : "Clip")}
                      {s.start_time != null && s.end_time != null
                        ? ` · ${formatTimecode(s.start_time)}–${formatTimecode(s.end_time)}`
                        : ""}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {s.status === "ready"
                        ? `${(s.duration_seconds ?? 0).toFixed(1)}s`
                        : s.status === "error"
                          ? s.error_message || "Failed"
                          : "Processing..."}
                      {" · "}{s.source === "upload" ? "uploaded" : "from footage"}
                    </p>
                  </div>
                  {s.status === "pending" && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground shrink-0" />}
                  {s.status === "error" && <Badge variant="outline" className="bg-red-500/15 text-red-400 shrink-0">error</Badge>}
                  {s.status === "ready" && (
                    <audio controls preload="none" src={`/api/voice/samples/${s.id}/audio`} className="h-8 w-44 shrink-0" />
                  )}
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-7 w-7 text-muted-foreground hover:text-red-400 shrink-0"
                    onClick={() => deleteSample.mutate({ id: s.id }, { onSuccess: invalidateProfile })}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              No samples yet. Add clean stretches of {personName} speaking — at least {minSeconds} seconds total unlocks cloning and dubbing in their own voice.
            </p>
          )}
        </div>

        <div className="border border-border bg-card rounded-md p-4 space-y-3">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-sm font-semibold">Voice Generator</h3>
            {voiceSettings ? (
              <Badge className="bg-primary/15 text-primary border-primary/30 text-[10px]">
                style: Custom
              </Badge>
            ) : voicePreset ? (
              <Badge className="bg-primary/15 text-primary border-primary/30 text-[10px]">
                style: {PRESET_LABELS[voicePreset] ?? voicePreset}
              </Badge>
            ) : null}
            {profile?.ready ? (
              <Button
                size="sm"
                variant="ghost"
                className="ml-auto h-7 gap-1.5 text-xs text-muted-foreground"
                onClick={() => setTuneOpen((v) => !v)}
              >
                <SlidersHorizontal className="h-3.5 w-3.5" /> Fine-tune
              </Button>
            ) : null}
          </div>
          {tuneOpen && profile?.ready ? (
            <div className="rounded border border-border/60 bg-muted/30 p-3 space-y-3">
              {TUNE_SLIDERS.map((s) => (
                <div key={s.key} className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-medium">{s.label}</span>
                    <span className="text-muted-foreground">
                      {tune[s.key].toFixed(2)} <span className="hidden sm:inline">— {s.hint}</span>
                    </span>
                  </div>
                  <Slider
                    min={s.min}
                    max={s.max}
                    step={s.step}
                    value={[tune[s.key]]}
                    onValueChange={([v]) => setTune((t) => ({ ...t, [s.key]: v }))}
                  />
                </div>
              ))}
              <div className="flex items-center gap-2 pt-1">
                <p className="text-[11px] text-muted-foreground flex-1">
                  Speed changes the most. Generate below to hear these settings.
                </p>
                <Button size="sm" variant="ghost" className="h-7 text-xs"
                  onClick={() => setTune({ ...DEFAULT_TUNE })}>
                  Reset
                </Button>
                <Button size="sm" variant="outline" className="h-7 text-xs"
                  disabled={saveSettings.isPending}
                  onClick={saveTuneAsDefault}>
                  {saveSettings.isPending ? "Saving…" : "Save as default"}
                </Button>
              </div>
            </div>
          ) : null}
          {profile?.ready ? (
            <>
              <Textarea
                rows={3}
                value={genText}
                onChange={(e) => setGenText(e.target.value)}
                placeholder={`Type anything — hear it in ${personName}'s voice`}
                maxLength={2000}
              />
              <div className="flex items-center gap-2">
                <Select value={genLang} onValueChange={setGenLang}>
                  <SelectTrigger className="w-36 h-9"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {XTTS_LANGUAGES.map((l) => (
                      <SelectItem key={l.code} value={l.code}>{l.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button variant="outline" className="ml-auto gap-2" onClick={submitTune}
                  disabled={!genText.trim() || tuneVoice.isPending}
                  title="Generate the same line in 4 synthesis styles, then pick the one that sounds best">
                  {tuneVoice.isPending
                    ? <><Loader2 className="h-4 w-4 animate-spin" /> Queuing...</>
                    : <><Sparkles className="h-4 w-4" /> Compare styles</>}
                </Button>
                <Button className="gap-2" onClick={submitGeneration}
                  disabled={!genText.trim() || createGen.isPending}>
                  {createGen.isPending
                    ? <><Loader2 className="h-4 w-4 animate-spin" /> Queuing...</>
                    : <><Play className="h-4 w-4" /> Generate</>}
                </Button>
              </div>
              {(createGen.isError || tuneVoice.isError) && (
                <p className="text-sm text-red-400">Generation failed to start — is the pipeline running?</p>
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              Locked until the voice profile is ready — add {Math.max(0, Math.ceil(minSeconds - readySeconds))} more seconds of clean samples.
            </p>
          )}

          {generations?.length ? (
            <div className="space-y-2 pt-1">
              {generations.map((g: VoiceGeneration) => (
                <div key={g.id} className="bg-muted/50 rounded p-2 text-sm space-y-1.5">
                  <div className="flex items-start gap-2">
                    <p className="flex-1 min-w-0 text-xs leading-relaxed line-clamp-2">&ldquo;{g.text}&rdquo;</p>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-6 w-6 text-muted-foreground hover:text-red-400 shrink-0"
                      onClick={() => deleteGen.mutate({ id: g.id }, { onSuccess: invalidateGens })}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-[10px]">
                      {XTTS_LANGUAGES.find((l) => l.code === g.language)?.label ?? g.language}
                    </Badge>
                    {g.preset ? (
                      <Badge className="bg-primary/15 text-primary border-primary/30 text-[10px]">
                        {PRESET_LABELS[g.preset] ?? g.preset}
                      </Badge>
                    ) : null}
                    {g.status === "success" ? (
                      <>
                        <audio controls preload="none" src={`/api/voice/generations/${g.id}/audio`} className="h-8 flex-1 min-w-0" />
                        {g.preset ? (
                          g.preset === voicePreset ? (
                            <Badge className="bg-green-500/15 text-green-400 border-green-500/30 text-[10px] shrink-0">in use</Badge>
                          ) : (
                            <Button size="sm" variant="outline" className="h-7 text-xs shrink-0"
                              disabled={setPreset.isPending}
                              onClick={() => choosePreset(g.preset!)}>
                              Use this style
                            </Button>
                          )
                        ) : null}
                        <a href={`/api/voice/generations/${g.id}/audio`} download className="shrink-0">
                          <Button size="icon" variant="ghost" className="h-7 w-7"><Download className="h-3.5 w-3.5" /></Button>
                        </a>
                      </>
                    ) : g.status === "error" ? (
                      <span className="text-xs text-red-400 truncate">{g.error_message || "Generation failed"}</span>
                    ) : (
                      <span className="text-xs text-muted-foreground flex items-center gap-1.5">
                        <Loader2 className="h-3 w-3 animate-spin" /> Generating… {Math.round(g.progress ?? 0)}%
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function formatDuration(seconds: number | null | undefined) {
  if (!seconds) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  if (m >= 60) return `${Math.floor(m / 60)}h ${m % 60}m`;
  return `${m}m ${s}s`;
}

function formatTimecode(seconds: number | null | undefined) {
  if (seconds == null) return null;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function AppearanceMoments({ personId, mediaId }: { personId: string; mediaId: string }) {
  const { data, isLoading, isError } = useGetPersonAssetMoments(personId, mediaId, {
    query: { queryKey: getGetPersonAssetMomentsQueryKey(personId, mediaId) },
  });

  if (isLoading) {
    return (
      <div className="px-4 pb-4 pt-1 text-xs text-muted-foreground flex items-center gap-1.5">
        <Loader2 className="h-3 w-3 animate-spin" /> Loading moments…
      </div>
    );
  }
  if (isError) {
    return (
      <p className="px-4 pb-4 pt-1 text-xs text-red-400">
        Could not load moments for this asset — try again.
      </p>
    );
  }
  if (!data || (!data.speaking?.length && !data.on_camera?.length)) {
    return (
      <p className="px-4 pb-4 pt-1 text-xs text-muted-foreground">
        No timecoded moments recorded for this asset.
      </p>
    );
  }
  return (
    <div className="px-4 pb-4 pt-1 space-y-3 border-t border-border/60 mt-3">
      {data.on_camera?.length ? (
        <div className="pt-3">
          <p className="text-xs font-semibold text-muted-foreground mb-1.5 flex items-center gap-1.5">
            <Eye className="h-3.5 w-3.5" /> On camera
          </p>
          <div className="flex flex-wrap gap-1.5">
            {data.on_camera.map((r, i) => (
              <Link key={i} href={`/library/${mediaId}?t=${Math.floor(r.start_time)}`}>
                <Badge
                  variant="outline"
                  className="text-xs font-mono cursor-pointer hover:border-primary hover:text-primary transition-colors"
                >
                  {formatTimecode(r.start_time)}–{formatTimecode(r.end_time)}
                </Badge>
              </Link>
            ))}
          </div>
        </div>
      ) : null}
      {data.speaking?.length ? (
        <div className={data.on_camera?.length ? "" : "pt-3"}>
          <p className="text-xs font-semibold text-muted-foreground mb-1.5 flex items-center gap-1.5">
            <Mic className="h-3.5 w-3.5" /> Speaking ({data.speaking.length})
          </p>
          <div className="space-y-0.5 max-h-80 overflow-y-auto pr-1">
            {data.speaking.map((s, i) => (
              <Link
                key={i}
                href={`/library/${mediaId}?t=${Math.floor(s.start_time)}`}
                className="flex items-start gap-3 rounded px-2 py-1.5 hover:bg-muted/60 group"
              >
                <span className="text-xs font-mono text-primary shrink-0 mt-0.5">
                  {formatTimecode(s.start_time)}
                </span>
                <span className="text-xs text-muted-foreground group-hover:text-foreground leading-relaxed min-w-0">
                  {s.text}
                </span>
              </Link>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function PersonDetail() {
  const [, params] = useRoute("/people/:id");
  const id = params?.id ?? "";
  const queryClient = useQueryClient();
  const { data: person, isLoading } = useGetPerson(id, {
    query: { queryKey: getGetPersonQueryKey(id), enabled: !!id },
  });
  const [mergeOpen, setMergeOpen] = useState(false);
  const [mergeSearch, setMergeSearch] = useState("");
  const [mergeSource, setMergeSource] = useState<{
    id: string;
    display_name: string;
    thumbnail_url?: string | null;
    asset_count?: number;
  } | null>(null);
  const [mergeSearchDebounced, setMergeSearchDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setMergeSearchDebounced(mergeSearch.trim()), 300);
    return () => clearTimeout(t);
  }, [mergeSearch]);
  const mergeParams = useMemo(
    () => ({ ...(mergeSearchDebounced ? { q: mergeSearchDebounced } : {}), limit: 100 }),
    [mergeSearchDebounced]
  );
  const { data: mergePeoplePage, isLoading: mergePeopleLoading } = useListPeople(
    mergeParams,
    {
      query: {
        queryKey: getListPeopleQueryKey(mergeParams),
        enabled: mergeOpen,
        placeholderData: (p) => p,
      },
    }
  );

  const updatePerson = useUpdatePerson();
  const reprofilePerson = useReprofilePerson();
  const [reprofileQueued, setReprofileQueued] = useState(false);
  const mergePerson = useMergePerson();
  const splitPerson = useSplitPerson();
  const unmergePerson = useUnmergePerson();
  const [, navigate] = useLocation();

  const [renameOpen, setRenameOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [openMoments, setOpenMoments] = useState<Record<string, boolean>>({});
  const [editingBio, setEditingBio] = useState(false);
  const [bioDraft, setBioDraft] = useState("");

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: getGetPersonQueryKey(id) });
    queryClient.invalidateQueries({ queryKey: getListPeopleQueryKey() });
  };

  const handleRename = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    updatePerson.mutate(
      { id, data: { display_name: newName.trim() } },
      {
        onSuccess: () => {
          setRenameOpen(false);
          setNewName("");
          invalidate();
        },
      }
    );
  };

  const handleSplit = (
    e: React.MouseEvent,
    a: { media_id: string; speaker_label?: string | null; face_cluster_id?: string | null }
  ) => {
    e.preventDefault();
    e.stopPropagation();
    if (splitPerson.isPending) return;
    if (
      !window.confirm(
        "Split this appearance out into a new, separate person? Use this to undo a merge that combined two different people."
      )
    )
      return;
    splitPerson.mutate(
      {
        id,
        data: {
          media_id: a.media_id,
          speaker_label: a.speaker_label ?? null,
          face_cluster_id: a.face_cluster_id ?? null,
        },
      },
      {
        onSuccess: (newPerson) => {
          invalidate();
          navigate(`/people/${newPerson.id}`);
        },
        onError: (err: unknown) => {
          const e = err as { data?: { detail?: string; error?: string }; message?: string };
          window.alert(e?.data?.detail || e?.data?.error || e?.message || "Split failed");
        },
      }
    );
  };

  const handleUnmerge = (fromId: string, name: string, count: number) => {
    if (unmergePerson.isPending) return;
    if (
      !window.confirm(
        `Undo the merge with "${name}"? All ${count} appearance${count === 1 ? "" : "s"} that came from them will move back out into a restored "${name}".`
      )
    )
      return;
    unmergePerson.mutate(
      { id, data: { merged_from_person_id: fromId } },
      {
        onSuccess: (restored) => {
          invalidate();
          navigate(`/people/${restored.id}`);
        },
        onError: (err: unknown) => {
          const e = err as { data?: { detail?: string; error?: string }; message?: string };
          window.alert(e?.data?.detail || e?.data?.error || e?.message || "Unmerge failed");
        },
      }
    );
  };

  const handleMerge = (e: React.FormEvent) => {
    e.preventDefault();
    if (!mergeSource) return;
    mergePerson.mutate(
      { id, data: { source_person_id: mergeSource.id } },
      {
        onSuccess: () => {
          setMergeOpen(false);
          setMergeSource(null);
          setMergeSearch("");
          invalidate();
        },
        onError: (err: unknown) => {
          const e = err as { data?: { detail?: string; error?: string }; message?: string };
          window.alert(e?.data?.detail || e?.data?.error || e?.message || "Merge failed");
        },
      }
    );
  };

  if (isLoading) {
    return (
      <div className="flex-1 p-8 overflow-y-auto">
        <div className="animate-pulse space-y-4">
          <div className="h-8 w-64 bg-muted rounded" />
          <div className="h-40 bg-muted rounded" />
        </div>
      </div>
    );
  }

  if (!person) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground">
        <User className="h-12 w-12 mb-4 opacity-50" />
        <p>Person not found.</p>
        <Link href="/people" className="text-primary text-sm mt-2 hover:underline">
          Back to People
        </Link>
      </div>
    );
  }

  const mergeCandidates = (mergePeoplePage?.items ?? []).filter((p) => p.id !== id);

  const mergedGroups: { person_id: string; display_name: string; count: number }[] = [];
  for (const a of person.appearances ?? []) {
    const mf = a.merged_from as { person_id?: string; display_name?: string } | null | undefined;
    if (!mf?.person_id) continue;
    const existing = mergedGroups.find((g) => g.person_id === mf.person_id);
    if (existing) existing.count += 1;
    else mergedGroups.push({ person_id: mf.person_id, display_name: mf.display_name ?? "Unknown", count: 1 });
  }

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <Link href="/people" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-6">
        <ArrowLeft className="h-4 w-4" />
        People
      </Link>

      <div className="flex flex-col md:flex-row gap-6 mb-8">
        <div className="w-40 h-40 rounded-md bg-muted flex-shrink-0 overflow-hidden">
          {person.thumbnail_url ? (
            <img
              src={`/api/thumbnails/${person.thumbnail_url}`}
              alt={person.display_name}
              className="w-full h-full object-cover"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center">
              <User className="h-16 w-16 text-muted-foreground/50" />
            </div>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-3xl font-bold tracking-tight">{person.display_name}</h1>
            {person.name_source && (
              <Badge variant={person.name_source === "manual" ? "default" : "secondary"} className="text-xs">
                {person.name_source === "manual" ? "manually named" : "auto-identified"}
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-4 mt-2 text-sm text-muted-foreground">
            <span className="flex items-center gap-1">
              <Film className="h-4 w-4" />
              {person.asset_count} {person.asset_count === 1 ? "asset" : "assets"}
            </span>
            <span className="flex items-center gap-1">
              <Mic className="h-4 w-4" />
              {formatDuration(person.total_speaking_seconds)} speaking
            </span>
            <span>{person.segment_count} segments</span>
          </div>
          {editingBio ? (
            <div className="mt-3 max-w-3xl space-y-2">
              <Textarea
                value={bioDraft}
                onChange={(e) => setBioDraft(e.target.value)}
                rows={4}
                maxLength={2000}
                placeholder="Write a short bio for this person…"
                autoFocus
              />
              <div className="flex gap-2">
                <Button
                  size="sm"
                  disabled={updatePerson.isPending}
                  onClick={() =>
                    updatePerson.mutate(
                      { id, data: { summary: bioDraft } },
                      {
                        onSuccess: () => {
                          setEditingBio(false);
                          invalidate();
                        },
                      }
                    )
                  }
                >
                  {updatePerson.isPending ? "Saving..." : "Save Bio"}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setEditingBio(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <div className="mt-3 max-w-3xl flex items-start gap-2 group">
              <p className="text-sm">
                {person.summary || <span className="text-muted-foreground italic">No bio yet.</span>}
              </p>
              <button
                type="button"
                className="shrink-0 mt-0.5 text-muted-foreground/50 hover:text-foreground transition-colors"
                title="Edit bio"
                onClick={() => {
                  setBioDraft(person.summary ?? "");
                  setEditingBio(true);
                }}
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
          <div className="flex gap-2 mt-4">
            <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
              <DialogTrigger asChild>
                <Button variant="secondary" size="sm" className="gap-2">
                  <Pencil className="h-3.5 w-3.5" />
                  Rename
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Rename Person</DialogTitle>
                </DialogHeader>
                <form onSubmit={handleRename} className="space-y-4 pt-4">
                  <Input
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder={person.display_name}
                    autoFocus
                  />
                  <Button type="submit" className="w-full" disabled={!newName.trim() || updatePerson.isPending}>
                    {updatePerson.isPending ? "Saving..." : "Save Name"}
                  </Button>
                </form>
              </DialogContent>
            </Dialog>
            <Dialog
              open={mergeOpen}
              onOpenChange={(open) => {
                setMergeOpen(open);
                if (!open) {
                  setMergeSource(null);
                  setMergeSearch("");
                }
              }}
            >
              <DialogTrigger asChild>
                <Button variant="secondary" size="sm" className="gap-2">
                  <Merge className="h-3.5 w-3.5" />
                  Merge Into This Person
                </Button>
              </DialogTrigger>
              <DialogContent className="max-w-lg">
                <DialogHeader>
                  <DialogTitle>Merge a Duplicate Into {person.display_name}</DialogTitle>
                </DialogHeader>
                <form onSubmit={handleMerge} className="space-y-3 pt-2">
                  <p className="text-sm text-muted-foreground">
                    The selected person's appearances will be moved into {person.display_name}, and the duplicate will be removed.
                  </p>
                  <div className="relative">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                    <Input
                      autoFocus
                      placeholder="Search people by name..."
                      value={mergeSearch}
                      onChange={(e) => setMergeSearch(e.target.value)}
                      className="pl-8"
                    />
                  </div>
                  <div className="max-h-[40vh] overflow-y-auto border border-border rounded-md divide-y divide-border bg-background">
                    {mergePeopleLoading ? (
                      <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" /> Loading people...
                      </div>
                    ) : mergeCandidates.length === 0 ? (
                      <div className="py-8 text-center text-sm text-muted-foreground">
                        {mergeSearch.trim() ? `No people match "${mergeSearch.trim()}"` : "No other people in the library"}
                      </div>
                    ) : (
                      mergeCandidates.map((p) => {
                        const selected = mergeSource?.id === p.id;
                        return (
                          <button
                            type="button"
                            key={p.id}
                            onClick={() => setMergeSource(selected ? null : p)}
                            className={`w-full flex items-center gap-3 px-3 py-2 text-left transition-colors ${
                              selected ? "bg-primary/15" : "hover:bg-muted/50"
                            }`}
                          >
                            <div className="h-12 w-12 rounded bg-muted overflow-hidden shrink-0 flex items-center justify-center">
                              {p.thumbnail_url ? (
                                <img
                                  src={`/api/thumbnails/${p.thumbnail_url}`}
                                  alt={p.display_name}
                                  className="w-full h-full object-cover"
                                  loading="lazy"
                                />
                              ) : (
                                <User className="h-5 w-5 text-muted-foreground/50" />
                              )}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="text-sm font-medium truncate">{p.display_name}</div>
                              <div className="text-xs text-muted-foreground">
                                {p.asset_count} {p.asset_count === 1 ? "video" : "videos"}
                              </div>
                            </div>
                            {selected && <Check className="h-4 w-4 text-primary shrink-0" />}
                          </button>
                        );
                      })
                    )}
                  </div>
                  {mergeSource && (
                    <div className="flex items-center gap-2 text-sm border border-border rounded-md px-3 py-2 bg-muted/40">
                      <div className="h-8 w-8 rounded bg-muted overflow-hidden shrink-0 flex items-center justify-center">
                        {mergeSource.thumbnail_url ? (
                          <img
                            src={`/api/thumbnails/${mergeSource.thumbnail_url}`}
                            alt={mergeSource.display_name}
                            className="w-full h-full object-cover"
                          />
                        ) : (
                          <User className="h-4 w-4 text-muted-foreground/50" />
                        )}
                      </div>
                      <span className="min-w-0 truncate">
                        <span className="font-medium">{mergeSource.display_name}</span>
                        {" "}will be merged into{" "}
                        <span className="font-medium">{person.display_name}</span> and removed. This can be undone later from this page.
                      </span>
                    </div>
                  )}
                  <Button type="submit" className="w-full" disabled={!mergeSource || mergePerson.isPending}>
                    {mergePerson.isPending
                      ? "Merging..."
                      : mergeSource
                        ? `Merge ${mergeSource.display_name} into ${person.display_name}`
                        : "Merge"}
                  </Button>
                </form>
              </DialogContent>
            </Dialog>
            <Button
              variant="secondary"
              size="sm"
              className="gap-2"
              disabled={reprofilePerson.isPending || reprofileQueued}
              onClick={() =>
                reprofilePerson.mutate(
                  { id },
                  {
                    onSuccess: () => {
                      setReprofileQueued(true);
                      setTimeout(() => {
                        setReprofileQueued(false);
                        invalidate();
                      }, 60_000);
                    },
                  }
                )
              }
            >
              <RefreshCw className={`h-3.5 w-3.5 ${reprofilePerson.isPending ? "animate-spin" : ""}`} />
              {reprofileQueued ? "Profile Queued" : "Regenerate Profile"}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              className="gap-2"
              disabled={reprofilePerson.isPending || reprofileQueued}
              title="Regenerate the profile using a web search (self-hosted SearXNG) for this person's name"
              onClick={() =>
                reprofilePerson.mutate(
                  { id, data: { use_web: true } },
                  {
                    onSuccess: () => {
                      setReprofileQueued(true);
                      setTimeout(() => {
                        setReprofileQueued(false);
                        invalidate();
                      }, 60_000);
                    },
                  }
                )
              }
            >
              <Globe className="h-3.5 w-3.5" />
              {reprofileQueued ? "Profile Queued" : "Regenerate with Web Search"}
            </Button>
          </div>
        </div>
      </div>

      {(person.speech_style || person.key_topics?.length) ? (
        <div className="grid gap-4 md:grid-cols-2 mb-8">
          {person.speech_style && (
            <div className="border border-border bg-card rounded-md p-4">
              <h2 className="text-sm font-semibold flex items-center gap-2 mb-2">
                <MessageSquareQuote className="h-4 w-4 text-primary" />
                Speech Style
              </h2>
              <p className="text-sm text-muted-foreground">{person.speech_style}</p>
            </div>
          )}
          {person.key_topics?.length ? (
            <div className="border border-border bg-card rounded-md p-4">
              <h2 className="text-sm font-semibold mb-2">Key Topics</h2>
              <div className="flex flex-wrap gap-1.5">
                {person.key_topics.map((t) => (
                  <Badge key={t} variant="outline" className="text-xs">
                    {t}
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      <VoiceSection personId={id} personName={person.display_name} appearances={person.appearances ?? []} voicePreset={person.voice_preset} voiceSettings={person.voice_settings} />

      <h2 className="text-lg font-semibold mb-4">Appearances</h2>
      {mergedGroups.length > 0 && (
        <div className="border border-border bg-card rounded-md p-4 mb-4">
          <p className="text-sm font-medium mb-1">Merged people</p>
          <p className="text-xs text-muted-foreground mb-3">
            These people were merged into {person.display_name}. Undo a merge to move their appearances back out into a restored person.
          </p>
          <div className="flex flex-wrap gap-2">
            {mergedGroups.map((g) => (
              <Button
                key={g.person_id}
                variant="outline"
                size="sm"
                className="gap-1.5"
                disabled={unmergePerson.isPending}
                onClick={() => handleUnmerge(g.person_id, g.display_name, g.count)}
              >
                <Undo2 className="h-3.5 w-3.5" />
                Unmerge {g.display_name} ({g.count} video{g.count === 1 ? "" : "s"})
              </Button>
            ))}
          </div>
        </div>
      )}
      {person.appearances?.length ? (
        <div className="space-y-2">
          {person.appearances.map((a) => {
            const momentsKey = `${a.media_id}-${a.speaker_label ?? ""}-${a.face_cluster_id ?? ""}`;
            const isOpen = !!openMoments[momentsKey];
            return (
              <div
                key={momentsKey}
                className="border border-border bg-card rounded-md hover:border-primary transition-colors"
              >
                <div className="p-4 pb-0 flex items-center gap-4">
                  <Link
                    href={`/library/${a.media_id}${a.first_spoken_at != null ? `?t=${Math.floor(a.first_spoken_at)}` : ""}`}
                    className="flex items-center gap-4 flex-1 min-w-0 cursor-pointer"
                  >
                    <div className="w-24 h-14 bg-muted rounded flex-shrink-0 overflow-hidden">
                      {a.thumbnail_url ? (
                        <img src={`/api/thumbnails/${a.thumbnail_url}`} alt={a.filename} className="w-full h-full object-cover" />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center">
                          <Film className="h-5 w-5 text-muted-foreground/50" />
                        </div>
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{a.filename}</p>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {a.speaker_label ? `${a.speaker_label} · ` : ""}
                        {formatDuration(a.speaking_seconds)} speaking · {a.segment_count ?? 0} segments
                        {a.first_spoken_at != null ? ` · first speaks at ${formatTimecode(a.first_spoken_at)}` : ""}
                      </p>
                      {(a.merged_from as { display_name?: string } | null | undefined)?.display_name && (
                        <Badge variant="secondary" className="mt-1.5 text-[10px] font-normal">
                          merged from {(a.merged_from as { display_name?: string }).display_name}
                        </Badge>
                      )}
                    </div>
                    <span className="text-xs text-muted-foreground flex-shrink-0">
                      {formatDuration(a.duration_seconds)}
                    </span>
                  </Link>
                  {(person.appearances?.length ?? 0) > 1 && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="gap-1.5 flex-shrink-0 text-muted-foreground hover:text-foreground"
                      disabled={splitPerson.isPending}
                      onClick={(e) => handleSplit(e, a)}
                      title="Split this appearance into a new person (undo a bad merge)"
                    >
                      <Scissors className="h-3.5 w-3.5" />
                      Split out
                    </Button>
                  )}
                </div>
                <button
                  type="button"
                  className="w-full flex items-center gap-1.5 px-4 py-2.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                  onClick={() =>
                    setOpenMoments((m) => ({ ...m, [momentsKey]: !m[momentsKey] }))
                  }
                >
                  {isOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                  {isOpen ? "Hide moments" : "Show every moment in this asset"}
                </button>
                {isOpen && <AppearanceMoments personId={id} mediaId={a.media_id} />}
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No appearances recorded.</p>
      )}
    </div>
  );
}
