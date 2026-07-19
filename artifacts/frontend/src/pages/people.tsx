import { useEffect, useState } from "react";
import { useListPeople, useReanalyzePeople, useUpdatePerson, useDeletePerson, getListPeopleQueryKey } from "@workspace/api-client-react";
import { Link } from "wouter";
import { Users, User, Mic, Film, ScanFace, Pencil, Check, X, ChevronLeft, ChevronRight, Trash2, LayoutGrid, Share2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useQueryClient } from "@tanstack/react-query";
import CoAppearanceMap from "@/components/co-appearance-map";

function formatSpeaking(seconds: number) {
  const m = Math.floor(seconds / 60);
  if (m >= 60) return `${Math.floor(m / 60)}h ${m % 60}m`;
  return `${m}m`;
}

const PAGE_SIZE = 48;

export default function People() {
  const [view, setView] = useState<"grid" | "map">(() =>
    new URLSearchParams(window.location.search).get("view") === "map" ? "map" : "grid"
  );
  const [page, setPage] = useState(0);
  const { data, isLoading } = useListPeople({ limit: PAGE_SIZE, offset: page * PAGE_SIZE });
  const people = data?.items;
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  useEffect(() => {
    if (data && page > 0 && page > totalPages - 1) {
      setPage(totalPages - 1);
    }
  }, [data, page, totalPages]);

  const reanalyzeMutation = useReanalyzePeople();
  const updatePerson = useUpdatePerson();
  const deletePerson = useDeletePerson();
  const queryClient = useQueryClient();
  const [queuedMessage, setQueuedMessage] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");

  const startEdit = (e: React.MouseEvent, id: string, currentName: string) => {
    e.preventDefault();
    e.stopPropagation();
    setEditingId(id);
    setEditName(currentName.startsWith("Person ") || currentName.startsWith("SPEAKER_") ? "" : currentName);
  };

  const cancelEdit = (e?: React.SyntheticEvent) => {
    e?.preventDefault();
    e?.stopPropagation();
    setEditingId(null);
    setEditName("");
  };

  const saveEdit = (e: React.SyntheticEvent, id: string) => {
    e.preventDefault();
    e.stopPropagation();
    const name = editName.trim();
    if (!name || updatePerson.isPending) return;
    updatePerson.mutate(
      { id, data: { display_name: name } },
      {
        onSuccess: () => {
          setEditingId(null);
          setEditName("");
          queryClient.invalidateQueries({ queryKey: getListPeopleQueryKey() });
        },
        onError: () => setQueuedMessage("Rename failed — check the API server."),
      }
    );
  };

  const handleDelete = (e: React.MouseEvent, id: string, name: string) => {
    e.preventDefault();
    e.stopPropagation();
    if (deletePerson.isPending) return;
    if (!window.confirm(`Delete "${name}"? This removes the person, their appearances, and any voice-clone data.`)) return;
    deletePerson.mutate(
      { id },
      {
        onSuccess: () => queryClient.invalidateQueries({ queryKey: getListPeopleQueryKey() }),
        onError: () => setQueuedMessage("Delete failed — check the API server."),
      }
    );
  };

  const handleReanalyze = () => {
    reanalyzeMutation.mutate(undefined, {
      onSuccess: (result) => {
        setQueuedMessage(
          result.assets_queued > 0
            ? `Queued ${result.jobs_created} analysis jobs across ${result.assets_queued} assets — people will appear as processing completes.`
            : "Nothing to re-analyze — all assets are already queued or processing."
        );
        queryClient.invalidateQueries({ queryKey: getListPeopleQueryKey() });
      },
      onError: () => setQueuedMessage("Re-analysis request failed — check the API server."),
    });
  };

  return (
    <div className="flex-1 p-8 overflow-y-auto flex flex-col">
      <div className="flex justify-between items-center mb-8 flex-wrap gap-3">
        <h1 className="text-3xl font-bold tracking-tight">People</h1>
        <div className="flex items-center gap-4">
          {total > 0 ? (
            <p className="text-sm text-muted-foreground">
              {total} {total === 1 ? "person" : "people"} identified across the library
            </p>
          ) : null}
          <div className="flex rounded-md border border-border overflow-hidden">
            <Button
              size="sm"
              variant={view === "grid" ? "secondary" : "ghost"}
              className="gap-1.5 rounded-none"
              onClick={() => setView("grid")}
            >
              <LayoutGrid className="h-4 w-4" />
              Grid
            </Button>
            <Button
              size="sm"
              variant={view === "map" ? "secondary" : "ghost"}
              className="gap-1.5 rounded-none"
              onClick={() => setView("map")}
            >
              <Share2 className="h-4 w-4" />
              Co-appearance Map
            </Button>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="gap-1.5"
            onClick={handleReanalyze}
            disabled={reanalyzeMutation.isPending}
          >
            <ScanFace className="h-4 w-4" />
            {reanalyzeMutation.isPending ? "Queuing..." : "Re-analyze Library"}
          </Button>
        </div>
      </div>

      {queuedMessage && (
        <div className="mb-6 px-4 py-3 rounded-md border border-border bg-card text-sm text-muted-foreground">
          {queuedMessage}
        </div>
      )}

      {view === "map" ? (
        <CoAppearanceMap />
      ) : isLoading ? (
        <div className="grid gap-3 grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-8">
          {[...Array(16)].map((_, i) => (
            <div key={i} className="animate-pulse bg-muted aspect-square rounded-md" />
          ))}
        </div>
      ) : people?.length ? (
        <>
        <div className="grid gap-3 grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-8">
          {people.map((person) => (
            <Link key={person.id} href={`/people/${person.id}`}>
              <div className="group border border-border bg-card rounded-md overflow-hidden cursor-pointer hover:border-primary transition-colors flex flex-col h-full">
                <div className="aspect-square bg-muted relative">
                  {person.thumbnail_url ? (
                    <img
                      src={`/api/thumbnails/${person.thumbnail_url}`}
                      alt={person.display_name}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="absolute inset-0 flex items-center justify-center">
                      <User className="h-12 w-12 text-muted-foreground/50" />
                    </div>
                  )}
                  {person.name_source !== "manual" &&
                    (person.display_name.startsWith("Person ") || person.display_name.startsWith("SPEAKER_")) && (
                    <div className="absolute top-1.5 right-1.5">
                      <Badge variant="secondary" className="text-[10px] px-1.5 py-0">unnamed</Badge>
                    </div>
                  )}
                </div>
                <div className="p-2 flex-1 flex flex-col gap-1">
                  {editingId === person.id ? (
                    <div className="flex items-center gap-1" onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}>
                      <Input
                        autoFocus
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") saveEdit(e, person.id);
                          if (e.key === "Escape") cancelEdit(e);
                        }}
                        placeholder="Enter name..."
                        className="h-6 text-xs px-1.5"
                      />
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-6 w-6 shrink-0"
                        onClick={(e) => saveEdit(e, person.id)}
                        disabled={!editName.trim() || updatePerson.isPending}
                      >
                        <Check className="h-3 w-3" />
                      </Button>
                      <Button size="icon" variant="ghost" className="h-6 w-6 shrink-0" onClick={cancelEdit}>
                        <X className="h-3 w-3" />
                      </Button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1">
                      <p className="text-xs font-medium truncate flex-1" title={person.display_name}>
                        {person.display_name}
                      </p>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-5 w-5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                        onClick={(e) => startEdit(e, person.id, person.display_name)}
                        title="Rename"
                      >
                        <Pencil className="h-3 w-3" />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-5 w-5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-destructive hover:text-destructive"
                        onClick={(e) => handleDelete(e, person.id, person.display_name)}
                        title="Delete person"
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>
                  )}
                  <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                    <span className="flex items-center gap-0.5">
                      <Film className="h-2.5 w-2.5" />
                      {person.asset_count}
                    </span>
                    <span className="flex items-center gap-0.5">
                      <Mic className="h-2.5 w-2.5" />
                      {formatSpeaking(person.total_speaking_seconds ?? 0)}
                    </span>
                  </div>
                </div>
              </div>
            </Link>
          ))}
        </div>
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-4 mt-8">
            <Button
              size="sm"
              variant="outline"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
            >
              <ChevronLeft className="h-4 w-4 mr-1" /> Previous
            </Button>
            <span className="text-sm text-muted-foreground">
              Page {page + 1} of {totalPages}
            </span>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
            >
              Next <ChevronRight className="h-4 w-4 ml-1" />
            </Button>
          </div>
        )}
        </>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground">
          <Users className="h-12 w-12 mb-4 opacity-50" />
          <p>No people identified yet.</p>
          <p className="text-xs mt-1 mb-4">People appear here automatically as media is transcribed and analyzed.</p>
          <p className="text-xs max-w-md text-center">
            Already have processed media? It was analyzed before person identification existed —
            use <span className="text-foreground font-medium">Re-analyze Library</span> above to
            backfill voice and face profiles for existing assets.
          </p>
        </div>
      )}
    </div>
  );
}
