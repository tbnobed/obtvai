import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { CutClip } from "@workspace/api-client-react";
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { formatTC } from "@/lib/timecode";

/**
 * Plays a draft cut clip-by-clip straight from the source files — no render
 * needed. The timeline shows every clip as a segment with a frame thumbnail;
 * click or drag anywhere on it to scrub through the entire cut.
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
  // Offset (seconds into the current clip) to seek once media is ready.
  const pendingOffset = useRef(0);
  const [clipElapsed, setClipElapsed] = useState(0);
  const [scrubbing, setScrubbing] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const clip = clips[index];

  const durations = useMemo(() => clips.map((c) => Math.max(0.01, c.end_time - c.start_time)), [clips]);
  const total = useMemo(() => durations.reduce((s, d) => s + d, 0), [durations]);
  const starts = useMemo(() => {
    const out: number[] = [];
    let acc = 0;
    for (const d of durations) { out.push(acc); acc += d; }
    return out;
  }, [durations]);

  useEffect(() => {
    if (open) {
      setIndex(0);
      pendingOffset.current = 0;
      setClipElapsed(0);
      setPlaying(true);
    }
  }, [open]);

  // Seek to in-point (+ pending scrub offset) when the clip changes, track
  // time, stop at the out-point and auto-advance.
  useEffect(() => {
    const v = videoRef.current;
    if (!v || !clip || !open) return;
    const target = clip.start_time + pendingOffset.current;
    const onLoaded = () => {
      if (Math.abs(v.currentTime - target) > 0.3) v.currentTime = target;
      if (playing && !scrubbing) v.play().catch(() => {});
    };
    const onTime = () => {
      setClipElapsed(Math.max(0, v.currentTime - clip.start_time));
      if (scrubbing) return;
      if (v.currentTime >= clip.end_time - 0.05) {
        if (index < clips.length - 1) {
          pendingOffset.current = 0;
          setIndex((i) => i + 1);
        } else {
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
  }, [clip, index, clips.length, open, playing, scrubbing]);

  const globalTime = (starts[index] ?? 0) + Math.min(clipElapsed, durations[index] ?? 0);

  // Map a global cut time to (clip index, offset) and seek there.
  const seekGlobal = useCallback((t: number) => {
    const clamped = Math.max(0, Math.min(total - 0.05, t));
    let i = 0;
    while (i < clips.length - 1 && clamped >= starts[i + 1]) i++;
    const offset = clamped - starts[i];
    const v = videoRef.current;
    if (i === index && v && clips[i]) {
      v.currentTime = clips[i].start_time + offset;
      setClipElapsed(offset);
    } else {
      pendingOffset.current = offset;
      setClipElapsed(offset);
      setIndex(i);
    }
  }, [clips, starts, total, index]);

  const timeFromPointer = (e: React.PointerEvent) => {
    const el = timelineRef.current;
    if (!el) return 0;
    const rect = el.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    return frac * total;
  };

  const onPointerDown = (e: React.PointerEvent) => {
    e.preventDefault();
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    setScrubbing(true);
    videoRef.current?.pause();
    seekGlobal(timeFromPointer(e));
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!scrubbing) return;
    seekGlobal(timeFromPointer(e));
  };
  const onPointerUp = (e: React.PointerEvent) => {
    if (!scrubbing) return;
    seekGlobal(timeFromPointer(e));
    setScrubbing(false);
    if (playing) videoRef.current?.play().catch(() => {});
  };

  if (!clip) return null;

  const goToClip = (i: number) => {
    pendingOffset.current = 0;
    setClipElapsed(0);
    setIndex(Math.max(0, Math.min(clips.length - 1, i)));
    setPlaying(true);
  };

  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      if (index === clips.length - 1 && v.currentTime >= clip.end_time - 0.1) {
        goToClip(0);
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
        <div className="space-y-1.5 select-none">
          {/* Scrubbable timeline: each segment shows a frame thumbnail */}
          <div
            ref={timelineRef}
            className="relative flex h-14 w-full cursor-ew-resize gap-px overflow-hidden rounded touch-none"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            data-testid="preview-timeline"
          >
            {clips.map((c, i) => (
              <div
                key={i}
                title={`${i + 1}. ${c.filename} · ${formatTC(c.start_time)}–${formatTC(c.end_time)}`}
                style={{ flexGrow: durations[i] }}
                className={`relative h-full min-w-[6px] overflow-hidden bg-muted ${i === index ? "" : "opacity-60"}`}
              >
                <img
                  src={`/api/media/${c.media_id}/frame?t=${Math.max(0, c.start_time).toFixed(2)}`}
                  alt=""
                  loading="lazy"
                  draggable={false}
                  className="h-full w-full object-cover pointer-events-none"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                />
                {i === index && <div className="absolute inset-0 ring-2 ring-inset ring-primary" />}
              </div>
            ))}
            {/* Playhead */}
            <div
              className="pointer-events-none absolute top-0 h-full w-0.5 bg-white shadow-[0_0_4px_rgba(0,0,0,0.9)]"
              style={{ left: `${total ? (globalTime / total) * 100 : 0}%` }}
            />
          </div>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span className="truncate pr-3">
              {clip.filename} · {formatTC(clip.start_time)}–{formatTC(clip.end_time)}
              {clip.snippet ? ` · “${clip.snippet.slice(0, 60)}${clip.snippet.length > 60 ? "…" : ""}”` : ""}
            </span>
            <span className="shrink-0 tabular-nums">
              {formatTC(globalTime)} / {formatTC(total)}
            </span>
          </div>
        </div>
        <div className="flex items-center justify-center gap-2">
          <Button size="icon" variant="outline" onClick={() => goToClip(index - 1)} disabled={index === 0} data-testid="button-preview-prev">
            <SkipBack className="h-4 w-4" />
          </Button>
          <Button size="icon" onClick={togglePlay} data-testid="button-preview-playpause">
            {playing && !scrubbing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          </Button>
          <Button size="icon" variant="outline" onClick={() => goToClip(index + 1)} disabled={index >= clips.length - 1} data-testid="button-preview-next">
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
