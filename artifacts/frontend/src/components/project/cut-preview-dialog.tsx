import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { CutClip } from "@workspace/api-client-react";
import { Maximize2, Minimize2, Pause, Play, SkipBack, SkipForward, X } from "lucide-react";
import { formatTC } from "@/lib/timecode";

/**
 * Plays a draft cut clip-by-clip straight from the source files — no render
 * needed. The timeline shows every clip as a segment with a frame thumbnail;
 * click or drag anywhere on it to scrub through the entire cut.
 */
export function CutPreviewPlayer({
  clips,
  open,
  onClose,
  initialIndex = 0,
  compact = false,
  onToggleExpand,
  expanded = false,
  vertical = false,
  autoPlayInitial = true,
}: {
  clips: CutClip[];
  open: boolean;
  onClose: () => void;
  /** Clip to start playback from (e.g. the row the user clicked). */
  initialIndex?: number;
  /** Docked mode: smaller video, no filmstrip/footer — leaves room for the clip list below. */
  compact?: boolean;
  /** When set, shows an expand/shrink button in the header. */
  onToggleExpand?: () => void;
  expanded?: boolean;
  /** Preview the 9:16 center crop the vertical render will apply. */
  vertical?: boolean;
  /** Autoplay on first open. Set false for the always-docked player so it doesn't start on page load; later clip selections still play. */
  autoPlayInitial?: boolean;
}) {
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  // Offset (seconds into the current clip) to seek once media is ready.
  const pendingOffset = useRef(0);
  const [clipElapsed, setClipElapsed] = useState(0);
  const [scrubbing, setScrubbing] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const firstOpen = useRef(true);
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
      setIndex(Math.max(0, Math.min(clips.length - 1, initialIndex)));
      pendingOffset.current = 0;
      seekedFor.current = -1;
      setClipElapsed(0);
      // Don't autoplay the very first open when autoPlayInitial is off (the
      // docked player is open on page load); explicit clip picks still play.
      setPlaying(firstOpen.current ? autoPlayInitial : true);
      firstOpen.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialIndex]);

  // Tracks which clip index we've already seeked for — the effect re-runs on
  // play/pause/scrub changes too, and must not re-seek (it would snap the
  // playhead back and skip parts of the clip).
  const seekedFor = useRef(-1);

  // Seek to in-point (+ pending scrub offset) when the clip changes, track
  // time, stop at the out-point and auto-advance.
  useEffect(() => {
    const v = videoRef.current;
    if (!v || !clip || !open) return;
    const onLoaded = () => {
      if (seekedFor.current !== index) {
        const target = clip.start_time + pendingOffset.current;
        pendingOffset.current = 0;
        seekedFor.current = index;
        if (Math.abs(v.currentTime - target) > 0.3) v.currentTime = target;
      }
      if (playing && !scrubbing) v.play().catch(() => {});
    };
    const onTime = () => {
      setClipElapsed(Math.max(0, v.currentTime - clip.start_time));
      if (scrubbing) return;
      if (seekedFor.current !== index) return; // seek for this clip hasn't landed yet
      if (v.currentTime >= clip.end_time - 0.05) {
        if (index < clips.length - 1) {
          pendingOffset.current = 0;
          seekedFor.current = -1;
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
      seekedFor.current = -1;
      setClipElapsed(offset);
      setIndex(i);
    }
  }, [clips, starts, total, index]);

  const timeFromPointer = (e: React.PointerEvent) => {
    const el = e.currentTarget as HTMLElement;
    const rect = el.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    return frac * total;
  };

  const onPointerDown = (e: React.PointerEvent) => {
    e.preventDefault();
    // Capture on the container — capturing the child under the pointer loses
    // the pointerup if that child re-renders mid-drag, leaving scrubbing stuck.
    e.currentTarget.setPointerCapture?.(e.pointerId);
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

  if (!open || !clip) return null;

  const goToClip = (i: number) => {
    pendingOffset.current = 0;
    seekedFor.current = -1;
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
    <div className="space-y-3 rounded-lg border border-border bg-black/30 p-3" data-testid="inline-cut-preview">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">
            Preview draft cut — clip {index + 1} of {clips.length}
          </span>
          <div className="flex items-center gap-1">
            {onToggleExpand && (
              <Button
                size="icon" variant="ghost" className="h-7 w-7"
                onClick={onToggleExpand}
                title={expanded ? "Back to docked view" : "Open in larger window"}
                data-testid="button-toggle-preview-size"
              >
                {expanded ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
              </Button>
            )}
            <Button size="icon" variant="ghost" className="h-7 w-7" onClick={onClose} title="Close preview" data-testid="button-close-preview">
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>
        <video
          key={clip.media_id}
          ref={videoRef}
          src={`/api/media/${clip.media_id}/stream#t=${clip.start_time},${clip.end_time}`}
          className={
            vertical
              ? `w-auto mx-auto aspect-[9/16] ${compact ? "max-h-[30vh]" : expanded ? "max-h-[62vh]" : "max-h-[48vh]"} rounded bg-black object-cover`
              : `w-full aspect-video ${compact ? "max-h-[30vh]" : expanded ? "max-h-[62vh]" : "max-h-[48vh]"} rounded bg-black object-contain`
          }
          onClick={togglePlay}
          playsInline
        />
        {/* Playback bar: play/pause + click/drag-to-scrub progress */}
        <div className="flex items-center gap-3 select-none">
          <Button size="icon" className="h-9 w-9 shrink-0" onClick={togglePlay} data-testid="button-playbar-playpause">
            {playing && !scrubbing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          </Button>
          <div
            className="group relative h-6 flex-1 cursor-pointer touch-none"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            data-testid="preview-seekbar"
          >
            <div className="absolute top-1/2 -translate-y-1/2 h-1.5 w-full rounded-full bg-muted group-hover:h-2 transition-all" />
            <div
              className="absolute top-1/2 -translate-y-1/2 h-1.5 rounded-full bg-primary group-hover:h-2 transition-all"
              style={{ width: `${total ? (globalTime / total) * 100 : 0}%` }}
            />
            <div
              className="absolute top-1/2 h-3.5 w-3.5 -translate-y-1/2 -translate-x-1/2 rounded-full bg-primary shadow"
              style={{ left: `${total ? (globalTime / total) * 100 : 0}%` }}
            />
          </div>
          <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
            {formatTC(globalTime)} / {formatTC(total)}
          </span>
        </div>
        <div className="space-y-1.5 select-none">
          {/* Scrubbable timeline: each segment shows a frame thumbnail */}
          <div
            className={`relative flex ${compact ? "h-8" : "h-14"} w-full cursor-ew-resize gap-px overflow-hidden rounded touch-none`}
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
        {!compact && (
          <>
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
          </>
        )}
    </div>
  );
}
