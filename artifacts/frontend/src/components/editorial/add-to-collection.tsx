import { useState } from "react";
import type { Collection, CollectionItem } from "@workspace/api-client-react";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Layers, Plus, Pin, Users, User, Check } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { useCanEdit } from "@/lib/auth";
import { useEditorialActions, useEditorialState, collectionInput, workspaceInput } from "@/hooks/use-editorial";
import { containsItem } from "@/lib/editorial";
import { CollectionDialog } from "./editorial-dialogs";

export type CollectionEntry = { media_id: string; start: number | null; end: number | null; note?: string };

const newItem = (e: CollectionEntry): CollectionItem => ({
  id: crypto.randomUUID(), media_id: e.media_id, start: e.start, end: e.end, note: e.note ?? "",
});

/**
 * Adds whole assets and/or timecoded selects to a manual collection, or pins
 * whole assets to a workspace. `getEntries` is read at click time so callers
 * can capture the current playhead.
 */
export function AddToCollectionMenu({ getEntries, label = "Collect", size = "sm", className = "" }: {
  getEntries: () => CollectionEntry[]; label?: string; size?: "sm" | "default"; className?: string;
}) {
  const { data: state, isError, refetch } = useEditorialState();
  const actions = useEditorialActions();
  const { toast } = useToast();
  const [creating, setCreating] = useState<CollectionItem[] | null>(null);
  const canEdit = useCanEdit();
  if (!canEdit) return null;

  const manual = (state?.collections ?? []).filter((c) => c.kind === "manual")
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));

  const addTo = (c: Collection) => {
    const entries = getEntries();
    const fresh = entries.filter((e) => !containsItem(c.items, e.media_id, e.start, e.end));
    if (!fresh.length) { toast({ description: `Already in “${c.name}”.` }); return; }
    actions.saveCollection(c.id, collectionInput(c, { items: [...c.items, ...fresh.map(newItem)] }), () =>
      toast({ description: `Added ${fresh.length} item${fresh.length === 1 ? "" : "s"} to “${c.name}”.` }),
      `Couldn't add to “${c.name}”`);
  };

  const pinTo = (wsId: string) => {
    const w = state?.workspaces.find((x) => x.id === wsId);
    if (!w) return;
    const ids = Array.from(new Set(getEntries().map((e) => e.media_id))).filter((id) => !w.media_ids.includes(id));
    if (!ids.length) { toast({ description: `Already pinned to ${w.name}.` }); return; }
    actions.saveWorkspace(w.id, workspaceInput(w, { media_ids: [...w.media_ids, ...ids] }), () =>
      toast({ description: `Pinned ${ids.length} asset${ids.length === 1 ? "" : "s"} to ${w.name}.` }));
  };

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size={size} className={`gap-1.5 shrink-0 ${className}`} data-testid="button-add-to-collection">
            <Layers className="h-4 w-4" /> <span>{label}</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-64">
          {isError ? (
            <DropdownMenuItem onSelect={() => refetch()} className="text-destructive" data-testid="menu-collections-retry">
              Collections failed to load — retry
            </DropdownMenuItem>
          ) : (
            <>
              <DropdownMenuLabel className="text-[11px] uppercase tracking-wider text-muted-foreground">Add to collection</DropdownMenuLabel>
              {manual.length === 0 && <p className="px-2 py-1.5 text-xs text-muted-foreground">No manual collections yet.</p>}
              <div className="max-h-64 overflow-y-auto">
                {manual.map((c) => {
                  const entries = getEntries();
                  const all = entries.length > 0 && entries.every((e) => containsItem(c.items, e.media_id, e.start, e.end));
                  return (
                    <DropdownMenuItem key={c.id} onSelect={() => addTo(c)} data-testid={`menu-add-collection-${c.id}`}>
                      {c.visibility === "personal" ? <User className="h-3.5 w-3.5 mr-2 opacity-60" /> : <Users className="h-3.5 w-3.5 mr-2 opacity-60" />}
                      <span className="truncate flex-1">{c.name}</span>
                      {all ? <Check className="h-3.5 w-3.5 text-primary" /> : <span className="text-[10px] text-muted-foreground tabular-nums">{c.items.length}</span>}
                    </DropdownMenuItem>
                  );
                })}
              </div>
              <DropdownMenuItem onSelect={() => setCreating(getEntries().map(newItem))} data-testid="menu-new-collection-from-selection">
                <Plus className="h-3.5 w-3.5 mr-2" /> New collection with {getEntries().length === 1 ? "this" : "these"}…
              </DropdownMenuItem>
              {(state?.workspaces.length ?? 0) > 0 && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuLabel className="text-[11px] uppercase tracking-wider text-muted-foreground">Pin whole asset to workspace</DropdownMenuLabel>
                  {state!.workspaces.map((w) => (
                    <DropdownMenuItem key={w.id} onSelect={() => pinTo(w.id)} data-testid={`menu-pin-workspace-${w.id}`}>
                      <Pin className="h-3.5 w-3.5 mr-2 opacity-60" /> {w.name}
                    </DropdownMenuItem>
                  ))}
                </>
              )}
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {creating && (
        <SeededCollectionDialog items={creating} defaultWorkspaceId={state?.me.workspace_id ?? null} onClose={() => setCreating(null)} />
      )}
    </>
  );
}

/** Opens the collection dialog pre-filled with items by creating an unsaved draft. */
function SeededCollectionDialog({ items, defaultWorkspaceId, onClose }: { items: CollectionItem[]; defaultWorkspaceId: string | null; onClose: () => void }) {
  const draft: Collection = {
    id: "", name: "", description: "", workspace_id: defaultWorkspaceId, kind: "manual", visibility: "team",
    rules: {}, items, created_by: null,
  };
  return <DraftCollectionDialog draft={draft} onClose={onClose} />;
}

function DraftCollectionDialog({ draft, onClose }: { draft: Collection; onClose: () => void }) {
  const [stable] = useState(draft);
  return (
    <CollectionDialog open onOpenChange={(o) => { if (!o) onClose(); }} collection={stable} draft
      defaultWorkspaceId={stable.workspace_id ?? null} />
  );
}
