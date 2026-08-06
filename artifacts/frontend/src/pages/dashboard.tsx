import { useEffect, useState } from "react";
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
import { Card, CardContent } from "@/components/ui/card";
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
  Scissors,
  BookOpen,
  Clapperboard,
  AlertTriangle,
  Users,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatHours } from "@/lib/format";

const SEARCH_PROMPTS = [
  "every clip where someone mentions Jerusalem…",
  "close-up shots of a microphone…",
  "\u201cfaith and modernity\u201d — exact quotes…",
  "scenes with two people talking outdoors…",
  "everything Nikki Haley says about diplomacy…",
  "wide shots of a concert crowd…",
];

function formatSpeaking(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

export default function Dashboard() {
  const { data: stats, isLoading } = useGetLibraryStats({ query: { queryKey: getGetLibraryStatsQueryKey() } });
  const { data: insights } = useGetLibraryInsights({ query: { queryKey: getGetLibraryInsightsQueryKey() } });
  const { data: projects } = useListProjects({ query: { queryKey: getListProjectsQueryKey() } });
  const { data: jobStats } = useGetJobStats({ query: { queryKey: getGetJobStatsQueryKey(), refetchInterval: 15000 } });
  const [, navigate] = useLocation();
  const [quickQuery, setQuickQuery] = useState("");
  const [promptIdx, setPromptIdx] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setPromptIdx((i) => (i + 1) % SEARCH_PROMPTS.length), 3500);
    return () => clearInterval(t);
  }, []);

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

  const topPeople = (insights?.top_people ?? []).slice(0, 12);
  const topTopics = (insights?.top_topics ?? []).slice(0, 12);
  const maxTopicCount = topTopics.length > 0 ? Math.max(...topTopics.map((t) => t.asset_count)) : 1;

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
    <div className="flex-1 overflow-y-auto">
      {/* ---- Library hero: ask anything --------------------------------- */}
      <div className="relative border-b border-border bg-gradient-to-b from-primary/10 via-background to-background">
        <div className="max-w-5xl mx-auto px-8 pt-14 pb-10 text-center">
          <h1 className="text-4xl font-bold tracking-tight" data-testid="text-hero-title">
            Ask your library anything
          </h1>
          {stats && (
            <p className="mt-3 text-muted-foreground" data-testid="text-hero-stats">
              {stats.total_assets} assets · {formatHours(stats.total_duration_seconds)} of footage ·{" "}
              {insights?.stats?.named_people_count != null ? `${insights.stats.named_people_count} people identified · ` : ""}
              every word and frame indexed
            </p>
          )}
          <div className="mt-6 relative max-w-3xl mx-auto">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground pointer-events-none" />
            <input
              value={quickQuery}
              onChange={(e) => setQuickQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submitQuickSearch()}
              placeholder={`Find ${SEARCH_PROMPTS[promptIdx]}`}
              className="w-full h-14 pl-12 pr-32 rounded-xl bg-card border border-border text-base shadow-lg focus:outline-none focus:ring-2 focus:ring-primary/60 placeholder:text-muted-foreground/70 transition-shadow"
              data-testid="input-hero-search"
            />
            <Button
              className="absolute right-2 top-1/2 -translate-y-1/2 h-10"
              onClick={submitQuickSearch}
              disabled={quickQuery.trim().length < 2}
              data-testid="button-hero-search"
            >
              Search
            </Button>
          </div>
          <p className="mt-3 text-xs text-muted-foreground/70">
            Semantic search across transcripts, visuals, and people — not just filenames.
          </p>
        </div>
      </div>

      <div className="p-8 max-w-7xl mx-auto">
        {/* ---- Library vitals ------------------------------------------- */}
        {isLoading ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {[...Array(4)].map((_, i) => (
              <Card key={i} className="animate-pulse bg-muted h-24" />
            ))}
          </div>
        ) : stats ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {[
              { href: "/library", icon: Film, label: "Assets", value: String(stats.total_assets), sub: "Indexed media files" },
              { icon: Clock, label: "Footage", value: formatHours(stats.total_duration_seconds), sub: `${formatHours(stats.speech_indexed_seconds)} speech-searchable` },
              { icon: HardDrive, label: "Storage", value: formatBytes(stats.storage_bytes), sub: "Across all qualities" },
              {
                href: "/jobs",
                icon: errorCount > 0 ? AlertTriangle : Activity,
                label: "Pipeline",
                value: String(jobStats?.jobs_running ?? stats.status_counts.processing ?? 0),
                sub: errorCount > 0
                  ? `${errorCount} failed asset${errorCount === 1 ? "" : "s"} need attention`
                  : `running · ${jobStats?.jobs_pending ?? stats.status_counts.pending ?? 0} queued`,
                alert: errorCount > 0,
              },
            ].map((c, i) => {
              const card = (
                <Card key={i} className={`h-full ${c.href ? "hover:border-primary transition-colors cursor-pointer" : ""} ${c.alert ? "border-red-500/50" : ""}`}>
                  <CardContent className="p-4 flex items-center gap-4">
                    <c.icon className={`h-6 w-6 flex-shrink-0 ${c.alert ? "text-red-400" : "text-primary/70"}`} />
                    <div className="min-w-0">
                      <div className="text-2xl font-bold leading-tight">{c.value}</div>
                      <p className={`text-xs truncate ${c.alert ? "text-red-400" : "text-muted-foreground"}`}>{c.label} · {c.sub}</p>
                    </div>
                  </CardContent>
                </Card>
              );
              return c.href ? <Link key={i} href={c.href}>{card}</Link> : card;
            })}
          </div>
        ) : null}

        {/* ---- People wall ---------------------------------------------- */}
        {topPeople.length > 0 && (
          <div className="mt-10">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold tracking-tight flex items-center gap-2">
                <Users className="h-5 w-5 text-primary/70" />
                People in your library
              </h2>
              <Link href="/people" className="text-sm text-muted-foreground hover:text-foreground flex items-center gap-1">
                All people <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
            <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-12 gap-3">
              {topPeople.map((p) => (
                <Link key={p.person_id} href={`/people/${p.person_id}`}>
                  <div className="group text-center cursor-pointer" data-testid={`card-person-${p.person_id}`}>
                    <div className="aspect-square rounded-full overflow-hidden bg-muted ring-2 ring-transparent group-hover:ring-primary transition-all mx-auto">
                      {p.thumbnail_url ? (
                        <img src={`/api/thumbnails/${p.thumbnail_url}`} alt={p.display_name} className="w-full h-full object-cover" />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-lg font-semibold text-muted-foreground">
                          {p.display_name.slice(0, 1)}
                        </div>
                      )}
                    </div>
                    <p className="mt-1.5 text-xs font-medium truncate" title={p.display_name}>{p.display_name}</p>
                    <p className="text-[10px] text-muted-foreground">
                      {formatSpeaking(p.speaking_seconds)} · {p.asset_count} asset{p.asset_count === 1 ? "" : "s"}
                    </p>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* ---- Topic landscape ------------------------------------------ */}
        {topTopics.length > 0 && (
          <div className="mt-10">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold tracking-tight flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-primary/70" />
                What your library is about
              </h2>
              <Link href="/insights" className="text-sm text-muted-foreground hover:text-foreground flex items-center gap-1">
                Full insights <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
            <div className="flex flex-wrap gap-2">
              {topTopics.map((t) => {
                const weight = t.asset_count / maxTopicCount;
                return (
                  <Link key={t.topic} href={`/library?topic=${encodeURIComponent(t.topic)}`}>
                    <span
                      className="inline-flex items-baseline gap-1.5 rounded-full border border-border bg-card hover:border-primary cursor-pointer transition-colors px-3 py-1.5"
                      style={{ fontSize: `${0.75 + weight * 0.5}rem`, opacity: 0.6 + weight * 0.4 }}
                      data-testid={`chip-topic-${t.topic}`}
                    >
                      <span className="font-medium">{t.topic}</span>
                      <span className="text-[0.65em] text-muted-foreground">{t.asset_count}</span>
                    </span>
                  </Link>
                );
              })}
            </div>
          </div>
        )}

        {/* ---- Insight teasers ------------------------------------------ */}
        {teasers.length > 0 && (
          <div className="mt-10">
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

        {/* ---- Active projects ------------------------------------------ */}
        {activeProjects.length > 0 && (
          <div className="mt-10">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold tracking-tight">Active Projects</h2>
              <Link href="/studio" className="text-sm text-muted-foreground hover:text-foreground flex items-center gap-1">
                All projects <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
              {activeProjects.map((p) => (
                <Link key={p.id} href={`/studio/${p.id}`}>
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
      </div>
    </div>
  );
}
