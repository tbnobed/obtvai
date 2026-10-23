import { useState } from "react";
import { useListMedia, getListMediaQueryKey } from "@workspace/api-client-react";
import type { Workspace, Collection, CollectionItem } from "@workspace/api-client-react";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import {
  Library as LibraryIcon, ChevronDown, Check, Plus, Pencil, X, Layers, Sparkles as SmartIcon, User, Users, AlertTriangle, Play, Clock,
} from "lucide-react";
import { useEditorialActions, useEditorialState } from "@/hooks/use-editorial";
import { useCanEdit } from "@/lib/auth";
import { DEFAULT_WORKSPACES, collectionsForWorkspace, rulesSummary, formatTime, isTimed } from "@/lib/editorial";
import { WorkspaceDialog, CollectionDialog } from "./editorial-dialogs";

/**
 * Library scope switcher: All Library ⟷ team workspace ⟷ collection.
 * The "All Library" escape is always visible while scoped.
 */
export function ScopeBar({ workspace, collection, workspaceId, collectionId, onChange, scopedCount, explicitAllHint }: {
  /** true when the user explicitly chose All Library (?ws=all) */
  explicitAllHint?: boolean;
  workspace: Workspace | null; collection: Collection | null;
  workspaceId: string | null; collectionId: string | null;
  onChange: (workspaceId: string | null, collectionId: string | null) => void;
  scopedCount?: number | null;
}) {
  const { data: state, isLoading, isError, refetch } = useEditorialState();
  const actions = useEditorialActions();
  const canEdit = useCanEdit();
  const [wsDialog, setWsDialog] = useState<{ open: boolean; ws: Workspace | null }>({ open: false, ws: null });
  const [colDialog, setColDialog] = useState<{ open: boolean; col: Collection | null }>({ open: false, col: null });
  const scoped = !!(workspaceId || collectionId);
  const missing = (workspaceId && state && !workspace) || (collectionId && state && !collection);

  if (isLoading) {
    return <div className="h-8 w-72 rounded-md bg-muted/40 animate-pulse" data-testid="scope-bar-loading" />;
  }
  if (isError) {
    return (
      <div className="flex items-center gap-2 text-xs rounded-md border border-destructive/40 bg-destructive/10 px-2.5 py-1.5 w-fit" data-testid="scope-bar-error">
        <AlertTriangle className="h-3.5 w-3.5 text-destructive" />
        <span>{workspaceId || collectionId || !explicitAllHint ? "Workspaces couldn't load — scope unresolved." : "Workspaces couldn't load. Browsing All Library."}</span>
        <button className="underline underline-offset-2 hover:text-foreground" onClick={() => refetch()} data-testid="button-retry-workspaces">Retry</button>
        {!explicitAllHint && (
          <button className="underline underline-offset-2 hover:text-foreground" onClick={() => onChange(null, null)} data-testid="button-error-all-library">All Library</button>
        )}
      </div>
    );
  }

  const workspaces = state?.workspaces ?? [];
  const collections = collectionsForWorkspace(state?.collections ?? [], workspaceId);
  const createDefaults = () => {
    const existing = new Set(workspaces.map((w) => w.name.toLowerCase()));
    DEFAULT_WORKSPACES.filter((d) => !existing.has(d.name.toLowerCase()))
      .forEach((d) => actions.saveWorkspace(null, { ...d, media_ids: [] }));
  };
  const summary = collection ? (collection.kind === "smart" ? rulesSummary(collection.rules) : `${collection.items.length} item${collection.items.length === 1 ? "" : "s"}`)
    : workspace ? [rulesSummary(workspace.rules), workspace.media_ids.length ? `${workspace.media_ids.length} pinned` : ""].filter(Boolean).join(" · ") : "";

  const chip = "h-8 gap-1.5 px-2.5 text-xs font-medium max-w-[220px]";

  return (
    <div className="flex flex-wrap items-center gap-1.5 min-w-0" data-testid="scope-bar">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" className={`${chip} ${workspaceId ? "border-primary/50 bg-primary/10 text-foreground" : ""}`} data-testid="button-scope-workspace">
            {workspaceId ? <Users className="h-3.5 w-3.5 text-primary" /> : <LibraryIcon className="h-3.5 w-3.5" />}
            <span className="truncate">{workspace?.name ?? (workspaceId ? "Unknown workspace" : "All Library")}</span>
            <ChevronDown className="h-3 w-3 opacity-60" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-64">
          <DropdownMenuItem onSelect={() => onChange(null, null)} data-testid="menu-scope-all">
            <LibraryIcon className="h-3.5 w-3.5 mr-2" /> <span className="flex-1">All Library</span>
            {!scoped && <Check className="h-3.5 w-3.5 text-primary" />}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuLabel className="text-[11px] uppercase tracking-wider text-muted-foreground">Team workspaces</DropdownMenuLabel>
          {workspaces.length === 0 && canEdit && (
            <DropdownMenuItem onSelect={createDefaults} data-testid="menu-create-default-workspaces">
              <Plus className="h-3.5 w-3.5 mr-2" /> Set up Praise &amp; Stakelbeck
            </DropdownMenuItem>
          )}
          {workspaces.map((w) => (
            <DropdownMenuItem key={w.id} onSelect={() => onChange(w.id, null)} data-testid={`menu-scope-workspace-${w.id}`}>
              <Users className="h-3.5 w-3.5 mr-2 opacity-60" />
              <span className="flex-1 truncate">{w.name}</span>
              {state?.me.workspace_id === w.id && <span className="text-[10px] text-muted-foreground mr-1.5">default</span>}
              {workspaceId === w.id && <Check className="h-3.5 w-3.5 text-primary" />}
            </DropdownMenuItem>
          ))}
          {canEdit && <DropdownMenuSeparator />}
          {canEdit && <DropdownMenuItem onSelect={() => setWsDialog({ open: true, ws: null })} data-testid="menu-new-workspace">
            <Plus className="h-3.5 w-3.5 mr-2" /> New workspace…
          </DropdownMenuItem>}
          {workspace && canEdit && (
            <DropdownMenuItem onSelect={() => setWsDialog({ open: true, ws: workspace })} data-testid="menu-edit-workspace">
              <Pencil className="h-3.5 w-3.5 mr-2" /> Edit “{workspace.name}”…
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <span className="text-muted-foreground/50 text-xs">/</span>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" className={`${chip} ${collectionId ? "border-primary/50 bg-primary/10 text-foreground" : "text-muted-foreground"}`} data-testid="button-scope-collection">
            {collection?.kind === "smart" ? <SmartIcon className="h-3.5 w-3.5 text-primary" /> : <Layers className={`h-3.5 w-3.5 ${collectionId ? "text-primary" : ""}`} />}
            <span className="truncate">{collection?.name ?? (collectionId ? "Unknown collection" : "Collections")}</span>
            <ChevronDown className="h-3 w-3 opacity-60" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-72">
          {collectionId && (
            <>
              <DropdownMenuItem onSelect={() => onChange(workspaceId, null)} data-testid="menu-scope-no-collection">
                <X className="h-3.5 w-3.5 mr-2" /> {workspace ? `All of ${workspace.name}` : "Leave collection"}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
            </>
          )}
          {collections.length === 0 && <p className="px-2 py-2 text-xs text-muted-foreground">No collections {workspace ? `in ${workspace.name}` : "yet"}.</p>}
          <div className="max-h-72 overflow-y-auto">
            {collections.map((c) => (
              <DropdownMenuItem key={c.id} onSelect={() => onChange(c.workspace_id ?? null, c.id)} data-testid={`menu-scope-collection-${c.id}`}>
                {c.kind === "smart" ? <SmartIcon className="h-3.5 w-3.5 mr-2 opacity-60" /> : <Layers className="h-3.5 w-3.5 mr-2 opacity-60" />}
                <span className="flex-1 truncate">{c.name}</span>
                {c.visibility === "personal" ? <User className="h-3 w-3 opacity-50 ml-1" /> : null}
                {c.kind === "manual" && <span className="text-[10px] text-muted-foreground tabular-nums ml-1.5">{c.items.length}</span>}
                {collectionId === c.id && <Check className="h-3.5 w-3.5 text-primary ml-1.5" />}
              </DropdownMenuItem>
            ))}
          </div>
          {canEdit && <DropdownMenuSeparator />}
          {canEdit && <DropdownMenuItem onSelect={() => setColDialog({ open: true, col: null })} data-testid="menu-new-collection">
            <Plus className="h-3.5 w-3.5 mr-2" /> New collection…
          </DropdownMenuItem>}
          {collection && canEdit && (
            <DropdownMenuItem onSelect={() => setColDialog({ open: true, col: collection })} data-testid="menu-edit-collection">
              <Pencil className="h-3.5 w-3.5 mr-2" /> Edit “{collection.name}”…
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      {missing && (
        <span className="text-[11px] text-destructive flex items-center gap-1" data-testid="text-scope-missing">
          <AlertTriangle className="h-3 w-3" /> This scope no longer exists
        </span>
      )}
      {!missing && summary && (
        <span className="text-[11px] text-muted-foreground truncate max-w-[280px]" title={summary} data-testid="text-scope-summary">
          {summary}{scopedCount != null ? ` · ${scopedCount.toLocaleString()} in scope` : ""}
        </span>
      )}
      {scoped && (
        <button
          onClick={() => onChange(null, null)}
          className="ml-1 inline-flex items-center gap-1 h-6 px-2 rounded-full text-[11px] text-muted-foreground border border-border hover:text-foreground hover:border-foreground/30 transition-colors"
          data-testid="button-escape-all-library"
          title="Browse and search the full archive"
        >
          <X className="h-3 w-3" /> All Library
        </button>
      )}

      <WorkspaceDialog open={wsDialog.open} workspace={wsDialog.ws}
        onOpenChange={(open) => setWsDialog((d) => ({ ...d, open }))}
        onSaved={(w) => { if (!wsDialog.ws) onChange(w.id, null); }} />
      <CollectionDialog open={colDialog.open} collection={colDialog.col} defaultWorkspaceId={workspaceId}
        onOpenChange={(open) => setColDialog((d) => ({ ...d, open }))}
        onSaved={(c) => { if (!colDialog.col) onChange(c.workspace_id ?? workspaceId, c.id); }} />
    </div>
  );
}

/** Timecoded selects in the active collection, playable in place. */
export function CollectionSelects({ collection, onPlay }: {
  collection: Collection; onPlay: (item: CollectionItem, filename: string) => void;
}) {
  const timed = collection.items.filter(isTimed);
  const ids = Array.from(new Set(timed.map((i) => i.media_id)));
  const params = { ids: ids.join(","), limit: Math.max(1, ids.length) };
  const { data, isError } = useListMedia(params, { query: { queryKey: getListMediaQueryKey(params), enabled: ids.length > 0 } });
  const [open, setOpen] = useState(true);
  if (!timed.length) return null;
  const byId = new Map((data?.items ?? []).map((m) => [m.id, m]));
  return (
    <section className="mb-5 rounded-lg border border-border bg-card/60" data-testid="collection-selects">
      <button className="w-full flex items-center justify-between px-3 py-2 text-xs" onClick={() => setOpen((o) => !o)} data-testid="button-toggle-selects">
        <span className="flex items-center gap-1.5 font-medium"><Clock className="h-3.5 w-3.5 text-primary" /> Timecoded selects · {timed.length}</span>
        <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <ul className="border-t border-border divide-y divide-border/60 max-h-56 overflow-y-auto">
          {isError && <li className="px-3 py-2 text-xs text-destructive">Couldn't load asset names for these selects.</li>}
          {timed.map((it) => {
            const m = byId.get(it.media_id);
            const name = m?.filename ?? `Asset ${it.media_id.slice(0, 8)}`;
            return (
              <li key={it.id} className="group flex items-center gap-3 px-3 py-1.5 text-xs hover:bg-muted/40" data-testid={`row-select-${it.id}`}>
                <button className="h-6 w-6 rounded flex items-center justify-center bg-primary/15 text-primary hover:bg-primary/25 shrink-0"
                  onClick={() => onPlay(it, name)} aria-label="Play select" data-testid={`button-play-select-${it.id}`}>
                  <Play className="h-3 w-3 fill-current" />
                </button>
                <span className="font-mono tabular-nums text-muted-foreground shrink-0">{formatTime(it.start)}–{formatTime(it.end)}</span>
                <span className="truncate flex-1">{name}</span>
                {it.note && <span className="truncate max-w-[40%] text-muted-foreground italic">{it.note}</span>}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
