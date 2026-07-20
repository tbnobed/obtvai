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
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useLocation } from "wouter";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
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
} from "lucide-react";
import { formatHours } from "@/lib/format";

const PLACEHOLDER_NAME_RE = /^person \d+$/i;

const personHref = (id: string, name: string) =>
  `/library?person=${encodeURIComponent(id)}&person_name=${encodeURIComponent(name)}`;
const topicHref = (key: string, label: string) =>
  `/library?topic=${encodeURIComponent(key)}&topic_label=${encodeURIComponent(label)}`;

const formatViews = (n: number) =>
  new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);

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
          navigate(`/projects/${created.id}`);
        },
        onError: () => setStartingStory(null),
      },
    );
  };

  if (isLoading) {
    return (
      <div className="flex-1 p-8 overflow-y-auto">
        <div className="animate-pulse space-y-4">
          <div className="h-8 w-64 bg-muted rounded" />
          <div className="grid gap-4 md:grid-cols-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-24 bg-muted rounded" />
            ))}
          </div>
          <div className="h-64 bg-muted rounded" />
        </div>
      </div>
    );
  }

  const stats = data?.stats;

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <div className="flex justify-between items-center mb-2">
        <h1 className="text-3xl font-bold tracking-tight">Library Insights</h1>
        <Button onClick={handleRefresh} disabled={refresh.isPending} variant="secondary" className="gap-2">
          <RefreshCw className={`h-4 w-4 ${refresh.isPending ? "animate-spin" : ""}`} />
          {refresh.isPending ? "Queued..." : "Refresh Insights"}
        </Button>
      </div>
      <p className="text-sm text-muted-foreground mb-8">
        {data?.generated_at
          ? `AI analysis last generated ${new Date(data.generated_at).toLocaleString()}`
          : "AI analysis has not been generated yet — refresh to build it."}
        {refresh.isSuccess && " · Refresh queued, check the Processing Pipeline for progress."}
      </p>

      {stats && (
        <div className="grid gap-4 grid-cols-2 md:grid-cols-5 mb-8">
          <div className="border border-border bg-card rounded-md p-4">
            <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
              <Film className="h-3.5 w-3.5" /> Assets
            </div>
            <p className="text-2xl font-bold">{stats.total_assets}</p>
          </div>
          <div className="border border-border bg-card rounded-md p-4">
            <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
              <Clock className="h-3.5 w-3.5" /> Total Footage
            </div>
            <p className="text-2xl font-bold">{formatHours(stats.total_duration_seconds)}</p>
          </div>
          <div className="border border-border bg-card rounded-md p-4">
            <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
              <Users className="h-3.5 w-3.5" /> People
            </div>
            <p className="text-2xl font-bold">{stats.named_people_count}</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {stats.named_people_count} named · {stats.unidentified_people_count} unidentified
            </p>
          </div>
          <div className="border border-border bg-card rounded-md p-4">
            <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
              <Mic className="h-3.5 w-3.5" /> Speech Indexed
            </div>
            <p className="text-2xl font-bold">{formatHours(stats.speech_indexed_seconds)}</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              of {formatHours(stats.total_duration_seconds)} total
            </p>
          </div>
          <div className="border border-border bg-card rounded-md p-4">
            <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
              <Sparkles className="h-3.5 w-3.5" /> Transcribed
            </div>
            <p className="text-2xl font-bold">
              {stats.transcribed_assets}
              <span className="text-sm text-muted-foreground font-normal"> / {stats.total_assets}</span>
            </p>
          </div>
        </div>
      )}

      {data?.headline && (
        <div className="border border-primary/30 bg-primary/5 rounded-md p-5 mb-8">
          <div className="flex items-start gap-3">
            <Sparkles className="h-5 w-5 text-primary flex-shrink-0 mt-0.5" />
            <p className="text-base font-medium">{data.headline}</p>
          </div>
        </div>
      )}

      <div className="grid gap-8 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-8">
          {data?.opportunities?.length ? (
            <div>
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <Clapperboard className="h-4 w-4 text-primary" />
                Story Opportunities
              </h2>
              <div className="space-y-3">
                {data.opportunities.map((opp, i) => (
                  <div key={i} className="border border-primary/30 bg-card rounded-md p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold mb-1">{opp.title}</p>
                        <p className="text-sm text-muted-foreground">{opp.rationale}</p>
                        <p className="text-xs text-muted-foreground mt-2">
                          {opp.asset_ids.length} {opp.asset_ids.length === 1 ? "asset" : "assets"} ·{" "}
                          {formatHours(opp.total_duration_seconds)} of material
                          {opp.people.length > 0 && <> · {opp.people.map((p) => p.display_name).join(", ")}</>}
                        </p>
                      </div>
                      <Button
                        size="sm"
                        className="flex-shrink-0 gap-1.5"
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

          <div>
            <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <Lightbulb className="h-4 w-4 text-primary" />
              Key Findings
            </h2>
            {data?.insights?.length ? (
              <div className="space-y-3">
                {data.insights.map((item, i) => (
                  <div key={i} className="border border-border bg-card rounded-md p-4">
                    <p className="text-sm font-semibold mb-1">{item.title}</p>
                    <p className="text-sm text-muted-foreground">{item.detail}</p>
                    {(item.related_people?.length || item.related_topics?.length) ? (
                      <div className="flex flex-wrap gap-1.5 mt-3">
                        {item.related_people?.map((p, j) =>
                          p.person_id ? (
                            <Link key={`p-${j}`} href={personHref(p.person_id, p.display_name)}>
                              <Badge variant="secondary" className="text-xs cursor-pointer hover:bg-primary/20 gap-1">
                                <User className="h-3 w-3" />
                                {p.display_name}
                              </Badge>
                            </Link>
                          ) : (
                            <Badge key={`p-${j}`} variant="secondary" className="text-xs gap-1 opacity-70">
                              <User className="h-3 w-3" />
                              {p.display_name}
                            </Badge>
                          ),
                        )}
                        {item.related_topics?.map((t, j) => (
                          <Link key={`t-${j}`} href={topicHref(t.key, t.label)}>
                            <Badge variant="outline" className="text-xs cursor-pointer hover:border-primary">
                              {t.label}
                            </Badge>
                          </Link>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No AI findings yet. Refresh insights once media has been processed.
              </p>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <h2 className="text-lg font-semibold flex items-center gap-2">
                <TrendingUp className="h-4 w-4 text-primary" />
                Trending Now
              </h2>
              <Button
                size="sm"
                variant="ghost"
                className="gap-1.5 text-xs"
                disabled={refreshTrends.isPending}
                onClick={handleTrendsRefresh}
              >
                <RefreshCw className={`h-3.5 w-3.5 ${refreshTrends.isPending ? "animate-spin" : ""}`} />
                {refreshTrends.isPending ? "Queued..." : "Refresh"}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground mb-4">
              {trends?.fetched_at
                ? `External trend data fetched ${new Date(trends.fetched_at).toLocaleString()} · keywords only, nothing leaves the library`
                : "No trend data yet — refreshes automatically every 3 hours."}
            </p>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="border border-border bg-card rounded-md p-4">
                <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                  <Youtube className="h-4 w-4 text-red-500" />
                  Your Topics on YouTube
                </h3>
                {!trends?.youtube_configured ? (
                  <p className="text-sm text-muted-foreground">
                    Not configured — set YOUTUBE_API_KEY to search recent videos for your topics.
                  </p>
                ) : trends?.youtube?.length ? (
                  <div className="space-y-3">
                    {trends.youtube.slice(0, 8).map((v) => (
                      <div key={`${v.rank}-${v.title}`} className="text-sm">
                        <div className="flex items-start gap-2">
                          <span className="text-xs text-muted-foreground font-mono mt-0.5 flex-shrink-0 w-5">
                            #{v.rank}
                          </span>
                          <div className="flex-1 min-w-0">
                            {v.url ? (
                              <a
                                href={v.url}
                                target="_blank"
                                rel="noreferrer"
                                className="font-medium hover:text-primary inline-flex items-start gap-1"
                              >
                                <span className="line-clamp-2">{v.title}</span>
                                <ExternalLink className="h-3 w-3 flex-shrink-0 mt-1 text-muted-foreground" />
                              </a>
                            ) : (
                              <span className="font-medium line-clamp-2">{v.title}</span>
                            )}
                            <p className="text-xs text-muted-foreground mt-0.5">
                              {v.channel}
                              {v.views != null && <> · {formatViews(v.views)} views</>}
                            </p>
                            {v.matched_topics.length > 0 && (
                              <div className="flex flex-wrap gap-1.5 mt-1.5">
                                {v.matched_topics.map((t) => (
                                  <Link key={t.key} href={topicHref(t.key, t.topic)}>
                                    <Badge variant="outline" className="text-xs cursor-pointer hover:border-primary">
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

              <div className="border border-border bg-card rounded-md p-4">
                <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                  <Newspaper className="h-4 w-4 text-primary" />
                  Your Topics in the News
                </h3>
                {!trends?.web_configured ? (
                  <p className="text-sm text-muted-foreground">
                    Not configured — start the SearXNG container to track news momentum.
                  </p>
                ) : trends?.web?.length ? (
                  <div className="space-y-3">
                    {trends.web.slice(0, 8).map((w) => (
                      <div key={w.key} className="text-sm">
                        <div className="flex items-center justify-between gap-2">
                          <Link href={topicHref(w.key, w.topic)}>
                            <span className="font-medium cursor-pointer hover:text-primary">{w.topic}</span>
                          </Link>
                          <span className="text-xs text-muted-foreground flex-shrink-0">
                            {w.result_count} {w.result_count === 1 ? "story" : "stories"} this week ·{" "}
                            {w.asset_count} {w.asset_count === 1 ? "asset" : "assets"}
                          </span>
                        </div>
                        {w.headlines.length > 0 && w.headlines[0].url && (
                          <a
                            href={w.headlines[0].url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-xs text-muted-foreground hover:text-primary line-clamp-1 mt-0.5 inline-block"
                          >
                            {w.headlines[0].title}
                          </a>
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

        <div className="space-y-8">
          <div>
            <h2 className="text-lg font-semibold mb-4">Most Featured People</h2>
            {data?.top_people?.length ? (
              <div className="space-y-2">
                {data.top_people.slice(0, 6).map((p) => {
                  const isPlaceholder = PLACEHOLDER_NAME_RE.test(p.display_name);
                  const isRenaming = renamingId === p.person_id;
                  const inner = (
                    <div className="border border-border bg-card rounded-md p-3 flex items-center gap-3 cursor-pointer hover:border-primary transition-colors mb-2">
                      <div className="w-9 h-9 rounded-full bg-muted flex-shrink-0 overflow-hidden">
                        {p.thumbnail_url ? (
                          <img src={`/api/thumbnails/${p.thumbnail_url}`} alt={p.display_name} className="w-full h-full object-cover" />
                        ) : (
                          <div className="w-full h-full flex items-center justify-center">
                            <User className="h-4 w-4 text-muted-foreground/50" />
                          </div>
                        )}
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
                            className="h-7 text-sm"
                          />
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 w-7 p-0"
                            disabled={updatePerson.isPending || !renameValue.trim()}
                            onClick={() => saveRename(p.person_id)}
                          >
                            <Check className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 w-7 p-0"
                            onClick={() => setRenamingId(null)}
                          >
                            <X className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      ) : (
                        <>
                          <div className="flex-1 min-w-0">
                            <p className={`text-sm font-medium truncate ${isPlaceholder ? "text-muted-foreground italic" : ""}`}>
                              {p.display_name}
                            </p>
                            <p className="text-xs text-muted-foreground">
                              {p.asset_count} {p.asset_count === 1 ? "asset" : "assets"} · {formatHours(p.speaking_seconds)} speaking
                            </p>
                          </div>
                          {isPlaceholder && (
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-7 gap-1 text-xs flex-shrink-0"
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
              <p className="text-sm text-muted-foreground">No people identified yet.</p>
            )}
          </div>

          <div>
            <h2 className="text-lg font-semibold mb-4">Top Topics</h2>
            {data?.top_topics?.length ? (
              <div className="flex flex-wrap gap-2">
                {data.top_topics.map((t) => (
                  <Link key={t.key} href={topicHref(t.key, t.topic)}>
                    <Badge variant="outline" className="text-xs cursor-pointer hover:border-primary">
                      {t.topic}
                      <span className="ml-1.5 text-muted-foreground">{t.asset_count}</span>
                    </Badge>
                  </Link>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No topics extracted yet.</p>
            )}
          </div>

          {data?.coverage_gaps?.length ? (
            <div>
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <MapPinned className="h-4 w-4 text-primary" />
                Coverage Gaps
              </h2>
              <div className="space-y-2">
                {data.coverage_gaps.map((g) => (
                  <Link key={g.key} href={topicHref(g.key, g.label)}>
                    <div className="border border-border bg-card rounded-md px-3 py-2.5 flex items-center justify-between cursor-pointer hover:border-primary transition-colors mb-2">
                      <p className="text-sm font-medium">{g.label}</p>
                      <p className="text-xs text-muted-foreground">
                        {g.asset_count === 0 ? "no assets" : `${g.asset_count} ${g.asset_count === 1 ? "asset" : "assets"}`}
                      </p>
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
