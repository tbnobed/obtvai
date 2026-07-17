import { useRef, useState } from "react";
import { useRoute, Link } from "wouter";
import {
  useGetPerson,
  getGetPersonQueryKey,
  getListPeopleQueryKey,
  useUpdatePerson,
  useMergePerson,
  useSplitPerson,
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
  SlidersHorizontal,
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
            <p className="text-xs text-red-400">Upload failed — use wav, mp3, m4a, flac, or ogg.</p>
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

export default function PersonDetail() {
  const [, params] = useRoute("/people/:id");
  const id = params?.id ?? "";
  const queryClient = useQueryClient();
  const { data: person, isLoading } = useGetPerson(id, {
    query: { queryKey: getGetPersonQueryKey(id), enabled: !!id },
  });
  const { data: allPeople } = useListPeople({ limit: 200 });

  const updatePerson = useUpdatePerson();
  const mergePerson = useMergePerson();
  const splitPerson = useSplitPerson();
  const [, navigate] = useLocation();

  const [renameOpen, setRenameOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [mergeOpen, setMergeOpen] = useState(false);
  const [mergeSource, setMergeSource] = useState("");

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
          const detail =
            (err as { response?: { data?: { detail?: string; error?: string } } })?.response?.data;
          window.alert(detail?.detail || detail?.error || "Split failed");
        },
      }
    );
  };

  const handleMerge = (e: React.FormEvent) => {
    e.preventDefault();
    if (!mergeSource) return;
    mergePerson.mutate(
      { id, data: { source_person_id: mergeSource } },
      {
        onSuccess: () => {
          setMergeOpen(false);
          setMergeSource("");
          invalidate();
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

  const mergeCandidates = (allPeople?.items ?? []).filter((p) => p.id !== id);

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
          {person.summary && <p className="text-sm mt-3 max-w-3xl">{person.summary}</p>}
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
            <Dialog open={mergeOpen} onOpenChange={setMergeOpen}>
              <DialogTrigger asChild>
                <Button variant="secondary" size="sm" className="gap-2">
                  <Merge className="h-3.5 w-3.5" />
                  Merge Into This Person
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Merge a Duplicate Into {person.display_name}</DialogTitle>
                </DialogHeader>
                <form onSubmit={handleMerge} className="space-y-4 pt-4">
                  <p className="text-sm text-muted-foreground">
                    The selected person's appearances will be moved into {person.display_name}, and the duplicate will be removed. This cannot be undone.
                  </p>
                  <select
                    value={mergeSource}
                    onChange={(e) => setMergeSource(e.target.value)}
                    className="w-full h-9 px-3 py-1 rounded-md border border-input bg-background text-sm"
                  >
                    <option value="">Select a person to merge in...</option>
                    {mergeCandidates.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.display_name} ({p.asset_count} assets)
                      </option>
                    ))}
                  </select>
                  <Button type="submit" className="w-full" disabled={!mergeSource || mergePerson.isPending}>
                    {mergePerson.isPending ? "Merging..." : "Merge"}
                  </Button>
                </form>
              </DialogContent>
            </Dialog>
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
      {person.appearances?.length ? (
        <div className="space-y-2">
          {person.appearances.map((a) => (
            <div
              key={`${a.media_id}-${a.speaker_label ?? ""}-${a.face_cluster_id ?? ""}`}
              className="border border-border bg-card rounded-md p-4 flex items-center gap-4 hover:border-primary transition-colors"
            >
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
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No appearances recorded.</p>
      )}
    </div>
  );
}
