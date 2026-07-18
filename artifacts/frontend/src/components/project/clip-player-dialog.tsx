import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Expand, RotateCcw } from "lucide-react";
import { fmtTC } from "./trim-player";

export type PlayerClip = {
  media_id: string;
  start_time: number;
  end_time?: number | null;
  label?: string | null;
  filename?: string | null;
};

export function ClipPlayerDialog({ clip, onClose }: { clip: PlayerClip | null; onClose: () => void }) {
  const [videoEl, setVideoEl] = useState<HTMLVideoElement | null>(null);
  const [full, setFull] = useState(false);

  useEffect(() => {
    setFull(false);
  }, [clip]);

  const startAt = full ? 0 : (clip?.start_time ?? 0);
  const stopAt = full ? null : (clip?.end_time ?? null);

  // Media fragment: the browser natively starts at startAt and pauses at
  // stopAt even if no JS listener is attached. The listeners below are a
  // second layer for browsers with partial fragment support, plus replay.
  const src = clip
    ? `/api/media/${clip.media_id}/stream#t=${startAt}${stopAt != null ? `,${stopAt}` : ""}`
    : undefined;

  useEffect(() => {
    const v = videoEl;
    if (!v || !clip) return;
    document.querySelectorAll("video").forEach((other) => {
      if (other !== v && !other.paused) other.pause();
    });
    const onLoaded = () => {
      if (Math.abs(v.currentTime - startAt) > 0.5) v.currentTime = startAt;
      v.play().catch(() => {});
    };
    const onTime = () => {
      if (stopAt != null && !v.paused && v.currentTime >= stopAt) v.pause();
    };
    v.addEventListener("loadedmetadata", onLoaded);
    v.addEventListener("timeupdate", onTime);
    if (v.readyState >= 1) onLoaded();
    return () => {
      v.removeEventListener("loadedmetadata", onLoaded);
      v.removeEventListener("timeupdate", onTime);
    };
  }, [videoEl, clip, full]); // eslint-disable-line react-hooks/exhaustive-deps

  const replay = () => {
    if (!videoEl) return;
    videoEl.currentTime = startAt;
    videoEl.play().catch(() => {});
  };

  const isClipRange = clip?.end_time != null;

  return (
    <Dialog open={!!clip} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="truncate pr-8">
            {clip?.label || clip?.filename || "Clip"}
          </DialogTitle>
        </DialogHeader>
        {clip && (
          <div className="space-y-3">
            <video
              key={src}
              ref={setVideoEl}
              src={src}
              controls
              autoPlay
              className="w-full max-h-[60vh] rounded bg-black object-contain"
            />
            <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
              <span className="min-w-0 truncate">
                {isClipRange && !full ? (
                  <span className="font-mono">{fmtTC(clip.start_time)} – {fmtTC(clip.end_time!)}</span>
                ) : (
                  <span className="font-mono">Full asset</span>
                )}
                {clip.filename ? <span className="ml-2">{clip.filename}</span> : null}
              </span>
              <div className="flex items-center gap-2 shrink-0">
                <Button size="sm" variant="outline" onClick={replay}>
                  <RotateCcw className="h-3.5 w-3.5 mr-1.5" /> Replay
                </Button>
                {isClipRange && (
                  <Button
                    size="sm"
                    variant={full ? "default" : "ghost"}
                    title={full ? "Back to just this clip" : "Watch the whole file right here"}
                    onClick={() => setFull((f) => !f)}
                  >
                    <Expand className="h-3.5 w-3.5 mr-1.5" /> {full ? "Clip only" : "Full asset"}
                  </Button>
                )}
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
