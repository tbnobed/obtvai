import { useEffect, useRef, useState } from "react";
import { Link } from "wouter";
import type { DeskItem } from "@workspace/api-client-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Star, Bookmark, Layers, Sparkles as SmartIcon, Film, AlertTriangle, User, Users, ArrowLeft,
  ChevronLeft, ChevronRight, LayoutGrid, List, Search, Pencil, FolderPlus, X, Loader2,
} from "lucide-react";
import { useEditorialState } from "@/hooks/use-editorial";
import { useDeskList, useUrlFilters, useDeskBulk, type DeskSection, type DeskParams } from "@/hooks/use-desk";
import { formatTime, withScope } from "@/lib/editorial";
import { recoverPage } from "@/lib/desk-url";
import { CollectionPicker, useOpenCollection } from "@/components/editorial/desk-collection-tools";
import { SaveProjectButton } from "@/components/editorial/desk-buttons";

const ALL = "__all";
const FAV_PAGE = 50;
const LIST_PAGE = 25;

/* ---------- shared bits ---------- */

function Shell({ icon: Icon, title, total, children }: {
  icon: React.ComponentType<{ className?: string }>; title: string; total?: number; children: React.ReactNode;
}) {
  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8 lg:py-8 max-w-7xl mx-auto space-y-5" data-testid={`page-desk-${title.toLowerCase().replace(/\s+/g, "-")}`}>
      <Link href="/desk" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground" data-testid="link-back-desk">
        <ArrowLeft className="h-3 w-3" /> My Desk
      </Link>
      <h1 className="text-2xl lg:text-3xl font-bold tracking-tight flex items-center gap-2.5">
        <Icon className="h-6 w-6 text-primary" /> {title}
        {total != null && <span className="text-sm text-muted-foreground font-normal tabular-nums" data-testid="text-desk-total">{total}</span>}
      </h1>
      {children}
    </div>
  );
}

function SearchBox({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  const [local, setLocal] = useState(value);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const cb = useRef(onChange);
  cb.current = onChange;
  useEffect(() => { setLocal(value); }, [value]);
  useEffect(() => () => clearTimeout(timer.current), []);
  return (
    <div className="relative flex-1 min-w-[180px] max-w-sm">
      <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
      <Input value={local} placeholder={placeholder} className="h-8 pl-8 text-xs" data-testid="input-desk-search"
        onChange={(e) => {
          const v = e.target.value;
          setLocal(v);
          clearTimeout(timer.current);
          timer.current = setTimeout(() => cb.current(v.trim()), 300);
        }} />
    </div>
  );
}

function Pick({ value, onChange, options, label, testId, width = "w-40" }: {
  value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; label: string; testId: string; width?: string;
}) {
  return (
    <Select value={value || ALL} onValueChange={(v) => onChange(v === ALL ? "" : v)}>
      <SelectTrigger className={`h-8 text-xs ${width}`} aria-label={label} data-testid={testId}><SelectValue /></SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{label}</SelectItem>
        {options.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

function Failed({ what, onRetry }: { what: string; onRetry: () => void }) {
  return (
    <div className="flex items-center gap-2 text-xs rounded-md border border-destructive/40 bg-destructive/10 px-3 py-3" data-testid="status-desk-error">
      <AlertTriangle className="h-3.5 w-3.5 text-destructive" /> Couldn't load {what}.
      <button className="underline underline-offset-2" onClick={onRetry} data-testid="button-desk-retry">Retry</button>
    </div>
  );
}

function Empty({ filtered, none, onClear }: { filtered: boolean; none: string; onClear: () => void }) {
  return (
    <div className="rounded-md border border-dashed border-border px-4 py-10 text-center space-y-2" data-testid="status-desk-empty">
      <p className="text-sm">{filtered ? "Nothing matches these filters." : none}</p>
      {filtered && <Button variant="outline" size="sm" className="h-7 text-xs" onClick={onClear} data-testid="button-clear-filters">Clear filters</Button>}
    </div>
  );
}

function Pager({ page, total, limit, onPage }: { page: number; total: number; limit: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / limit));
  if (total <= limit) return null;
  const from = (page - 1) * limit + 1;
  const to = Math.min(total, page * limit);
  return (
    <div className="flex items-center justify-between gap-2 text-xs pt-2">
      <span className="text-muted-foreground tabular-nums" data-testid="text-desk-range">{from}–{to} of {total}</span>
      <div className="flex items-center gap-1">
        <Button variant="outline" size="sm" className="h-7 w-7 p-0" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page" data-testid="button-page-prev">
          <ChevronLeft className="h-3.5 w-3.5" />
        </Button>
        <span className="tabular-nums px-2" data-testid="text-desk-page">{page} / {pages}</span>
        <Button variant="outline" size="sm" className="h-7 w-7 p-0" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page" data-testid="button-page-next">
          <ChevronRight className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}

/** Paged list driven by URL; jumps back to the last valid page when removals empty the current one. */
function usePagedDesk(section: DeskSection, params: Omit<DeskParams, "offset" | "limit">, page: number, limit: number, setPage: (p: number) => void) {
  const q = useDeskList(section, { ...params, offset: (page - 1) * limit, limit });
  const settled = !!q.data && !q.isPlaceholderData;
  const target = settled ? recoverPage(page, q.data!.items.length, q.data!.total, limit) : null;
  const setPageRef = useRef(setPage);
  setPageRef.current = setPage;
  useEffect(() => { if (target != null) setPageRef.current(target); }, [target]);
  return q;
}

function ListSkeleton({ rows = 8 }: { rows?: number }) {
  return <div className="space-y-1.5" data-testid="status-desk-loading">{Array.from({ length: rows }).map((_, i) => <div key={i} className="h-10 rounded-md bg-muted/40 animate-pulse" />)}</div>;
}

const year = (d?: string | null) => (d ? d.slice(0, 4) : null);

/* ---------- Favorites ---------- */

const FAV_KEYS = ["q", "workspace_id", "topic", "air_year", "sort", "view"] as const;

export function DeskFavorites() {
  const { values: f, page, update, setPage } = useUrlFilters(FAV_KEYS);
  const { data: state } = useEditorialState();
  const bulk = useDeskBulk();
  const view = f.view === "list" ? "list" : "grid";
  const sort = (f.sort || "recent") as DeskParams["sort"];
  const params = {
    q: f.q || undefined, workspace_id: f.workspace_id || undefined, topic: f.topic || undefined,
    air_year: f.air_year ? Number(f.air_year) : undefined, sort,
  } as Omit<DeskParams, "offset" | "limit">;
  const q = usePagedDesk("favorites", params, page, FAV_PAGE, setPage);
  const items = q.data?.items ?? [];
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [target, setTarget] = useState<{ id: string; title: string } | null>(null);
  const filtered = !!(f.q || f.workspace_id || f.topic || f.air_year);
  const pageIds = items.map((i) => i.id);
  const allOnPage = pageIds.length > 0 && pageIds.every((id) => selected.has(id));
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const thisYear = new Date().getFullYear();
  const years = Array.from({ length: 40 }, (_, i) => String(thisYear - i));

  const removeSelected = async () => {
    if (await bulk.setFavorites([...selected], "remove")) setSelected(new Set());
  };
  const addSelected = async () => {
    if (target && await bulk.addToCollection(target.id, target.title, [...selected])) setSelected(new Set());
  };

  return (
    <Shell icon={Star} title="Favorites" total={q.data?.total}>
      <div className="flex flex-wrap items-center gap-2">
        <SearchBox value={f.q} onChange={(v) => update({ q: v })} placeholder="Search favorites" />
        <Pick value={f.workspace_id} onChange={(v) => update({ workspace_id: v })} label="All shows" testId="select-fav-workspace"
          options={(state?.workspaces ?? []).map((w) => ({ value: w.id, label: w.name }))} />
        <TopicBox value={f.topic} onChange={(v) => update({ topic: v })} />
        <Pick value={f.air_year} onChange={(v) => update({ air_year: v })} label="Any air year" testId="select-fav-year" width="w-32"
          options={years.map((y) => ({ value: y, label: y }))} />
        <Select value={sort} onValueChange={(v) => update({ sort: v === "recent" ? "" : v })}>
          <SelectTrigger className="h-8 text-xs w-44" aria-label="Sort" data-testid="select-fav-sort"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="recent">Recently favorited</SelectItem>
            <SelectItem value="title">Title</SelectItem>
            <SelectItem value="air_date">Original air date</SelectItem>
          </SelectContent>
        </Select>
        <div className="ml-auto flex rounded-md border border-border">
          <button className={`h-8 w-8 flex items-center justify-center ${view === "grid" ? "bg-muted text-foreground" : "text-muted-foreground"}`}
            onClick={() => update({ view: "", page: String(page) })} aria-label="Grid view" data-testid="button-view-grid"><LayoutGrid className="h-3.5 w-3.5" /></button>
          <button className={`h-8 w-8 flex items-center justify-center ${view === "list" ? "bg-muted text-foreground" : "text-muted-foreground"}`}
            onClick={() => update({ view: "list", page: String(page) })} aria-label="List view" data-testid="button-view-list"><List className="h-3.5 w-3.5" /></button>
        </div>
      </div>

      {items.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-xs sticky top-0 z-10">
          <Checkbox checked={allOnPage} onCheckedChange={() => setSelected((s) => {
            const n = new Set(s);
            if (allOnPage) pageIds.forEach((id) => n.delete(id)); else pageIds.forEach((id) => n.add(id));
            return n;
          })} aria-label="Select page" data-testid="checkbox-select-page" />
          <span className="tabular-nums" data-testid="text-selected-count">{selected.size ? `${selected.size} selected` : "Select page"}</span>
          {selected.size > 0 && (
            <>
              <button className="text-muted-foreground hover:text-foreground" onClick={() => setSelected(new Set())} aria-label="Clear selection" data-testid="button-clear-selection"><X className="h-3 w-3" /></button>
              <div className="ml-auto flex flex-wrap items-center gap-2">
                <CollectionPicker value={target} onChange={setTarget} />
                <Button size="sm" variant="outline" className="h-7 text-xs gap-1" disabled={!target || bulk.pending} onClick={addSelected} data-testid="button-bulk-add-collection">
                  <FolderPlus className="h-3.5 w-3.5" /> Add to collection
                </Button>
                <Button size="sm" variant="outline" className="h-7 text-xs gap-1 text-destructive" disabled={bulk.pending} onClick={removeSelected} data-testid="button-bulk-unfavorite">
                  <Star className="h-3.5 w-3.5" /> Remove favorites
                </Button>
              </div>
            </>
          )}
        </div>
      )}

      {q.isLoading ? (view === "grid"
        ? <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(170px,1fr))]" data-testid="status-desk-loading">{Array.from({ length: 12 }).map((_, i) => <div key={i} className="aspect-video rounded-md bg-muted/40 animate-pulse" />)}</div>
        : <ListSkeleton />)
        : q.isError ? <Failed what="favorites" onRetry={() => q.refetch()} />
        : items.length === 0 ? <Empty filtered={filtered} none="Star an asset from its page to keep it here." onClear={() => update({ q: "", workspace_id: "", topic: "", air_year: "" })} />
        : (
          <div className={q.isPlaceholderData ? "opacity-60 transition-opacity" : "transition-opacity"}>
            {view === "grid" ? (
              <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(170px,1fr))]">
                {items.map((a) => <FavTile key={a.id} a={a} checked={selected.has(a.id)} onCheck={() => toggle(a.id)} />)}
              </div>
            ) : (
              <ul className="divide-y divide-border rounded-md border border-border">
                {items.map((a) => (
                  <li key={a.id} className="flex items-center gap-3 px-3 py-2 text-sm" data-testid={`row-fav-${a.id}`}>
                    <Checkbox checked={selected.has(a.id)} onCheckedChange={() => toggle(a.id)} aria-label={`Select ${a.title}`} data-testid={`checkbox-fav-${a.id}`} />
                    <Link href={`/library/${a.id}`} className="flex-1 min-w-0 truncate hover:text-primary" data-testid={`link-desk-asset-${a.id}`}>{a.title}</Link>
                    <span className="text-[11px] text-muted-foreground tabular-nums w-24 text-right">{a.air_date ? a.air_date.slice(0, 10) : "—"}</span>
                    <span className="text-[11px] font-mono text-muted-foreground w-16 text-right">{a.duration_seconds != null ? formatTime(a.duration_seconds) : ""}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      {q.data && <Pager page={page} total={q.data.total} limit={FAV_PAGE} onPage={setPage} />}
    </Shell>
  );
}

function TopicBox({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [local, setLocal] = useState(value);
  useEffect(() => { setLocal(value); }, [value]);
  return (
    <Input value={local} placeholder="Topic" className="h-8 text-xs w-32" data-testid="input-fav-topic"
      onChange={(e) => setLocal(e.target.value)}
      onBlur={() => local.trim() !== value && onChange(local.trim())}
      onKeyDown={(e) => { if (e.key === "Enter") onChange(local.trim()); }} />
  );
}

function FavTile({ a, checked, onCheck }: { a: DeskItem; checked: boolean; onCheck: () => void }) {
  return (
    <div className={`group relative rounded-md ${checked ? "ring-2 ring-primary" : ""}`} data-testid={`card-fav-${a.id}`}>
      <Link href={`/library/${a.id}`} className="block rounded-md overflow-hidden border border-border bg-card hover:border-primary/50 transition-colors" data-testid={`link-desk-asset-${a.id}`}>
        <div className="aspect-video bg-muted relative">
          {a.thumbnail_url
            ? <img src={`/api/thumbnails/${a.thumbnail_url}`} alt="" className="w-full h-full object-cover" loading="lazy" />
            : <div className="absolute inset-0 flex items-center justify-center"><Film className="h-6 w-6 text-muted-foreground/50" /></div>}
          {a.duration_seconds != null && <span className="absolute bottom-1 right-1 text-[10px] font-mono px-1 rounded bg-black/70 text-white">{formatTime(a.duration_seconds)}</span>}
        </div>
        <div className="px-2 py-1.5">
          <p className="text-xs truncate" title={a.title}>{a.title}</p>
          {year(a.air_date) && <p className="text-[10px] text-muted-foreground tabular-nums">Aired {year(a.air_date)}</p>}
        </div>
      </Link>
      <div className={`absolute top-1 left-1 rounded bg-black/60 p-1 ${checked ? "opacity-100" : "opacity-0 group-hover:opacity-100 focus-within:opacity-100"} transition-opacity`}>
        <Checkbox checked={checked} onCheckedChange={onCheck} aria-label={`Select ${a.title}`} data-testid={`checkbox-fav-${a.id}`} />
      </div>
    </div>
  );
}

/* ---------- Saved projects ---------- */

const PROJ_KEYS = ["q", "sort"] as const;

export function DeskProjects() {
  const { values: f, page, update, setPage } = useUrlFilters(PROJ_KEYS);
  const sort = (f.sort || "recent") as DeskParams["sort"];
  const q = usePagedDesk("projects", { q: f.q || undefined, sort }, page, LIST_PAGE, setPage);
  const items = q.data?.items ?? [];
  return (
    <Shell icon={Bookmark} title="Saved projects" total={q.data?.total}>
      <div className="flex flex-wrap items-center gap-2">
        <SearchBox value={f.q} onChange={(v) => update({ q: v })} placeholder="Search saved projects" />
        <Select value={sort} onValueChange={(v) => update({ sort: v === "recent" ? "" : v })}>
          <SelectTrigger className="h-8 text-xs w-40" aria-label="Sort" data-testid="select-project-sort"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="recent">Recently saved</SelectItem>
            <SelectItem value="title">Name</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {q.isLoading ? <ListSkeleton /> : q.isError ? <Failed what="saved projects" onRetry={() => q.refetch()} />
        : items.length === 0 ? <Empty filtered={!!f.q} none="Bookmark a Studio project to pin it here. Saving doesn't change who owns it." onClear={() => update({ q: "" })} />
        : (
          <ul className={`divide-y divide-border rounded-md border border-border ${q.isPlaceholderData ? "opacity-60" : ""}`}>
            {items.map((p) => (
              <li key={p.id} className="flex items-center gap-2 px-2 py-1" data-testid={`row-desk-project-${p.id}`}>
                <Link href={`/studio/${p.id}`} className="flex-1 min-w-0 px-2 py-1.5 text-sm rounded-md hover:bg-muted/40 truncate" data-testid={`link-desk-project-${p.id}`}>{p.title}</Link>
                <SaveProjectButton projectId={p.id} compact />
              </li>
            ))}
          </ul>
        )}
      {q.data && <Pager page={page} total={q.data.total} limit={LIST_PAGE} onPage={setPage} />}
    </Shell>
  );
}

/* ---------- Collections ---------- */

const COL_KEYS = ["q", "sort", "workspace_id", "visibility"] as const;

export function DeskCollections() {
  const { values: f, page, update, setPage } = useUrlFilters(COL_KEYS);
  const { data: state } = useEditorialState();
  const opener = useOpenCollection();
  const sort = (f.sort || "recent") as DeskParams["sort"];
  const visibility = (f.visibility || "all") as DeskParams["visibility"];
  const q = usePagedDesk("collections", { q: f.q || undefined, sort, workspace_id: f.workspace_id || undefined, visibility }, page, LIST_PAGE, setPage);
  const items = q.data?.items ?? [];
  const wsName = (id?: string | null) => state?.workspaces.find((w) => w.id === id)?.name;
  return (
    <Shell icon={Layers} title="My collections" total={q.data?.total}>
      <div className="flex flex-wrap items-center gap-2">
        <SearchBox value={f.q} onChange={(v) => update({ q: v })} placeholder="Search collections" />
        <Pick value={f.workspace_id} onChange={(v) => update({ workspace_id: v })} label="All workspaces" testId="select-col-workspace"
          options={(state?.workspaces ?? []).map((w) => ({ value: w.id, label: w.name }))} />
        <Select value={visibility} onValueChange={(v) => update({ visibility: v === "all" ? "" : v })}>
          <SelectTrigger className="h-8 text-xs w-36" aria-label="Visibility" data-testid="select-col-visibility"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Mine and team</SelectItem>
            <SelectItem value="personal">Personal</SelectItem>
            <SelectItem value="team">Team</SelectItem>
          </SelectContent>
        </Select>
        <Select value={sort} onValueChange={(v) => update({ sort: v === "recent" ? "" : v })}>
          <SelectTrigger className="h-8 text-xs w-36" aria-label="Sort" data-testid="select-col-sort"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="recent">Recently updated</SelectItem>
            <SelectItem value="title">Name</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {q.isLoading ? <ListSkeleton /> : q.isError ? <Failed what="collections" onRetry={() => q.refetch()} />
        : items.length === 0 ? <Empty filtered={!!(f.q || f.workspace_id || f.visibility)} none="Create one from the library's Collections menu." onClear={() => update({ q: "", workspace_id: "", visibility: "" })} />
        : (
          <ul className={`divide-y divide-border rounded-md border border-border ${q.isPlaceholderData ? "opacity-60" : ""}`}>
            {items.map((c) => {
              const loading = opener.loadingId === c.id;
              return (
                <li key={c.id} className="flex items-center gap-2 px-2 py-1" data-testid={`row-desk-collection-${c.id}`}>
                  <Link href={`/library?${withScope("", c.workspace_id ?? null, c.id)}`} className="flex flex-1 min-w-0 items-center gap-2.5 px-2 py-1.5 text-sm rounded-md hover:bg-muted/40" data-testid={`link-desk-collection-${c.id}`}>
                    {c.kind === "smart" ? <SmartIcon className="h-3.5 w-3.5 text-primary" /> : <Layers className="h-3.5 w-3.5 text-muted-foreground" />}
                    <span className="truncate flex-1">{c.title}</span>
                    {wsName(c.workspace_id) && <span className="text-[11px] text-muted-foreground truncate max-w-[10rem]">{wsName(c.workspace_id)}</span>}
                    {c.visibility === "team" ? <Users className="h-3 w-3 text-muted-foreground" aria-label="Team" /> : <User className="h-3 w-3 text-muted-foreground" aria-label="Personal" />}
                  </Link>
                  <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-muted-foreground" disabled={!!opener.loadingId}
                    title={loading ? "Loading collection" : "Edit collection"} aria-label="Edit collection"
                    onClick={() => opener.open(c.id)} data-testid={`button-edit-collection-${c.id}`}>
                    {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Pencil className="h-3.5 w-3.5" />}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      {q.data && <Pager page={page} total={q.data.total} limit={LIST_PAGE} onPage={setPage} />}
      {opener.dialog}
    </Shell>
  );
}
