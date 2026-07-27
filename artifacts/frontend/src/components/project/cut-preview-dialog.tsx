import { useEffect, useRef, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { CutClip } from "@workspace/api-client-react";
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { formatTC } from "@/lib/timecode";

/**
 * Plays a draft cut clip-by-clip straight from the source files — no render
 * needed. Seeks each clip's in-point, pauses at its out-point, then advances
 * to the next clip. Cuts are near-instant when clips share a source file;
 * switching files re-buffers briefly.
 */
export function CutPreviewDialog({
  clips,
  open,
  onClose,
}: {
  clips: CutClip[];
  open: boolean;
  onClose: () => void;
}) {
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const clip = clips[index];

  useEffect(() => {
    if (open) {
      setIndex(0);
      setPlaying(true);
    }
  }, [open]);

  // Seek to the in-point when the clip changes / metadata loads, stop at the
  // out-point and auto-advance.
  useEffect(() => {
    const v = videoRef.current;
    if (!v || !clip || !open) return;
    const onLoaded = () => {
      if (Math.abs(v.currentTime - clip.start_time) > 0.4) v.currentTime = clip.start_time;
      if (playing) v.play().catch(() => {});
    };
    const onTime = () => {
      if (v.currentTime >= clip.end_time - 0.05) {
        if (index < clips.length - 1) setIndex((i) => i + 1);
        else {
          v.pause();
          setPlaying(false);
        }
      }
    };
    v.addEventListener("loadedmetadata", onLoaded);
    v.addEventListener("timeupdate", onTime);
    if (v.readyState >= 1) onLoaded();
    return () => {
      v.removeEventListener("loadedmetadata", onLoaded);
      v.removeEventListener("timeupdate", onTime);
    };
  }, [clip, index, clips.length, open, playing]);

  if (!clip) return null;

  const elapsedBefore = clips.slice(0, index).reduce((s, c) => s + (c.end_time - c.start_time), 0);
  const total = clips.reduce((s, c) => s + (c.end_time - c.start_time), 0);

  const goTo = (i: number) => {
    setIndex(Math.max(0, Math.min(clips.length - 1, i)));
    setPlaying(true);
  };

  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      // If we're past the out-point (end of preview), restart from the top.
      if (index === clips.length - 1 && v.currentTime >= clip.end_time - 0.1) {
        goTo(0);
        return;
      }
      v.play().catch(() => {});
      setPlaying(true);
    } else {
      v.pause();
      setPlaying(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle className="text-base">
            Preview draft cut — clip {index + 1} of {clips.length}
          </DialogTitle>
        </DialogHeader>
        <video
          key={clip.media_id}
          ref={videoRef}
          src={`/api/media/${clip.media_id}/stream#t=${clip.start_time},${clip.end_time}`}
          className="w-full aspect-video rounded bg-black"
          onClick={togglePlay}
          playsInline
        />
        <div className="space-y-1.5">
          {/* Cut timeline: click a segment to jump */}
          <div className="flex h-2 w-full gap-px overflow-hidden rounded">
            {clips.map((c, i) => (
              <button
                key={i}
                type="button"
                title={`${i + 1}. ${c.filename}`}
                onClick={() => goTo(i)}
                style={{ flexGrow: Math.max(0.5, c.end_time - c.start_time) }}
                className={`h-full min-w-[3px] ${i === index ? "bg-primary" : i < index ? "bg-primary/40" : "bg-muted"}`}
              />
            ))}
          </div>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span className="truncate pr-3">
              {clip.filename} · {formatTC(clip.start_time)}–{formatTC(clip.end_time)}
              {clip.snippet ? ` · “${clip.snippet.slice(0, 60)}${clip.snippet.length > 60 ? "…" : ""}”` : ""}
            </span>
            <span className="shrink-0">
              {formatTC(elapsedBefore)} / {formatTC(total)}
            </span>
          </div>
        </div>
        <div className="flex items-center justify-center gap-2">
          <Button size="icon" variant="outline" onClick={() => goTo(index - 1)} disabled={index === 0} data-testid="button-preview-prev">
            <SkipBack className="h-4 w-4" />
          </Button>
          <Button size="icon" onClick={togglePlay} data-testid="button-preview-playpause">
            {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          </Button>
          <Button size="icon" variant="outline" onClick={() => goTo(index + 1)} disabled={index >= clips.length - 1} data-testid="button-preview-next">
            <SkipForward className="h-4 w-4" />
          </Button>
        </div>
        <p className="text-xs text-muted-foreground text-center">
          Rough preview straight from the source files — transitions between different files may pause briefly to buffer. Render for the real thing.
        </p>
      </DialogContent>
    </Dialog>
  );
}
