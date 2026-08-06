import {
  useGetLibraryInsights,
  getGetLibraryInsightsQueryKey,
  getListPeopleQueryKey,
  useRefreshLibraryInsights,
  useUpdatePerson,
  useCreateProject,
  useGetTrends,
  getGetTrendsQueryKey,
  useRefreshTrends,
  useGetKeywordHeatmap,
  getGetKeywordHeatmapQueryKey,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Fragment, useState, useEffect, useRef } from "react";
import { Link, useLocation } from "wouter";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import {
  Sparkles,
  RefreshCw,
  User,
  Film,
  Clock,
  Users,
  Mic,
  Lightbulb,
  Clapperboard,
  MapPinned,
  Pencil,
  Check,
  X,
  TrendingUp,
  Youtube,
  Newspaper,
  ExternalLink,
  Flame,
} from "lucide-react";
import { formatHours } from "@/lib/format";

const PLACEHOLDER_NAME_RE = /^person \d+$/i;

const personHref = (id: string, name: string) =>
  `/library?person=${encodeURIComponent(id)}&person_name=${encodeURIComponent(name)}`;
const topicHref = (key: string, label: string) =>
  `/library?topic=${encodeURIComponent(key)}&topic_label=${encodeURIComponent(label)}`;

const formatViews = (n: number) =>
  new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);

const monthLabel = (ym: string) => {
  const [y, m] = ym.split("-");
  const short = new Date(Number(y), Number(m) - 1, 1).toLocaleString("en", { month: "short" });
  return m === "01" ? `${short} ${y.slice(2)}` : short;
};

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

/** Ease-out count-up for vital numbers. */
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
function Donut({ frac, children, colorClass = "stroke-primary" }: { frac: number; children?: React.ReactNode; colorClass?: string }) {
  const r = 26;
  const c = 2 * Math.PI * r;
  const clamped = Math.min(1, Math.max(0, frac));
  return (
    <div className="relative h-16 w-16 flex-shrink-0">
      <svg viewBox="0 0 64 64" className="h-16 w-16 -rotate-90">
        <circle cx="32" cy="32" r={r} fill="none" strokeWidth="6" className="stroke-muted" />
        <circle
          cx="32" cy="32" r={r} fill="none" strokeWidth="6" strokeLinecap="round"
          className={`${colorClass} transition-[stroke-dasharray] duration-1000 ease-out`}
          strokeDasharray={`${c * clamped} ${c}`}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center text-[11px] font-semibold">
        {children}
      </div>
    </div>
  );
}

export default function Insights() {
  const queryClient = useQueryClient();
  const [, navigate] = useLocation();
  const { data, isLoading } = useGetLibraryInsights({
    query: { queryKey: getGetLibraryInsightsQueryKey() },
  });
  const refresh = useRefreshLibraryInsights();
  const updatePerson = useUpdatePerson();
  const createProject = useCreateProject();
  const { data: trends } = useGetTrends({
    query: { queryKey: getGetTrendsQueryKey() },
  });
  const refreshTrends = useRefreshTrends();
  const { data: heatmap } = useGetKeywordHeatmap(undefined, {
    query: { queryKey: getGetKeywordHeatmapQueryKey() },
  });

  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [startingStory, setStartingStory] = useState<number | null>(null);

  const handleRefresh = () => {
    refresh.mutate(undefined as never, {
      onSuccess: () => {
        setTimeout(() => {
          queryClient.invalidateQueries({ queryKey: getGetLibraryInsightsQueryKey() });
        }, 8000);
      },
    });
  };

  const handleTrendsRefresh = () => {
    refreshTrends.mutate(undefined as never, {
      onSuccess: () => {
        setTimeout(() => {
          queryClient.invalidateQueries({ queryKey: getGetTrendsQueryKey() });
        }, 8000);
      },
    });
  };

  const saveRename = (personId: string) => {
    const name = renameValue.trim();
    if (!name) return;
    updatePerson.mutate(
      { id: personId, data: { display_name: name } },
      {
        onSuccess: () => {
          setRenamingId(null);
          setRenameValue("");
          queryClient.invalidateQueries({ queryKey: getGetLibraryInsightsQueryKey() });
          queryClient.invalidateQueries({ queryKey: getListPeopleQueryKey() });
        },
      },
    );
  };

  const startStory = (i: number) => {
    const opp = data?.opportunities?.[i];
    if (!opp || startingStory !== null) return;
    setStartingStory(i);
    createProject.mutate(
      { data: { name: opp.title, description: opp.rationale, media_ids: opp.asset_ids } },
      {
        onSuccess: (created: any) => {
          navigate(`/studio/${created.id}`);
        },
        onError: () => setStartingStory(null),
      },
    );
  };

  if (isLoading) {
    return (
      <div className="flex-1 overflow-y-auto">
        <div className="p-8 max-w-7xl mx-auto animate-pulse mt-16 space-y-12">
          <div className="space-y-4 text-center">
            <div className="h-10 w-64 bg-muted rounded mx-auto" />
            <div className="h-6 w-96 bg-muted rounded mx-auto" />
          </div>
          <div className="grid gap-4 md:grid-cols-5">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-28 bg-muted rounded-xl" />
            ))}
          </div>
          <div className="h-64 bg-muted rounded-xl" />
        </div>
      </div>
    );
  }

  const stats = data?.stats;
  const animAssets = Math.round(useCountUp(stats?.total_assets ?? 0));
  const animHours = useCountUp((stats?.total_duration_seconds ?? 0) / 3600);
  const animPeople = Math.round(useCountUp(stats?.named_people_count ?? 0));
  const animIndexed = useCountUp((stats?.speech_indexed_seconds ?? 0) / 3600);
  const animTranscribed = Math.round(useCountUp(stats?.transcribed_assets ?? 0));

  const totalPeople = stats ? stats.named_people_count + stats.unidentified_people_count : 1;
  const namedFrac = stats ? stats.named_people_count / Math.max(1, totalPeople) : 0;
  
  const indexedFrac = stats && stats.total_duration_seconds > 0 ? stats.speech_indexed_seconds / stats.total_duration_seconds : 0;
  const transcribedFrac = stats && stats.total_assets > 0 ? stats.transcribed_assets / stats.total_assets : 0;

  const topPeople = data?.top_people ?? [];
  const totalTopSpeaking = topPeople.reduce((s, p) => s + p.speaking_seconds, 0);

  return (
    <div className="flex-1 overflow-y-auto">
      {/* ---- Hero Section --------------------------------------------- */}
      <div className="relative border-b border-border bg-gradient-to-b from-primary/10 via-background to-background overflow-hidden">
        <div
          className="absolute inset-0 opacity-[0.35] pointer-events-none"
          style={{
            backgroundImage:
              "radial-gradient(circle at 20% 0%, hsl(var(--primary) / 0.25), transparent 45%), radial-gradient(circle at 80% 10%, hsl(280 80% 60% / 0.15), transparent 40%)",
          }}
        />
        <div className="relative max-w-6xl mx-auto px-8 pt-16 pb-14 text-center">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
            <h1 className="text-4xl font-bold tracking-tight text-left">Library Intelligence</h1>
            <Button onClick={handleRefresh} disabled={refresh.isPending} variant="secondary" className="gap-2 sm:self-start">
              <RefreshCw className={`h-4 w-4 ${refresh.isPending ? "animate-spin" : ""}`} />
              {refresh.isPending ? "Queued..." : "Refresh Insights"}
            </Button>
          </div>

          {data?.headline && (
            <div className="mt-8 mb-2 flex justify-start">
              <div className="inline-flex items-start gap-3 border border-primary/20 bg-primary/5 rounded-2xl px-6 py-4 shadow-[0_0_40px_-10px_hsl(var(--primary)/0.2)]">
                <Sparkles className="h-5 w-5 text-primary flex-shrink-0 mt-0.5 animate-pulse" />
                <p className="text-lg md:text-xl font-medium text-foreground/90 max-w-3xl text-left leading-snug">
                  {data.headline}
                </p>
              </div>
            </div>
          )}

          <p className="text-sm text-muted-foreground mt-4 text-left">
            {data?.generated_at
              ? `AI analysis last generated ${new Date(data.generated_at).toLocaleString()}`
              : "AI analysis has not been generated yet — refresh to build it."}
            {refresh.isSuccess && " · Refresh queued, check the Processing Pipeline."}
          </p>
        </div>
      </div>

      <div className="p-8 max-w-7xl mx-auto space-y-12">
        {/* ---- Vitals --------------------------------------------------- */}
        {stats && (
          <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-5">
            <Card className="hover:border-primary/50 transition-colors shadow-sm">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <Film className="h-5 w-5 text-primary/70" />
                  <div className="text-3xl font-bold tabular-nums">{animAssets}</div>
                </div>
                <p className="text-xs text-muted-foreground mt-1 font-medium">Assets in library</p>
              </CardContent>
            </Card>
            
            <Card className="hover:border-primary/50 transition-colors shadow-sm">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <Clock className="h-5 w-5 text-primary/70" />
                  <div className="text-3xl font-bold tabular-nums">{animHours.toFixed(1)}h</div>
                </div>
                <p className="text-xs text-muted-foreground mt-1 font-medium">Total Footage</p>
              </CardContent>
            </Card>

            <Card className="hover:border-primary/50 transition-colors shadow-sm">
              <CardContent className="p-4 flex flex-col justify-center h-full">
                <div className="flex items-center gap-3">
                  <Users className="h-5 w-5 text-primary/70" />
                  <div className="text-3xl font-bold tabular-nums">{animPeople}</div>
                </div>
                <div className="flex items-center justify-between mt-1">
                  <p className="text-xs text-muted-foreground font-medium">Named People</p>
                  <p className="text-[10px] text-muted-foreground">{stats.unidentified_people_count} unnamed</p>
                </div>
                <div className="mt-2.5 flex h-1.5 w-full overflow-hidden rounded-full bg-muted">
                  <div className="bg-primary/70 transition-[width] duration-1000" style={{ width: `${namedFrac * 100}%` }} />
                </div>
              </CardContent>
            </Card>

            <Card className="hover:border-primary/50 transition-colors shadow-sm">
              <CardContent className="p-4 flex items-center gap-4 h-full">
                <Donut frac={indexedFrac}>{Math.round(indexedFrac * 100)}%</Donut>
                <div className="min-w-0">
                  <div className="text-2xl font-bold leading-tight tabular-nums">{animIndexed.toFixed(1)}h</div>
                  <p className="text-[11px] text-muted-foreground leading-tight mt-0.5 font-medium">Speech Indexed</p>
                </div>
              </CardContent>
            </Card>

            <Card className="hover:border-primary/50 transition-colors shadow-sm">
              <CardContent className="p-4 flex items-center gap-4 h-full">
                <Donut frac={transcribedFrac} colorClass="stroke-emerald-500">{Math.round(transcribedFrac * 100)}%</Donut>
                <div className="min-w-0">
                  <div className="text-2xl font-bold leading-tight tabular-nums">{animTranscribed}</div>
                  <p className="text-[11px] text-muted-foreground leading-tight mt-0.5 font-medium">Transcribed</p>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* ---- Heatmap -------------------------------------------------- */}
        {heatmap?.rows?.length ? (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <Flame className="h-5 w-5 text-orange-500" />
              <h2 className="text-xl font-semibold tracking-tight">Keyword Heatmap</h2>
            </div>
            <p className="text-xs text-muted-foreground mb-4">
              Videos per keyword per month — spot topics running hot or going cold. Click a row to open those videos.
            </p>
            <div className="border border-border bg-card/50 rounded-xl p-6 overflow-x-auto shadow-sm backdrop-blur-sm">
              <div
                className="grid gap-[3px] min-w-[640px]"
                style={{
                  gridTemplateColumns: `minmax(150px, max-content) repeat(${heatmap.months.length}, minmax(28px, 1fr))`,
                }}
              >
                <div />
                {heatmap.months.map((ym) => (
                  <div
                    key={ym}
                    className="text-[10px] text-muted-foreground text-center pb-2 whitespace-nowrap font-medium"
                  >
                    {monthLabel(ym)}
                  </div>
                ))}
                {heatmap.rows.map((row) => {
                  const rowMax = Math.max(1, ...row.counts);
                  return (
                    <Fragment key={row.key}>
                      <Link href={topicHref(row.key, row.label)}>
                        <div className="h-8 pr-4 flex items-center justify-end gap-2 text-xs cursor-pointer hover:text-primary group">
                          <span className="truncate max-w-[200px] transition-colors group-hover:text-primary font-medium">{row.label}</span>
                          <span className="text-muted-foreground/50 tabular-nums">{row.total}</span>
                        </div>
                      </Link>
                      {row.counts.map((c, i) => (
                        <Link key={heatmap.months[i]} href={topicHref(row.key, row.label)}>
                          <div
                            className="h-8 rounded-[4px] cursor-pointer transition-all hover:scale-[1.15] hover:z-10 hover:shadow-md bg-muted/40"
                            style={
                              c > 0
                                ? {
                                    backgroundColor: `hsl(20 90% 55% / ${(0.15 + 0.85 * (c / rowMax)).toFixed(2)})`,
                                  }
                                : undefined
                            }
                            title={`${row.label} — ${c} ${c === 1 ? "video" : "videos"} in ${new Date(Number(heatmap.months[i].slice(0, 4)), Number(heatmap.months[i].slice(5)) - 1, 1).toLocaleString("en", { month: "long", year: "numeric" })}`}
                          />
                        </Link>
                      ))}
                    </Fragment>
                  );
                })}
              </div>
            </div>
          </div>
        ) : null}

        {/* ---- Main Content Grid ---------------------------------------- */}
        <div className="grid gap-10 lg:grid-cols-3">
          
          {/* ---- Left Column (Span 2) ----------------------------------- */}
          <div className="lg:col-span-2 space-y-10">
            
            {/* Story Opportunities */}
            {data?.opportunities?.length ? (
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <Clapperboard className="h-5 w-5 text-primary" />
                  <h2 className="text-xl font-semibold tracking-tight">Story Opportunities</h2>
                </div>
                <div className="space-y-4">
                  {data.opportunities.map((opp, i) => (
                    <div key={i} className="group relative border border-border bg-card/40 hover:bg-card rounded-xl p-5 transition-all hover:shadow-md hover:border-primary/50 overflow-hidden">
                      <div className="absolute inset-0 bg-gradient-to-r from-primary/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none" />
                      <div className="relative flex flex-col sm:flex-row sm:items-start justify-between gap-5">
                        <div className="flex-1 min-w-0">
                          <p className="text-base font-semibold mb-1.5 text-foreground/90">{opp.title}</p>
                          <p className="text-sm text-muted-foreground leading-relaxed">{opp.rationale}</p>
                          <div className="flex flex-wrap items-center gap-3 mt-4">
                             <Badge variant="secondary" className="text-[10px] uppercase tracking-wider bg-background/50">
                               {opp.asset_ids.length} Assets
                             </Badge>
                             <span className="text-xs text-muted-foreground flex items-center gap-1 font-medium">
                               <Clock className="h-3.5 w-3.5" /> {formatHours(opp.total_duration_seconds)}
                             </span>
                             {opp.people.length > 0 && (
                               <span className="text-xs text-muted-foreground flex items-center gap-1 truncate font-medium">
                                 <Users className="h-3.5 w-3.5" /> {opp.people.map(p => p.display_name).join(", ")}
                               </span>
                             )}
                          </div>
                        </div>
                        <Button
                          size="sm"
                          className="flex-shrink-0 gap-1.5 shadow-sm sm:mt-1 w-full sm:w-auto"
                          disabled={startingStory !== null}
                          onClick={() => startStory(i)}
                        >
                          <Clapperboard className="h-3.5 w-3.5" />
                          {startingStory === i ? "Creating..." : "Start story"}
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {/* Key Findings */}
            <div>
              <div className="flex items-center gap-2 mb-4">
                <Lightbulb className="h-5 w-5 text-primary" />
                <h2 className="text-xl font-semibold tracking-tight">Key Findings</h2>
              </div>
              {data?.insights?.length ? (
                <div className="grid gap-4 sm:grid-cols-2">
                  {data.insights.map((item, i) => (
                    <Card key={i} className="hover:border-primary/50 transition-colors bg-card/40 hover:bg-card shadow-sm flex flex-col">
                      <CardContent className="p-5 flex-1 flex flex-col">
                        <p className="text-sm font-semibold mb-2 text-foreground/90">{item.title}</p>
                        <p className="text-sm text-muted-foreground leading-relaxed flex-1">{item.detail}</p>
                        {(item.related_people?.length || item.related_topics?.length) ? (
                          <div className="flex flex-wrap gap-1.5 mt-4 pt-4 border-t border-border/50">
                            {item.related_people?.map((p, j) =>
                              p.person_id ? (
                                <Link key={`p-${j}`} href={personHref(p.person_id, p.display_name)}>
                                  <Badge variant="secondary" className="text-[10px] cursor-pointer hover:bg-primary/20 gap-1 bg-background/50 text-foreground/80">
                                    <User className="h-3 w-3" />
                                    {p.display_name}
                                  </Badge>
                                </Link>
                              ) : (
                                <Badge key={`p-${j}`} variant="secondary" className="text-[10px] gap-1 opacity-70 bg-background/50 text-foreground/80">
                                  <User className="h-3 w-3" />
                                  {p.display_name}
                                </Badge>
                              ),
                            )}
                            {item.related_topics?.map((t, j) => (
                              <Link key={`t-${j}`} href={topicHref(t.key, t.label)}>
                                <Badge variant="outline" className="text-[10px] cursor-pointer hover:border-primary bg-background/50 text-foreground/80">
                                  {t.label}
                                </Badge>
                              </Link>
                            ))}
                          </div>
                        ) : null}
                      </CardContent>
                    </Card>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground border border-dashed border-border rounded-xl p-6 text-center">
                  No AI findings yet. Refresh insights once media has been processed.
                </p>
              )}
            </div>

            {/* Trending Now */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <TrendingUp className="h-5 w-5 text-primary" />
                  <h2 className="text-xl font-semibold tracking-tight">Trending Now</h2>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  className="gap-1.5 text-xs h-8 bg-card/40 hover:bg-card border border-border/50"
                  disabled={refreshTrends.isPending}
                  onClick={handleTrendsRefresh}
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${refreshTrends.isPending ? "animate-spin" : ""}`} />
                  {refreshTrends.isPending ? "Queued..." : "Refresh"}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground mb-5">
                {trends?.fetched_at
                  ? `External trend data fetched ${new Date(trends.fetched_at).toLocaleString()} · keywords only, nothing leaves the library`
                  : "No trend data yet — refreshes automatically every 3 hours."}
              </p>
              
              <div className="space-y-6">
                <div className="border border-border bg-card/40 rounded-xl p-5 shadow-sm hover:bg-card/60 transition-colors">
                  <h3 className="text-sm font-semibold mb-5 flex items-center gap-2">
                    <Youtube className="h-4 w-4 text-red-500" />
                    Your Topics on YouTube
                  </h3>
                  {!trends?.youtube_configured ? (
                    <p className="text-sm text-muted-foreground">
                      Not configured — set YOUTUBE_API_KEY to search recent videos for your topics.
                    </p>
                  ) : trends?.youtube?.length ? (
                    <div className="space-y-4">
                      {trends.youtube.slice(0, 8).map((v) => (
                        <div key={`${v.rank}-${v.title}`} className="text-sm">
                          <div className="flex items-start gap-3">
                            <div className="flex flex-col items-center justify-center bg-background/50 rounded-lg w-10 h-10 border border-border/50 shrink-0">
                              <span className="text-[9px] text-muted-foreground uppercase leading-none mb-0.5">Rank</span>
                              <span className="text-sm font-bold text-foreground leading-none">#{v.rank}</span>
                            </div>
                            <div className="flex-1 min-w-0">
                              {v.url ? (
                                <a
                                  href={v.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="font-medium text-foreground/90 hover:text-primary inline-flex items-start gap-1.5 transition-colors"
                                >
                                  <span className="line-clamp-2">{v.title}</span>
                                  <ExternalLink className="h-3 w-3 flex-shrink-0 mt-1 text-muted-foreground" />
                                </a>
                              ) : (
                                <span className="font-medium text-foreground/90 line-clamp-2">{v.title}</span>
                              )}
                              <p className="text-xs text-muted-foreground mt-1">
                                {v.channel}
                                {v.views != null && <> · <span className="font-medium">{formatViews(v.views)} views</span></>}
                              </p>
                              {v.matched_topics.length > 0 && (
                                <div className="flex flex-wrap gap-1.5 mt-2">
                                  {v.matched_topics.map((t) => (
                                    <Link key={t.key} href={topicHref(t.key, t.topic)}>
                                      <Badge variant="outline" className="text-[10px] cursor-pointer hover:border-primary bg-background/50">
                                        {t.topic}
                                        <span className="ml-1.5 text-muted-foreground">{t.asset_count}</span>
                                      </Badge>
                                    </Link>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      No recent videos found for your library topics yet.
                    </p>
                  )}
                </div>

                <div className="border border-border bg-card/40 rounded-xl p-5 shadow-sm hover:bg-card/60 transition-colors">
                  <h3 className="text-sm font-semibold mb-5 flex items-center gap-2">
                    <Newspaper className="h-4 w-4 text-blue-500" />
                    Your Topics in the News
                  </h3>
                  {!trends?.web_configured ? (
                    <p className="text-sm text-muted-foreground">
                      Not configured — start the SearXNG container to track news momentum.
                    </p>
                  ) : trends?.web?.length ? (
                    <div className="space-y-5">
                      {trends.web.slice(0, 8).map((w) => (
                        <div key={w.key} className="text-sm">
                          <div className="flex items-center justify-between gap-3">
                            <Link href={topicHref(w.key, w.topic)}>
                              <span className="font-semibold text-foreground/90 cursor-pointer hover:text-primary transition-colors text-sm">{w.topic}</span>
                            </Link>
                            <Badge variant="secondary" className="text-[10px] bg-background/50 text-muted-foreground shrink-0">
                              {w.result_count} {w.result_count === 1 ? "story" : "stories"} · {w.asset_count} {w.asset_count === 1 ? "asset" : "assets"}
                            </Badge>
                          </div>
                          {w.headlines.length > 0 && w.headlines[0].url && (
                            <div className="mt-2.5 pl-3 border-l-2 border-primary/30">
                              <a
                                href={w.headlines[0].url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-[13px] text-muted-foreground hover:text-primary line-clamp-2 transition-colors leading-snug"
                              >
                                {w.headlines[0].title}
                              </a>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      No news matches yet — refresh once topics have been extracted.
                    </p>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* ---- Right Column (Span 1) ---------------------------------- */}
          <div className="space-y-10">
            
            {/* Top People */}
            <div>
              <div className="flex items-center gap-2 mb-4">
                <Users className="h-5 w-5 text-primary" />
                <h2 className="text-xl font-semibold tracking-tight">Most Featured People</h2>
              </div>
              {data?.top_people?.length ? (
                <div className="space-y-3">
                  {data.top_people.slice(0, 6).map((p) => {
                    const isPlaceholder = PLACEHOLDER_NAME_RE.test(p.display_name);
                    const isRenaming = renamingId === p.person_id;
                    const ringDeg = totalTopSpeaking > 0 ? (p.speaking_seconds / totalTopSpeaking) * 360 : 0;

                    const inner = (
                      <div className="group border border-border bg-card/40 hover:bg-card rounded-xl p-3 flex items-center gap-4 hover:border-primary/50 transition-all shadow-sm">
                        <div className="relative flex-shrink-0 transition-transform group-hover:scale-105">
                          <div
                            className="rounded-full p-[2px]"
                            style={{
                              background: `conic-gradient(hsl(var(--primary)) ${ringDeg}deg, hsl(var(--muted)) ${ringDeg}deg)`,
                            }}
                          >
                            <div className="w-10 h-10 rounded-full bg-muted overflow-hidden border-2 border-background">
                              {p.thumbnail_url ? (
                                <img src={`/api/thumbnails/${p.thumbnail_url}`} alt={p.display_name} className="w-full h-full object-cover" />
                              ) : (
                                <div className="w-full h-full flex items-center justify-center font-semibold text-muted-foreground/60 text-xs">
                                  {p.display_name.slice(0, 1)}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                        {isRenaming ? (
                          <div
                            className="flex-1 min-w-0 flex items-center gap-1.5"
                            onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}
                          >
                            <Input
                              autoFocus
                              value={renameValue}
                              onChange={(e) => setRenameValue(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") { e.preventDefault(); saveRename(p.person_id); }
                                if (e.key === "Escape") setRenamingId(null);
                              }}
                              placeholder="Who is this?"
                              className="h-8 text-xs bg-background"
                            />
                            <Button
                              size="sm"
                              variant="secondary"
                              className="h-8 w-8 p-0 shrink-0"
                              disabled={updatePerson.isPending || !renameValue.trim()}
                              onClick={() => saveRename(p.person_id)}
                            >
                              <Check className="h-4 w-4" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-8 w-8 p-0 shrink-0"
                              onClick={() => setRenamingId(null)}
                            >
                              <X className="h-4 w-4" />
                            </Button>
                          </div>
                        ) : (
                          <>
                            <div className="flex-1 min-w-0">
                              <p className={`text-sm font-semibold truncate ${isPlaceholder ? "text-muted-foreground italic font-normal" : "text-foreground/90"}`}>
                                {p.display_name}
                              </p>
                              <p className="text-[11px] text-muted-foreground mt-0.5 font-medium">
                                {p.asset_count} {p.asset_count === 1 ? "asset" : "assets"} · {formatSpeaking(p.speaking_seconds)}
                              </p>
                            </div>
                            {isPlaceholder && (
                              <Button
                                size="sm"
                                variant="outline"
                                className="h-7 gap-1 text-[10px] flex-shrink-0 bg-background/50 hover:bg-background"
                                onClick={(e) => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  setRenamingId(p.person_id);
                                  setRenameValue("");
                                }}
                              >
                                <Pencil className="h-3 w-3" />
                                Name
                              </Button>
                            )}
                          </>
                        )}
                      </div>
                    );
                    return isRenaming ? (
                      <div key={p.person_id}>{inner}</div>
                    ) : (
                      <Link key={p.person_id} href={`/people/${p.person_id}`}>
                        {inner}
                      </Link>
                    );
                  })}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground border border-dashed border-border rounded-xl p-6 text-center">
                  No people identified yet.
                </p>
              )}
            </div>

            {/* Top Topics */}
            <div>
              <div className="flex items-center gap-2 mb-4">
                <Sparkles className="h-5 w-5 text-primary" />
                <h2 className="text-xl font-semibold tracking-tight">Top Topics</h2>
              </div>
              {data?.top_topics?.length ? (
                <div className="grid grid-cols-2 gap-3 auto-rows-[88px]">
                  {data.top_topics.slice(0, 8).map((t, i) => {
                    const big = i === 0;
                    return (
                      <Link key={t.key} href={topicHref(t.key, t.topic)} className={big ? "col-span-2 row-span-2" : ""}>
                        <div className={`h-full w-full rounded-xl border border-border bg-gradient-to-br ${TILE_GRADIENTS[i % TILE_GRADIENTS.length]} hover:border-primary cursor-pointer transition-all hover:shadow-lg p-4 flex flex-col justify-between overflow-hidden group`}>
                          <span className={`font-semibold leading-tight text-foreground/90 group-hover:scale-[1.02] transition-transform origin-top-left ${big ? "text-2xl" : "text-[13px]"}`}>{t.topic}</span>
                          <span className="text-[11px] text-muted-foreground font-medium mt-2">
                            {t.asset_count} {t.asset_count === 1 ? "asset" : "assets"}
                          </span>
                        </div>
                      </Link>
                    );
                  })}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground border border-dashed border-border rounded-xl p-6 text-center">
                  No topics extracted yet.
                </p>
              )}
            </div>

            {/* Coverage Gaps */}
            {data?.coverage_gaps?.length ? (
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <MapPinned className="h-5 w-5 text-primary" />
                  <h2 className="text-xl font-semibold tracking-tight">Coverage Gaps</h2>
                </div>
                <div className="space-y-2.5">
                  {data.coverage_gaps.map((g) => (
                    <Link key={g.key} href={topicHref(g.key, g.label)}>
                      <div className="border border-border bg-card/40 hover:bg-card rounded-xl px-4 py-3.5 flex items-center justify-between cursor-pointer hover:border-primary/50 transition-colors shadow-sm group">
                        <p className="text-sm font-medium text-foreground/90 group-hover:text-primary transition-colors">{g.label}</p>
                        <Badge variant="secondary" className="text-[10px] bg-background/50 text-muted-foreground">
                          {g.asset_count === 0 ? "no assets" : `${g.asset_count} ${g.asset_count === 1 ? "asset" : "assets"}`}
                        </Badge>
                      </div>
                    </Link>
                  ))}
                </div>
              </div>
            ) : null}

          </div>
        </div>
      </div>
    </div>
  );
}
