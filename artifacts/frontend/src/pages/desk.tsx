import { Link } from "wouter";
import type { DeskItem } from "@workspace/api-client-react";
import { useDeskList } from "@/hooks/use-desk";
import { Button } from "@/components/ui/button";
import { Star, History, Bookmark, Layers, Sparkles as SmartIcon, Film, AlertTriangle, User, Users, ArrowRight, X } from "lucide-react";
import { useEditorialActions, useEditorialState } from "@/hooks/use-editorial";
import { formatTime, withScope } from "@/lib/editorial";
import { SaveProjectButton } from "@/components/editorial/desk-buttons";

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

type TileAsset = Pick<DeskItem, "id" | "title" | "thumbnail_url" | "duration_seconds">;

function AssetTile({ asset, onUnfavorite }: { asset: TileAsset; onUnfavorite?: () => void }) {
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
        <p className="px-2 py-1.5 text-xs truncate" title={asset.title}>{asset.title}</p>
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

const collectionHref = (c: DeskItem) => `/library?${withScope("", c.workspace_id ?? null, c.id)}`;

export default function Desk() {
  const { data: state, isLoading, isError, refetch } = useEditorialState();
  const actions = useEditorialActions();
  // Recent views stay bounded; the server caps the list too.
  const recent = useDeskList("recent", { offset: 0, limit: 12 });
  const favorites = useDeskList("favorites", { sort: "recent", offset: 0, limit: 12 });
  const projects = useDeskList("projects", { sort: "recent", offset: 0, limit: 8 });
  const mine = useDeskList("collections", { visibility: "personal", sort: "recent", offset: 0, limit: 8 });
  const team = useDeskList("collections", { visibility: "team", sort: "recent", offset: 0, limit: 8,
    workspace_id: state?.me.workspace_id ?? undefined });
  const workspace = state?.workspaces.find((w) => w.id === state.me.workspace_id) ?? null;
  const favCount = favorites.data?.total;

  if (isError) {
    return (
      <div className="p-8"><Failed what="your desk" onRetry={() => refetch()} /></div>
    );
  }

  const seeAll = (href: string, n: number | undefined, id: string) => (
    <Link href={href} className="text-xs text-muted-foreground hover:text-primary inline-flex items-center gap-1" data-testid={`link-desk-all-${id}`}>
      View all{n != null ? ` ${n}` : ""} <ArrowRight className="h-3 w-3" />
    </Link>
  );

  const collectionRow = (c: DeskItem) => (
    <li key={c.id}>
      <Link href={collectionHref(c)} className="flex items-center gap-2.5 px-3 py-2 text-sm hover:bg-muted/40 rounded-md" data-testid={`link-desk-collection-${c.id}`}>
        {c.kind === "smart" ? <SmartIcon className="h-3.5 w-3.5 text-primary" /> : <Layers className="h-3.5 w-3.5 text-muted-foreground" />}
        <span className="truncate flex-1">{c.title}</span>
        {c.visibility === "personal" ? <User className="h-3 w-3 text-muted-foreground" /> : <Users className="h-3 w-3 text-muted-foreground" />}
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
          <Section icon={Star} title="Favorites" count={favCount} action={seeAll("/desk/favorites", favCount, "favorites")}>
            {favorites.isLoading ? <SkeletonGrid /> : favorites.isError ? <Failed what="favorites" onRetry={() => favorites.refetch()} /> :
              (favorites.data?.items.length ?? 0) === 0 ? <Empty>Star an asset from its page to keep it here.</Empty> : (
                <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(160px,1fr))]">
                  {favorites.data!.items.map((a) => <AssetTile key={a.id} asset={a} onUnfavorite={() => actions.toggleFavorite(a.id)} />)}
                </div>
              )}
          </Section>

          <Section icon={History} title="Recently viewed" count={recent.data?.items.length}>
            {recent.isLoading ? <SkeletonGrid /> : recent.isError ? <Failed what="recent media" onRetry={() => recent.refetch()} /> :
              (recent.data?.items.length ?? 0) === 0 ? <Empty>Assets you open will show up here.</Empty> : (
                <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(140px,1fr))]">
                  {recent.data!.items.map((a) => <AssetTile key={a.id} asset={a} />)}
                </div>
              )}
          </Section>
        </div>

        <aside className="space-y-8">
          <Section icon={Bookmark} title="Saved projects" count={projects.data?.total} action={seeAll("/desk/projects", projects.data?.total, "projects")}>
            {projects.isLoading ? <div className="h-24 rounded-md bg-muted/40 animate-pulse" /> :
              projects.isError ? <Failed what="projects" onRetry={() => projects.refetch()} /> :
              (projects.data?.items.length ?? 0) === 0 ? <Empty>Bookmark a Studio project to pin it here. Saving doesn't change who owns it.</Empty> : (
                <ul className="space-y-0.5">
                  {projects.data!.items.map((p) => (
                    <li key={p.id} className="flex items-center gap-1">
                      <Link href={`/studio/${p.id}`} className="flex-1 min-w-0 px-3 py-2 text-sm rounded-md hover:bg-muted/40 truncate" data-testid={`link-desk-project-${p.id}`}>{p.title}</Link>
                      <SaveProjectButton projectId={p.id} compact />
                    </li>
                  ))}
                </ul>
              )}
          </Section>

          <Section icon={Layers} title="My collections" count={mine.data?.total} action={seeAll("/desk/collections?visibility=personal", mine.data?.total, "collections")}>
            {mine.isLoading ? <div className="h-24 rounded-md bg-muted/40 animate-pulse" /> :
              mine.isError ? <Failed what="collections" onRetry={() => mine.refetch()} /> :
              (mine.data?.items.length ?? 0) === 0 ? <Empty>Create one from the library's Collections menu.</Empty> :
              <ul className="space-y-0.5">{mine.data!.items.map(collectionRow)}</ul>}
          </Section>

          {team.isError ? <Failed what="team collections" onRetry={() => team.refetch()} /> : (team.data?.items.length ?? 0) > 0 && (
            <Section icon={Users} title={workspace ? `${workspace.name} collections` : "Team collections"} count={team.data?.total}
              action={seeAll(`/desk/collections?visibility=team${workspace ? `&workspace_id=${workspace.id}` : ""}`, team.data?.total, "team-collections")}>
              <ul className="space-y-0.5">{team.data!.items.map(collectionRow)}</ul>
            </Section>
          )}
        </aside>
      </div>
    </div>
  );
}
