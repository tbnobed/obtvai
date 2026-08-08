import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import {
  useGetMediaTranscript, getGetMediaTranscriptQueryKey,
  getAssetPeople, getGetAssetPeopleQueryKey,
} from "@workspace/api-client-react";
import type { CutClip, AssetPerson } from "@workspace/api-client-react";
import { formatTC } from "@/lib/timecode";

/** Timeline strips for the draft cut — transcript, sentiment/emotion, and per-person
 *  tracks, mapped from each clip's source asset onto the cut's timeline. */

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

const LABEL_W = "w-[110px]";

function TranscriptCell({
  clip,
  kind,
  onSeek,
}: {
  clip: CutClip;
  kind: "speech" | "emotion";
  onSeek?: (srcTime: number) => void;
}) {
  const { data: transcript } = useGetMediaTranscript(clip.media_id, {}, {
    query: { queryKey: getGetMediaTranscriptQueryKey(clip.media_id, {}) },
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
        className="absolute inset-0 cursor-pointer"
        style={{ background: segs.length > 1 ? `linear-gradient(90deg, ${stops})` : emotionColor(segs[0].emotion) }}
        onClick={() => onSeek?.(clip.start_time)}
      />
    );
  }

  return (
    <>
      {segs.map((s, i) => (
        <div
          key={i}
          className="absolute top-0 h-full bg-sky-500/70 hover:bg-sky-400 rounded-[1px] cursor-pointer"
          style={{ left: pct(s.start_time), width: widthPct(s.start_time, s.end_time) }}
          title={`${formatTC(Math.max(s.start_time, clip.start_time))} — ${s.speaker ? `${s.speaker}: ` : ""}${s.text} — click to play`}
          onClick={() => onSeek?.(Math.max(s.start_time, clip.start_time))}
        />
      ))}
    </>
  );
}

export function CutStrips({
  clips,
  onSeek,
}: {
  clips: CutClip[];
  onSeek?: (clipIndex: number, srcTime: number) => void;
}) {
  const total = clips.reduce((s, c) => s + Math.max(0, c.end_time - c.start_time), 0);
  const mediaIds = useMemo(() => Array.from(new Set(clips.map((c) => c.media_id))), [clips]);

  // People across every source asset in the cut.
  const peopleQueries = useQueries({
    queries: mediaIds.map((id) => ({
      queryKey: getGetAssetPeopleQueryKey(id),
      queryFn: () => getAssetPeople(id),
      staleTime: 60_000,
    })),
  });

  const people = useMemo(() => {
    const byPerson = new Map<
      string,
      { person: AssetPerson; byMedia: Map<string, AssetPerson>; speaking: number }
    >();
    peopleQueries.forEach((q, i) => {
      const mediaId = mediaIds[i];
      for (const p of q.data ?? []) {
        let entry = byPerson.get(p.person_id);
        if (!entry) {
          entry = { person: p, byMedia: new Map(), speaking: 0 };
          byPerson.set(p.person_id, entry);
        }
        entry.byMedia.set(mediaId, p);
        entry.speaking += p.speaking_seconds ?? (p.speaking ?? []).reduce((s, r) => s + (r.end_time - r.start_time), 0);
      }
    });
    return Array.from(byPerson.values())
      .sort((a, b) => b.speaking - a.speaking)
      .slice(0, 6);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mediaIds, ...peopleQueries.map((q) => q.data)]);

  if (!clips.length || total <= 0) return null;

  const clipWidth = (c: CutClip) => `${((c.end_time - c.start_time) / total) * 100}%`;

  const track = (render: (c: CutClip, i: number) => React.ReactNode, h = "h-5") => (
    <div className={`flex ${h} flex-1 rounded-sm overflow-hidden bg-white/5`}>
      {clips.map((c, i) => (
        <div key={i} className="relative h-full border-r border-black/60 last:border-r-0" style={{ width: clipWidth(c) }}>
          {render(c, i)}
        </div>
      ))}
    </div>
  );

  return (
    <div className="space-y-1" data-testid="cut-strips">
      <div className="flex items-center gap-2">
        <div className={`${LABEL_W} shrink-0 text-right text-[9px] font-bold tracking-widest text-zinc-600 select-none`}>[DIALOGUE]</div>
        {track((c, i) => <TranscriptCell clip={c} kind="speech" onSeek={(t) => onSeek?.(i, t)} />)}
      </div>
      <div className="flex items-center gap-2">
        <div className={`${LABEL_W} shrink-0 text-right text-[9px] font-bold tracking-widest text-zinc-600 select-none`}>[EMOTION]</div>
        {track((c, i) => <TranscriptCell clip={c} kind="emotion" onSeek={(t) => onSeek?.(i, t)} />)}
      </div>
      {people.map(({ person, byMedia }, pi) => {
        const color = PERSON_COLORS[pi % PERSON_COLORS.length];
        return (
          <div key={person.person_id} className="flex items-center gap-2" data-testid={`cut-person-${person.person_id}`}>
            <div className={`${LABEL_W} shrink-0 flex items-center justify-end gap-1.5`} title={person.display_name}>
              <span className="text-[10px] font-medium text-zinc-400 truncate">{person.display_name}</span>
              {person.thumbnail_url ? (
                <img src={`/api/thumbnails/${person.thumbnail_url}`} alt="" className="h-4 w-4 rounded-full object-cover shrink-0" />
              ) : null}
            </div>
            {track((c, i) => {
              const p = byMedia.get(c.media_id);
              if (!p) return null;
              const dur = Math.max(0.001, c.end_time - c.start_time);
              const pct = (t: number) => `${Math.min(100, Math.max(0, ((t - c.start_time) / dur) * 100))}%`;
              const widthPct = (a: number, b: number) =>
                `${Math.max(0.6, Math.min(100, ((Math.min(b, c.end_time) - Math.max(a, c.start_time)) / dur) * 100))}%`;
              const inClip = (a: number, b: number) => b > c.start_time && a < c.end_time;
              return (
                <>
                  {(p.on_camera ?? []).filter((r) => inClip(r.start_time, r.end_time)).map((r, j) => (
                    <div
                      key={`cam-${j}`}
                      className="absolute top-0 h-full opacity-25 hover:opacity-40 cursor-pointer"
                      style={{ left: pct(r.start_time), width: widthPct(r.start_time, r.end_time), background: color }}
                      title={`${person.display_name} on camera — click to play`}
                      onClick={() => onSeek?.(i, Math.max(r.start_time, c.start_time))}
                    />
                  ))}
                  {(p.speaking ?? []).filter((s) => inClip(s.start_time, s.end_time)).map((s, j) => (
                    <div
                      key={`spk-${j}`}
                      className="absolute top-0 h-full opacity-85 hover:opacity-100 rounded-[1px] cursor-pointer"
                      style={{ left: pct(s.start_time), width: widthPct(s.start_time, s.end_time), background: color }}
                      title={`${person.display_name}${s.text ? `\n${s.text}` : ""} — click to play`}
                      onClick={() => onSeek?.(i, Math.max(s.start_time, c.start_time))}
                    />
                  ))}
                </>
              );
            }, "h-4")}
          </div>
        );
      })}
    </div>
  );
}
