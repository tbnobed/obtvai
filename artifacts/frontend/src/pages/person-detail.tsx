import { useState } from "react";
import { useRoute, Link } from "wouter";
import {
  useGetPerson,
  getGetPersonQueryKey,
  getListPeopleQueryKey,
  useUpdatePerson,
  useMergePerson,
  useSplitPerson,
  useListPeople,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ArrowLeft, User, Pencil, Merge, Film, Mic, MessageSquareQuote, Scissors } from "lucide-react";
import { useLocation } from "wouter";

function formatDuration(seconds: number | null | undefined) {
  if (!seconds) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  if (m >= 60) return `${Math.floor(m / 60)}h ${m % 60}m`;
  return `${m}m ${s}s`;
}

function formatTimecode(seconds: number | null | undefined) {
  if (seconds == null) return null;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export default function PersonDetail() {
  const [, params] = useRoute("/people/:id");
  const id = params?.id ?? "";
  const queryClient = useQueryClient();
  const { data: person, isLoading } = useGetPerson(id, {
    query: { queryKey: getGetPersonQueryKey(id), enabled: !!id },
  });
  const { data: allPeople } = useListPeople({ limit: 200 });

  const updatePerson = useUpdatePerson();
  const mergePerson = useMergePerson();
  const splitPerson = useSplitPerson();
  const [, navigate] = useLocation();

  const [renameOpen, setRenameOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [mergeOpen, setMergeOpen] = useState(false);
  const [mergeSource, setMergeSource] = useState("");

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: getGetPersonQueryKey(id) });
    queryClient.invalidateQueries({ queryKey: getListPeopleQueryKey() });
  };

  const handleRename = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    updatePerson.mutate(
      { id, data: { display_name: newName.trim() } },
      {
        onSuccess: () => {
          setRenameOpen(false);
          setNewName("");
          invalidate();
        },
      }
    );
  };

  const handleSplit = (
    e: React.MouseEvent,
    a: { media_id: string; speaker_label?: string | null; face_cluster_id?: string | null }
  ) => {
    e.preventDefault();
    e.stopPropagation();
    if (splitPerson.isPending) return;
    if (
      !window.confirm(
        "Split this appearance out into a new, separate person? Use this to undo a merge that combined two different people."
      )
    )
      return;
    splitPerson.mutate(
      {
        id,
        data: {
          media_id: a.media_id,
          speaker_label: a.speaker_label ?? null,
          face_cluster_id: a.face_cluster_id ?? null,
        },
      },
      {
        onSuccess: (newPerson) => {
          invalidate();
          navigate(`/people/${newPerson.id}`);
        },
        onError: (err: unknown) => {
          const detail =
            (err as { response?: { data?: { detail?: string; error?: string } } })?.response?.data;
          window.alert(detail?.detail || detail?.error || "Split failed");
        },
      }
    );
  };

  const handleMerge = (e: React.FormEvent) => {
    e.preventDefault();
    if (!mergeSource) return;
    mergePerson.mutate(
      { id, data: { source_person_id: mergeSource } },
      {
        onSuccess: () => {
          setMergeOpen(false);
          setMergeSource("");
          invalidate();
        },
      }
    );
  };

  if (isLoading) {
    return (
      <div className="flex-1 p-8 overflow-y-auto">
        <div className="animate-pulse space-y-4">
          <div className="h-8 w-64 bg-muted rounded" />
          <div className="h-40 bg-muted rounded" />
        </div>
      </div>
    );
  }

  if (!person) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground">
        <User className="h-12 w-12 mb-4 opacity-50" />
        <p>Person not found.</p>
        <Link href="/people" className="text-primary text-sm mt-2 hover:underline">
          Back to People
        </Link>
      </div>
    );
  }

  const mergeCandidates = (allPeople?.items ?? []).filter((p) => p.id !== id);

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <Link href="/people" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-6">
        <ArrowLeft className="h-4 w-4" />
        People
      </Link>

      <div className="flex flex-col md:flex-row gap-6 mb-8">
        <div className="w-40 h-40 rounded-md bg-muted flex-shrink-0 overflow-hidden">
          {person.thumbnail_url ? (
            <img
              src={`/api/thumbnails/${person.thumbnail_url}`}
              alt={person.display_name}
              className="w-full h-full object-cover"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center">
              <User className="h-16 w-16 text-muted-foreground/50" />
            </div>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-3xl font-bold tracking-tight">{person.display_name}</h1>
            {person.name_source && (
              <Badge variant={person.name_source === "manual" ? "default" : "secondary"} className="text-xs">
                {person.name_source === "manual" ? "manually named" : "auto-identified"}
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-4 mt-2 text-sm text-muted-foreground">
            <span className="flex items-center gap-1">
              <Film className="h-4 w-4" />
              {person.asset_count} {person.asset_count === 1 ? "asset" : "assets"}
            </span>
            <span className="flex items-center gap-1">
              <Mic className="h-4 w-4" />
              {formatDuration(person.total_speaking_seconds)} speaking
            </span>
            <span>{person.segment_count} segments</span>
          </div>
          {person.summary && <p className="text-sm mt-3 max-w-3xl">{person.summary}</p>}
          <div className="flex gap-2 mt-4">
            <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
              <DialogTrigger asChild>
                <Button variant="secondary" size="sm" className="gap-2">
                  <Pencil className="h-3.5 w-3.5" />
                  Rename
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Rename Person</DialogTitle>
                </DialogHeader>
                <form onSubmit={handleRename} className="space-y-4 pt-4">
                  <Input
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder={person.display_name}
                    autoFocus
                  />
                  <Button type="submit" className="w-full" disabled={!newName.trim() || updatePerson.isPending}>
                    {updatePerson.isPending ? "Saving..." : "Save Name"}
                  </Button>
                </form>
              </DialogContent>
            </Dialog>
            <Dialog open={mergeOpen} onOpenChange={setMergeOpen}>
              <DialogTrigger asChild>
                <Button variant="secondary" size="sm" className="gap-2">
                  <Merge className="h-3.5 w-3.5" />
                  Merge Into This Person
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Merge a Duplicate Into {person.display_name}</DialogTitle>
                </DialogHeader>
                <form onSubmit={handleMerge} className="space-y-4 pt-4">
                  <p className="text-sm text-muted-foreground">
                    The selected person's appearances will be moved into {person.display_name}, and the duplicate will be removed. This cannot be undone.
                  </p>
                  <select
                    value={mergeSource}
                    onChange={(e) => setMergeSource(e.target.value)}
                    className="w-full h-9 px-3 py-1 rounded-md border border-input bg-background text-sm"
                  >
                    <option value="">Select a person to merge in...</option>
                    {mergeCandidates.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.display_name} ({p.asset_count} assets)
                      </option>
                    ))}
                  </select>
                  <Button type="submit" className="w-full" disabled={!mergeSource || mergePerson.isPending}>
                    {mergePerson.isPending ? "Merging..." : "Merge"}
                  </Button>
                </form>
              </DialogContent>
            </Dialog>
          </div>
        </div>
      </div>

      {(person.speech_style || person.key_topics?.length) ? (
        <div className="grid gap-4 md:grid-cols-2 mb-8">
          {person.speech_style && (
            <div className="border border-border bg-card rounded-md p-4">
              <h2 className="text-sm font-semibold flex items-center gap-2 mb-2">
                <MessageSquareQuote className="h-4 w-4 text-primary" />
                Speech Style
              </h2>
              <p className="text-sm text-muted-foreground">{person.speech_style}</p>
            </div>
          )}
          {person.key_topics?.length ? (
            <div className="border border-border bg-card rounded-md p-4">
              <h2 className="text-sm font-semibold mb-2">Key Topics</h2>
              <div className="flex flex-wrap gap-1.5">
                {person.key_topics.map((t) => (
                  <Badge key={t} variant="outline" className="text-xs">
                    {t}
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      <h2 className="text-lg font-semibold mb-4">Appearances</h2>
      {person.appearances?.length ? (
        <div className="space-y-2">
          {person.appearances.map((a) => (
            <div
              key={`${a.media_id}-${a.speaker_label ?? ""}-${a.face_cluster_id ?? ""}`}
              className="border border-border bg-card rounded-md p-4 flex items-center gap-4 hover:border-primary transition-colors"
            >
              <Link
                href={`/library/${a.media_id}${a.first_spoken_at != null ? `?t=${Math.floor(a.first_spoken_at)}` : ""}`}
                className="flex items-center gap-4 flex-1 min-w-0 cursor-pointer"
              >
                <div className="w-24 h-14 bg-muted rounded flex-shrink-0 overflow-hidden">
                  {a.thumbnail_url ? (
                    <img src={`/api/thumbnails/${a.thumbnail_url}`} alt={a.filename} className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <Film className="h-5 w-5 text-muted-foreground/50" />
                    </div>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{a.filename}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {a.speaker_label ? `${a.speaker_label} · ` : ""}
                    {formatDuration(a.speaking_seconds)} speaking · {a.segment_count ?? 0} segments
                    {a.first_spoken_at != null ? ` · first speaks at ${formatTimecode(a.first_spoken_at)}` : ""}
                  </p>
                </div>
                <span className="text-xs text-muted-foreground flex-shrink-0">
                  {formatDuration(a.duration_seconds)}
                </span>
              </Link>
              {(person.appearances?.length ?? 0) > 1 && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="gap-1.5 flex-shrink-0 text-muted-foreground hover:text-foreground"
                  disabled={splitPerson.isPending}
                  onClick={(e) => handleSplit(e, a)}
                  title="Split this appearance into a new person (undo a bad merge)"
                >
                  <Scissors className="h-3.5 w-3.5" />
                  Split out
                </Button>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No appearances recorded.</p>
      )}
    </div>
  );
}
