import { useState } from "react";
import { useListClipLists, getListClipListsQueryKey, useExportClipList, useRenderClipList, useCreateClipListRoughCut } from "@workspace/api-client-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Download, Play, Clapperboard, Smartphone, Monitor, ChevronDown, Wand2, Loader2 } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Link, useLocation } from "wouter";

const EXPORT_FORMATS: { format: string; label: string; hint: string }[] = [
  { format: "edl", label: "EDL", hint: "CMX3600 edit decision list" },
  { format: "fcpxml", label: "FCPXML", hint: "Final Cut Pro / DaVinci Resolve" },
  { format: "otio", label: "OTIO", hint: "OpenTimelineIO timeline" },
  { format: "csv", label: "CSV", hint: "Spreadsheet" },
  { format: "json", label: "JSON", hint: "Raw clip data" },
];

export default function ClipLists() {
  const [, navigate] = useLocation();
  const { data: lists, isLoading } = useListClipLists({ query: { queryKey: getListClipListsQueryKey() } });
  const exportMutation = useExportClipList();
  const renderMutation = useRenderClipList();
  const roughCutMutation = useCreateClipListRoughCut();

  const [exportData, setExportData] = useState<string | null>(null);
  const [exportFilename, setExportFilename] = useState<string | null>(null);
  const [renderTarget, setRenderTarget] = useState<{ id: string; name: string; clipCount: number } | null>(null);
  const [preset, setPreset] = useState<"original" | "vertical">("original");
  const [burnCaptions, setBurnCaptions] = useState(false);

  const handleExport = (listId: string, format: string) => {
    exportMutation.mutate({ id: listId, data: { format } }, {
      onSuccess: (res) => {
        setExportData(res.content);
        setExportFilename(res.filename ?? `export.${format}`);
      }
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

  const startRoughCut = (listId: string) => {
    roughCutMutation.mutate({ id: listId, data: { preset: "original", burn_captions: false } }, {
      onSuccess: () => navigate("/reels"),
    });
  };

  const openRender = (list: { id: string; name: string; clips: unknown[] }) => {
    setPreset("original");
    setBurnCaptions(false);
    setRenderTarget({ id: list.id, name: list.name, clipCount: list.clips.length });
  };

  const submitRender = () => {
    if (!renderTarget) return;
    renderMutation.mutate(
      { id: renderTarget.id, data: { preset, burn_captions: burnCaptions } },
      {
        onSuccess: () => {
          setRenderTarget(null);
          navigate("/exports");
        },
      },
    );
  };

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold tracking-tight">Clip Lists</h1>
        <Button disabled>Create New List</Button>
      </div>

      <Dialog open={!!exportData} onOpenChange={(open) => !open && setExportData(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Export Result</DialogTitle>
          </DialogHeader>
          <pre className="bg-muted p-4 rounded-md overflow-x-auto text-xs font-mono max-h-96">
            {exportData}
          </pre>
          <div className="flex gap-2">
            <Button onClick={downloadExport}>
              <Download className="h-4 w-4 mr-2" /> Download {exportFilename}
            </Button>
            <Button variant="outline" onClick={() => navigator.clipboard.writeText(exportData || "")}>Copy to Clipboard</Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={!!renderTarget} onOpenChange={(open) => !open && setRenderTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Clapperboard className="h-5 w-5" /> Render "{renderTarget?.name}"
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-5">
            <p className="text-sm text-muted-foreground">
              Renders {renderTarget?.clipCount} clip{renderTarget?.clipCount === 1 ? "" : "s"} to standalone MP4 files.
            </p>
            <div className="space-y-2">
              <Label>Format</Label>
              <div className="grid grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() => setPreset("original")}
                  className={`flex flex-col items-center gap-2 rounded-lg border p-4 text-sm transition-colors ${
                    preset === "original" ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:bg-muted"
                  }`}
                >
                  <Monitor className="h-6 w-6" />
                  <span className="font-medium">Original</span>
                  <span className="text-xs">Keeps source framing</span>
                </button>
                <button
                  type="button"
                  onClick={() => setPreset("vertical")}
                  className={`flex flex-col items-center gap-2 rounded-lg border p-4 text-sm transition-colors ${
                    preset === "vertical" ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:bg-muted"
                  }`}
                >
                  <Smartphone className="h-6 w-6" />
                  <span className="font-medium">Vertical 9:16</span>
                  <span className="text-xs">1080×1920, center crop</span>
                </button>
              </div>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-border p-4">
              <div>
                <Label htmlFor="burn-captions" className="font-medium">Burn in captions</Label>
                <p className="text-xs text-muted-foreground mt-1">Overlays transcript text onto the video</p>
              </div>
              <Switch id="burn-captions" checked={burnCaptions} onCheckedChange={setBurnCaptions} />
            </div>
            {renderMutation.isError && (
              <p className="text-sm text-red-400">Render request failed — is the list empty?</p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenderTarget(null)}>Cancel</Button>
            <Button onClick={submitRender} disabled={renderMutation.isPending}>
              {renderMutation.isPending ? "Starting..." : "Start Render"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {isLoading ? (
        <div className="grid gap-6 md:grid-cols-2">
          {[...Array(2)].map((_, i) => <Card key={i} className="animate-pulse h-48 bg-muted" />)}
        </div>
      ) : lists?.length ? (
        <div className="grid gap-6 md:grid-cols-2">
          {lists.map(list => (
            <Card key={list.id} className="flex flex-col">
              <CardHeader className="flex flex-row items-start justify-between">
                <div>
                  <CardTitle>{list.name}</CardTitle>
                  <p className="text-sm text-muted-foreground mt-1">{list.description}</p>
                </div>
                <div className="flex gap-2">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button size="sm" variant="outline">
                        <Download className="h-4 w-4 mr-2" /> Export <ChevronDown className="h-3 w-3 ml-1" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {EXPORT_FORMATS.map((f) => (
                        <DropdownMenuItem key={f.format} onClick={() => handleExport(list.id, f.format)}>
                          <div>
                            <div className="font-medium">{f.label}</div>
                            <div className="text-xs text-muted-foreground">{f.hint}</div>
                          </div>
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => startRoughCut(list.id)}
                    disabled={!list.clips.length || roughCutMutation.isPending}
                  >
                    {roughCutMutation.isPending
                      ? <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      : <Wand2 className="h-4 w-4 mr-2" />} Rough Cut
                  </Button>
                  <Button size="sm" onClick={() => openRender(list)} disabled={!list.clips.length}>
                    <Clapperboard className="h-4 w-4 mr-2" /> Render
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col">
                <div className="text-sm font-medium mb-3">{list.clips.length} Clips</div>
                <div className="space-y-2 flex-1 overflow-y-auto max-h-48">
                  {list.clips.map((clip, i) => (
                    <div key={clip.id} className="flex items-center justify-between bg-muted/50 p-2 rounded text-sm">
                      <div className="truncate pr-4 flex-1">
                        <span className="text-muted-foreground mr-2">{i+1}.</span>
                        {clip.label || clip.filename || clip.media_id}
                      </div>
                      <div className="flex items-center gap-3 shrink-0">
                        <span className="font-mono text-xs">{clip.start_time}s - {clip.end_time}s</span>
                        <Link href={`/library/${clip.media_id}?t=${clip.start_time}`}>
                          <Button size="icon" variant="ghost" className="h-6 w-6"><Play className="h-3 w-3" /></Button>
                        </Link>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <div className="text-center text-muted-foreground py-20 border border-dashed border-border rounded-lg">
          No clip lists created yet.
        </div>
      )}
    </div>
  );
}
