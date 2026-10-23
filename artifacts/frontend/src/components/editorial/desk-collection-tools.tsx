import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getEditorialCollection, getGetEditorialCollectionQueryKey } from "@workspace/api-client-react";
import type { Collection } from "@workspace/api-client-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ChevronDown, ChevronLeft, ChevronRight, Layers, Sparkles as SmartIcon, User, Users, AlertTriangle } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { errorMessage } from "@/hooks/use-editorial";
import { useDeskList } from "@/hooks/use-desk";
import { CollectionDialog } from "@/components/editorial/editorial-dialogs";

const PICK_LIMIT = 50;

/** Searchable, server-paginated collection picker. Smart collections are listed but disabled. */
export function CollectionPicker({ value, onChange }: {
  value: { id: string; title: string } | null; onChange: (v: { id: string; title: string }) => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const list = useDeskList("collections", { q: q || undefined, sort: "title", offset: (page - 1) * PICK_LIMIT, limit: PICK_LIMIT });
  const total = list.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PICK_LIMIT));
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="h-7 text-xs w-52 justify-between" data-testid="select-bulk-collection">
          <span className="truncate">{value?.title ?? "Choose collection"}</span><ChevronDown className="h-3 w-3 opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-2 space-y-2" align="end">
        <Input autoFocus value={text} placeholder="Search collections" className="h-8 text-xs" data-testid="input-collection-picker-search"
          onChange={(e) => {
            const v = e.target.value; setText(v);
            clearTimeout(timer.current);
            timer.current = setTimeout(() => { setQ(v.trim()); setPage(1); }, 250);
          }} />
        <div className={`max-h-64 overflow-y-auto ${list.isPlaceholderData ? "opacity-60" : ""}`}>
          {list.isLoading ? Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-7 my-1 rounded bg-muted/40 animate-pulse" />)
            : list.isError ? (
              <div className="flex items-center gap-2 text-xs p-2"><AlertTriangle className="h-3.5 w-3.5 text-destructive" /> Couldn't load collections.
                <button className="underline" onClick={() => list.refetch()} data-testid="button-picker-retry">Retry</button></div>
            ) : (list.data?.items.length ?? 0) === 0 ? <p className="text-xs text-muted-foreground p-3 text-center">No collections found.</p>
            : list.data!.items.map((c) => {
              const smart = c.kind === "smart";
              return (
                <button key={c.id} disabled={smart} title={smart ? "Smart collections fill themselves from rules" : undefined}
                  onClick={() => { onChange({ id: c.id, title: c.title }); setOpen(false); }}
                  className={`w-full flex items-center gap-2 px-2 py-1.5 text-xs rounded text-left ${smart ? "opacity-50 cursor-not-allowed" : "hover:bg-muted/50"} ${value?.id === c.id ? "bg-primary/10" : ""}`}
                  data-testid={`option-collection-${c.id}`}>
                  {smart ? <SmartIcon className="h-3 w-3" /> : <Layers className="h-3 w-3 text-muted-foreground" />}
                  <span className="truncate flex-1">{c.title}</span>
                  {c.visibility === "team" ? <Users className="h-3 w-3 text-muted-foreground" /> : <User className="h-3 w-3 text-muted-foreground" />}
                </button>
              );
            })}
        </div>
        {total > PICK_LIMIT && (
          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
            <span className="tabular-nums">{page} / {pages} · {total}</span>
            <div className="flex gap-1">
              <Button variant="ghost" size="sm" className="h-6 w-6 p-0" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous" data-testid="button-picker-prev"><ChevronLeft className="h-3 w-3" /></Button>
              <Button variant="ghost" size="sm" className="h-6 w-6 p-0" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next" data-testid="button-picker-next"><ChevronRight className="h-3 w-3" /></Button>
            </div>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}

/** Fetches one full collection on demand, then opens the existing editor. */
export function useOpenCollection() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Collection | null>(null);
  const open = async (id: string) => {
    setLoadingId(id);
    try {
      const c = await qc.fetchQuery({ queryKey: getGetEditorialCollectionQueryKey(id), queryFn: () => getEditorialCollection(id), staleTime: 0 });
      setEditing(c);
    } catch (e) {
      toast({ variant: "destructive", title: "Couldn't open collection", description: errorMessage(e, "Try again in a moment.") });
    } finally { setLoadingId(null); }
  };
  const dialog = (
    <CollectionDialog open={!!editing} onOpenChange={(o) => { if (!o) setEditing(null); }} collection={editing}
      defaultWorkspaceId={editing?.workspace_id ?? null} onSaved={() => setEditing(null)} />
  );
  return { open, loadingId, dialog };
}
