import { useToast } from "@/hooks/use-toast";
import { useCanEdit } from "@/lib/auth";
import {
  getGetSocialChannelAnalysisQueryKey,
  useAnalyzeSocialChannel,
  useGetSocialChannelAnalysis,
  type SocialChannelOverview,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  CalendarDays,
  Eye,
  ExternalLink,
  History,
  Lightbulb,
  MessageCircle,
  PlaySquare,
  Sparkles,
  ThumbsUp,
  Users,
} from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * The generated client will gain these fields when the API schema is updated.
 * Keep this boundary deliberately runtime-checked so the page can consume a
 * v2 response while codegen is still catching up, without rendering legacy
 * estimates as if they were observations.
 */
type JsonRecord = Record<string, unknown>;

interface AnalysisMetricsV2 {
  subscriber_count: number | null;
  total_views: number | null;
  total_videos: number | null;
  sample_size: number | null;
  avg_views: number | null;
  median_views: number | null;
  avg_likes: number | null;
  avg_comments: number | null;
  engagement_rate: number | null;
  uploads_last_30d: number | null;
  uploads_per_week: number | null;
  recent_median_views: number | null;
  previous_median_views: number | null;
  performance_change_percent: number | null;
  subscriber_change: number | null;
  subscriber_change_percent: number | null;
  history_days: number | null;
  observed_at: string | null;
  sample_oldest_at: string | null;
  sample_newest_at: string | null;
}

interface TopVideoV2 {
  title: string;
  url: string | null;
  thumbnail: string | null;
  views: number | null;
  likes: number | null;
  comments: number | null;
  published_at: string | null;
}

interface AnalysisV2 {
  status: string;
  error: unknown;
  analyzed_at: string | null;
  analysis_version: number | null;
  metrics: AnalysisMetricsV2 | null;
  data_warnings: string[];
  summary: string | null;
  recommendations: string[];
  top_videos: TopVideoV2[];
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringOrNull(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function readNumber(record: JsonRecord, key: string): number | null {
  return numberOrNull(record[key]);
}

function readString(record: JsonRecord, key: string): string | null {
  return stringOrNull(record[key]);
}

function readStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

function readMetrics(value: unknown): AnalysisMetricsV2 | null {
  if (!isRecord(value)) return null;
  return {
    subscriber_count: readNumber(value, "subscriber_count"),
    total_views: readNumber(value, "total_views"),
    total_videos: readNumber(value, "total_videos"),
    sample_size: readNumber(value, "sample_size"),
    avg_views: readNumber(value, "avg_views"),
    median_views: readNumber(value, "median_views"),
    avg_likes: readNumber(value, "avg_likes"),
    avg_comments: readNumber(value, "avg_comments"),
    engagement_rate: readNumber(value, "engagement_rate"),
    uploads_last_30d: readNumber(value, "uploads_last_30d"),
    uploads_per_week: readNumber(value, "uploads_per_week"),
    recent_median_views: readNumber(value, "recent_median_views"),
    previous_median_views: readNumber(value, "previous_median_views"),
    performance_change_percent: readNumber(value, "performance_change_percent"),
    subscriber_change: readNumber(value, "subscriber_change"),
    subscriber_change_percent: readNumber(value, "subscriber_change_percent"),
    history_days: readNumber(value, "history_days"),
    observed_at: readString(value, "observed_at"),
    sample_oldest_at: readString(value, "sample_oldest_at"),
    sample_newest_at: readString(value, "sample_newest_at"),
  };
}

function readTopVideos(value: unknown): TopVideoV2[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): TopVideoV2[] => {
    if (!isRecord(item)) return [];
    const title = readString(item, "title");
    if (!title) return [];
    return [{
      title,
      url: readString(item, "url") ?? readString(item, "link"),
      thumbnail: readString(item, "thumbnail") ?? readString(item, "thumbnail_url"),
      views: readNumber(item, "views"),
      likes: readNumber(item, "likes"),
      comments: readNumber(item, "comments"),
      published_at: readString(item, "published_at") ?? readString(item, "publishedAt"),
    }];
  });
}

function readAiInsights(value: JsonRecord): { summary: string | null; recommendations: string[] } {
  const nested = isRecord(value.aiInsights)
    ? value.aiInsights
    : isRecord(value.ai_insights)
      ? value.ai_insights
      : null;
  const summary = nested
    ? readString(nested, "summary")
    : readString(value, "ai_summary");
  const recommendations = nested
    ? readStringList(nested.recommendations)
    : readStringList(value.ai_recommendations);
  return { summary, recommendations };
}

function parseAnalysis(value: unknown): AnalysisV2 | null {
  if (!isRecord(value)) return null;
  const ai = readAiInsights(value);
  return {
    status: readString(value, "status") ?? "",
    error: value.error,
    analyzed_at: readString(value, "analyzed_at"),
    analysis_version: readNumber(value, "analysis_version"),
    metrics: readMetrics(value.analysis_metrics ?? value.metrics),
    data_warnings: readStringList(value.data_warnings ?? value.dataWarnings),
    summary: ai.summary,
    recommendations: ai.recommendations,
    top_videos: readTopVideos(value.top_videos ?? value.topVideos),
  };
}

function errorStatus(error: unknown): number | null {
  if (!isRecord(error)) return null;
  if (typeof error.status === "number") return error.status;
  if (isRecord(error.response) && typeof error.response.status === "number") return error.response.status;
  if (isRecord(error.data) && typeof error.data.status === "number") return error.data.status;
  return null;
}

function errorMessage(error: unknown): string | null {
  if (typeof error === "string" && error.trim()) return error;
  if (!isRecord(error)) return null;
  for (const key of ["message", "detail", "error"]) {
    const value = error[key];
    if (typeof value === "string" && value.trim()) return value;
    if (isRecord(value)) {
      const nested = errorMessage(value);
      if (nested) return nested;
    }
  }
  return null;
}

function formatCount(value: number | null): string {
  if (value == null) return "Unavailable";
  return new Intl.NumberFormat("en", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function formatExactCount(value: number | null): string {
  if (value == null) return "Unavailable";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

function formatPercent(value: number | null): string {
  return value == null ? "Unavailable" : `${value.toFixed(2)}%`;
}

function formatDate(value: string | null): string {
  if (!value) return "Unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Unavailable"
    : date.toLocaleDateString("en", { month: "short", day: "numeric", year: "numeric" });
}

function formatDateCoverage(oldest: string | null, newest: string | null): string {
  if (!oldest && !newest) return "Unavailable";
  if (oldest && newest && oldest !== newest) return `${formatDate(oldest)} – ${formatDate(newest)}`;
  return formatDate(oldest ?? newest);
}

function isValidNonNegative(value: number | null): value is number {
  return value != null && Number.isFinite(value) && value >= 0;
}

function MetricTile({
  label,
  value,
  detail,
  icon: Icon,
}: {
  label: string;
  value: string;
  detail?: string;
  icon: typeof Activity;
}) {
  return (
    <div className="min-w-0 rounded-xl border border-border/60 bg-background p-4 shadow-sm">
      <div className="mb-2 flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-muted-foreground">
        <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span>{label}</span>
      </div>
      <div className="truncate text-xl font-bold tabular-nums tracking-tight">{value}</div>
      {detail && <div className="mt-1 text-xs text-muted-foreground">{detail}</div>}
    </div>
  );
}

function LegacyNotice({ canEdit }: { canEdit: boolean }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-amber-400/25 bg-amber-400/10 p-4 text-sm text-amber-200">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <p className="leading-relaxed">
        This is a legacy analysis (version 1). {canEdit
          ? "Re-analyze this channel to replace it with measured public-data results."
          : "An editor can re-analyze this channel to replace it with measured public-data results."}
      </p>
    </div>
  );
}

/** Grounded v2 public-data analysis for YouTube channels. */
export function ChannelAnalysis({ channel }: { channel: SocialChannelOverview }) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const canEdit = useCanEdit();
  const analysisKey = getGetSocialChannelAnalysisQueryKey(channel.id);
  const {
    data: analysisResponse,
    error: analysisQueryError,
    isError: isAnalysisQueryError,
    isFetched,
  } = useGetSocialChannelAnalysis(channel.id, {
    query: {
      queryKey: analysisKey,
      retry: false,
      refetchOnWindowFocus: false,
      refetchInterval: (query) => (parseAnalysis(query.state.data)?.status === "running" ? 5000 : false),
    },
  });
  const analyze = useAnalyzeSocialChannel({
    mutation: {
      onSuccess: (data) => queryClient.setQueryData(analysisKey, data),
      onError: (error: unknown) =>
        toast({
          title: "Could not start analysis",
          description: errorMessage(error) ?? "The analysis request failed.",
          variant: "destructive",
        }),
    },
  });

  const analysis = parseAnalysis(analysisResponse);
  const status = analysis?.status;
  const running = status === "running" || analyze.isPending;
  const ready = status === "ready" ? analysis : null;
  const isV2 = ready?.analysis_version === 2;
  const notFound = errorStatus(analysisQueryError) === 404;
  const malformedResponse = isFetched && !isAnalysisQueryError
    ? analysisResponse == null
      ? "Analysis response was empty."
      : !isRecord(analysisResponse) || !["running", "ready", "error"].includes(readString(analysisResponse, "status") ?? "")
        ? "Analysis response was malformed."
        : null
    : null;
  const queryError = isAnalysisQueryError && !notFound
    ? errorMessage(analysisQueryError) ?? "Could not load channel analysis."
    : malformedResponse;
  const mutationError = analyze.error
    ? errorMessage(analyze.error) ?? "The analysis request failed."
    : null;
  const visibleRequestError = queryError ?? mutationError;
  const statusError = status === "error"
    ? errorMessage(analysis?.error) ?? "Analysis failed — try again."
    : null;
  const resultError = ready?.error ? errorMessage(ready.error) ?? "Analysis failed — try again." : null;

  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
      <div className="flex flex-col gap-4 border-b border-border bg-muted/10 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <span className="flex items-center gap-2 text-lg font-bold tracking-tight">
          <Sparkles className="h-5 w-5 text-primary" aria-hidden="true" />
          Channel Analysis
          {ready?.analyzed_at && (
            <span className="ml-1 text-xs font-normal tracking-normal text-muted-foreground">
              · {formatDate(ready.analyzed_at)}
            </span>
          )}
        </span>
        {canEdit && (
          <Button
            size="sm"
            variant="outline"
            className="h-8 w-full rounded-lg sm:w-auto"
            disabled={running}
            onClick={() => analyze.mutate({ channelId: channel.id })}
            data-testid={`button-analyze-${channel.id}`}
          >
            <Sparkles className={`mr-1.5 h-3.5 w-3.5 text-primary ${running ? "animate-pulse" : ""}`} aria-hidden="true" />
            {running ? "Analyzing…" : ready ? "Re-analyze" : "Analyze"}
          </Button>
        )}
      </div>

      <div className="space-y-6 p-4 sm:p-6">
        {visibleRequestError && (
          <p className="flex items-start gap-2 text-sm font-medium text-red-400" role="alert">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            {visibleRequestError}
          </p>
        )}
        {(statusError || resultError) && (
          <p className="flex items-start gap-2 text-sm font-medium text-red-400" role="alert">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            {statusError ?? resultError}
          </p>
        )}
        {running && (
          <p className="text-sm font-medium text-muted-foreground">
            Analysis in progress — measured public-data results will appear when complete.
          </p>
        )}
        {!analysis && !running && !visibleRequestError && !statusError && !resultError && (
          <p className="text-sm font-medium text-muted-foreground">
            No analysis yet{canEdit ? " — run one to see measured channel observations." : "."}
          </p>
        )}

        {ready && !running && !isV2 && <LegacyNotice canEdit={canEdit} />}

        {ready && !running && isV2 && (
          <>
            {ready.metrics ? (
              <section aria-labelledby={`measured-metrics-${channel.id}`} className="space-y-4">
                <div className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-primary" aria-hidden="true" />
                  <h3 id={`measured-metrics-${channel.id}`} className="text-[11px] font-bold uppercase tracking-widest text-muted-foreground">
                    Measured public metrics
                  </h3>
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <MetricTile label="Sample average views" value={formatCount(ready.metrics.avg_views)} icon={Eye} />
                  <MetricTile label="Sample median views" value={formatCount(ready.metrics.median_views)} icon={Eye} />
                  <MetricTile
                    label="Engagement rate"
                    value={formatPercent(ready.metrics.engagement_rate)}
                    detail={ready.metrics.engagement_rate == null ? "Unavailable from public data" : undefined}
                    icon={Activity}
                  />
                  <MetricTile label="Sample average likes" value={formatCount(ready.metrics.avg_likes)} icon={ThumbsUp} />
                  <MetricTile label="Sample average comments" value={formatCount(ready.metrics.avg_comments)} icon={MessageCircle} />
                  <MetricTile
                    label="Sample size"
                    value={formatExactCount(ready.metrics.sample_size)}
                    detail="uploads in this sample"
                    icon={PlaySquare}
                  />
                  <MetricTile label="Subscribers" value={formatCount(ready.metrics.subscriber_count)} icon={Users} />
                  <MetricTile label="Channel total views" value={formatCount(ready.metrics.total_views)} detail="cumulative, not monthly" icon={Eye} />
                  <MetricTile label="Total videos" value={formatExactCount(ready.metrics.total_videos)} icon={PlaySquare} />
                  <MetricTile
                    label="Sample date coverage"
                    value={formatDateCoverage(ready.metrics.sample_oldest_at, ready.metrics.sample_newest_at)}
                    icon={CalendarDays}
                  />
                  {isValidNonNegative(ready.metrics.uploads_per_week) && (
                    <MetricTile label="Upload cadence" value={`${ready.metrics.uploads_per_week.toFixed(1)} / week`} icon={CalendarDays} />
                  )}
                  {isValidNonNegative(ready.metrics.uploads_last_30d) && (
                    <MetricTile label="Uploads in last 30 days" value={formatExactCount(ready.metrics.uploads_last_30d)} icon={CalendarDays} />
                  )}
                  {ready.metrics.subscriber_change != null && (
                    <MetricTile
                      label="Observed subscriber delta"
                      value={`${ready.metrics.subscriber_change > 0 ? "+" : ""}${formatExactCount(ready.metrics.subscriber_change)}`}
                      detail={ready.metrics.subscriber_change_percent == null
                        ? undefined
                        : `${ready.metrics.subscriber_change_percent > 0 ? "+" : ""}${ready.metrics.subscriber_change_percent.toFixed(2)}% observed`}
                      icon={Users}
                    />
                  )}
                  {ready.metrics.history_days != null && (
                    <MetricTile label="Subscriber history" value={`${formatExactCount(ready.metrics.history_days)} days`} icon={History} />
                  )}
                </div>
              </section>
            ) : (
              <p className="text-sm font-medium text-muted-foreground">
                No measured metrics are available for this analysis.
              </p>
            )}

            <div className="rounded-xl border border-border/60 bg-muted/15 p-4 text-sm text-muted-foreground">
              <p className="font-semibold text-foreground">Public-data limits</p>
              <p className="mt-1 leading-relaxed">
                This report uses sampled public YouTube uploads and dated public observations. CTR, retention, watch time, and revenue require private YouTube Analytics access and are unavailable here.
              </p>
            </div>

            {ready.data_warnings.length > 0 && (
              <section aria-labelledby={`data-warnings-${channel.id}`} className="rounded-xl border border-amber-400/25 bg-amber-400/10 p-4">
                <h3 id={`data-warnings-${channel.id}`} className="flex items-center gap-2 text-sm font-semibold text-amber-200">
                  <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
                  Data notes
                </h3>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-relaxed text-amber-100/90">
                  {ready.data_warnings.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}
                </ul>
              </section>
            )}

            {(ready.summary || ready.recommendations.length > 0) && (
              <section className="space-y-4 rounded-xl border border-border/60 bg-muted/15 p-4 sm:p-5">
                {ready.summary && (
                  <div>
                    <h3 className="mb-2 flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-primary">
                      <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                      Grounded summary
                    </h3>
                    <p className="text-sm leading-relaxed text-foreground/90">{ready.summary}</p>
                  </div>
                )}
                {ready.recommendations.length > 0 && (
                  <div>
                    <h3 className="mb-2 flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-primary">
                      <Lightbulb className="h-3.5 w-3.5" aria-hidden="true" />
                      Recommendations
                    </h3>
                    <ul className="space-y-2 text-sm text-foreground/90">
                      {ready.recommendations.map((recommendation, index) => (
                        <li key={`${recommendation}-${index}`} className="flex gap-3 leading-relaxed">
                          <span className="mt-0.5 shrink-0 text-[10px] text-primary" aria-hidden="true">❖</span>
                          <span>{recommendation}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </section>
            )}

            {ready.top_videos.length > 0 && (
              <section aria-labelledby={`top-videos-${channel.id}`} className="space-y-4">
                <div className="flex items-center gap-2">
                  <PlaySquare className="h-4 w-4 text-primary" aria-hidden="true" />
                  <h3 id={`top-videos-${channel.id}`} className="text-[11px] font-bold uppercase tracking-widest text-muted-foreground">
                    Top videos within sample
                  </h3>
                </div>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  {ready.top_videos.map((video, index) => (
                    <div
                      key={`${video.title}-${index}`}
                      className="group relative flex min-w-0 items-center gap-3 rounded-xl border border-border/60 bg-background p-3 transition-all hover:border-primary/50 hover:shadow-lg"
                      data-testid={`row-top-video-${channel.id}-${index}`}
                    >
                      {video.thumbnail ? (
                        <div className="relative h-16 w-28 shrink-0 overflow-hidden rounded-lg border border-border">
                          <img
                            src={video.thumbnail}
                            alt={`${video.title} thumbnail`}
                            className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105"
                            loading="lazy"
                          />
                          <div className="absolute bottom-1.5 left-2 text-[10px] font-bold tracking-wider text-white">#{index + 1}</div>
                        </div>
                      ) : (
                        <div className="flex h-16 w-28 shrink-0 items-center justify-center rounded-lg border border-border bg-muted font-bold text-muted-foreground">
                          #{index + 1}
                        </div>
                      )}
                      <div className="min-w-0 flex-1 pr-2">
                        <div className="truncate text-sm font-semibold transition-colors group-hover:text-primary">
                          {video.url && /^https?:\/\//.test(video.url) ? (
                            <a href={video.url} target="_blank" rel="noreferrer" className="before:absolute before:inset-0">
                              {video.title}
                            </a>
                          ) : video.title}
                        </div>
                        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs font-bold tabular-nums text-muted-foreground">
                          <span className="flex items-center gap-1.5"><Eye className="h-3.5 w-3.5" aria-hidden="true" />{formatCount(video.views)}</span>
                          {video.likes != null && <span className="flex items-center gap-1.5"><ThumbsUp className="h-3.5 w-3.5" aria-hidden="true" />{formatCount(video.likes)}</span>}
                          {video.comments != null && <span className="flex items-center gap-1.5"><MessageCircle className="h-3.5 w-3.5" aria-hidden="true" />{formatCount(video.comments)}</span>}
                          {video.published_at && <span>{formatDate(video.published_at)}</span>}
                        </div>
                      </div>
                      {video.url && /^https?:\/\//.test(video.url) && (
                        <ExternalLink className="absolute right-3 top-3 h-3.5 w-3.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
                      )}
                    </div>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}