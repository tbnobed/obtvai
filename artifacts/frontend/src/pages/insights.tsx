import {
  useGetLibraryInsights,
  getGetLibraryInsightsQueryKey,
  useRefreshLibraryInsights,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "wouter";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Sparkles, RefreshCw, User, Film, Clock, Users, Mic, Lightbulb } from "lucide-react";

function formatHours(seconds: number) {
  const h = seconds / 3600;
  if (h >= 1) return `${h.toFixed(1)}h`;
  return `${Math.floor(seconds / 60)}m`;
}

export default function Insights() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useGetLibraryInsights({
    query: { queryKey: getGetLibraryInsightsQueryKey() },
  });
  const refresh = useRefreshLibraryInsights();

  const handleRefresh = () => {
    refresh.mutate(undefined as never, {
      onSuccess: () => {
        setTimeout(() => {
          queryClient.invalidateQueries({ queryKey: getGetLibraryInsightsQueryKey() });
        }, 8000);
      },
    });
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
            <p className="text-2xl font-bold">{stats.total_people}</p>
          </div>
          <div className="border border-border bg-card rounded-md p-4">
            <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
              <Mic className="h-3.5 w-3.5" /> Speech Indexed
            </div>
            <p className="text-2xl font-bold">{formatHours(stats.total_speaking_seconds)}</p>
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
        <div className="lg:col-span-2">
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
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              No AI findings yet. Refresh insights once media has been processed.
            </p>
          )}
        </div>

        <div className="space-y-8">
          <div>
            <h2 className="text-lg font-semibold mb-4">Most Featured People</h2>
            {data?.top_people?.length ? (
              <div className="space-y-2">
                {data.top_people.slice(0, 6).map((p) => (
                  <Link key={p.person_id} href={`/people/${p.person_id}`}>
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
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{p.display_name}</p>
                        <p className="text-xs text-muted-foreground">
                          {p.asset_count} {p.asset_count === 1 ? "asset" : "assets"} · {formatHours(p.speaking_seconds)} speaking
                        </p>
                      </div>
                    </div>
                  </Link>
                ))}
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
                  <Badge key={t.topic} variant="outline" className="text-xs">
                    {t.topic}
                    <span className="ml-1.5 text-muted-foreground">{t.asset_count}</span>
                  </Badge>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No topics extracted yet.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
