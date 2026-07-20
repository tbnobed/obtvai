import { useState } from "react";
import {
  useGetLibraryStats,
  getGetLibraryStatsQueryKey,
  useGetLibraryInsights,
  getGetLibraryInsightsQueryKey,
  useListProjects,
  getListProjectsQueryKey,
  useGetJobStats,
  getGetJobStatsQueryKey,
} from "@workspace/api-client-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Link, useLocation } from "wouter";
import {
  Film,
  Clock,
  HardDrive,
  Activity,
  Search,
  Lightbulb,
  MapPinned,
  Sparkles,
  ArrowRight,
  FolderKanban,
  Scissors,
  BookOpen,
  Clapperboard,
  AlertTriangle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatHours } from "@/lib/format";

const EVENT_LABELS: Record<string, string> = {
  ready: "Indexed",
  processing: "Processing",
  pending: "Added",
  error: "Error",
};

export default function Dashboard() {
  const { data: stats, isLoading } = useGetLibraryStats({ query: { queryKey: getGetLibraryStatsQueryKey() } });
  const { data: insights } = useGetLibraryInsights({ query: { queryKey: getGetLibraryInsightsQueryKey() } });
  const { data: projects } = useListProjects({ query: { queryKey: getListProjectsQueryKey() } });
  const { data: jobStats } = useGetJobStats({ query: { queryKey: getGetJobStatsQueryKey(), refetchInterval: 15000 } });
  const [, navigate] = useLocation();
  const [quickQuery, setQuickQuery] = useState("");

  function formatBytes(bytes: number) {
    const gb = bytes / (1024 * 1024 * 1024);
    return `${gb.toFixed(2)} GB`;
  }

  const submitQuickSearch = () => {
    const q = quickQuery.trim();
    if (q.length < 2) return;
    navigate(`/search?q=${encodeURIComponent(q)}`);
  };

  const errorCount = stats?.status_counts.error || 0;

  const activeProjects = (projects ?? [])
    .slice()
    .sort((a, b) =>
      (b.updated_at ?? b.created_at).localeCompare(a.updated_at ?? a.created_at),
    )
    .slice(0, 4);

  const teasers =
    insights?.generated_at
      ? [
          insights.opportunities.length > 0 && {
            icon: Lightbulb,
            text: `${insights.opportunities.length} story ${insights.opportunities.length === 1 ? "opportunity" : "opportunities"} found`,
            sub: insights.opportunities[0].title,
          },
          insights.coverage_gaps.length > 0 && {
            icon: MapPinned,
            text: `${insights.coverage_gaps.length} coverage ${insights.coverage_gaps.length === 1 ? "gap" : "gaps"} identified`,
            sub: insights.coverage_gaps.map((g) => g.label).slice(0, 3).join(" · "),
          },
          insights.top_topics.length > 0 && {
            icon: Sparkles,
            text: `Dominant theme: ${insights.top_topics[0].topic}`,
            sub: `${insights.top_topics[0].asset_count} assets touch this topic`,
          },
        ].filter((t): t is { icon: typeof Lightbulb; text: string; sub: string } => Boolean(t))
      : [];

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold tracking-tight">Overview</h1>
        <Button asChild variant="outline">
          <Link href="/projects" className="gap-2">
            <FolderKanban className="h-4 w-4" />
            Projects
          </Link>
        </Button>
      </div>

      <div className="flex gap-2 mb-8 max-w-2xl">
        <Input
          value={quickQuery}
          onChange={(e) => setQuickQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submitQuickSearch()}
          placeholder="Search the whole library — people, quotes, scenes…"
          className="h-10"
        />
        <Button className="h-10" onClick={submitQuickSearch} disabled={quickQuery.trim().length < 2}>
          <Search className="h-4 w-4" />
        </Button>
      </div>

      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <Card key={i} className="animate-pulse bg-muted h-32" />
          ))}
        </div>
      ) : stats ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Link href="/library">
            <Card className="hover:border-primary transition-colors cursor-pointer h-full">
              <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
                <CardTitle className="text-sm font-medium">Total Assets</CardTitle>
                <Film className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{stats.total_assets}</div>
                <p className="text-xs text-muted-foreground mt-1">Indexed media files</p>
              </CardContent>
            </Card>
          </Link>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
              <CardTitle className="text-sm font-medium">Total Duration</CardTitle>
              <Clock className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{formatHours(stats.total_duration_seconds)}</div>
              <p className="text-xs text-muted-foreground mt-1">
                Searchable: {formatHours(stats.speech_indexed_seconds)} of {formatHours(stats.total_duration_seconds)}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
              <CardTitle className="text-sm font-medium">Storage Used</CardTitle>
              <HardDrive className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{formatBytes(stats.storage_bytes)}</div>
              <p className="text-xs text-muted-foreground mt-1">Across all qualities</p>
            </CardContent>
          </Card>
          <Link href="/jobs">
            <Card className={`hover:border-primary transition-colors cursor-pointer h-full ${errorCount > 0 ? "border-red-500/50" : ""}`}>
              <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
                <CardTitle className="text-sm font-medium">Pipeline</CardTitle>
                {errorCount > 0 ? (
                  <AlertTriangle className="h-4 w-4 text-red-400" />
                ) : (
                  <Activity className="h-4 w-4 text-muted-foreground" />
                )}
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{jobStats?.jobs_running ?? stats.status_counts.processing ?? 0}</div>
                <p className={`text-xs mt-1 ${errorCount > 0 ? "text-red-400" : "text-muted-foreground"}`}>
                  {errorCount > 0
                    ? `Jobs running · ${errorCount} failed asset${errorCount === 1 ? "" : "s"} need attention`
                    : `Jobs running · ${jobStats?.jobs_pending ?? stats.status_counts.pending ?? 0} queued`}
                </p>
              </CardContent>
            </Card>
          </Link>
        </div>
      ) : null}

      {activeProjects.length > 0 && (
        <div className="mt-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold tracking-tight">Active Projects</h2>
            <Link href="/projects" className="text-sm text-muted-foreground hover:text-foreground flex items-center gap-1">
              All projects <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {activeProjects.map((p) => (
              <Link key={p.id} href={`/projects/${p.id}`}>
                <Card className="hover:border-primary transition-colors cursor-pointer h-full">
                  <CardContent className="p-4">
                    <p className="text-sm font-medium truncate" title={p.name}>{p.name}</p>
                    {p.description && (
                      <p className="text-xs text-muted-foreground mt-1 truncate" title={p.description}>{p.description}</p>
                    )}
                    <div className="flex items-center gap-3 mt-3 text-xs text-muted-foreground">
                      <span className="flex items-center gap-1"><Scissors className="h-3 w-3" />{p.counts.clip_lists}</span>
                      <span className="flex items-center gap-1"><BookOpen className="h-3 w-3" />{p.counts.stories}</span>
                      <span className="flex items-center gap-1"><Clapperboard className="h-3 w-3" />{p.counts.renders}</span>
                    </div>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        </div>
      )}

      {teasers.length > 0 && (
        <div className="mt-8">
          <h2 className="text-xl font-semibold mb-4 tracking-tight">From your library</h2>
          <div className="grid gap-4 md:grid-cols-3">
            {teasers.map((t, i) => (
              <Link key={i} href="/insights">
                <Card className="hover:border-primary transition-colors cursor-pointer h-full">
                  <CardContent className="p-4 flex items-start gap-3">
                    <t.icon className="h-4 w-4 text-primary flex-shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium">{t.text}</p>
                      <p className="text-xs text-muted-foreground mt-1 truncate" title={t.sub}>{t.sub}</p>
                    </div>
                    <ArrowRight className="h-4 w-4 text-muted-foreground flex-shrink-0 mt-0.5" />
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        </div>
      )}

      <div className="mt-8">
        <h2 className="text-xl font-semibold mb-4 tracking-tight">Recent Activity</h2>
        {stats?.recent_activity && stats.recent_activity.length > 0 ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {stats.recent_activity.map(asset => (
              <Link key={asset.id} href={`/library/${asset.id}`}>
                <Card className="hover:border-primary transition-colors cursor-pointer overflow-hidden group">
                  <div className="aspect-video bg-muted relative">
                    {asset.thumbnail_url ? (
                      <img src={`/api/thumbnails/${asset.thumbnail_url}`} alt={asset.filename} className="w-full h-full object-cover" />
                    ) : (
                      <div className="absolute inset-0 flex items-center justify-center">
                        <Film className="h-8 w-8 text-muted-foreground/50" />
                      </div>
                    )}
                  </div>
                  <CardContent className="p-4">
                    <p className="text-sm font-medium truncate" title={asset.filename}>{asset.filename}</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      {EVENT_LABELS[asset.status] ?? "Added"} · {new Date(asset.created_at).toLocaleDateString()}
                    </p>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No recent activity.</p>
        )}
      </div>
    </div>
  );
}
