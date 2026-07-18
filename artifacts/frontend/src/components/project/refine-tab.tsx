import { useEffect, useMemo, useState } from "react";
import { Link } from "wouter";
import {
  useUpdateClipList,
  useCreateClipList,
  useGetMediaTranscript,
  getGetMediaTranscriptQueryKey,
} from "@workspace/api-client-react";
import type { ClipList, Clip, MediaAsset, ClipListUpdateClipsItem } from "@workspace/api-client-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  ArrowDown, ArrowUp, CheckCircle2, Circle, Copy, ExternalLink, FileText,
  Loader2, Lock, LockOpen, Save, Wand2, X,
} from "lucide-react";
import { ClipThumb } from "./clip-thumb";
import { TrimPlayer, fmtTC } from "./trim-player";
import { useToast } from "@/hooks/use-toast";

function errDetail(err: unknown, fallback: string): string {
  const e = err as { response?: { status?: number; data?: { detail?: string } } };
  if (e?.response?.status === 423)
    return "This story is picture-locked — unlock it before making changes.";
  return e?.response?.data?.detail ?? fallback;
}

type DraftClip = {
  media_id: string;
  start_time: number;
  end_time: number;
  label: string | null;
  notes: string | null;
  approved: boolean;
  match_reason: string | null;
  filename: string | null;
  thumbnail_url: string | null;
};

const fromClip = (c: Clip): DraftClip => ({
  media_id: c.media_id,
  start_time: c.start_time,
  end_time: c.end_time,
  label: c.label ?? null,
  notes: c.notes ?? null,
  approved: c.approved ?? false,
  match_reason: c.match_reason ?? null,
  filename: c.filename ?? null,
  thumbnail_url: c.thumbnail_url ?? null,
});

const toUpdateItem = (c: DraftClip): ClipListUpdateClipsItem => ({
  media_id: c.media_id,
  start_time: c.start_time,
  end_time: c.end_time,
  label: c.label ?? undefined,
  notes: c.notes,
  approved: c.approved,
  match_reason: c.match_reason,
});

interface RefineTabProps {
  projectId: string;
  clipLists: ClipList[] | undefined;
  assets: MediaAsset[] | undefined;
  onChanged: () => void;
}

export function RefineTab({ projectId, clipLists, assets, onChanged }: RefineTabProps) {
  const { toast } = useToast();
  const lists = useMemo(() => clipLists ?? [], [clipLists]);
  const [listId, setListId] = useState<string>("");
  const list = lists.find((l) => l.id === listId) ?? null;

  useEffect(() => {
    if (!list && lists.length) setListId((lists.find((l) => l.clips.length) ?? lists[0]).id);
  }, [lists, list]);

  const [draft, setDraft] = useState<DraftClip[]>([]);
  const [dirty, setDirty] = useState(false);
  const [selIdx, setSelIdx] = useState(0);

  useEffect(() => {
    if (list && !dirty) setDraft(list.clips.map(fromClip));
  }, [list, dirty]);

  useEffect(() => {
    setDirty(false);
    setSelIdx(0);
  }, [listId]);

  const updateMutation = useUpdateClipList();
  const createMutation = useCreateClipList();

  const locked = !!list?.locked;
  const sel = draft[Math.min(selIdx, Math.max(draft.length - 1, 0))] as DraftClip | undefined;
  const selAsset = assets?.find((a) => a.id === sel?.media_id);
  const approvedCount = draft.filter((c) => c.approved).length;
  const allApproved = draft.length > 0 && approvedCount === draft.length;

  const transcriptParams = undefined;
  const { data: transcript } = useGetMediaTranscript(sel?.media_id ?? "", transcriptParams, {
    query: {
      enabled: !!sel?.media_id,
      queryKey: getGetMediaTranscriptQueryKey(sel?.media_id ?? "", transcriptParams),
    },
  });

  const whySegments = useMemo(() => {
    if (!sel || !transcript?.length) return [];
    const lo = sel.start_time - 2;
    const hi = sel.end_time + 2;
    return transcript.filter((t) => t.end_time > lo && t.start_time < hi);
  }, [transcript, sel]);

  const saveClips = (clips: DraftClip[], onOk?: () => void) => {
    if (!list) return;
    updateMutation.mutate(
      { id: list.id, data: { clips: clips.map(toUpdateItem) } },
      {
        onSuccess: () => {
          setDirty(false);
          onChanged();
          onOk?.();
        },
        onError: (err) => {
          toast({
            variant: "destructive",
            title: "Could not save the beats",
            description: errDetail(err, "The changes were not saved — try again."),
          });
        },
      },
    );
  };

  const patchClip = (idx: number, patch: Partial<DraftClip>) => {
    setDraft((d) => d.map((c, i) => (i === idx ? { ...c, ...patch } : c)));
    setDirty(true);
  };

  const toggleApprove = (idx: number) => {
    if (locked) return;
    const next = draft.map((c, i) => (i === idx ? { ...c, approved: !c.approved } : c));
    setDraft(next);
    saveClips(next);
  };

  const move = (idx: number, dir: -1 | 1) => {
    const next = [...draft];
    const j = idx + dir;
    if (j < 0 || j >= next.length) return;
    [next[idx], next[j]] = [next[j], next[idx]];
    setDraft(next);
    setDirty(true);
    if (selIdx === idx) setSelIdx(j);
    else if (selIdx === j) setSelIdx(idx);
  };

  const toggleLock = () => {
    if (!list) return;
    updateMutation.mutate(
      { id: list.id, data: { locked: !list.locked } },
      {
        onSuccess: onChanged,
        onError: (err) => {
          toast({
            variant: "destructive",
            title: list.locked ? "Could not unlock the story" : "Could not lock the story",
            description: errDetail(err, "Try again."),
          });
        },
      },
    );
  };

  const duplicateAsNext = () => {
    if (!list) return;
    const m = list.name.match(/^(.*?)\s+v(\d+)$/);
    const name = m ? `${m[1]} v${parseInt(m[2], 10) + 1}` : `${list.name} v2`;
    createMutation.mutate(
      {
        data: {
          name,
          project_id: projectId,
          description: list.description ?? undefined,
          clips: draft.map((c) => ({
            media_id: c.media_id,
            start_time: c.start_time,
            end_time: c.end_time,
            label: c.label ?? undefined,
            notes: c.notes,
            approved: c.approved,
            match_reason: c.match_reason,
          })),
        },
      },
      {
        onSuccess: (created) => {
          onChanged();
          setListId(created.id);
          toast({ title: `Created "${created.name}"`, description: "You're now editing the new version." });
        },
        onError: (err) => {
          toast({
            variant: "destructive",
            title: "Could not duplicate the story",
            description: errDetail(err, "The new version was not created — try again."),
          });
        },
      },
    );
  };

  if (!lists.length) {
    return (
      <div className="text-center text-muted-foreground py-10 border border-dashed border-border rounded-lg">
        Nothing to refine yet — add clips from the Find tab or build a story in Assemble.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header: list picker + approval status + lock */}
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="bg-muted border border-border rounded-md px-2 py-1.5 text-sm max-w-[280px]"
          value={listId}
          onChange={(e) => setListId(e.target.value)}
        >
          {lists.map((l) => (
            <option key={l.id} value={l.id}>{l.name} ({l.clips.length})</option>
          ))}
        </select>
        {draft.length > 0 && (
          <Badge
            variant="outline"
            className={allApproved ? "text-emerald-400 border-emerald-500/40" : "text-amber-500 border-amber-500/40"}
          >
            {approvedCount}/{draft.length} approved
          </Badge>
        )}
        {locked && (
          <Badge variant="outline" className="gap-1 text-amber-500 border-amber-500/40">
            <Lock className="h-3 w-3" /> Picture locked
          </Badge>
        )}
        <div className="flex items-center gap-2 ml-auto">
          {dirty && (
            <>
              <Button size="sm" variant="ghost" onClick={() => setDirty(false)}>
                <X className="h-4 w-4 mr-1" /> Discard
              </Button>
              <Button size="sm" onClick={() => saveClips(draft)} disabled={updateMutation.isPending}>
                {updateMutation.isPending
                  ? <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                  : <Save className="h-4 w-4 mr-1" />}
                Save changes
              </Button>
            </>
          )}
          {locked && (
            <Button size="sm" variant="outline" onClick={duplicateAsNext} disabled={createMutation.isPending}
              title="Copy this locked story to a new version for changes">
              {createMutation.isPending
                ? <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                : <Copy className="h-4 w-4 mr-1" />}
              Duplicate as new version
            </Button>
          )}
          <Button
            size="sm" variant="outline"
            className={locked ? "text-amber-500" : "text-muted-foreground"}
            onClick={toggleLock}
            disabled={updateMutation.isPending || !list}
            title={locked
              ? "Unlock to allow edits"
              : allApproved
                ? "All beats approved — freeze this story"
                : `Only ${approvedCount}/${draft.length} beats approved — you can still lock, but review first`}
          >
            {locked ? <Lock className="h-4 w-4 mr-1" /> : <LockOpen className="h-4 w-4 mr-1" />}
            {locked ? "Unlock" : "Lock story"}
          </Button>
        </div>
      </div>

      {!draft.length ? (
        <div className="text-center text-muted-foreground py-10 border border-dashed border-border rounded-lg">
          This list is empty — add clips from the Find tab.
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(280px,340px)_1fr]">
          {/* Beat list */}
          <Card className="self-start">
            <CardHeader className="py-3">
              <CardTitle className="text-sm">Beats</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5 max-h-[560px] overflow-y-auto">
              {draft.map((c, i) => (
                <div
                  key={`${c.media_id}-${i}`}
                  className={`flex items-center gap-2 rounded p-1.5 text-sm cursor-pointer border ${
                    i === selIdx ? "border-primary/60 bg-primary/10" : "border-transparent bg-muted/50 hover:bg-muted"
                  }`}
                  onClick={() => setSelIdx(i)}
                >
                  <div className="flex flex-col shrink-0">
                    <Button size="icon" variant="ghost" className="h-4 w-4" disabled={locked || i === 0}
                      onClick={(e) => { e.stopPropagation(); move(i, -1); }}>
                      <ArrowUp className="h-3 w-3" />
                    </Button>
                    <Button size="icon" variant="ghost" className="h-4 w-4" disabled={locked || i === draft.length - 1}
                      onClick={(e) => { e.stopPropagation(); move(i, 1); }}>
                      <ArrowDown className="h-3 w-3" />
                    </Button>
                  </div>
                  <ClipThumb url={c.thumbnail_url} mediaId={c.media_id} time={c.start_time} className="h-9 w-14" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-medium">{i + 1}. {c.label || c.filename || c.media_id}</div>
                    <div className="font-mono text-[10px] text-muted-foreground">
                      {fmtTC(c.start_time)} – {fmtTC(c.end_time)}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="shrink-0 disabled:opacity-40"
                    disabled={locked || updateMutation.isPending}
                    title={locked ? "Picture locked" : c.approved ? "Approved — click to revoke" : "Approve this beat"}
                    onClick={(e) => { e.stopPropagation(); toggleApprove(i); }}
                  >
                    {c.approved
                      ? <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                      : <Circle className="h-5 w-5 text-muted-foreground/50" />}
                  </button>
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Player + why panel */}
          <div className="space-y-4 min-w-0">
            {sel && (
              <Card>
                <CardContent className="pt-4 space-y-3">
                  <TrimPlayer
                    mediaId={sel.media_id}
                    clipKey={`${listId}-${selIdx}`}
                    inPoint={sel.start_time}
                    outPoint={sel.end_time}
                    fps={selAsset?.fps}
                    disabled={locked}
                    onChange={(inP, outP) => patchClip(selIdx, { start_time: inP, end_time: outP })}
                  />
                  <div className="flex items-center gap-2">
                    <Input
                      className="h-8 flex-1"
                      placeholder="Beat label"
                      value={sel.label ?? ""}
                      disabled={locked}
                      onChange={(e) => patchClip(selIdx, { label: e.target.value })}
                    />
                    <Button
                      size="sm"
                      variant={sel.approved ? "outline" : "default"}
                      disabled={locked || updateMutation.isPending}
                      onClick={() => toggleApprove(selIdx)}
                    >
                      {sel.approved
                        ? <><CheckCircle2 className="h-4 w-4 mr-1 text-emerald-400" /> Approved</>
                        : <><CheckCircle2 className="h-4 w-4 mr-1" /> Approve beat</>}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )}

            {sel && (
              <Card>
                <CardHeader className="py-3">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Wand2 className="h-4 w-4" /> Why this beat
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  {sel.match_reason ? (
                    <p className="text-muted-foreground leading-relaxed">{sel.match_reason}</p>
                  ) : (
                    <p className="text-muted-foreground/60 italic">No match rationale recorded — this clip was added manually.</p>
                  )}
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <FileText className="h-3.5 w-3.5" />
                    <span className="truncate">{sel.filename || sel.media_id}</span>
                    <Link href={`/library/${sel.media_id}?t=${sel.start_time}`}>
                      <Button size="icon" variant="ghost" className="h-6 w-6" title="Open the full asset">
                        <ExternalLink className="h-3 w-3" />
                      </Button>
                    </Link>
                  </div>
                  {whySegments.length > 0 && (
                    <div className="space-y-1.5 border-t border-border pt-3 max-h-52 overflow-y-auto">
                      {whySegments.map((t) => {
                        const inRange = t.end_time > sel.start_time && t.start_time < sel.end_time;
                        return (
                          <p key={t.id} className={`text-xs leading-relaxed ${inRange ? "text-foreground" : "text-muted-foreground/50"}`}>
                            <span className="font-mono text-[10px] text-muted-foreground mr-1.5">{fmtTC(t.start_time)}</span>
                            {t.speaker && <span className="text-primary/80 mr-1">{t.speaker}:</span>}
                            {t.text}
                          </p>
                        );
                      })}
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
