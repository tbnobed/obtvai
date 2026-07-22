import { useEffect, useRef, useState } from "react";
import {
  useListMedia, getListMediaQueryKey, useIngestMedia, useImportMediaFromLink,
  useListFolders, getListFoldersQueryKey, useCreateFolder, useUpdateFolder, useDeleteFolder,
  useMoveMedia, useListProjects, getListProjectsQueryKey, useUpdateProject, getGetProjectQueryKey,
} from "@workspace/api-client-react";
import type { MediaAsset, MediaFolder } from "@workspace/api-client-react";
import { Link, useLocation, useSearch } from "wouter";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import {
  ContextMenu, ContextMenuTrigger, ContextMenuContent, ContextMenuItem,
  ContextMenuSeparator, ContextMenuSub, ContextMenuSubTrigger, ContextMenuSubContent,
} from "@/components/ui/context-menu";
import { Film, Upload, Plus, Search, LayoutGrid, List, ChevronLeft, ChevronRight, ChevronDown, User, Tag, X, Link2, Folder, FolderOpen, FolderPlus, FolderInput, Clapperboard, Pencil, Trash2, CheckSquare, Library as LibraryIcon, Inbox } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/use-toast";

const ASSET_DRAG_TYPE = "application/x-obtv-asset-ids";
const FOLDER_DRAG_TYPE = "application/x-obtv-folder-id";

// fetch() cannot report upload progress — use XHR so large uploads show a
// real progress bar instead of an indefinite "uploading..." state.
function uploadFileWithProgress(
  file: File,
  title: string | undefined,
  onProgress: (percent: number) => void,
): { promise: Promise<void>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<void>((resolve, reject) => {
    const formData = new FormData();
    formData.append("file", file);
    if (title) formData.append("title", title);

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`HTTP ${xhr.status}`));
    });
    xhr.addEventListener("error", () => reject(new Error("Network error during upload")));
    xhr.addEventListener("abort", () => reject(new Error("Upload cancelled")));

    xhr.open("POST", "/api/media/upload");
    xhr.send(formData);
  });
  return { promise, abort: () => xhr.abort() };
}

const PAGE_SIZE = 60;

export default function Library() {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<string>("created_desc");
  const [view, setView] = useState<"grid" | "list">(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("view");
    if (fromUrl === "list" || fromUrl === "grid") return fromUrl;
    return (localStorage.getItem("library-view") as "grid" | "list") || "grid";
  });
  const [page, setPage] = useState(0);
  // "" = all media, "root" = unfiled only, otherwise a folder id.
  const [folderFilter, setFolderFilter] = useState<string>("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Debounce typing so we don't refetch on every keystroke.
  useEffect(() => {
    const t = setTimeout(() => { setSearch(searchInput); setPage(0); }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  // Person/topic filters arrive via URL from the Insights page ("find view").
  const searchString = useSearch();
  const urlParams = new URLSearchParams(searchString);
  const personFilter = urlParams.get("person") || "";
  const personName = urlParams.get("person_name") || "";
  const topicFilter = urlParams.get("topic") || "";
  const topicLabel = urlParams.get("topic_label") || topicFilter;

  useEffect(() => { setPage(0); }, [personFilter, topicFilter]);

  const listParams = {
    status: statusFilter || undefined,
    search: search || undefined,
    sort: (sort as any) || undefined,
    person: personFilter || undefined,
    topic: topicFilter || undefined,
    folder: folderFilter || undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  };
  const { data, isLoading } = useListMedia(listParams, { query: { queryKey: getListMediaQueryKey(listParams) } });
  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const setViewPersist = (v: "grid" | "list") => {
    setView(v);
    localStorage.setItem("library-view", v);
  };

  const [, navigate] = useLocation();

  const formatDuration = (s?: number | null) =>
    s == null ? "—" : `${Math.floor(s / 60)}m ${Math.floor(s % 60)}s`;
  
  const queryClient = useQueryClient();
  const { toast } = useToast();

  // ── Folders / selection / projects ─────────────────────────────────────
  const { data: folders } = useListFolders();
  const { data: projects } = useListProjects();
  const createFolder = useCreateFolder();
  const updateFolder = useUpdateFolder();
  const deleteFolder = useDeleteFolder();
  const moveMedia = useMoveMedia();
  const updateProject = useUpdateProject();

  const [newFolderOpen, setNewFolderOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [newFolderParent, setNewFolderParent] = useState<{ id: string; name: string } | null>(null);
  const [renameTarget, setRenameTarget] = useState<{ id: string; name: string } | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem("library-folders-expanded") || "[]"));
    } catch {
      return new Set();
    }
  });

  const toggleExpanded = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      localStorage.setItem("library-folders-expanded", JSON.stringify(Array.from(next)));
      return next;
    });
  };

  // Folder tree helpers — folders are flat rows with parent_id; build a tree.
  const childrenOf = (parentId: string | null) =>
    (folders ?? [])
      .filter(f => (f.parent_id ?? null) === parentId)
      .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));

  const isDescendantOf = (candidateId: string, ancestorId: string): boolean => {
    let cur: string | null | undefined = candidateId;
    const seen = new Set<string>();
    while (cur) {
      if (cur === ancestorId) return true;
      if (seen.has(cur)) return false;
      seen.add(cur);
      cur = (folders ?? []).find(f => f.id === cur)?.parent_id ?? null;
    }
    return false;
  };

  // Total asset count for a folder including everything nested under it.
  // Visited set guards against runaway recursion if legacy data ever holds a cycle.
  const deepCount = (folderId: string, visited: Set<string> = new Set()): number => {
    if (visited.has(folderId)) return 0;
    visited.add(folderId);
    return (
      ((folders ?? []).find(f => f.id === folderId)?.asset_count ?? 0) +
      childrenOf(folderId).reduce((sum, c) => sum + deepCount(c.id, visited), 0)
    );
  };

  const invalidateLibrary = () => {
    queryClient.invalidateQueries({ queryKey: getListMediaQueryKey() });
    queryClient.invalidateQueries({ queryKey: getListFoldersQueryKey() });
  };

  useEffect(() => { setSelected(new Set()); }, [folderFilter, page, statusFilter, search]);

  const toggleSelected = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Drag payload: if the dragged asset is part of the selection, move the
  // whole selection; otherwise just the dragged asset.
  const dragIds = (assetId: string) =>
    selected.has(assetId) ? Array.from(selected) : [assetId];

  const handleAssetDragStart = (e: React.DragEvent, assetId: string) => {
    const ids = dragIds(assetId);
    e.dataTransfer.setData(ASSET_DRAG_TYPE, JSON.stringify(ids));
    e.dataTransfer.effectAllowed = "move";
  };

  const readDraggedIds = (e: React.DragEvent): string[] => {
    try {
      const raw = e.dataTransfer.getData(ASSET_DRAG_TYPE);
      const ids = raw ? JSON.parse(raw) : [];
      return Array.isArray(ids) ? ids.map(String) : [];
    } catch {
      return [];
    }
  };

  const doMove = (ids: string[], folderId: string | null, folderName: string) => {
    if (!ids.length) return;
    moveMedia.mutate({ data: { media_ids: ids, folder_id: folderId } }, {
      onSuccess: (res) => {
        invalidateLibrary();
        setSelected(new Set());
        toast({ description: `Moved ${res.moved} file${res.moved === 1 ? "" : "s"} to ${folderName}` });
      },
      onError: () => toast({ variant: "destructive", description: "Move failed" }),
    });
  };

  const handleFolderDrop = (e: React.DragEvent, folderId: string | null, folderName: string) => {
    e.preventDefault();
    e.stopPropagation();
    setDropTarget(null);
    // A folder is being dragged — reparent it instead of moving assets.
    const draggedFolder = e.dataTransfer.getData(FOLDER_DRAG_TYPE);
    if (draggedFolder) {
      if (draggedFolder === folderId) return;
      if (folderId && isDescendantOf(folderId, draggedFolder)) {
        toast({ variant: "destructive", description: "Can't move a folder into its own subfolder" });
        return;
      }
      updateFolder.mutate({ id: draggedFolder, data: { parent_id: folderId } }, {
        onSuccess: () => {
          if (folderId) setExpanded(prev => new Set(prev).add(folderId));
          queryClient.invalidateQueries({ queryKey: getListFoldersQueryKey() });
        },
        onError: () => toast({ variant: "destructive", description: "Move failed" }),
      });
      return;
    }
    doMove(readDraggedIds(e), folderId, folderName);
  };

  const handleCreateFolder = (e: React.FormEvent) => {
    e.preventDefault();
    const name = newFolderName.trim();
    if (!name) return;
    createFolder.mutate({ data: { name, parent_id: newFolderParent?.id ?? null } }, {
      onSuccess: () => {
        if (newFolderParent) setExpanded(prev => new Set(prev).add(newFolderParent.id));
        setNewFolderOpen(false);
        setNewFolderName("");
        setNewFolderParent(null);
        queryClient.invalidateQueries({ queryKey: getListFoldersQueryKey() });
      },
      onError: () => toast({ variant: "destructive", description: "Could not create folder" }),
    });
  };

  const handleRenameFolder = (e: React.FormEvent) => {
    e.preventDefault();
    if (!renameTarget) return;
    const name = renameTarget.name.trim();
    if (!name) return;
    updateFolder.mutate({ id: renameTarget.id, data: { name } }, {
      onSuccess: () => {
        setRenameTarget(null);
        queryClient.invalidateQueries({ queryKey: getListFoldersQueryKey() });
      },
      onError: () => toast({ variant: "destructive", description: "Rename failed" }),
    });
  };

  const handleDeleteFolder = (id: string) => {
    deleteFolder.mutate({ id }, {
      onSuccess: () => {
        if (folderFilter === id) setFolderFilter("");
        invalidateLibrary();
      },
      onError: () => toast({ variant: "destructive", description: "Delete failed" }),
    });
  };

  // ── Folder tree (file-browser sidebar) ─────────────────────────────────
  const folderDragProps = (folderId: string | null, folderName: string, key: string) => ({
    onDragOver: (e: React.DragEvent) => {
      if (e.dataTransfer.types.includes(ASSET_DRAG_TYPE) || e.dataTransfer.types.includes(FOLDER_DRAG_TYPE)) {
        e.preventDefault();
        e.stopPropagation();
        setDropTarget(key);
      }
    },
    onDragLeave: () => setDropTarget(prev => (prev === key ? null : prev)),
    onDrop: (e: React.DragEvent) => handleFolderDrop(e, folderId, folderName),
  });

  const renderFolderNode = (f: MediaFolder, depth: number): React.ReactElement => {
    const kids = childrenOf(f.id);
    const isOpen = expanded.has(f.id);
    const active = folderFilter === f.id;
    const count = deepCount(f.id);
    return (
      <div key={f.id}>
        <ContextMenu>
          <ContextMenuTrigger asChild>
            <div
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData(FOLDER_DRAG_TYPE, f.id);
                e.dataTransfer.effectAllowed = "move";
              }}
              onClick={() => { setFolderFilter(f.id); setPage(0); }}
              style={{ paddingLeft: `${depth * 14 + 6}px` }}
              className={`group/node flex items-center gap-1 h-7 pr-2 rounded-md text-sm cursor-pointer select-none transition-colors ${active ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground hover:bg-muted/50"} ${dropTarget === f.id ? "ring-1 ring-primary bg-primary/10" : ""}`}
              {...folderDragProps(f.id, f.name, f.id)}
            >
              <button
                type="button"
                className={`h-4 w-4 shrink-0 flex items-center justify-center rounded hover:bg-muted ${kids.length ? "" : "invisible"}`}
                onClick={(e) => { e.stopPropagation(); toggleExpanded(f.id); }}
              >
                {isOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              </button>
              {active || isOpen ? <FolderOpen className="h-4 w-4 shrink-0 text-primary/80" /> : <Folder className="h-4 w-4 shrink-0" />}
              <span className="truncate flex-1">{f.name}</span>
              {count > 0 && <span className="text-[11px] text-muted-foreground tabular-nums">{count}</span>}
            </div>
          </ContextMenuTrigger>
          <ContextMenuContent>
            <ContextMenuItem onSelect={() => { setNewFolderParent({ id: f.id, name: f.name }); setNewFolderOpen(true); }}>
              <FolderPlus className="h-4 w-4 mr-2" />
              New subfolder
            </ContextMenuItem>
            <ContextMenuItem onSelect={() => setRenameTarget({ id: f.id, name: f.name })}>
              <Pencil className="h-4 w-4 mr-2" />
              Rename
            </ContextMenuItem>
            <ContextMenuSeparator />
            <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={() => handleDeleteFolder(f.id)}>
              <Trash2 className="h-4 w-4 mr-2" />
              Delete folder
            </ContextMenuItem>
          </ContextMenuContent>
        </ContextMenu>
        {isOpen && kids.map(k => renderFolderNode(k, depth + 1))}
      </div>
    );
  };

  // Flattened tree for the "Move to folder" context submenu.
  const flatTree = (parentId: string | null = null, depth = 0): { f: MediaFolder; depth: number }[] =>
    childrenOf(parentId).flatMap(f => [{ f, depth }, ...flatTree(f.id, depth + 1)]);

  const addToProject = (assetId: string, projectId: string) => {
    const ids = selected.has(assetId) ? Array.from(selected) : [assetId];
    const project = (projects ?? []).find(p => p.id === projectId);
    if (!project) return;
    const merged = Array.from(new Set([...(project.media_ids ?? []), ...ids]));
    updateProject.mutate({ id: projectId, data: { name: project.name, media_ids: merged } }, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListProjectsQueryKey() });
        queryClient.invalidateQueries({ queryKey: getGetProjectQueryKey(projectId) });
        setSelected(new Set());
        toast({ description: `Added ${ids.length} file${ids.length === 1 ? "" : "s"} to ${project.name}` });
      },
      onError: () => toast({ variant: "destructive", description: "Could not add to project" }),
    });
  };

  // Shared right-click menu content for an asset (grid card or list row).
  const assetMenu = (asset: MediaAsset) => {
    const count = selected.has(asset.id) ? selected.size : 1;
    return (
      <ContextMenuContent className="w-56">
        <ContextMenuItem onSelect={() => navigate(`/library/${asset.id}`)}>
          Open
        </ContextMenuItem>
        <ContextMenuItem onSelect={() => toggleSelected(asset.id)}>
          <CheckSquare className="h-4 w-4 mr-2" />
          {selected.has(asset.id) ? "Deselect" : "Select"}
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuSub>
          <ContextMenuSubTrigger>
            <Clapperboard className="h-4 w-4 mr-2" />
            Add to project{count > 1 ? ` (${count})` : ""}
          </ContextMenuSubTrigger>
          <ContextMenuSubContent className="w-56 max-h-72 overflow-y-auto">
            {(projects ?? []).filter(p => p.status !== "archived").length ? (
              (projects ?? []).filter(p => p.status !== "archived").map(p => (
                <ContextMenuItem key={p.id} onSelect={() => addToProject(asset.id, p.id)}>
                  {p.name}
                </ContextMenuItem>
              ))
            ) : (
              <ContextMenuItem disabled>No projects yet</ContextMenuItem>
            )}
          </ContextMenuSubContent>
        </ContextMenuSub>
        <ContextMenuSub>
          <ContextMenuSubTrigger>
            <FolderInput className="h-4 w-4 mr-2" />
            Move to folder{count > 1 ? ` (${count})` : ""}
          </ContextMenuSubTrigger>
          <ContextMenuSubContent className="w-56 max-h-72 overflow-y-auto">
            <ContextMenuItem onSelect={() => doMove(dragIds(asset.id), null, "the library root")}>
              Library root
            </ContextMenuItem>
            {flatTree().map(({ f, depth }) => (
              <ContextMenuItem key={f.id} onSelect={() => doMove(dragIds(asset.id), f.id, f.name)}>
                <span style={{ width: `${depth * 12}px` }} className="shrink-0" />
                <Folder className="h-4 w-4 mr-2" />
                <span className="truncate">{f.name}</span>
              </ContextMenuItem>
            ))}
          </ContextMenuSubContent>
        </ContextMenuSub>
      </ContextMenuContent>
    );
  };

  const ingest = useIngestMedia();
  const [ingestPath, setIngestPath] = useState("");
  const [ingestTitle, setIngestTitle] = useState("");
  const [ingestOpen, setIngestOpen] = useState(false);

  const handleIngest = (e: React.FormEvent) => {
    e.preventDefault();
    if (!ingestPath) return;
    ingest.mutate({ data: { file_path: ingestPath, title: ingestTitle || undefined } }, {
      onSuccess: () => {
        setIngestOpen(false);
        setIngestPath("");
        setIngestTitle("");
        queryClient.invalidateQueries({ queryKey: getListMediaQueryKey() });
      }
    });
  };

  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const abortUploadRef = useRef<(() => void) | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const VIDEO_EXTENSIONS = [".mp4", ".mov", ".mkv", ".avi", ".mxf", ".ts", ".m2ts", ".wmv", ".flv", ".webm"];

  const pickFile = (file: File | undefined | null) => {
    if (!file) return;
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!VIDEO_EXTENSIONS.includes(ext)) {
      setUploadError(`Unsupported file type: ${ext || "unknown"}`);
      setUploadFile(null);
      return;
    }
    setUploadError(null);
    setUploadFile(file);
  };

  const resetUpload = () => {
    abortUploadRef.current?.();
    abortUploadRef.current = null;
    setUploadFile(null);
    setUploadTitle("");
    setUploadError(null);
    setDragActive(false);
    setUploading(false);
    setUploadProgress(0);
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile || uploading) return;
    setUploadError(null);
    setUploading(true);
    setUploadProgress(0);
    const { promise, abort } = uploadFileWithProgress(uploadFile, uploadTitle || undefined, setUploadProgress);
    abortUploadRef.current = abort;
    try {
      await promise;
      abortUploadRef.current = null;
      setUploadOpen(false);
      resetUpload();
      queryClient.invalidateQueries({ queryKey: getListMediaQueryKey() });
    } catch (err) {
      abortUploadRef.current = null;
      setUploading(false);
      if (err instanceof Error && err.message === "Upload cancelled") return;
      setUploadError("Upload failed. Check the file and try again.");
    }
  };

  const [linkOpen, setLinkOpen] = useState(false);
  const [linkUrl, setLinkUrl] = useState("");
  const [linkTitle, setLinkTitle] = useState("");
  const [linkError, setLinkError] = useState<string | null>(null);
  const importLink = useImportMediaFromLink();

  const handleLinkImport = (e: React.FormEvent) => {
    e.preventDefault();
    const url = linkUrl.trim();
    if (!url) return;
    if (!/^https?:\/\/\S+$/.test(url)) {
      setLinkError("Enter a valid http(s) link.");
      return;
    }
    setLinkError(null);
    importLink.mutate({ data: { url, title: linkTitle || undefined } }, {
      onSuccess: () => {
        setLinkOpen(false);
        setLinkUrl("");
        setLinkTitle("");
        queryClient.invalidateQueries({ queryKey: getListMediaQueryKey() });
      },
      onError: () => setLinkError("Import failed — make sure the link is public and points to a video or folder."),
    });
  };

  const clearFilterParam = (param: "person" | "topic") => {
    const next = new URLSearchParams(searchString);
    next.delete(param);
    next.delete(param === "person" ? "person_name" : "topic_label");
    const qs = next.toString();
    navigate(`/library${qs ? `?${qs}` : ""}`);
  };

  const formatSize = (bytes: number) => {
    if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
    if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
    return `${(bytes / 1024).toFixed(0)} KB`;
  };

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* ── Folder browser sidebar ── */}
      <aside className="w-60 shrink-0 border-r border-border flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-3 h-12 border-b border-border shrink-0">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Folders</span>
          <button
            type="button"
            onClick={() => { setNewFolderParent(null); setNewFolderOpen(true); }}
            className="h-6 w-6 flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted"
            title="New folder"
          >
            <FolderPlus className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
          <div
            onClick={() => { setFolderFilter(""); setPage(0); }}
            className={`flex items-center gap-1.5 h-7 px-1.5 rounded-md text-sm cursor-pointer select-none transition-colors ${folderFilter === "" ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground hover:bg-muted/50"} ${dropTarget === "all" ? "ring-1 ring-primary bg-primary/10" : ""}`}
            {...folderDragProps(null, "the library root", "all")}
          >
            <LibraryIcon className="h-4 w-4 shrink-0" />
            <span className="flex-1">All Media</span>
            <span className="text-[11px] text-muted-foreground tabular-nums">{folderFilter === "" ? total : ""}</span>
          </div>
          <div
            onClick={() => { setFolderFilter("root"); setPage(0); }}
            className={`flex items-center gap-1.5 h-7 px-1.5 rounded-md text-sm cursor-pointer select-none transition-colors ${folderFilter === "root" ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground hover:bg-muted/50"} ${dropTarget === "root" ? "ring-1 ring-primary bg-primary/10" : ""}`}
            {...folderDragProps(null, "the library root", "root")}
          >
            <Inbox className="h-4 w-4 shrink-0" />
            <span className="flex-1">Unfiled</span>
          </div>
          <div className="pt-2 mt-1 border-t border-border/60">
            {childrenOf(null).map(f => renderFolderNode(f, 0))}
            {!childrenOf(null).length && (
              <p className="text-xs text-muted-foreground px-1.5 py-2">No folders yet — create one, then drag files onto it.</p>
            )}
          </div>
        </div>
        {selected.size > 0 && (
          <div className="border-t border-border p-2 flex items-center justify-between shrink-0">
            <span className="text-xs text-muted-foreground">{selected.size} selected</span>
            <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={() => setSelected(new Set())}>
              Clear
            </Button>
          </div>
        )}
      </aside>

      <div className="flex-1 p-8 overflow-y-auto flex flex-col min-w-0">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold tracking-tight">Media Library</h1>
        <div className="flex gap-3 items-center flex-wrap justify-end">
          <div className="relative">
            <Search className="h-4 w-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              placeholder="Search media..."
              className="h-9 w-56 pl-8"
            />
          </div>
          <select
            value={sort}
            onChange={e => { setSort(e.target.value); setPage(0); }}
            className="h-9 px-3 py-1 rounded-md border border-input bg-background text-sm"
          >
            <option value="created_desc">Newest First</option>
            <option value="created_asc">Oldest First</option>
            <option value="name_asc">Name A–Z</option>
            <option value="name_desc">Name Z–A</option>
            <option value="duration_desc">Longest First</option>
            <option value="duration_asc">Shortest First</option>
            <option value="size_desc">Largest First</option>
            <option value="size_asc">Smallest First</option>
          </select>
          <select 
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(0); }}
            className="h-9 px-3 py-1 rounded-md border border-input bg-background text-sm"
          >
            <option value="">All Statuses</option>
            <option value="ready">Ready</option>
            <option value="processing">Processing</option>
            <option value="pending">Pending</option>
            <option value="error">Error</option>
          </select>
          <div className="flex rounded-md border border-input overflow-hidden">
            <button
              type="button"
              onClick={() => setViewPersist("grid")}
              className={`h-9 px-2.5 flex items-center ${view === "grid" ? "bg-secondary text-foreground" : "bg-background text-muted-foreground hover:text-foreground"}`}
              title="Grid view"
            >
              <LayoutGrid className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setViewPersist("list")}
              className={`h-9 px-2.5 flex items-center border-l border-input ${view === "list" ? "bg-secondary text-foreground" : "bg-background text-muted-foreground hover:text-foreground"}`}
              title="List view"
            >
              <List className="h-4 w-4" />
            </button>
          </div>
          <Dialog open={uploadOpen} onOpenChange={(open) => { setUploadOpen(open); if (!open) resetUpload(); }}>
            <DialogTrigger asChild>
              <Button variant="secondary" className="gap-2">
                <Upload className="h-4 w-4" />
                Upload File
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Upload Media</DialogTitle>
              </DialogHeader>
              <form onSubmit={handleUpload} className="space-y-4 pt-4">
                <div
                  className={`border-2 border-dashed rounded-md p-8 text-center cursor-pointer transition-colors ${dragActive ? "border-primary bg-primary/5" : "border-border hover:border-primary/50"}`}
                  onClick={() => fileInputRef.current?.click()}
                  onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
                  onDragLeave={() => setDragActive(false)}
                  onDrop={(e) => { e.preventDefault(); setDragActive(false); pickFile(e.dataTransfer.files?.[0]); }}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept={VIDEO_EXTENSIONS.join(",")}
                    className="hidden"
                    onChange={(e) => pickFile(e.target.files?.[0])}
                  />
                  {uploadFile ? (
                    <div className="space-y-1">
                      <Film className="h-8 w-8 mx-auto text-primary" />
                      <p className="text-sm font-medium break-all">{uploadFile.name}</p>
                      <p className="text-xs text-muted-foreground">{formatSize(uploadFile.size)}</p>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      <Upload className="h-8 w-8 mx-auto text-muted-foreground" />
                      <p className="text-sm">Drag & drop a video file here, or click to browse</p>
                      <p className="text-xs text-muted-foreground">MP4, MOV, MKV, AVI, MXF and more</p>
                    </div>
                  )}
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Title (Optional)</label>
                  <Input
                    value={uploadTitle}
                    onChange={e => setUploadTitle(e.target.value)}
                    placeholder="Interview setup"
                  />
                </div>
                {uploadError && <p className="text-sm text-destructive">{uploadError}</p>}
                {uploading && (
                  <div className="space-y-1.5">
                    <Progress value={uploadProgress} />
                    <div className="flex justify-between text-xs text-muted-foreground">
                      <span>
                        {uploadProgress < 100
                          ? `Uploading... ${uploadFile ? formatSize(uploadFile.size * uploadProgress / 100) : ""} of ${uploadFile ? formatSize(uploadFile.size) : ""}`
                          : "Processing upload on server..."}
                      </span>
                      <span className="tabular-nums font-medium">{uploadProgress}%</span>
                    </div>
                  </div>
                )}
                <Button type="submit" className="w-full" disabled={!uploadFile || uploading}>
                  {uploading ? (uploadProgress < 100 ? `Uploading... ${uploadProgress}%` : "Finalizing...") : "Upload & Process"}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
          <Dialog open={linkOpen} onOpenChange={(open) => { setLinkOpen(open); if (!open) { setLinkUrl(""); setLinkTitle(""); setLinkError(null); } }}>
            <DialogTrigger asChild>
              <Button variant="secondary" className="gap-2">
                <Link2 className="h-4 w-4" />
                Import Link
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Import from Link</DialogTitle>
              </DialogHeader>
              <form onSubmit={handleLinkImport} className="space-y-4 pt-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium">Shared Link</label>
                  <Input
                    value={linkUrl}
                    onChange={e => setLinkUrl(e.target.value)}
                    placeholder="https://www.dropbox.com/scl/fi/..."
                    required
                  />
                  <p className="text-xs text-muted-foreground">
                    Paste a public Dropbox link to a video file or a folder of videos — the server downloads it in the background and processes it like any other upload. Folder links import every video inside.
                  </p>
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Title (Optional)</label>
                  <Input
                    value={linkTitle}
                    onChange={e => setLinkTitle(e.target.value)}
                    placeholder="Interview setup"
                  />
                </div>
                {linkError && <p className="text-sm text-destructive">{linkError}</p>}
                <Button type="submit" className="w-full" disabled={!linkUrl.trim() || importLink.isPending}>
                  {importLink.isPending ? "Queuing download..." : "Import & Process"}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
          <Dialog open={ingestOpen} onOpenChange={setIngestOpen}>
            <DialogTrigger asChild>
              <Button className="gap-2">
                <Plus className="h-4 w-4" />
                Ingest File
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Ingest Media</DialogTitle>
              </DialogHeader>
              <form onSubmit={handleIngest} className="space-y-4 pt-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium">Absolute File Path</label>
                  <Input 
                    value={ingestPath} 
                    onChange={e => setIngestPath(e.target.value)}
                    placeholder="/data/media/video.mp4"
                    required
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Title (Optional)</label>
                  <Input 
                    value={ingestTitle} 
                    onChange={e => setIngestTitle(e.target.value)}
                    placeholder="Interview setup"
                  />
                </div>
                <Button type="submit" className="w-full" disabled={ingest.isPending}>
                  {ingest.isPending ? "Ingesting..." : "Start Ingest"}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      <Dialog open={newFolderOpen} onOpenChange={(open) => { setNewFolderOpen(open); if (!open) { setNewFolderName(""); setNewFolderParent(null); } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{newFolderParent ? `New subfolder in ${newFolderParent.name}` : "New Folder"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreateFolder} className="space-y-4 pt-4">
            <Input
              value={newFolderName}
              onChange={e => setNewFolderName(e.target.value)}
              placeholder="Folder name"
              autoFocus
              maxLength={120}
            />
            <Button type="submit" className="w-full" disabled={!newFolderName.trim() || createFolder.isPending}>
              {createFolder.isPending ? "Creating..." : "Create Folder"}
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={!!renameTarget} onOpenChange={(open) => { if (!open) setRenameTarget(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename Folder</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleRenameFolder} className="space-y-4 pt-4">
            <Input
              value={renameTarget?.name ?? ""}
              onChange={e => setRenameTarget(t => (t ? { ...t, name: e.target.value } : t))}
              placeholder="Folder name"
              autoFocus
              maxLength={120}
            />
            <Button type="submit" className="w-full" disabled={!renameTarget?.name.trim() || updateFolder.isPending}>
              {updateFolder.isPending ? "Renaming..." : "Rename"}
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      {(personFilter || topicFilter) && (
        <div className="flex items-center gap-2 mb-6 -mt-4 flex-wrap">
          <span className="text-xs text-muted-foreground">Showing footage for:</span>
          {personFilter && (
            <Badge variant="secondary" className="gap-1.5 pr-1">
              <User className="h-3 w-3" />
              {personName || personFilter}
              <button
                type="button"
                className="ml-0.5 rounded-sm hover:bg-muted-foreground/20 p-0.5"
                onClick={() => clearFilterParam("person")}
                title="Clear person filter"
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          )}
          {topicFilter && (
            <Badge variant="secondary" className="gap-1.5 pr-1">
              <Tag className="h-3 w-3" />
              {topicLabel}
              <button
                type="button"
                className="ml-0.5 rounded-sm hover:bg-muted-foreground/20 p-0.5"
                onClick={() => clearFilterParam("topic")}
                title="Clear topic filter"
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          )}
        </div>
      )}

      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {[...Array(10)].map((_, i) => (
            <div key={i} className="animate-pulse bg-muted aspect-video rounded-md" />
          ))}
        </div>
      ) : data?.items.length ? (
        view === "grid" ? (
          <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {data.items.map(asset => (
              <ContextMenu key={asset.id}>
                <ContextMenuTrigger asChild>
                  <div
                    draggable
                    onDragStart={(e) => handleAssetDragStart(e, asset.id)}
                    onClick={(e) => {
                      if (e.ctrlKey || e.metaKey || e.shiftKey) {
                        e.preventDefault();
                        toggleSelected(asset.id);
                        return;
                      }
                      navigate(`/library/${asset.id}`);
                    }}
                    className={`group border bg-card rounded-md overflow-hidden cursor-pointer transition-colors flex flex-col h-full ${selected.has(asset.id) ? "border-primary ring-1 ring-primary" : "border-border hover:border-primary"}`}
                  >
                    <div className="aspect-video bg-muted relative">
                      {asset.thumbnail_url ? (
                        <img src={`/api/thumbnails/${asset.thumbnail_url}`} alt={asset.filename} className="w-full h-full object-cover" draggable={false} />
                      ) : (
                        <div className="absolute inset-0 flex items-center justify-center">
                          <Film className="h-8 w-8 text-muted-foreground/50" />
                        </div>
                      )}
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); toggleSelected(asset.id); }}
                        className={`absolute top-2 left-2 h-5 w-5 rounded border flex items-center justify-center transition-opacity ${selected.has(asset.id) ? "bg-primary border-primary text-primary-foreground opacity-100" : "bg-background/80 border-border opacity-0 group-hover:opacity-100"}`}
                        title={selected.has(asset.id) ? "Deselect" : "Select"}
                      >
                        {selected.has(asset.id) && <CheckSquare className="h-3.5 w-3.5" />}
                      </button>
                      <div className="absolute bottom-2 right-2">
                        <Badge variant={asset.status === 'ready' ? 'default' : asset.status === 'error' ? 'destructive' : 'secondary'} className="text-xs">
                          {asset.status}
                        </Badge>
                      </div>
                    </div>
                    <div className="p-3 flex-1">
                      <p className="text-sm font-medium truncate" title={asset.filename}>{asset.filename}</p>
                      {asset.duration_seconds ? (
                        <p className="text-xs text-muted-foreground mt-1">{formatDuration(asset.duration_seconds)}</p>
                      ) : null}
                    </div>
                  </div>
                </ContextMenuTrigger>
                {assetMenu(asset)}
              </ContextMenu>
            ))}
          </div>
        ) : (
          <div className="border border-border rounded-md overflow-hidden shrink-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/40 text-left text-xs text-muted-foreground">
                  <th className="px-3 py-2 font-medium w-16"></th>
                  <th className="px-3 py-2 font-medium">Name</th>
                  <th className="px-3 py-2 font-medium w-24">Duration</th>
                  <th className="px-3 py-2 font-medium w-24">Size</th>
                  <th className="px-3 py-2 font-medium w-24">Codec</th>
                  <th className="px-3 py-2 font-medium w-28">Added</th>
                  <th className="px-3 py-2 font-medium w-28">Status</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map(asset => (
                  <ContextMenu key={asset.id}>
                    <ContextMenuTrigger asChild>
                  <tr
                    draggable
                    onDragStart={(e) => handleAssetDragStart(e, asset.id)}
                    className={`border-b border-border last:border-b-0 cursor-pointer ${selected.has(asset.id) ? "bg-primary/10" : "hover:bg-muted/30"}`}
                    onClick={(e) => {
                      if (e.ctrlKey || e.metaKey || e.shiftKey) {
                        e.preventDefault();
                        toggleSelected(asset.id);
                        return;
                      }
                      navigate(`/library/${asset.id}`);
                    }}
                  >
                    <td className="px-3 py-1.5">
                      <Link href={`/library/${asset.id}`}>
                        <div className="w-12 h-7 bg-muted rounded overflow-hidden flex items-center justify-center">
                          {asset.thumbnail_url ? (
                            <img src={`/api/thumbnails/${asset.thumbnail_url}`} alt="" className="w-full h-full object-cover" />
                          ) : (
                            <Film className="h-3.5 w-3.5 text-muted-foreground/50" />
                          )}
                        </div>
                      </Link>
                    </td>
                    <td className="px-3 py-1.5 max-w-0 w-full">
                      <Link href={`/library/${asset.id}`} className="block truncate font-medium hover:text-primary" title={asset.filename}>
                        {asset.filename}
                      </Link>
                    </td>
                    <td className="px-3 py-1.5 text-muted-foreground tabular-nums">{formatDuration(asset.duration_seconds)}</td>
                    <td className="px-3 py-1.5 text-muted-foreground tabular-nums">{asset.file_size_bytes ? formatSize(asset.file_size_bytes) : "—"}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">{asset.codec || "—"}</td>
                    <td className="px-3 py-1.5 text-muted-foreground whitespace-nowrap">{asset.created_at ? new Date(asset.created_at).toLocaleDateString() : "—"}</td>
                    <td className="px-3 py-1.5">
                      <Badge variant={asset.status === 'ready' ? 'default' : asset.status === 'error' ? 'destructive' : 'secondary'} className="text-xs">
                        {asset.status}
                      </Badge>
                    </td>
                  </tr>
                    </ContextMenuTrigger>
                    {assetMenu(asset)}
                  </ContextMenu>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground">
          <Upload className="h-12 w-12 mb-4 opacity-50" />
          <p>{search || statusFilter || personFilter || topicFilter ? "No media matches your filters." : "No media assets found."}</p>
        </div>
      )}

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between mt-6">
          <p className="text-xs text-muted-foreground">
            Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
          </p>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(p => p - 1)}>
              <ChevronLeft className="h-4 w-4" /> Prev
            </Button>
            <span className="text-xs text-muted-foreground tabular-nums">{page + 1} / {pageCount}</span>
            <Button variant="outline" size="sm" disabled={page + 1 >= pageCount} onClick={() => setPage(p => p + 1)}>
              Next <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
      </div>
    </div>
  );
}
