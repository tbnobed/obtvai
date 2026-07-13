import { useState } from "react";
import { useListPeople, useReanalyzePeople, useUpdatePerson, getListPeopleQueryKey } from "@workspace/api-client-react";
import { Link } from "wouter";
import { Users, User, Mic, Film, ScanFace, Pencil, Check, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useQueryClient } from "@tanstack/react-query";

function formatSpeaking(seconds: number) {
  const m = Math.floor(seconds / 60);
  if (m >= 60) return `${Math.floor(m / 60)}h ${m % 60}m`;
  return `${m}m`;
}

export default function People() {
  const { data, isLoading } = useListPeople();
  const reanalyzeMutation = useReanalyzePeople();
  const updatePerson = useUpdatePerson();
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
          {data?.length ? (
            <p className="text-sm text-muted-foreground">
              {data.length} {data.length === 1 ? "person" : "people"} identified across the library
            </p>
          ) : null}
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

      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="animate-pulse bg-muted aspect-square rounded-md" />
          ))}
        </div>
      ) : data?.length ? (
        <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {data.map((person) => (
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
                  {person.name_source !== "manual" && person.display_name.startsWith("Person ") && (
                    <div className="absolute top-2 right-2">
                      <Badge variant="secondary" className="text-xs">unnamed</Badge>
                    </div>
                  )}
                </div>
                <div className="p-3 flex-1 flex flex-col gap-1.5">
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
                        className="h-7 text-sm px-2"
                      />
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7 shrink-0"
                        onClick={(e) => saveEdit(e, person.id)}
                        disabled={!editName.trim() || updatePerson.isPending}
                      >
                        <Check className="h-3.5 w-3.5" />
                      </Button>
                      <Button size="icon" variant="ghost" className="h-7 w-7 shrink-0" onClick={cancelEdit}>
                        <X className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1">
                      <p className="text-sm font-medium truncate flex-1" title={person.display_name}>
                        {person.display_name}
                      </p>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-6 w-6 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                        onClick={(e) => startEdit(e, person.id, person.display_name)}
                        title="Rename"
                      >
                        <Pencil className="h-3 w-3" />
                      </Button>
                    </div>
                  )}
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <Film className="h-3 w-3" />
                      {person.asset_count} {person.asset_count === 1 ? "asset" : "assets"}
                    </span>
                    <span className="flex items-center gap-1">
                      <Mic className="h-3 w-3" />
                      {formatSpeaking(person.total_speaking_seconds ?? 0)}
                    </span>
                  </div>
                  {person.key_topics?.length ? (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {person.key_topics.slice(0, 2).map((t) => (
                        <Badge key={t} variant="outline" className="text-[10px] px-1.5 py-0 truncate max-w-full">
                          {t}
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            </Link>
          ))}
        </div>
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
