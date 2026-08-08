import { useMemo, useState } from "react";
import {
  useListFolders, getListFoldersQueryKey,
  useListMedia, getListMediaQueryKey,
} from "@workspace/api-client-react";
import type { MediaAsset, MediaFolder } from "@workspace/api-client-react";
import { Button } from "@/components/ui/button";
import { Check, ChevronDown, ChevronRight, Folder, FolderOpen, Loader2, Plus } from "lucide-react";
import { ClipThumb } from "@/components/project/clip-thumb";
import { formatTC } from "@/lib/timecode";

/** Browsable library folder tree for the Find & Media tab — the NLE "media
 *  browser": explore the whole library by folder, preview, and pull assets
 *  (or entire folders) into the project's media pool. */

function AssetRow({
  asset,
  inPool,
  disabled,
  onAdd,
  onPreview,
}: {
  asset: MediaAsset;
  inPool: boolean;
  disabled: boolean;
  onAdd: () => void;
  onPreview: () => void;
}) {
  return (
    <div
      className={`flex items-center gap-2 rounded p-1.5 text-sm ${
        inPool ? "bg-emerald-500/10" : "bg-muted/40 hover:bg-muted/70"
      } transition-colors`}
      data-testid={`browse-asset-${asset.id}`}
    >
      <button type="button" className="flex items-center gap-2 flex-1 min-w-0 text-left" title={`${asset.filename} — click to preview`} onClick={onPreview}>
        <ClipThumb url={asset.thumbnail_url} mediaId={asset.id} time={0} className="h-8 w-12 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-medium">{asset.filename}</div>
          <div className="text-[10px] text-muted-foreground font-mono">{formatTC(asset.duration_seconds ?? 0)}</div>
        </div>
      </button>
      {inPool ? (
        <span className="flex items-center gap-1 text-[10px] text-emerald-400 shrink-0 pr-1" title="Already in the media pool">
          <Check className="h-3.5 w-3.5" /> In pool
        </span>
      ) : (
        <Button size="sm" variant="outline" className="h-6 text-xs shrink-0" disabled={disabled} onClick={onAdd} data-testid={`button-browse-add-${asset.id}`}>
          <Plus className="h-3 w-3 mr-1" /> Add
        </Button>
      )}
    </div>
  );
}

function FolderNode({
  folder,
  childFolders,
  depth,
  pool,
  disabled,
  onAdd,
  onPreview,
  folderChildren,
}: {
  folder: { id: string; name: string; asset_count?: number };
  childFolders: (f: string | null) => MediaFolder[];
  depth: number;
  pool: string[];
  disabled: boolean;
  onAdd: (ids: string[]) => void;
  onPreview: (a: MediaAsset) => void;
  folderChildren: MediaFolder[];
}) {
  const [open, setOpen] = useState(false);
  const params = { folder: folder.id, limit: 200 };
  const { data, isLoading } = useListMedia(params, {
    query: { queryKey: getListMediaQueryKey(params), enabled: open, staleTime: 30_000 },
  });
  const assets = data?.items ?? [];
  const addable = assets.filter((a) => !pool.includes(a.id)).map((a) => a.id);

  return (
    <div>
      <div
        className="flex items-center gap-1.5 rounded px-1.5 py-1 hover:bg-muted/60 cursor-pointer select-none"
        style={{ paddingLeft: depth * 14 + 6 }}
        onClick={() => setOpen((o) => !o)}
        data-testid={`browse-folder-${folder.id}`}
      >
        {open ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}
        {open ? <FolderOpen className="h-4 w-4 text-amber-400/80 shrink-0" /> : <Folder className="h-4 w-4 text-amber-400/80 shrink-0" />}
        <span className="text-sm truncate flex-1">{folder.name}</span>
        {folder.asset_count != null && (
          <span className="text-[10px] text-muted-foreground font-mono shrink-0">{folder.asset_count}</span>
        )}
        {open && addable.length > 0 && (
          <Button
            size="sm" variant="outline" className="h-6 text-xs shrink-0"
            disabled={disabled}
            onClick={(e) => { e.stopPropagation(); onAdd(addable); }}
            title={`Add all ${addable.length} asset${addable.length === 1 ? "" : "s"} in this folder to the pool`}
            data-testid={`button-add-all-${folder.id}`}
          >
            <Plus className="h-3 w-3 mr-1" /> Add all
          </Button>
        )}
      </div>
      {open && (
        <div className="space-y-1 py-1" style={{ paddingLeft: depth * 14 + 20 }}>
          {childFolders(folder.id).map((f) => (
            <FolderNode
              key={f.id} folder={f} childFolders={childFolders} depth={0}
              pool={pool} disabled={disabled} onAdd={onAdd} onPreview={onPreview}
              folderChildren={childFolders(f.id)}
            />
          ))}
          {isLoading && <div className="flex items-center gap-2 text-xs text-muted-foreground px-1.5 py-1"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…</div>}
          {assets.map((a) => (
            <AssetRow
              key={a.id} asset={a} inPool={pool.includes(a.id)} disabled={disabled}
              onAdd={() => onAdd([a.id])} onPreview={() => onPreview(a)}
            />
          ))}
          {!isLoading && !assets.length && !folderChildren.length && (
            <div className="text-xs text-muted-foreground px-1.5 py-1">Empty folder.</div>
          )}
        </div>
      )}
    </div>
  );
}

export function LibraryBrowser({
  pool,
  disabled,
  onAdd,
  onPreview,
}: {
  pool: string[];
  disabled: boolean;
  onAdd: (ids: string[]) => void;
  onPreview: (a: MediaAsset) => void;
}) {
  const { data: folders, isLoading } = useListFolders({
    query: { queryKey: getListFoldersQueryKey(), staleTime: 30_000 },
  });

  const childFolders = useMemo(() => {
    const byParent = new Map<string | null, MediaFolder[]>();
    for (const f of folders ?? []) {
      const key = f.parent_id ?? null;
      if (!byParent.has(key)) byParent.set(key, []);
      byParent.get(key)!.push(f);
    }
    for (const list of byParent.values()) list.sort((a, b) => a.name.localeCompare(b.name));
    return (parent: string | null) => byParent.get(parent) ?? [];
  }, [folders]);

  if (isLoading) {
    return <div className="flex items-center gap-2 text-sm text-muted-foreground py-6 justify-center"><Loader2 className="h-4 w-4 animate-spin" /> Loading library…</div>;
  }

  const roots = childFolders(null);

  return (
    <div className="space-y-0.5" data-testid="library-browser">
      {roots.map((f) => (
        <FolderNode
          key={f.id} folder={f} childFolders={childFolders} depth={0}
          pool={pool} disabled={disabled} onAdd={onAdd} onPreview={onPreview}
          folderChildren={childFolders(f.id)}
        />
      ))}
      {/* Unfiled assets live at the library root */}
      <FolderNode
        folder={{ id: "root", name: "Unfiled" }} childFolders={() => []} depth={0}
        pool={pool} disabled={disabled} onAdd={onAdd} onPreview={onPreview}
        folderChildren={[]}
      />
      {!roots.length && (
        <p className="text-xs text-muted-foreground px-1.5 pt-2">
          No folders yet — assets without a folder are under “Unfiled”.
        </p>
      )}
    </div>
  );
}
