import { useEffect, useRef } from "react";
import { Link } from "wouter";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ExternalLink, RotateCcw } from "lucide-react";
import { fmtTC } from "./trim-player";

export type PlayerClip = {
  media_id: string;
  start_time: number;
  end_time: number;
  label?: string | null;
  filename?: string | null;
};

export function ClipPlayerDialog({ clip, onClose }: { clip: PlayerClip | null; onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    const v = videoRef.current;
    if (!v || !clip) return;
    const onLoaded = () => {
      v.currentTime = clip.start_time;
      v.play().catch(() => {});
    };
    const onTime = () => {
      if (!v.paused && v.currentTime >= clip.end_time) v.pause();
    };
    v.addEventListener("loadedmetadata", onLoaded);
    v.addEventListener("timeupdate", onTime);
    if (v.readyState >= 1) onLoaded();
    return () => {
      v.removeEventListener("loadedmetadata", onLoaded);
      v.removeEventListener("timeupdate", onTime);
    };
  }, [clip]);

  const replay = () => {
    const v = videoRef.current;
    if (!v || !clip) return;
    v.currentTime = clip.start_time;
    v.play().catch(() => {});
  };

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
              <span className="font-mono">
                {fmtTC(clip.start_time)} – {fmtTC(clip.end_time)}
                {clip.filename ? <span className="ml-2 font-sans truncate">{clip.filename}</span> : null}
              </span>
              <div className="flex items-center gap-2 shrink-0">
                <Button size="sm" variant="outline" onClick={replay}>
                  <RotateCcw className="h-3.5 w-3.5 mr-1.5" /> Replay clip
                </Button>
                <Link href={`/library/${clip.media_id}?t=${clip.start_time}`}>
                  <Button size="sm" variant="ghost" title="Open the full asset in the player">
                    <ExternalLink className="h-3.5 w-3.5 mr-1.5" /> Full asset
                  </Button>
                </Link>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
