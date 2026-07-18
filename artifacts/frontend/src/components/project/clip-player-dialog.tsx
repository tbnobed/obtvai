import { useEffect, useRef, useState } from "react";
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
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [full, setFull] = useState(false);

  useEffect(() => {
    setFull(false);
  }, [clip]);

  const startAt = full ? 0 : (clip?.start_time ?? 0);
  const stopAt = full ? null : (clip?.end_time ?? null);

  useEffect(() => {
    const v = videoRef.current;
    if (!v || !clip) return;
    document.querySelectorAll("video").forEach((other) => {
      if (other !== v && !other.paused) other.pause();
    });
    const onLoaded = () => {
      v.currentTime = startAt;
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
  }, [clip, full]); // eslint-disable-line react-hooks/exhaustive-deps

  const replay = () => {
    const v = videoRef.current;
    if (!v || !clip) return;
    v.currentTime = startAt;
    v.play().catch(() => {});
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
              ref={videoRef}
              src={`/api/media/${clip.media_id}/stream`}
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
