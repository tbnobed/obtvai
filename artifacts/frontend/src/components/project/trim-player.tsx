import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ChevronLeft, ChevronRight, Pause, Play, Plus } from "lucide-react";

export function fmtTC(s: number, fps = 25) {
  if (!Number.isFinite(s) || s < 0) s = 0;
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  const fr = Math.floor((s - Math.floor(s)) * fps);
  return `${m}:${String(sec).padStart(2, "0")}.${String(fr).padStart(2, "0")}`;
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
}

const HANDLE_PAD = 2;

export function TrimPlayer({ mediaId, clipKey, inPoint, outPoint, fps, disabled, onChange }: TrimPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<"in" | "out" | "seek" | null>(null);
  const frame = 1 / (fps && fps > 0 ? fps : 25);

  const [win, setWin] = useState<[number, number]>([Math.max(0, inPoint - HANDLE_PAD), outPoint + HANDLE_PAD]);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(inPoint);
  const [duration, setDuration] = useState<number | null>(null);

  useEffect(() => {
    setWin([Math.max(0, inPoint - HANDLE_PAD), outPoint + HANDLE_PAD]);
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

  const numChange = (which: "in" | "out") => (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseFloat(e.target.value);
    if (!Number.isFinite(val) || val < 0) return;
    if (which === "in") onChange(Math.min(val, outPoint - frame), outPoint);
    else onChange(inPoint, Math.max(val, inPoint + frame));
  };

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
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration || null)}
        onTimeUpdate={(e) => {
          const v = e.currentTarget;
          setCurrent(v.currentTime);
          if (!v.paused && v.currentTime >= outPoint - 0.02) v.currentTime = inPoint;
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
        <span className="font-mono text-xs text-muted-foreground">{fmtTC(current, fps ?? 25)}</span>
        <div className="flex items-center gap-1.5 ml-auto">
          <Button size="sm" variant="outline" className="h-8" disabled={disabled}
            onClick={() => onChange(Math.min(current, outPoint - frame), outPoint)} title="Set the in-point at the playhead">
            Set IN
          </Button>
          <Input type="number" step={Math.round(frame * 100) / 100} min={0} disabled={disabled}
            className="h-8 w-24 font-mono text-xs" value={Number(inPoint.toFixed(2))} onChange={numChange("in")} />
          <span className="text-muted-foreground text-xs">→</span>
          <Input type="number" step={Math.round(frame * 100) / 100} min={0} disabled={disabled}
            className="h-8 w-24 font-mono text-xs" value={Number(outPoint.toFixed(2))} onChange={numChange("out")} />
          <Button size="sm" variant="outline" className="h-8" disabled={disabled}
            onClick={() => onChange(inPoint, Math.max(current, inPoint + frame))} title="Set the out-point at the playhead">
            Set OUT
          </Button>
        </div>
      </div>
    </div>
  );
}
