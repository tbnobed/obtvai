import { Link } from "wouter";
import { listMedia, getListMediaQueryKey, useListProjects } from "@workspace/api-client-react";
import { useQueries } from "@tanstack/react-query";
import type { MediaAsset, Collection } from "@workspace/api-client-react";
import { Button } from "@/components/ui/button";
import { Star, History, Bookmark, Layers, Sparkles as SmartIcon, Film, AlertTriangle, User, Users, ArrowRight, X } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useEditorialActions, useEditorialState } from "@/hooks/use-editorial";
import { formatTime, withScope } from "@/lib/editorial";
import { SaveProjectButton } from "@/components/editorial/desk-buttons";

/** Resolves an ordered id list into assets. Never queries with blank ids (that would list everything). */
function useAssetsById(ids: string[]) {
  // Batch below the API's 200-row maximum and proxy URL length limits.
  const batches = Array.from({ length: Math.ceil(ids.length / 75) }, (_, i) => ({
    ids: ids.slice(i * 75, (i + 1) * 75).join(","), limit: 75,
  }));
  const queries = useQueries({ queries: batches.map(params => ({
    queryKey: getListMediaQueryKey(params), queryFn: () => listMedia(params), staleTime: 30_000,
  })) });
  const byId = new Map(queries.flatMap(q => q.data?.items ?? []).map((m) => [m.id, m]));
  const assets = ids.map((id) => byId.get(id)).filter(Boolean) as MediaAsset[];
  return { assets, isLoading: queries.some(q => q.isLoading), isError: queries.some(q => q.isError),
    refetch: () => Promise.all(queries.map(q => q.refetch())),
    missing: queries.every(q => q.isSuccess) ? ids.length - assets.length : 0 };
}

function Section({ icon: Icon, title, count, children, action }: {
  icon: React.ComponentType<{ className?: string }>; title: string; count?: number; children: React.ReactNode; action?: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-2 border-b border-border pb-2">
        <h2 className="text-sm font-semibold flex items-center gap-2">
          <Icon className="h-4 w-4 text-primary" /> {title}
          {count != null && <span className="text-xs text-muted-foreground font-normal tabular-nums">{count}</span>}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-xs text-muted-foreground rounded-md border border-dashed border-border px-4 py-6 text-center">{children}</p>;
}

function Failed({ what, onRetry }: { what: string; onRetry: () => void }) {
  return (
    <div className="flex items-center gap-2 text-xs rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2">
      <AlertTriangle className="h-3.5 w-3.5 text-destructive" /> Couldn't load {what}.
      <button className="underline underline-offset-2" onClick={onRetry}>Retry</button>
    </div>
  );
}

function AssetTile({ asset, onUnfavorite }: { asset: MediaAsset; onUnfavorite?: () => void }) {
  return (
    <div className="group relative">
      <Link href={`/library/${asset.id}`} className="block rounded-md overflow-hidden border border-border bg-card hover:border-primary/50 transition-colors" data-testid={`link-desk-asset-${asset.id}`}>
        <div className="aspect-video bg-muted relative">
          {asset.thumbnail_url
            ? <img src={`/api/thumbnails/${asset.thumbnail_url}`} alt="" className="w-full h-full object-cover" loading="lazy" />
            : <div className="absolute inset-0 flex items-center justify-center"><Film className="h-6 w-6 text-muted-foreground/50" /></div>}
          {asset.duration_seconds != null && (
            <span className="absolute bottom-1 right-1 text-[10px] font-mono px-1 rounded bg-black/70 text-white">{formatTime(asset.duration_seconds)}</span>
          )}
        </div>
        <p className="px-2 py-1.5 text-xs truncate" title={asset.filename}>{asset.filename}</p>
      </Link>
      {onUnfavorite && (
        <button onClick={onUnfavorite} aria-label="Remove from favorites" title="Remove from favorites"
          className="absolute top-1 right-1 h-6 w-6 rounded bg-black/60 text-amber-300 flex items-center justify-center opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
          data-testid={`button-unfavorite-${asset.id}`}>
          <Star className="h-3.5 w-3.5 fill-current" />
        </button>
      )}
    </div>
  );
}

function SkeletonGrid() {
  return (
    <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(160px,1fr))]">
      {Array.from({ length: 6 }).map((_, i) => <div key={i} className="aspect-video rounded-md bg-muted/40 animate-pulse" />)}
    </div>
  );
}

const collectionHref = (c: Collection) => `/library?${withScope("", c.workspace_id ?? null, c.id)}`;

export default function Desk() {
  const { user } = useAuth();
  const { data: state, isLoading, isError, refetch } = useEditorialState();
  const actions = useEditorialActions();
  const favIds = state?.me.favorite_media_ids ?? [];
  const recentIds = (state?.me.recent_media_ids ?? []).slice(0, 24);
  const favorites = useAssetsById(favIds);
  const recent = useAssetsById(recentIds);
  const projects = useListProjects();
  const savedIds = state?.me.saved_project_ids ?? [];
  const savedProjects = (projects.data ?? []).filter((p) => savedIds.includes(p.id));
  const workspace = state?.workspaces.find((w) => w.id === state.me.workspace_id) ?? null;
  const myCollections = (state?.collections ?? []).filter((c) => c.visibility === "personal" || c.created_by === user?.id);
  const teamCollections = (state?.collections ?? []).filter((c) => c.visibility === "team" && c.created_by !== user?.id &&
    (!workspace || c.workspace_id === workspace.id || c.workspace_id == null));

  if (isError) {
    return (
      <div className="p-8"><Failed what="your desk" onRetry={() => refetch()} /></div>
    );
  }

  const collectionRow = (c: Collection) => (
    <li key={c.id}>
      <Link href={collectionHref(c)} className="flex items-center gap-2.5 px-3 py-2 text-sm hover:bg-muted/40 rounded-md" data-testid={`link-desk-collection-${c.id}`}>
        {c.kind === "smart" ? <SmartIcon className="h-3.5 w-3.5 text-primary" /> : <Layers className="h-3.5 w-3.5 text-muted-foreground" />}
        <span className="truncate flex-1">{c.name}</span>
        {c.visibility === "personal" ? <User className="h-3 w-3 text-muted-foreground" /> : <Users className="h-3 w-3 text-muted-foreground" />}
        <span className="text-[11px] text-muted-foreground tabular-nums w-14 text-right">{c.kind === "manual" ? `${c.items.length} items` : "smart"}</span>
      </Link>
    </li>
  );

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8 lg:py-8 max-w-7xl mx-auto space-y-8" data-testid="page-desk">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl lg:text-3xl font-bold tracking-tight">My Desk</h1>
          <p className="text-xs text-muted-foreground mt-1">Your favorites, recent views, saved projects and collections. Only you see this page.</p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">Default workspace</span>
          {isLoading ? <span className="h-7 w-24 rounded bg-muted/40 animate-pulse" /> : workspace ? (
            <span className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md border border-primary/40 bg-primary/10" data-testid="text-desk-workspace">
              <Users className="h-3.5 w-3.5 text-primary" /> {workspace.name}
              <button aria-label="Clear default workspace" className="text-muted-foreground hover:text-foreground" onClick={() => actions.rememberWorkspace(null)} data-testid="button-clear-default-workspace">
                <X className="h-3 w-3" />
              </button>
            </span>
          ) : <span className="h-7 px-2.5 inline-flex items-center rounded-md border border-border">All Library</span>}
          <Button asChild variant="outline" size="sm" className="h-7 text-xs gap-1">
            <Link href="/library" data-testid="link-desk-library">Library <ArrowRight className="h-3 w-3" /></Link>
          </Button>
        </div>
      </header>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-8 min-w-0">
          <Section icon={Star} title="Favorites" count={favIds.length}>
            {isLoading || favorites.isLoading ? <SkeletonGrid /> : favorites.isError ? <Failed what="favorites" onRetry={() => favorites.refetch()} /> :
              favIds.length === 0 ? <Empty>Star an asset from its page to keep it here.</Empty> : (
                <>
                  <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(160px,1fr))]">
                    {favorites.assets.map((a) => <AssetTile key={a.id} asset={a} onUnfavorite={() => actions.toggleFavorite(a.id)} />)}
                  </div>
                  {favorites.missing > 0 && <p className="text-[11px] text-muted-foreground">{favorites.missing} favorited asset{favorites.missing === 1 ? " is" : "s are"} no longer in the library.</p>}
                </>
              )}
          </Section>

          <Section icon={History} title="Recently viewed" count={recentIds.length}>
            {isLoading || recent.isLoading ? <SkeletonGrid /> : recent.isError ? <Failed what="recent media" onRetry={() => recent.refetch()} /> :
              recentIds.length === 0 ? <Empty>Assets you open will show up here.</Empty> : (
                <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(140px,1fr))]">
                  {recent.assets.map((a) => <AssetTile key={a.id} asset={a} />)}
                </div>
              )}
          </Section>
        </div>

        <aside className="space-y-8">
          <Section icon={Bookmark} title="Saved projects" count={savedIds.length}>
            {projects.isLoading || isLoading ? <div className="h-24 rounded-md bg-muted/40 animate-pulse" /> :
              projects.isError ? <Failed what="projects" onRetry={() => projects.refetch()} /> :
              savedProjects.length === 0 ? <Empty>Bookmark a Studio project to pin it here. Saving doesn't change who owns it.</Empty> : (
                <ul className="space-y-0.5">
                  {savedProjects.map((p) => (
                    <li key={p.id} className="flex items-center gap-1">
                      <Link href={`/studio/${p.id}`} className="flex-1 min-w-0 px-3 py-2 text-sm rounded-md hover:bg-muted/40 truncate" data-testid={`link-desk-project-${p.id}`}>{p.name}</Link>
                      <SaveProjectButton projectId={p.id} compact />
                    </li>
                  ))}
                </ul>
              )}
          </Section>

          <Section icon={Layers} title="My collections" count={myCollections.length}>
            {isLoading ? <div className="h-24 rounded-md bg-muted/40 animate-pulse" /> :
              myCollections.length === 0 ? <Empty>Create one from the library's Collections menu.</Empty> :
              <ul className="space-y-0.5">{myCollections.map(collectionRow)}</ul>}
          </Section>

          {teamCollections.length > 0 && (
            <Section icon={Users} title={workspace ? `${workspace.name} collections` : "Team collections"} count={teamCollections.length}>
              <ul className="space-y-0.5">{teamCollections.map(collectionRow)}</ul>
            </Section>
          )}
        </aside>
      </div>
    </div>
  );
}
