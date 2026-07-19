import { useMemo, useState } from "react";
import { Link } from "wouter";
import {
  useListGraphicsPresets,
  getListGraphicsPresetsQueryKey,
  useListGraphicsGenerations,
  getListGraphicsGenerationsQueryKey,
  useCreateGraphicsGeneration,
  useCancelGraphicsGeneration,
  useDeleteGraphicsGeneration,
  useAddGraphicsToLibrary,
} from "@workspace/api-client-react";
import type { GraphicsGeneration, GraphicsPreset } from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Wand2,
  Image as ImageIcon,
  Clapperboard,
  Trash2,
  Square,
  Download,
  Loader2,
  FolderInput,
  Dice5,
  FileJson,
} from "lucide-react";

const ACTIVE = new Set(["pending", "queued", "running"]);

function statusBadge(status: string) {
  switch (status) {
    case "success":
      return <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30">Done</Badge>;
    case "error":
      return <Badge className="bg-red-500/15 text-red-400 border-red-500/30">Error</Badge>;
    case "cancelled":
      return <Badge className="bg-muted text-muted-foreground">Cancelled</Badge>;
    case "running":
      return <Badge className="bg-blue-500/15 text-blue-400 border-blue-500/30">Running</Badge>;
    default:
      return <Badge className="bg-amber-500/15 text-amber-400 border-amber-500/30">Queued</Badge>;
  }
}

export default function Graphics() {
  const queryClient = useQueryClient();
  const { data: presets, isLoading: presetsLoading } = useListGraphicsPresets({
    query: { queryKey: getListGraphicsPresetsQueryKey() },
  });
  const { data: gensData, isLoading: gensLoading } = useListGraphicsGenerations(undefined, {
    query: {
      queryKey: getListGraphicsGenerationsQueryKey(),
      refetchInterval: (q) =>
        q.state.data?.items?.some((g) => ACTIVE.has(g.status)) ? 2000 : false,
    },
  });
  const createGen = useCreateGraphicsGeneration();
  const cancelGen = useCancelGraphicsGeneration();
  const deleteGen = useDeleteGraphicsGeneration();
  const addToLibrary = useAddGraphicsToLibrary();

  const [presetId, setPresetId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [width, setWidth] = useState<string>("");
  const [height, setHeight] = useState<string>("");
  const [steps, setSteps] = useState<string>("");
  const [frames, setFrames] = useState<string>("");
  const [seed, setSeed] = useState<string>("");
  const [formError, setFormError] = useState<string | null>(null);
  const [preview, setPreview] = useState<GraphicsGeneration | null>(null);
  const [addedMsg, setAddedMsg] = useState<string | null>(null);

  const preset: GraphicsPreset | undefined = useMemo(() => {
    if (!presets?.length) return undefined;
    return presets.find((p) => p.id === presetId) ?? presets.find((p) => p.available) ?? presets[0];
  }, [presets, presetId]);

  const generations = gensData?.items ?? [];
  const invalidateGens = () =>
    queryClient.invalidateQueries({ queryKey: getListGraphicsGenerationsQueryKey() });

  const pickPreset = (p: GraphicsPreset) => {
    setPresetId(p.id);
    setWidth("");
    setHeight("");
    setSteps("");
    setFrames("");
    setFormError(null);
  };

  const intOrNull = (s: string) => {
    const v = parseInt(s, 10);
    return Number.isFinite(v) ? v : null;
  };

  const handleGenerate = () => {
    if (!preset) return;
    const text = prompt.trim();
    if (!text) {
      setFormError("Describe what to generate first.");
      return;
    }
    setFormError(null);
    createGen.mutate(
      {
        data: {
          preset_id: preset.id,
          prompt: text,
          negative: preset.supports_negative && negative.trim() ? negative.trim() : null,
          width: preset.supports_size ? intOrNull(width) : null,
          height: preset.supports_size ? intOrNull(height) : null,
          steps: preset.supports_steps ? intOrNull(steps) : null,
          frames: preset.supports_frames ? intOrNull(frames) : null,
          seed: preset.supports_seed ? intOrNull(seed) : null,
        },
      },
      {
        onSuccess: () => invalidateGens(),
        onError: (err: any) =>
          setFormError(err?.error || err?.detail || "Generation failed to queue — is ComfyUI running?"),
      }
    );
  };

  const handleAddToLibrary = (g: GraphicsGeneration) => {
    addToLibrary.mutate(
      { id: g.id },
      {
        onSuccess: (asset: any) => {
          setAddedMsg(`Added to library as ${asset?.filename ?? "a new asset"} — processing will start automatically.`);
          invalidateGens();
        },
      }
    );
  };

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <div className="flex justify-between items-center mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Graphics</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Generate images and video clips on the local GPU server using your installed ComfyUI models.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[380px_1fr] gap-6 items-start">
        {/* Left: form */}
        <div className="rounded-lg border border-border bg-card p-4 space-y-4">
          <div>
            <Label className="text-xs uppercase tracking-wide text-muted-foreground">Model preset</Label>
            {presetsLoading ? (
              <div className="text-sm text-muted-foreground mt-2">Loading presets…</div>
            ) : !presets?.length ? (
              <div className="text-sm text-muted-foreground mt-2">
                No presets found. Check that ComfyUI is running and reachable.
              </div>
            ) : (
              <div className="mt-2 space-y-1.5">
                {presets.map((p) => {
                  const selected = preset?.id === p.id;
                  return (
                    <button
                      key={p.id}
                      onClick={() => pickPreset(p)}
                      disabled={!p.available}
                      className={`w-full text-left rounded-md border px-3 py-2 transition-colors ${
                        selected
                          ? "border-primary/60 bg-primary/10"
                          : "border-border hover:bg-muted/50"
                      } ${!p.available ? "opacity-50 cursor-not-allowed" : ""}`}
                      title={p.available ? undefined : p.unavailable_reason ?? "Unavailable"}
                    >
                      <div className="flex items-center gap-2">
                        {p.source === "custom" ? (
                          <FileJson className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        ) : p.kind === "video" ? (
                          <Clapperboard className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        ) : (
                          <ImageIcon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        )}
                        <span className="text-sm font-medium truncate">{p.name}</span>
                        <Badge variant="outline" className="ml-auto shrink-0 text-[10px] uppercase">
                          {p.kind}
                        </Badge>
                      </div>
                      {p.description && (
                        <div className="text-xs text-muted-foreground mt-1 line-clamp-2">{p.description}</div>
                      )}
                      {!p.available && p.unavailable_reason && (
                        <div className="text-xs text-amber-400/80 mt-1">{p.unavailable_reason}</div>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <div>
            <Label htmlFor="gfx-prompt" className="text-xs uppercase tracking-wide text-muted-foreground">
              Prompt
            </Label>
            <Textarea
              id="gfx-prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder={
                preset?.kind === "video"
                  ? "A slow aerial shot over a city skyline at dusk, cinematic lighting…"
                  : "A broadcast news studio backdrop, deep blue tones, professional lighting…"
              }
              rows={4}
              className="mt-2"
            />
          </div>

          {preset?.supports_negative && (
            <div>
              <Label htmlFor="gfx-negative" className="text-xs uppercase tracking-wide text-muted-foreground">
                Negative prompt <span className="normal-case text-muted-foreground/70">(optional)</span>
              </Label>
              <Input
                id="gfx-negative"
                value={negative}
                onChange={(e) => setNegative(e.target.value)}
                placeholder="blurry, low quality, watermark"
                className="mt-2"
              />
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            {preset?.supports_size && (
              <>
                <div>
                  <Label htmlFor="gfx-width" className="text-xs uppercase tracking-wide text-muted-foreground">
                    Width
                  </Label>
                  <Input
                    id="gfx-width"
                    type="number"
                    value={width}
                    onChange={(e) => setWidth(e.target.value)}
                    placeholder={String(preset.default_width ?? "")}
                    className="mt-2"
                  />
                </div>
                <div>
                  <Label htmlFor="gfx-height" className="text-xs uppercase tracking-wide text-muted-foreground">
                    Height
                  </Label>
                  <Input
                    id="gfx-height"
                    type="number"
                    value={height}
                    onChange={(e) => setHeight(e.target.value)}
                    placeholder={String(preset.default_height ?? "")}
                    className="mt-2"
                  />
                </div>
              </>
            )}
            {preset?.supports_steps && (
              <div>
                <Label htmlFor="gfx-steps" className="text-xs uppercase tracking-wide text-muted-foreground">
                  Steps
                </Label>
                <Input
                  id="gfx-steps"
                  type="number"
                  value={steps}
                  onChange={(e) => setSteps(e.target.value)}
                  placeholder={String(preset.default_steps ?? "")}
                  className="mt-2"
                />
              </div>
            )}
            {preset?.supports_frames && (
              <div>
                <Label htmlFor="gfx-frames" className="text-xs uppercase tracking-wide text-muted-foreground">
                  Frames
                </Label>
                <Input
                  id="gfx-frames"
                  type="number"
                  value={frames}
                  onChange={(e) => setFrames(e.target.value)}
                  placeholder={String(preset.default_frames ?? "")}
                  className="mt-2"
                />
              </div>
            )}
            {preset?.supports_seed && (
              <div>
                <Label htmlFor="gfx-seed" className="text-xs uppercase tracking-wide text-muted-foreground">
                  Seed
                </Label>
                <div className="flex gap-1.5 mt-2">
                  <Input
                    id="gfx-seed"
                    type="number"
                    value={seed}
                    onChange={(e) => setSeed(e.target.value)}
                    placeholder="random"
                  />
                  <Button
                    variant="outline"
                    size="icon"
                    className="shrink-0"
                    title="Clear seed (random each run)"
                    onClick={() => setSeed("")}
                  >
                    <Dice5 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}
          </div>

          {formError && <div className="text-sm text-red-400">{formError}</div>}

          <Button
            className="w-full gap-2"
            onClick={handleGenerate}
            disabled={!preset?.available || createGen.isPending}
          >
            {createGen.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
            Generate {preset?.kind === "video" ? "video" : "image"}
          </Button>
          <p className="text-xs text-muted-foreground">
            Drop ComfyUI "API format" workflow JSON files into the workflows folder on the server to add your own
            presets.
          </p>
        </div>

        {/* Right: gallery */}
        <div className="space-y-3">
          {addedMsg && (
            <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 text-sm px-3 py-2 flex items-center justify-between gap-3">
              <span>{addedMsg}</span>
              <Link href="/library" className="underline shrink-0">
                Open library
              </Link>
            </div>
          )}

          {gensLoading ? (
            <div className="text-sm text-muted-foreground">Loading generations…</div>
          ) : generations.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border p-12 text-center text-muted-foreground">
              <Wand2 className="h-8 w-8 mx-auto mb-3 opacity-50" />
              <div className="font-medium">Nothing generated yet</div>
              <div className="text-sm mt-1">Pick a preset, write a prompt, and hit Generate.</div>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 2xl:grid-cols-3 gap-4">
              {generations.map((g) => (
                <div key={g.id} className="rounded-lg border border-border bg-card overflow-hidden flex flex-col">
                  <button
                    className="relative aspect-video bg-black/40 flex items-center justify-center overflow-hidden"
                    onClick={() => g.status === "success" && setPreview(g)}
                    disabled={g.status !== "success"}
                  >
                    {g.status === "success" && g.thumbnail_url ? (
                      <img
                        src={g.thumbnail_url}
                        alt={g.prompt}
                        className="w-full h-full object-cover"
                        onError={(e) => {
                          (e.currentTarget as HTMLImageElement).style.display = "none";
                        }}
                      />
                    ) : ACTIVE.has(g.status) ? (
                      <div className="text-center px-4">
                        <Loader2 className="h-6 w-6 animate-spin mx-auto text-muted-foreground" />
                        <div className="text-xs text-muted-foreground mt-2">
                          {g.status === "running"
                            ? `${Math.round(g.progress)}%`
                            : g.queue_position != null
                              ? `Queue position ${g.queue_position + 1}`
                              : "Waiting…"}
                        </div>
                        {g.status === "running" && (
                          <div className="h-1 w-32 bg-muted rounded-full mt-2 mx-auto overflow-hidden">
                            <div
                              className="h-full bg-primary transition-all"
                              style={{ width: `${Math.min(100, g.progress)}%` }}
                            />
                          </div>
                        )}
                      </div>
                    ) : g.status === "error" ? (
                      <div className="text-xs text-red-400 px-4 text-center line-clamp-3">
                        {g.error_message || "Generation failed"}
                      </div>
                    ) : g.kind === "video" ? (
                      <Clapperboard className="h-8 w-8 text-muted-foreground/40" />
                    ) : (
                      <ImageIcon className="h-8 w-8 text-muted-foreground/40" />
                    )}
                    <div className="absolute top-2 left-2">{statusBadge(g.status)}</div>
                    <Badge variant="outline" className="absolute top-2 right-2 text-[10px] uppercase bg-background/70">
                      {g.kind}
                    </Badge>
                  </button>
                  <div className="p-3 flex-1 flex flex-col gap-2">
                    <div className="text-sm line-clamp-2" title={g.prompt}>
                      {g.prompt}
                    </div>
                    <div className="text-xs text-muted-foreground flex flex-wrap gap-x-3 gap-y-0.5">
                      {g.preset_name && <span>{g.preset_name}</span>}
                      {g.width && g.height && (
                        <span>
                          {g.width}×{g.height}
                        </span>
                      )}
                      {g.kind === "video" && g.duration_seconds != null && <span>{g.duration_seconds}s</span>}
                      {g.seed != null && <span>seed {g.seed}</span>}
                    </div>
                    <div className="flex items-center gap-1.5 mt-auto pt-1">
                      {ACTIVE.has(g.status) && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="gap-1.5"
                          onClick={() => cancelGen.mutate({ id: g.id }, { onSuccess: invalidateGens })}
                        >
                          <Square className="h-3 w-3" /> Cancel
                        </Button>
                      )}
                      {g.status === "success" && g.output_url && (
                        <a href={g.output_url} download>
                          <Button size="sm" variant="outline" className="gap-1.5">
                            <Download className="h-3 w-3" /> Download
                          </Button>
                        </a>
                      )}
                      {g.status === "success" && g.kind === "video" && !g.media_id && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="gap-1.5"
                          disabled={addToLibrary.isPending}
                          onClick={() => handleAddToLibrary(g)}
                        >
                          <FolderInput className="h-3 w-3" /> Add to library
                        </Button>
                      )}
                      {g.media_id && (
                        <Link href={`/library/${g.media_id}`}>
                          <Button size="sm" variant="ghost" className="gap-1.5 text-emerald-400">
                            In library
                          </Button>
                        </Link>
                      )}
                      <Button
                        size="icon"
                        variant="ghost"
                        className="ml-auto h-8 w-8 text-muted-foreground hover:text-red-400"
                        onClick={() => {
                          if (ACTIVE.has(g.status) && !window.confirm("This generation is still running. Delete anyway?"))
                            return;
                          deleteGen.mutate({ id: g.id }, { onSuccess: invalidateGens });
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Preview dialog */}
      {preview && (
        <div
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-6"
          onClick={() => setPreview(null)}
        >
          <div
            className="max-w-5xl w-full max-h-[90vh] rounded-lg overflow-hidden bg-card border border-border flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-2 border-b border-border">
              <div className="text-sm truncate pr-4">{preview.prompt}</div>
              <Button size="sm" variant="ghost" onClick={() => setPreview(null)}>
                Close
              </Button>
            </div>
            <div className="flex-1 min-h-0 bg-black flex items-center justify-center">
              {preview.kind === "video" ? (
                <video
                  src={preview.output_url ?? undefined}
                  controls
                  autoPlay
                  className="max-h-[75vh] w-auto max-w-full"
                />
              ) : (
                <img
                  src={preview.output_url ?? undefined}
                  alt={preview.prompt}
                  className="max-h-[75vh] w-auto max-w-full object-contain"
                />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
