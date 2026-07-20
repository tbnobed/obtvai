import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ChevronLeft, ChevronRight, Pause, Play, Plus } from "lucide-react";
import { formatTC } from "@/lib/timecode";
import { TimecodeInput } from "./timecode-input";

export { formatTC as fmtTC };

export interface TrimPlayerHandle {
  seek: (t: number) => void;
  playRange: (from: number, to: number) => void;
  pause: () => void;
  getCurrentTime: () => number;
}

interface TrimPlayerProps {
  mediaId: string;
  /** Changes when a different beat is selected — resets window and playhead. */
  clipKey: string;
  inPoint: number;
  outPoint: number;
  fps?: number | null;
  disabled?: boolean;
  onChange: (inPoint: number, outPoint: number) => void;
  /** Fires on every timeupdate with the playhead position. */
  onTime?: (t: number) => void;
  /** Fires when a playRange() run reaches its stop point. */
  onRangeDone?: () => void;
}

const HANDLE_PAD = 2;

export const TrimPlayer = forwardRef<TrimPlayerHandle, TrimPlayerProps>(function TrimPlayer(
  { mediaId, clipKey, inPoint, outPoint, fps, disabled, onChange, onTime, onRangeDone }: TrimPlayerProps,
  ref,
) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<"in" | "out" | "seek" | null>(null);
  const frame = 1 / (fps && fps > 0 ? fps : 25);

  const [win, setWin] = useState<[number, number]>([Math.max(0, inPoint - HANDLE_PAD), outPoint + HANDLE_PAD]);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(inPoint);
  const [duration, setDuration] = useState<number | null>(null);

  /** While set, playback stops (not loops) at this time — used by play-around and play-all. */
  const stopAtRef = useRef<number | null>(null);
  /** Whether the active range should fire onRangeDone (external playRange) or not (internal play-around). */
  const notifyRangeDoneRef = useRef(false);
  /** Range queued before the media had metadata; started in onLoadedMetadata. */
  const pendingRangeRef = useRef<[number, number, boolean] | null>(null);

  const startRange = (from: number, to: number, notify: boolean) => {
    const v = videoRef.current;
    if (!v) return;
    if (v.readyState < HTMLMediaElement.HAVE_METADATA) {
      pendingRangeRef.current = [from, to, notify];
      return;
    }
    pendingRangeRef.current = null;
    stopAtRef.current = to;
    notifyRangeDoneRef.current = notify;
    v.currentTime = Math.max(0, from);
    setCurrent(Math.max(0, from));
    v.play().catch(() => {});
  };

  useImperativeHandle(ref, () => ({
    seek: (t: number) => {
      const v = videoRef.current;
      if (!v) return;
      stopAtRef.current = null;
      pendingRangeRef.current = null;
      v.currentTime = Math.max(0, t);
      setCurrent(Math.max(0, t));
    },
    playRange: (from: number, to: number) => startRange(from, to, true),
    pause: () => videoRef.current?.pause(),
    getCurrentTime: () => videoRef.current?.currentTime ?? 0,
  }));

  useEffect(() => {
    setWin([Math.max(0, inPoint - HANDLE_PAD), outPoint + HANDLE_PAD]);
    stopAtRef.current = null;
    pendingRangeRef.current = null;
    const v = videoRef.current;
    if (v) {
      v.pause();
      v.currentTime = inPoint;
    }
    setPlaying(false);
    setCurrent(inPoint);
    // Only reset when a different beat/asset is loaded, not on every trim nudge.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clipKey, mediaId]);

  // If in/out are typed beyond the visible window, grow the window to fit.
  useEffect(() => {
    setWin(([ws, we]) => [Math.min(ws, Math.max(0, inPoint)), Math.max(we, outPoint)]);
  }, [inPoint, outPoint]);

  const span = Math.max(win[1] - win[0], 0.1);
  const pct = (t: number) => `${Math.min(100, Math.max(0, ((t - win[0]) / span) * 100))}%`;

  const timeFromEvent = (clientX: number) => {
    const bar = barRef.current;
    if (!bar) return win[0];
    const r = bar.getBoundingClientRect();
    const p = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
    return win[0] + p * span;
  };

  const applyDrag = (clientX: number) => {
    const t = timeFromEvent(clientX);
    const v = videoRef.current;
    if (dragRef.current === "seek") {
      if (v) v.currentTime = t;
      setCurrent(t);
    } else if (dragRef.current === "in") {
      const ni = Math.max(0, Math.min(t, outPoint - frame));
      onChange(ni, outPoint);
      if (v) v.currentTime = ni;
    } else if (dragRef.current === "out") {
      const no = Math.max(t, inPoint + frame);
      onChange(inPoint, no);
      if (v) v.currentTime = no;
    }
  };

  useEffect(() => {
    const move = (e: PointerEvent) => {
      if (dragRef.current) applyDrag(e.clientX);
    };
    const up = () => {
      dragRef.current = null;
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
    return () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
    };
  });

  const startDrag = (mode: "in" | "out" | "seek") => (e: React.PointerEvent) => {
    if (disabled && mode !== "seek") return;
    e.preventDefault();
    dragRef.current = mode;
    applyDrag(e.clientX);
  };

  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      if (v.currentTime < inPoint - 0.05 || v.currentTime >= outPoint - 0.05) v.currentTime = inPoint;
      void v.play();
    } else {
      v.pause();
    }
  };

  const step = (dir: 1 | -1) => {
    const v = videoRef.current;
    if (!v) return;
    v.pause();
    const t = Math.max(0, v.currentTime + dir * frame);
    v.currentTime = t;
    setCurrent(t);
  };

  const playAround = (which: "in" | "out") => {
    if (which === "in") startRange(Math.max(0, inPoint - 1), inPoint + 2, false);
    else startRange(Math.max(0, outPoint - 2), outPoint + 1, false);
  };

  const markIn = () => {
    const v = videoRef.current;
    if (!v || disabled) return;
    onChange(Math.min(v.currentTime, outPoint - frame), outPoint);
  };

  const markOut = () => {
    const v = videoRef.current;
    if (!v || disabled) return;
    onChange(inPoint, Math.max(v.currentTime, inPoint + frame));
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      switch (e.key) {
        case " ": e.preventDefault(); togglePlay(); break;
        case "ArrowLeft": e.preventDefault(); step(-1); break;
        case "ArrowRight": e.preventDefault(); step(1); break;
        case "i": case "I": e.preventDefault(); markIn(); break;
        case "o": case "O": e.preventDefault(); markOut(); break;
        case "[": e.preventDefault(); playAround("in"); break;
        case "]": e.preventDefault(); playAround("out"); break;
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  return (
    <div className="space-y-2">
      <video
        ref={videoRef}
        src={`/api/media/${mediaId}/stream`}
        className="w-full aspect-video rounded bg-black"
        preload="metadata"
        onClick={togglePlay}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onLoadedMetadata={(e) => {
          setDuration(e.currentTarget.duration || null);
          const pending = pendingRangeRef.current;
          if (pending) startRange(pending[0], pending[1], pending[2]);
        }}
        onTimeUpdate={(e) => {
          const v = e.currentTarget;
          setCurrent(v.currentTime);
          onTime?.(v.currentTime);
          const stopAt = stopAtRef.current;
          if (stopAt != null) {
            if (!v.paused && v.currentTime >= stopAt - 0.02) {
              v.pause();
              stopAtRef.current = null;
              if (notifyRangeDoneRef.current) {
                notifyRangeDoneRef.current = false;
                onRangeDone?.();
              }
            }
          } else if (!v.paused && v.currentTime >= outPoint - 0.02) {
            v.currentTime = inPoint;
          }
        }}
      />

      {/* Trim bar: window is [in − handles, out + handles] so the editor can extend, not just shrink */}
      <div className="flex items-center gap-1.5">
        <Button
          size="icon" variant="ghost" className="h-7 w-7 shrink-0" title="Show 2 more seconds before"
          onClick={() => setWin(([ws, we]) => [Math.max(0, ws - 2), we])} disabled={win[0] <= 0}
        >
          <Plus className="h-3 w-3" />
        </Button>
        <div
          ref={barRef}
          className="relative h-9 flex-1 rounded bg-muted/60 cursor-pointer select-none touch-none"
          onPointerDown={startDrag("seek")}
        >
          {/* selected range */}
          <div
            className="absolute inset-y-0 bg-primary/25 border-y border-primary/50"
            style={{ left: pct(inPoint), width: `calc(${pct(outPoint)} - ${pct(inPoint)})` }}
          />
          {/* playhead */}
          <div className="absolute inset-y-0 w-px bg-red-400 pointer-events-none" style={{ left: pct(current) }} />
          {/* in handle */}
          <div
            className={`absolute inset-y-0 w-2 -ml-1 rounded-sm bg-primary ${disabled ? "opacity-40" : "cursor-ew-resize hover:bg-primary/80"}`}
            style={{ left: pct(inPoint) }}
            onPointerDown={startDrag("in")}
            title="Drag to trim the in-point"
          />
          {/* out handle */}
          <div
            className={`absolute inset-y-0 w-2 -ml-1 rounded-sm bg-primary ${disabled ? "opacity-40" : "cursor-ew-resize hover:bg-primary/80"}`}
            style={{ left: pct(outPoint) }}
            onPointerDown={startDrag("out")}
            title="Drag to trim the out-point"
          />
        </div>
        <Button
          size="icon" variant="ghost" className="h-7 w-7 shrink-0" title="Show 2 more seconds after"
          onClick={() => setWin(([ws, we]) => [ws, duration ? Math.min(duration, we + 2) : we + 2])}
          disabled={duration != null && win[1] >= duration}
        >
          <Plus className="h-3 w-3" />
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          <Button size="icon" variant="outline" className="h-8 w-8" onClick={() => step(-1)} title="Back one frame (←)">
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button size="icon" variant="outline" className="h-8 w-8" onClick={togglePlay} title="Play / pause the beat">
            {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          </Button>
          <Button size="icon" variant="outline" className="h-8 w-8" onClick={() => step(1)} title="Forward one frame (→)">
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
        <span className="font-mono text-xs text-muted-foreground">{formatTC(current, fps ?? 25)}</span>
        <div className="flex items-center gap-1.5 ml-auto">
          <Button size="sm" variant="ghost" className="h-8 px-2" onClick={() => playAround("in")}
            title="Play around the in-point: 1s before to 2s after ( [ )">
            <Play className="h-3 w-3 mr-1" /> In
          </Button>
          <Button size="sm" variant="outline" className="h-8" disabled={disabled}
            onClick={markIn} title="Set the in-point at the playhead (I)">
            Set IN
          </Button>
          <TimecodeInput value={inPoint} fps={fps} disabled={disabled}
            className="h-8 w-24 font-mono text-xs" title="In-point (mm:ss.ff)"
            onCommit={(v) => onChange(Math.min(v, outPoint - frame), outPoint)} />
          <span className="text-muted-foreground text-xs">→</span>
          <TimecodeInput value={outPoint} fps={fps} disabled={disabled}
            className="h-8 w-24 font-mono text-xs" title="Out-point (mm:ss.ff)"
            onCommit={(v) => onChange(inPoint, Math.max(v, inPoint + frame))} />
          <Button size="sm" variant="outline" className="h-8" disabled={disabled}
            onClick={markOut} title="Set the out-point at the playhead (O)">
            Set OUT
          </Button>
          <Button size="sm" variant="ghost" className="h-8 px-2" onClick={() => playAround("out")}
            title="Play around the out-point: 2s before to 1s after ( ] )">
            <Play className="h-3 w-3 mr-1" /> Out
          </Button>
        </div>
      </div>
      <p className="text-[10px] text-muted-foreground">
        Shortcuts: <kbd>Space</kbd> play/pause · <kbd>I</kbd>/<kbd>O</kbd> set in/out · <kbd>[</kbd>/<kbd>]</kbd> play around cut · <kbd>←</kbd>/<kbd>→</kbd> 1 frame
      </p>
    </div>
  );
});
