import { useEffect, useState } from "react";
import { useListMedia, getListMediaQueryKey } from "@workspace/api-client-react";
import type { EditorialRules, Workspace, Collection, CollectionItem } from "@workspace/api-client-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Loader2, Trash2, X, Clock, Film } from "lucide-react";
import { useEditorialActions, useEditorialState } from "@/hooks/use-editorial";
import { useAuth } from "@/lib/auth";

/** Creator or admin may delete; seeded records (created_by null) are admin-only. */
export function useCanDelete(createdBy: string | null | undefined): boolean {
  const { user } = useAuth();
  if (!user) return false;
  if (user.role === "admin") return true;
  return !!createdBy && createdBy === user.id;
}
import { cleanRules, formatTime, parseTime, itemRangeError } from "@/lib/editorial";

const fieldCls = "h-8 text-sm";

export function RulesFields({ value, onChange, hint }: { value: EditorialRules; onChange: (r: EditorialRules) => void; hint?: string }) {
  const set = (k: keyof EditorialRules, v: string) => onChange({ ...value, [k]: k === "air_year" ? (v ? Number(v) : null) : v || null });
  return (
    <fieldset className="rounded-md border border-border p-3 space-y-2.5">
      <legend className="px-1 text-[11px] uppercase tracking-wider text-muted-foreground">Auto-match rules</legend>
      {hint && <p className="text-[11px] text-muted-foreground -mt-1">{hint}</p>}
      <div className="grid grid-cols-2 gap-2">
        <div className="col-span-2 space-y-1">
          <Label className="text-xs">Filename / path contains</Label>
          <Input className={fieldCls} value={value.text ?? ""} onChange={(e) => set("text", e.target.value)} placeholder="e.g. praise" data-testid="input-rule-text" />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Original air year</Label>
          <Input className={fieldCls} type="number" min={1900} max={2100} value={value.air_year ?? ""} onChange={(e) => set("air_year", e.target.value)} placeholder="Any" data-testid="input-rule-year" />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Status</Label>
          <select className={`${fieldCls} w-full rounded-md border border-input bg-transparent px-2`} value={value.status ?? ""} onChange={(e) => set("status", e.target.value)} data-testid="select-rule-status">
            <option value="">Any</option>
            <option value="ready">Ready</option>
            <option value="processing">Processing</option>
            <option value="pending">Pending</option>
            <option value="error">Error</option>
          </select>
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Type</Label>
          <select className={`${fieldCls} w-full rounded-md border border-input bg-transparent px-2`} value={value.media_type ?? ""} onChange={(e) => set("media_type", e.target.value)} data-testid="select-rule-type">
            <option value="">Any</option>
            <option value="hide_images">Video &amp; audio (no images)</option>
            <option value="images">Images only</option>
          </select>
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Topic</Label>
          <Input className={fieldCls} value={value.topic ?? ""} onChange={(e) => set("topic", e.target.value)} placeholder="Any" data-testid="input-rule-topic" />
        </div>
      </div>
    </fieldset>
  );
}

export function ConfirmDelete({ open, onOpenChange, title, body, onConfirm, pending }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; body: string; onConfirm: () => void; pending?: boolean;
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{body}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction className="bg-destructive text-destructive-foreground hover:bg-destructive/90" disabled={pending}
            onClick={(e) => { e.preventDefault(); onConfirm(); }} data-testid="button-confirm-delete">
            {pending && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />} Delete
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function WorkspaceDialog({ open, onOpenChange, workspace, onSaved }: {
  open: boolean; onOpenChange: (o: boolean) => void; workspace: Workspace | null; onSaved?: (w: Workspace) => void;
}) {
  const actions = useEditorialActions();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [rules, setRules] = useState<EditorialRules>({});
  const [mediaIds, setMediaIds] = useState<string[]>([]);
  const [confirm, setConfirm] = useState(false);
  const canDelete = useCanDelete(workspace?.created_by);

  useEffect(() => {
    if (!open) return;
    setName(workspace?.name ?? "");
    setDescription(workspace?.description ?? "");
    setRules(workspace?.rules ?? {});
    setMediaIds(workspace?.media_ids ?? []);
  }, [open, workspace]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    actions.saveWorkspace(workspace?.id ?? null, { name: name.trim(), description: description.trim(), rules: cleanRules(rules), media_ids: mediaIds }, (w) => {
      onOpenChange(false);
      onSaved?.(w);
    });
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-md">
          <form onSubmit={submit} className="space-y-3">
            <DialogHeader>
              <DialogTitle>{workspace ? "Edit workspace" : "New team workspace"}</DialogTitle>
              <DialogDescription className="text-xs">
                A shared lens on the library. It includes pinned assets plus anything matching the rules. The full library stays one click away.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-1">
              <Label className="text-xs">Name</Label>
              <Input className={fieldCls} value={name} onChange={(e) => setName(e.target.value)} autoFocus data-testid="input-workspace-name" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Description</Label>
              <Textarea className="text-sm min-h-[56px]" value={description} onChange={(e) => setDescription(e.target.value)} data-testid="input-workspace-description" />
            </div>
            <RulesFields value={rules} onChange={setRules} hint="Assets match when every filled rule matches." />
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span data-testid="text-workspace-pinned">{mediaIds.length} pinned asset{mediaIds.length === 1 ? "" : "s"}</span>
              {mediaIds.length > 0 && (
                <button type="button" className="hover:text-foreground underline-offset-2 hover:underline" onClick={() => setMediaIds([])} data-testid="button-clear-pinned">
                  Unpin all
                </button>
              )}
            </div>
            <DialogFooter className="gap-2 sm:justify-between">
              {workspace && canDelete ? (
                <Button type="button" variant="ghost" size="sm" className="text-destructive hover:text-destructive" onClick={() => setConfirm(true)} data-testid="button-delete-workspace">
                  <Trash2 className="h-3.5 w-3.5 mr-1.5" /> Delete
                </Button>
              ) : <span />}
              <Button type="submit" size="sm" disabled={!name.trim() || actions.pending.workspace} data-testid="button-save-workspace">
                {actions.pending.workspace && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
                {workspace ? "Save" : "Create workspace"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmDelete open={confirm} onOpenChange={setConfirm} pending={actions.pending.deleteWorkspace}
        title={`Delete “${workspace?.name}”?`}
        body="The workspace and its rules are removed for everyone. Media stays in the library; collections linked to it become unlinked."
        onConfirm={() => workspace && actions.removeWorkspace(workspace.id, () => { setConfirm(false); onOpenChange(false); })} />
    </>
  );
}

type ItemDraft = { id: string; media_id: string; inText: string; outText: string; note: string };

const toDraft = (i: CollectionItem): ItemDraft => ({
  id: i.id, media_id: i.media_id, inText: formatTime(i.start), outText: formatTime(i.end), note: i.note ?? "",
});

export function CollectionDialog({ open, onOpenChange, collection, defaultWorkspaceId, onSaved, draft }: {
  open: boolean; onOpenChange: (o: boolean) => void; collection: Collection | null; defaultWorkspaceId: string | null;
  onSaved?: (c: Collection) => void;
  /** collection is an unsaved pre-filled draft (create, not update) */
  draft?: boolean;
}) {
  const existing = draft ? null : collection;
  const canDelete = useCanDelete(existing?.created_by);
  const actions = useEditorialActions();
  const { data: state } = useEditorialState();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [kind, setKind] = useState<"manual" | "smart">("manual");
  const [visibility, setVisibility] = useState<"personal" | "team">("team");
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [rules, setRules] = useState<EditorialRules>({});
  const [items, setItems] = useState<ItemDraft[]>([]);
  const [confirm, setConfirm] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName(collection?.name ?? "");
    setDescription(collection?.description ?? "");
    setKind(collection?.kind ?? "manual");
    setVisibility(collection?.visibility ?? "team");
    setWorkspaceId(collection ? collection.workspace_id ?? null : defaultWorkspaceId);
    setRules(collection?.rules ?? {});
    setItems((collection?.items ?? []).map(toDraft));
  }, [open, collection, defaultWorkspaceId]);

  const ids = Array.from(new Set(items.map((i) => i.media_id)));
  const mediaParams = { ids: ids.join(","), limit: Math.max(1, ids.length) };
  const { data: media } = useListMedia(mediaParams, {
    query: { queryKey: getListMediaQueryKey(mediaParams), enabled: open && ids.length > 0 },
  });
  const nameOf = (id: string) => media?.items.find((m) => m.id === id)?.filename ?? `Asset ${id.slice(0, 8)}`;

  const errors = items.map((i) => {
    const s = parseTime(i.inText), e = parseTime(i.outText);
    if ((i.inText && s == null) || (i.outText && e == null)) return "Use m:ss or h:mm:ss.";
    return itemRangeError(s, e);
  });
  const invalid = errors.some(Boolean);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || invalid) return;
    actions.saveCollection(existing?.id ?? null, {
      name: name.trim(), description: description.trim(), workspace_id: workspaceId, kind, visibility,
      rules: kind === "smart" ? cleanRules(rules) : {},
      items: items.map((i) => ({ id: i.id, media_id: i.media_id, start: parseTime(i.inText), end: parseTime(i.outText), note: i.note.trim() })),
    }, (c) => { onOpenChange(false); onSaved?.(c); });
  };

  const patch = (idx: number, p: Partial<ItemDraft>) => setItems((cur) => cur.map((x, i) => (i === idx ? { ...x, ...p } : x)));
  const seg = (active: boolean) => `px-2.5 h-7 text-xs rounded transition-colors ${active ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground"}`;

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-xl max-h-[90dvh] overflow-y-auto">
          <form onSubmit={submit} className="space-y-3">
            <DialogHeader>
              <DialogTitle>{existing ? "Edit collection" : "New collection"}</DialogTitle>
              <DialogDescription className="text-xs">
                Manual collections hold hand-picked assets and timecoded selects. Smart collections follow rules inside their workspace.
              </DialogDescription>
            </DialogHeader>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <div className="space-y-1 sm:col-span-2">
                <Label className="text-xs">Name</Label>
                <Input className={fieldCls} value={name} onChange={(e) => setName(e.target.value)} autoFocus data-testid="input-collection-name" />
              </div>
              <div className="space-y-1 sm:col-span-2">
                <Label className="text-xs">Description</Label>
                <Input className={fieldCls} value={description} onChange={(e) => setDescription(e.target.value)} data-testid="input-collection-description" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Kind</Label>
                <div className="flex gap-1 rounded-md border border-border p-0.5 w-fit">
                  <button type="button" className={seg(kind === "manual")} onClick={() => setKind("manual")} data-testid="button-kind-manual">Manual</button>
                  <button type="button" className={seg(kind === "smart")} onClick={() => setKind("smart")} data-testid="button-kind-smart">Smart</button>
                </div>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Visible to</Label>
                <div className="flex gap-1 rounded-md border border-border p-0.5 w-fit">
                  <button type="button" className={seg(visibility === "team")} onClick={() => setVisibility("team")} data-testid="button-visibility-team">Team</button>
                  <button type="button" className={seg(visibility === "personal")} onClick={() => setVisibility("personal")} data-testid="button-visibility-personal">Only me</button>
                </div>
              </div>
              <div className="space-y-1 sm:col-span-2">
                <Label className="text-xs">Workspace</Label>
                <select className={`${fieldCls} w-full rounded-md border border-input bg-transparent px-2`} value={workspaceId ?? ""}
                  onChange={(e) => setWorkspaceId(e.target.value || null)} data-testid="select-collection-workspace">
                  <option value="">None (whole library)</option>
                  {(state?.workspaces ?? []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </select>
              </div>
            </div>
            {kind === "smart" && (
              <RulesFields value={rules} onChange={setRules}
                hint={workspaceId ? "Narrows the workspace: assets must match the workspace and these rules." : "Applies across the whole library."} />
            )}
            {kind === "manual" && (
              <div className="rounded-md border border-border">
                <div className="flex items-center justify-between px-3 py-2 border-b border-border">
                  <span className="text-[11px] uppercase tracking-wider text-muted-foreground">Items · {items.length}</span>
                  <span className="text-[11px] text-muted-foreground">Leave in/out empty for the whole asset</span>
                </div>
                {items.length === 0 ? (
                  <p className="px-3 py-5 text-xs text-muted-foreground text-center">
                    Empty. Add assets from the library selection or a select from an asset's player.
                  </p>
                ) : (
                  <ul className="divide-y divide-border max-h-72 overflow-y-auto">
                    {items.map((it, idx) => (
                      <li key={it.id} className="px-3 py-2 space-y-1.5" data-testid={`row-collection-item-${it.id}`}>
                        <div className="flex items-center gap-2 min-w-0">
                          {it.inText || it.outText ? <Clock className="h-3.5 w-3.5 text-primary shrink-0" /> : <Film className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}
                          <span className="text-xs truncate flex-1">{nameOf(it.media_id)}</span>
                          <button type="button" aria-label="Remove item" className="text-muted-foreground hover:text-destructive"
                            onClick={() => setItems((cur) => cur.filter((_, i) => i !== idx))} data-testid={`button-remove-item-${it.id}`}>
                            <X className="h-3.5 w-3.5" />
                          </button>
                        </div>
                        <div className="flex gap-1.5">
                          <Input className="h-7 text-xs font-mono w-20" placeholder="In" value={it.inText} onChange={(e) => patch(idx, { inText: e.target.value })} data-testid={`input-item-in-${it.id}`} />
                          <Input className="h-7 text-xs font-mono w-20" placeholder="Out" value={it.outText} onChange={(e) => patch(idx, { outText: e.target.value })} data-testid={`input-item-out-${it.id}`} />
                          <Input className="h-7 text-xs flex-1" placeholder="Note" value={it.note} onChange={(e) => patch(idx, { note: e.target.value })} data-testid={`input-item-note-${it.id}`} />
                        </div>
                        {errors[idx] && <p className="text-[11px] text-destructive">{errors[idx]}</p>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            <DialogFooter className="gap-2 sm:justify-between">
              {existing && canDelete ? (
                <Button type="button" variant="ghost" size="sm" className="text-destructive hover:text-destructive" onClick={() => setConfirm(true)} data-testid="button-delete-collection">
                  <Trash2 className="h-3.5 w-3.5 mr-1.5" /> Delete
                </Button>
              ) : <span />}
              <Button type="submit" size="sm" disabled={!name.trim() || invalid || actions.pending.collection} data-testid="button-save-collection">
                {actions.pending.collection && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
                {existing ? "Save" : "Create collection"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmDelete open={confirm} onOpenChange={setConfirm} pending={actions.pending.deleteCollection}
        title={`Delete “${collection?.name}”?`}
        body="The collection and its selects are removed. Media in the library is not affected."
        onConfirm={() => collection && actions.removeCollection(collection.id, () => { setConfirm(false); onOpenChange(false); })} />
    </>
  );
}
