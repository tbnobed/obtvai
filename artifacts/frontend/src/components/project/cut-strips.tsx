import { useMemo } from "react";
import {
  useGetMediaTranscript, getGetMediaTranscriptQueryKey,
  useGetAssetPeople, getGetAssetPeopleQueryKey,
} from "@workspace/api-client-react";
import type { CutClip } from "@workspace/api-client-react";
import { formatTC } from "@/lib/timecode";

/** Timeline strips for the draft cut — transcript, sentiment/emotion, and people,
 *  mapped from each clip's source asset onto the cut's timeline. */

const EMOTION_COLORS: Record<string, string> = {
  joy: "#facc15",
  happiness: "#facc15",
  surprise: "#fb923c",
  anger: "#ef4444",
  fear: "#a855f7",
  sadness: "#3b82f6",
  disgust: "#84cc16",
  neutral: "#3f3f46",
};
const emotionColor = (e?: string | null) => EMOTION_COLORS[e ?? ""] ?? "#3f3f46";

const PERSON_COLORS = ["#10b981", "#0ea5e9", "#f59e0b", "#d946ef", "#f43f5e", "#8b5cf6"];

function ClipCell({
  clip,
  kind,
  personColors,
}: {
  clip: CutClip;
  kind: "speech" | "emotion" | "people";
  personColors: Map<string, string>;
}) {
  const { data: transcript } = useGetMediaTranscript(clip.media_id, {}, {
    query: { queryKey: getGetMediaTranscriptQueryKey(clip.media_id, {}), enabled: kind !== "people" },
  });
  const { data: people } = useGetAssetPeople(clip.media_id, {
    query: { queryKey: getGetAssetPeopleQueryKey(clip.media_id), enabled: kind === "people" },
  });

  const dur = Math.max(0.001, clip.end_time - clip.start_time);
  const pct = (t: number) => `${Math.min(100, Math.max(0, ((t - clip.start_time) / dur) * 100))}%`;
  const widthPct = (a: number, b: number) =>
    `${Math.max(0.6, Math.min(100, ((Math.min(b, clip.end_time) - Math.max(a, clip.start_time)) / dur) * 100))}%`;

  const segs = useMemo(
    () => (transcript ?? []).filter((s) => s.end_time > clip.start_time && s.start_time < clip.end_time),
    [transcript, clip.start_time, clip.end_time],
  );

  if (kind === "emotion") {
    if (!segs.length) return null;
    const stops = segs
      .map((s) => {
        const mid = Math.min(clip.end_time, Math.max(clip.start_time, (s.start_time + s.end_time) / 2));
        return `${emotionColor(s.emotion)} ${(((mid - clip.start_time) / dur) * 100).toFixed(1)}%`;
      })
      .join(", ");
    return (
      <div
        className="absolute inset-0"
        style={{ background: segs.length > 1 ? `linear-gradient(90deg, ${stops})` : emotionColor(segs[0].emotion) }}
      />
    );
  }

  if (kind === "speech") {
    return (
      <>
        {segs.map((s, i) => (
          <div
            key={i}
            className="absolute top-0 h-full bg-sky-500/70 hover:bg-sky-400 rounded-[1px]"
            style={{ left: pct(s.start_time), width: widthPct(s.start_time, s.end_time) }}
            title={`${formatTC(Math.max(s.start_time, clip.start_time))} — ${s.speaker ? `${s.speaker}: ` : ""}${s.text}`}
          />
        ))}
      </>
    );
  }

  // people — speaking ranges colored per person (consistent colors across the cut)
  return (
    <>
      {(people ?? []).map((p) => {
        const hash = Array.from(p.person_id).reduce((a, ch) => (a * 31 + ch.charCodeAt(0)) >>> 0, 0);
        const color = personColors.get(p.person_id) ?? PERSON_COLORS[hash % PERSON_COLORS.length];
        return (p.speaking ?? [])
          .filter((s) => s.end_time > clip.start_time && s.start_time < clip.end_time)
          .map((s, j) => (
            <div
              key={`${p.person_id}-${j}`}
              className="absolute top-0 h-full opacity-80 hover:opacity-100 rounded-[1px]"
              style={{ left: pct(s.start_time), width: widthPct(s.start_time, s.end_time), background: color }}
              title={`${p.display_name}${s.text ? `\n${s.text}` : ""}`}
            />
          ));
      })}
    </>
  );
}

export function CutStrips({ clips }: { clips: CutClip[] }) {
  const total = clips.reduce((s, c) => s + Math.max(0, c.end_time - c.start_time), 0);
  // Stable person → color assignment across the whole cut.
  const mediaIds = useMemo(() => Array.from(new Set(clips.map((c) => c.media_id))), [clips]);
  const peopleQueries = useGetAssetPeople(mediaIds[0] ?? "", {
    query: { queryKey: getGetAssetPeopleQueryKey(mediaIds[0] ?? ""), enabled: !!mediaIds.length },
  });
  const personColors = useMemo(() => {
    const m = new Map<string, string>();
    // Color by first-seen order; per-media queries in cells reuse the same map keys.
    (peopleQueries.data ?? []).forEach((p, i) => m.set(p.person_id, PERSON_COLORS[i % PERSON_COLORS.length]));
    return m;
  }, [peopleQueries.data]);

  if (!clips.length || total <= 0) return null;

  const rows: { label: string; kind: "speech" | "emotion" | "people" }[] = [
    { label: "DIALOGUE", kind: "speech" },
    { label: "EMOTION", kind: "emotion" },
    { label: "PEOPLE", kind: "people" },
  ];

  return (
    <div className="space-y-1" data-testid="cut-strips">
      {rows.map((row) => (
        <div key={row.kind} className="flex items-center gap-2">
          <div className="w-[72px] shrink-0 text-right text-[9px] font-bold tracking-widest text-zinc-600 select-none">
            [{row.label}]
          </div>
          <div className="flex h-5 flex-1 rounded-sm overflow-hidden bg-white/5">
            {clips.map((c, i) => (
              <div
                key={i}
                className="relative h-full border-r border-black/60 last:border-r-0"
                style={{ width: `${((c.end_time - c.start_time) / total) * 100}%` }}
              >
                <ClipCell clip={c} kind={row.kind} personColors={personColors} />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
