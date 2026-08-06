import { useEffect, useRef, useState } from "react";
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

// Gradient palette cycled across topic tiles.
const TILE_GRADIENTS = [
  "from-sky-500/25 to-blue-600/10",
  "from-amber-500/25 to-orange-600/10",
  "from-emerald-500/25 to-teal-600/10",
  "from-fuchsia-500/25 to-purple-600/10",
  "from-rose-500/25 to-red-600/10",
  "from-cyan-500/25 to-sky-600/10",
  "from-violet-500/25 to-indigo-600/10",
  "from-lime-500/25 to-green-600/10",
];

function formatSpeaking(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

/** Ease-out count-up for hero/vital numbers. */
function useCountUp(target: number, duration = 900): number {
  const [value, setValue] = useState(0);
  const started = useRef<number | null>(null);
  useEffect(() => {
    let raf = 0;
    started.current = null;
    const step = (t: number) => {
      if (started.current === null) started.current = t;
      const p = Math.min(1, (t - started.current) / duration);
      setValue(target * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);
  return value;
}

/** SVG donut showing a fraction, with content slotted in the middle. */
function Donut({ frac, children }: { frac: number; children?: React.ReactNode }) {
  const r = 26;
  const c = 2 * Math.PI * r;
  const clamped = Math.min(1, Math.max(0, frac));
  return (
    <div className="relative h-16 w-16 flex-shrink-0">
      <svg viewBox="0 0 64 64" className="h-16 w-16 -rotate-90">
        <circle cx="32" cy="32" r={r} fill="none" strokeWidth="6" className="stroke-muted" />
        <circle
          cx="32" cy="32" r={r} fill="none" strokeWidth="6" strokeLinecap="round"
          className="stroke-primary transition-[stroke-dasharray] duration-1000 ease-out"
          strokeDasharray={`${c * clamped} ${c}`}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center text-[11px] font-semibold">
        {children}
      </div>
    </div>
  );
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

  const submitQuickSearch = () => {
    const q = quickQuery.trim();
    if (q.length < 2) return;
    navigate(`/search?q=${encodeURIComponent(q)}`);
  };

  const errorCount = stats?.status_counts.error || 0;
  const running = jobStats?.jobs_running ?? stats?.status_counts.processing ?? 0;
  const queued = jobStats?.jobs_pending ?? stats?.status_counts.pending ?? 0;

  const animAssets = Math.round(useCountUp(stats?.total_assets ?? 0));
  const animHours = useCountUp((stats?.total_duration_seconds ?? 0) / 3600);

  const activeProjects = (projects ?? [])
    .slice()
    .sort((a, b) =>
      (b.updated_at ?? b.created_at).localeCompare(a.updated_at ?? a.created_at),
    )
    .slice(0, 4);

  const topPeople = (insights?.top_people ?? []).slice(0, 10);
  const maxSpeaking = topPeople.length > 0 ? Math.max(...topPeople.map((p) => p.speaking_seconds)) : 1;
  const totalTopSpeaking = topPeople.reduce((s, p) => s + p.speaking_seconds, 0);

  const topTopics = (insights?.top_topics ?? []).slice(0, 9);
  const maxTopicCount = topTopics.length > 0 ? Math.max(...topTopics.map((t) => t.asset_count)) : 1;

  const statusSegments = stats
    ? [
        { key: "ready", count: stats.status_counts.ready ?? 0, cls: "bg-emerald-500/80" },
        { key: "processing", count: stats.status_counts.processing ?? 0, cls: "bg-sky-500/80" },
        { key: "pending", count: stats.status_counts.pending ?? 0, cls: "bg-amber-500/70" },
        { key: "error", count: stats.status_counts.error ?? 0, cls: "bg-red-500/80" },
      ].filter((s) => s.count > 0)
    : [];
  const statusTotal = statusSegments.reduce((s, x) => s + x.count, 0) || 1;

  const searchableFrac = stats && stats.total_duration_seconds > 0
    ? stats.speech_indexed_seconds / stats.total_duration_seconds
    : 0;

  const storageGb = (stats?.storage_bytes ?? 0) / 1024 ** 3;

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
      <div className="relative border-b border-border bg-gradient-to-b from-primary/10 via-background to-background overflow-hidden">
        <div
          className="absolute inset-0 opacity-[0.35] pointer-events-none"
          style={{
            backgroundImage:
              "radial-gradient(circle at 20% 0%, hsl(var(--primary) / 0.25), transparent 45%), radial-gradient(circle at 80% 10%, hsl(280 80% 60% / 0.15), transparent 40%)",
          }}
        />
        <div className="relative max-w-5xl mx-auto px-8 pt-16 pb-12 text-center">
          <h1 className="text-4xl font-bold tracking-tight" data-testid="text-hero-title">
            Ask your library anything
          </h1>
          {stats && (
            <p className="mt-3 text-muted-foreground" data-testid="text-hero-stats">
              {animAssets} assets · {animHours.toFixed(1)}h of footage ·{" "}
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
              <Card key={i} className="animate-pulse bg-muted h-28" />
            ))}
          </div>
        ) : stats ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {/* Assets + status mosaic */}
            <Link href="/library">
              <Card className="h-full hover:border-primary transition-colors cursor-pointer" data-testid="card-vital-assets">
                <CardContent className="p-4">
                  <div className="flex items-center gap-3">
                    <Film className="h-5 w-5 text-primary/70" />
                    <div className="text-3xl font-bold tabular-nums">{animAssets}</div>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">Assets in the library</p>
                  <div className="mt-3 flex h-2 w-full overflow-hidden rounded-full bg-muted">
                    {statusSegments.map((s) => (
                      <div key={s.key} className={s.cls} style={{ width: `${(s.count / statusTotal) * 100}%` }} title={`${s.key}: ${s.count}`} />
                    ))}
                  </div>
                  <div className="mt-1.5 flex gap-3 text-[10px] text-muted-foreground">
                    {statusSegments.map((s) => (
                      <span key={s.key} className="flex items-center gap-1">
                        <span className={`h-1.5 w-1.5 rounded-full ${s.cls}`} />
                        {s.count} {s.key}
                      </span>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </Link>

            {/* Footage donut */}
            <Card className="h-full" data-testid="card-vital-footage">
              <CardContent className="p-4 flex items-center gap-4">
                <Donut frac={searchableFrac}>{Math.round(searchableFrac * 100)}%</Donut>
                <div className="min-w-0">
                  <div className="text-2xl font-bold leading-tight">{formatHours(stats.total_duration_seconds)}</div>
                  <p className="text-xs text-muted-foreground">of footage</p>
                  <p className="text-[11px] text-muted-foreground mt-1">
                    {formatHours(stats.speech_indexed_seconds)} word-searchable
                  </p>
                </div>
              </CardContent>
            </Card>

            {/* Storage */}
            <Card className="h-full" data-testid="card-vital-storage">
              <CardContent className="p-4">
                <div className="text-2xl font-bold leading-tight">{storageGb.toFixed(1)} <span className="text-base font-semibold text-muted-foreground">GB</span></div>
                <p className="text-xs text-muted-foreground mt-1">Storage across all qualities</p>
                <div className="mt-3 h-2 w-full rounded-full bg-muted overflow-hidden">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-primary/60 to-primary transition-[width] duration-1000"
                    style={{ width: `${Math.min(100, (storageGb / 100) * 100)}%` }}
                  />
                </div>
                <p className="text-[10px] text-muted-foreground mt-1.5">~{(storageGb / Math.max(1, stats.total_assets)).toFixed(2)} GB per asset</p>
              </CardContent>
            </Card>

            {/* Pipeline pulse */}
            <Link href="/jobs">
              <Card className={`h-full hover:border-primary transition-colors cursor-pointer ${errorCount > 0 ? "border-red-500/50" : ""}`} data-testid="card-vital-pipeline">
                <CardContent className="p-4 flex items-center gap-4">
                  <div className="relative h-12 w-12 flex-shrink-0 flex items-center justify-center">
                    {running > 0 && <span className="absolute inline-flex h-10 w-10 rounded-full bg-primary/20 animate-ping" />}
                    <span className={`relative flex h-10 w-10 items-center justify-center rounded-full ${errorCount > 0 ? "bg-red-500/15" : running > 0 ? "bg-primary/15" : "bg-muted"}`}>
                      {errorCount > 0
                        ? <AlertTriangle className="h-5 w-5 text-red-400" />
                        : <Activity className={`h-5 w-5 ${running > 0 ? "text-primary" : "text-muted-foreground"}`} />}
                    </span>
                  </div>
                  <div className="min-w-0">
                    <div className="text-2xl font-bold leading-tight tabular-nums">{running}</div>
                    <p className={`text-xs ${errorCount > 0 ? "text-red-400" : "text-muted-foreground"}`}>
                      {errorCount > 0
                        ? `${errorCount} failed asset${errorCount === 1 ? "" : "s"} need attention`
                        : running > 0 ? `jobs running · ${queued} queued` : "pipeline idle"}
                    </p>
                  </div>
                </CardContent>
              </Card>
            </Link>
          </div>
        ) : null}

        {/* ---- People wall: share-of-voice ------------------------------ */}
        {topPeople.length > 0 && (
          <div className="mt-10">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold tracking-tight flex items-center gap-2">
                <Users className="h-5 w-5 text-primary/70" />
                Voices of your library
              </h2>
              <Link href="/people" className="text-sm text-muted-foreground hover:text-foreground flex items-center gap-1">
                All people <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
            <div className="flex flex-wrap items-end justify-center gap-x-5 gap-y-4 rounded-xl border border-border bg-card/50 px-6 pt-6 pb-4">
              {topPeople.map((p, i) => {
                const share = p.speaking_seconds / maxSpeaking;
                const size = 56 + Math.round(share * 40); // 56–96px by share of voice
                const ringDeg = totalTopSpeaking > 0 ? (p.speaking_seconds / totalTopSpeaking) * 360 : 0;
                return (
                  <Link key={p.person_id} href={`/people/${p.person_id}`}>
                    <div className="group text-center cursor-pointer transition-transform hover:-translate-y-1" data-testid={`card-person-${p.person_id}`}>
                      <div
                        className="rounded-full p-[3px] mx-auto"
                        style={{
                          width: size + 6,
                          height: size + 6,
                          background: `conic-gradient(hsl(var(--primary)) ${ringDeg}deg, hsl(var(--muted)) ${ringDeg}deg)`,
                        }}
                        title={`${p.display_name} — ${formatSpeaking(p.speaking_seconds)} of speech`}
                      >
                        <div className="rounded-full overflow-hidden bg-muted w-full h-full border-2 border-background">
                          {p.thumbnail_url ? (
                            <img src={`/api/thumbnails/${p.thumbnail_url}`} alt={p.display_name} className="w-full h-full object-cover" />
                          ) : (
                            <div className="w-full h-full flex items-center justify-center font-semibold text-muted-foreground" style={{ fontSize: size / 3 }}>
                              {p.display_name.slice(0, 1)}
                            </div>
                          )}
                        </div>
                      </div>
                      <p className="mt-1.5 text-xs font-medium truncate max-w-[6.5rem]" title={p.display_name}>{p.display_name}</p>
                      <p className="text-[10px] text-muted-foreground">
                        {formatSpeaking(p.speaking_seconds)} · {p.asset_count} asset{p.asset_count === 1 ? "" : "s"}
                      </p>
                      {i === 0 && <p className="text-[9px] uppercase tracking-wider text-primary/80 mt-0.5">most heard</p>}
                    </div>
                  </Link>
                );
              })}
            </div>
          </div>
        )}

        {/* ---- Topic mosaic --------------------------------------------- */}
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
            <div className="grid grid-cols-2 md:grid-cols-4 auto-rows-[92px] gap-3">
              {topTopics.map((t, i) => {
                const weight = t.asset_count / maxTopicCount;
                const big = weight > 0.6 || i === 0;
                const wide = !big && weight > 0.3;
                return (
                  <Link
                    key={t.key ?? t.topic}
                    href={`/library?topic=${encodeURIComponent(t.topic)}`}
                    className={big ? "col-span-2 row-span-2" : wide ? "col-span-2" : ""}
                  >
                    <div
                      className={`h-full w-full rounded-xl border border-border bg-gradient-to-br ${TILE_GRADIENTS[i % TILE_GRADIENTS.length]} hover:border-primary cursor-pointer transition-all hover:shadow-lg p-4 flex flex-col justify-between overflow-hidden`}
                      data-testid={`tile-topic-${t.topic}`}
                    >
                      <span className={`font-semibold leading-tight ${big ? "text-2xl" : wide ? "text-lg" : "text-sm"}`}>{t.topic}</span>
                      <span className="text-xs text-muted-foreground">
                        {t.asset_count} asset{t.asset_count === 1 ? "" : "s"}
                      </span>
                    </div>
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
