import { useState } from "react";
import { useLocation } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  useListProjects,
  getListProjectsQueryKey,
  useCreateProject,
  useUpdateProject,
  useDeleteProject,
  useListMedia,
  getListMediaQueryKey,
} from "@workspace/api-client-react";
import type { Project, MediaAsset } from "@workspace/api-client-react";
import { ClipThumb } from "@/components/project/clip-thumb";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  FolderKanban, Plus, Scissors, BookOpen, Wand2, Clapperboard, Trash2, Loader2,
  MoreVertical, Pencil, Archive, ArchiveRestore, Clock,
} from "lucide-react";
import { formatRuntime, parseRuntime } from "@/lib/runtime";

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export default function Projects() {
  const [, navigate] = useLocation();
  const queryClient = useQueryClient();
  const { data: projects, isLoading } = useListProjects();
  const mediaParams = { limit: 200 };
  const { data: media } = useListMedia(mediaParams, {
    query: { queryKey: getListMediaQueryKey(mediaParams) },
  });
  const createMutation = useCreateProject();
  const updateMutation = useUpdateProject();
  const deleteMutation = useDeleteProject();

  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [runtime, setRuntime] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);
  const [renameTarget, setRenameTarget] = useState<{ id: string; name: string } | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [showArchived, setShowArchived] = useState(false);

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: getListProjectsQueryKey() });

  const runtimeInvalid = runtime.trim() !== "" && parseRuntime(runtime) === null;

  const submitCreate = () => {
    if (!name.trim() || runtimeInvalid) return;
    createMutation.mutate(
      {
        data: {
          name: name.trim(),
          description: description.trim() || null,
          target_runtime_seconds: runtime.trim() ? parseRuntime(runtime) : null,
        },
      },
      {
        onSuccess: (p) => {
          invalidate();
          setCreateOpen(false);
          setName("");
          setDescription("");
          setRuntime("");
          navigate(`/projects/${p.id}`);
        },
      },
    );
  };

  const submitDelete = () => {
    if (!deleteTarget) return;
    deleteMutation.mutate(
      { id: deleteTarget.id },
      { onSuccess: () => { invalidate(); setDeleteTarget(null); } },
    );
  };

  const submitRename = () => {
    if (!renameTarget || !renameValue.trim()) return;
    updateMutation.mutate(
      { id: renameTarget.id, data: { name: renameValue.trim() } },
      { onSuccess: () => { invalidate(); setRenameTarget(null); } },
    );
  };

  const toggleArchive = (p: Project) => {
    updateMutation.mutate(
      { id: p.id, data: { status: p.status === "archived" ? "active" : "archived" } },
      { onSuccess: invalidate },
    );
  };

  const active = projects?.filter((p) => p.status !== "archived") ?? [];
  const archived = projects?.filter((p) => p.status === "archived") ?? [];
  const visible = showArchived ? archived : active;

  const previewAssets = (p: Project): MediaAsset[] => {
    const items = media?.items ?? [];
    const pool = p.media_ids?.length ? items.filter((a) => p.media_ids!.includes(a.id)) : items;
    return pool.slice(0, 4);
  };

  const projectCard = (p: Project) => (
    <Card
      key={p.id}
      className={`cursor-pointer hover:border-primary/50 transition-colors ${p.status === "archived" ? "opacity-70" : ""}`}
      onClick={() => navigate(`/projects/${p.id}`)}
    >
      <CardHeader className="flex flex-row items-start justify-between space-y-0">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <CardTitle className="truncate">{p.name}</CardTitle>
            {p.status === "archived" && <Badge variant="secondary">Archived</Badge>}
          </div>
          {p.description && (
            <p className="text-sm text-muted-foreground mt-1 line-clamp-2">{p.description}</p>
          )}
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="h-8 w-8 shrink-0 text-muted-foreground"
              onClick={(e) => e.stopPropagation()}
            >
              <MoreVertical className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
            <DropdownMenuItem onClick={() => { setRenameTarget({ id: p.id, name: p.name }); setRenameValue(p.name); }}>
              <Pencil className="h-4 w-4 mr-2" /> Rename
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => toggleArchive(p)}>
              {p.status === "archived"
                ? <><ArchiveRestore className="h-4 w-4 mr-2" /> Unarchive</>
                : <><Archive className="h-4 w-4 mr-2" /> Archive</>}
            </DropdownMenuItem>
            <DropdownMenuItem
              className="text-red-400 focus:text-red-400"
              onClick={() => setDeleteTarget({ id: p.id, name: p.name })}
            >
              <Trash2 className="h-4 w-4 mr-2" /> Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </CardHeader>
      <CardContent>
        {previewAssets(p).length > 0 && (
          <div className="flex gap-1.5 mb-3">
            {previewAssets(p).map((a) => (
              <ClipThumb key={a.id} url={a.thumbnail_url} className="h-12 w-20" />
            ))}
            {(p.media_ids?.length ?? 0) > 4 && (
              <div className="flex h-12 w-10 items-center justify-center rounded bg-muted/60 text-xs text-muted-foreground">
                +{p.media_ids!.length - 4}
              </div>
            )}
          </div>
        )}
        <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <Scissors className="h-3.5 w-3.5" /> {p.counts.clip_lists} lists
          </span>
          <span className="flex items-center gap-1.5">
            <BookOpen className="h-3.5 w-3.5" /> {p.counts.stories} stories
          </span>
          <span className="flex items-center gap-1.5">
            <Wand2 className="h-3.5 w-3.5" /> {p.counts.reels} reels
          </span>
          <span className="flex items-center gap-1.5">
            <Clapperboard className="h-3.5 w-3.5" /> {p.counts.renders} renders
          </span>
          {p.target_runtime_seconds != null && (
            <span className="flex items-center gap-1.5" title="Target run time">
              <Clock className="h-3.5 w-3.5" /> {formatRuntime(p.target_runtime_seconds)}
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground mt-3">
          Last activity {relativeTime(p.updated_at ?? p.created_at)} · created {new Date(p.created_at).toLocaleDateString()}
        </p>
      </CardContent>
    </Card>
  );

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Projects</h1>
          <p className="text-sm text-muted-foreground mt-1">
            One workspace per story — find footage, assemble clips, cut, and deliver.
          </p>
        </div>
        <div className="flex gap-2">
          {archived.length > 0 && (
            <Button variant="outline" onClick={() => setShowArchived(!showArchived)}>
              {showArchived ? "Show active" : `Archived (${archived.length})`}
            </Button>
          )}
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4 mr-2" /> New Project
          </Button>
        </div>
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FolderKanban className="h-5 w-5" /> New Project
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="proj-name">Name</Label>
              <Input
                id="proj-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Evening special — housing vote"
                onKeyDown={(e) => e.key === "Enter" && submitCreate()}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="proj-desc">Description (optional)</Label>
              <Textarea
                id="proj-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What is this project about?"
                rows={3}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="proj-runtime">Target run time (optional)</Label>
              <Input
                id="proj-runtime"
                value={runtime}
                onChange={(e) => setRuntime(e.target.value)}
                placeholder="MM:SS or HH:MM:SS — e.g. 22:30"
                onKeyDown={(e) => e.key === "Enter" && submitCreate()}
              />
              {runtimeInvalid ? (
                <p className="text-xs text-red-400">Use MM:SS or HH:MM:SS (a plain number counts as minutes).</p>
              ) : (
                <p className="text-xs text-muted-foreground">How long the finished piece should run — a plain number counts as minutes.</p>
              )}
            </div>
            {createMutation.isError && (
              <p className="text-sm text-red-400">Could not create the project — try again.</p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button onClick={submitCreate} disabled={!name.trim() || runtimeInvalid || createMutation.isPending}>
              {createMutation.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!renameTarget} onOpenChange={(open) => !open && setRenameTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename "{renameTarget?.name}"</DialogTitle>
          </DialogHeader>
          <Input
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submitRename()}
            autoFocus
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenameTarget(null)}>Cancel</Button>
            <Button onClick={submitRename} disabled={!renameValue.trim() || updateMutation.isPending}>
              {updateMutation.isPending ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete "{deleteTarget?.name}"?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Clip lists, stories, reels, and renders linked to this project are kept — they just lose the project link.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button variant="destructive" onClick={submitDelete} disabled={deleteMutation.isPending}>
              {deleteMutation.isPending ? "Deleting..." : "Delete Project"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {isLoading ? (
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {[...Array(3)].map((_, i) => <Card key={i} className="animate-pulse h-40 bg-muted" />)}
        </div>
      ) : visible.length ? (
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {visible.map(projectCard)}
        </div>
      ) : (
        <div className="text-center text-muted-foreground py-20 border border-dashed border-border rounded-lg">
          <FolderKanban className="h-8 w-8 mx-auto mb-3 opacity-50" />
          <p>{showArchived ? "No archived projects." : "No projects yet."}</p>
          {!showArchived && (
            <Button className="mt-4" variant="outline" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4 mr-2" /> Create your first project
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
