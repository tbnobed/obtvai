import { useEffect, useRef, useState } from "react";
import {
  useGetSocialsOverview,
  getGetSocialsOverviewQueryKey,
  useGetSocialChannelHistory,
  useListSocialChannelPosts,
  useCreateSocialProgram,
  useUpdateSocialProgram,
  useDeleteSocialProgram,
  useCreateSocialChannel,
  useUpdateSocialChannel,
  useDeleteSocialChannel,
  useRefreshSocials,
  useGenerateSocialsInsights,
  useGetSocialsInsights,
  getGetSocialsInsightsQueryKey,
  useListJobs,
  getListJobsQueryKey,
  useAnalyzeSocialChannel,
  useGetSocialChannelAnalysis,
  getGetSocialChannelAnalysisQueryKey,
  type SocialChannelOverview,
  type SocialChannelInputPlatform,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Share2,
  RefreshCw,
  Plus,
  Pencil,
  Trash2,
  ExternalLink,
  TrendingUp,
  TrendingDown,
  Youtube,
  Instagram,
  Facebook,
  Music2,
  AlertTriangle,
  Eye,
  Sparkles,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  XCircle,
  Lightbulb,
  Activity,
  BadgeDollarSign
} from "lucide-react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip as ChartTooltip,
  CartesianGrid,
} from "recharts";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";
import { useCanEdit } from "@/lib/auth";

const PLATFORM_META: Record<string, { label: string; icon: typeof Youtube; color: string }> = {
  youtube: { label: "YouTube", icon: Youtube, color: "text-red-500" },
  instagram: { label: "Instagram", icon: Instagram, color: "text-pink-500" },
  facebook: { label: "Facebook", icon: Facebook, color: "text-blue-500" },
  tiktok: { label: "TikTok", icon: Music2, color: "text-teal-400" },
};

function fmt(v: number | null | undefined): string {
  if (v == null) return "—";
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(v);
}

function money(v: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(v);
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

function Donut({ frac, children, className = "h-12 w-12" }: { frac: number; children?: React.ReactNode; className?: string }) {
  const r = 26;
  const c = 2 * Math.PI * r;
  const clamped = Math.min(1, Math.max(0, frac));
  return (
    <div className={`relative flex-shrink-0 ${className}`}>
      <svg viewBox="0 0 64 64" className="h-full w-full -rotate-90">
        <circle cx="32" cy="32" r={r} fill="none" strokeWidth="6" className="stroke-muted" />
        <circle
          cx="32" cy="32" r={r} fill="none" strokeWidth="6" strokeLinecap="round"
          stroke="currentColor"
          className="transition-[stroke-dasharray] duration-1000 ease-out"
          strokeDasharray={`${c * clamped} ${c}`}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center font-bold tracking-tight">
        {children}
      </div>
    </div>
  );
}

function Delta({ now, before }: { now?: number | null; before?: number | null }) {
  if (now == null || before == null || before === 0) return null;
  const diff = now - before;
  if (diff === 0) return <span className="text-xs text-muted-foreground font-medium">±0 this week</span>;
  const pct = (diff / before) * 100;
  const up = diff > 0;
  const Icon = up ? TrendingUp : TrendingDown;
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-semibold tracking-wide ${up ? "text-emerald-400" : "text-red-400"}`}>
      <Icon className="w-3.5 h-3.5" />
      {up ? "+" : ""}{fmt(diff)} ({pct.toFixed(1)}%) this week
    </span>
  );
}

const RISK_STYLE: Record<string, string> = {
  low: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  medium: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  high: "bg-red-500/15 text-red-400 border-red-500/30",
  unknown: "bg-muted text-muted-foreground border-border",
};

function ProjectionCard({ label, value, growthPct }: { label: string, value?: number | null, growthPct?: number | null }) {
  const anim = useCountUp(value ?? 0);
  return (
    <div className="border border-border/50 rounded-xl p-5 bg-background shadow-sm flex flex-col justify-center">
      <div className="text-[11px] text-muted-foreground mb-1 font-bold tracking-widest uppercase">{label}</div>
      <div className="text-3xl font-bold tabular-nums tracking-tight">{fmt(anim)}</div>
      {growthPct != null && (
        <div className={`mt-2 text-xs inline-flex items-center gap-1.5 font-bold tracking-wide ${growthPct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
          {growthPct >= 0 ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
          {growthPct >= 0 ? "+" : ""}{growthPct.toFixed(1)}% vs today
        </div>
      )}
    </div>
  );
}

/** n8n analyze-channel panel — YouTube channels only. */
function ChannelAnalysis({ channel }: { channel: SocialChannelOverview }) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const canEdit = useCanEdit();
  const analysisKey = getGetSocialChannelAnalysisQueryKey(channel.id);

  const { data: analysis } = useGetSocialChannelAnalysis(channel.id, {
    query: {
      queryKey: analysisKey,
      retry: false,
      refetchOnWindowFocus: false,
      refetchInterval: (q) => (q.state.data?.status === "running" ? 5000 : false),
    },
  });
  const analyze = useAnalyzeSocialChannel({
    mutation: {
      onSuccess: (data) => queryClient.setQueryData(analysisKey, data),
      onError: (e: any) =>
        toast({ title: "Could not start analysis", description: e?.data?.detail, variant: "destructive" }),
    },
  });

  const running = analysis?.status === "running" || analyze.isPending;
  const ready = analysis?.status === "ready" ? analysis : null;
  const currentFollowers = channel.latest?.followers ?? null;
  const growthPct =
    ready?.subs12 != null && currentFollowers ? ((ready.subs12 - currentFollowers) / currentFollowers) * 100 : null;

  return (
    <div className="bg-card rounded-2xl border border-border overflow-hidden shadow-sm">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between px-6 py-4 border-b border-border bg-muted/10 gap-4">
        <span className="text-lg font-bold flex items-center gap-2 tracking-tight">
          <Sparkles className="w-5 h-5 text-primary" /> Channel Analysis
          {ready && (
            <span className="text-xs font-normal text-muted-foreground tracking-normal ml-2">
              · {new Date(ready.analyzed_at).toLocaleString()}
            </span>
          )}
        </span>
        <div className="flex items-center gap-3">
          {ready && (
            <Badge variant="outline" className={`px-2.5 py-0.5 rounded-full uppercase tracking-widest text-[10px] font-bold ${RISK_STYLE[ready.risk_level] ?? RISK_STYLE.unknown}`} data-testid={`badge-risk-${channel.id}`}>
              {ready.risk_level === "unknown" ? "risk unknown" : `${ready.risk_level} risk`}
            </Badge>
          )}
          {canEdit && (
            <Button size="sm" variant="outline" className="h-8 rounded-lg" disabled={running} onClick={() => analyze.mutate({ channelId: channel.id })} data-testid={`button-analyze-${channel.id}`}>
              <Sparkles className={`w-3.5 h-3.5 mr-1.5 text-primary ${running ? "animate-pulse" : ""}`} />
              {running ? "Analyzing…" : ready ? "Re-analyze" : "Analyze"}
            </Button>
          )}
        </div>
      </div>

      <div className="p-6">
        {analysis?.status === "error" && (
          <p className="text-sm text-red-400 flex items-start gap-2 font-medium">
            <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" /> {analysis.error ?? "Analysis failed — try again."}
          </p>
        )}
        {running && (
          <p className="text-sm text-muted-foreground font-medium">
            Analyzing this channel — projections, profitability and risk will appear here in a minute or two.
          </p>
        )}
        {!analysis && !running && (
          <p className="text-sm text-muted-foreground font-medium">
            No analysis yet{canEdit ? " — run one to get growth projections, AI insights, profitability and risk." : "."}
          </p>
        )}

        {ready && !running && (
          <>
            <div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <ProjectionCard label="3 Months" value={ready.subs3 ?? 0} />
                <ProjectionCard label="6 Months" value={ready.subs6 ?? 0} />
                <ProjectionCard label="12 Months" value={ready.subs12 ?? 0} growthPct={growthPct} />
              </div>
            </div>

            {ready.ai_sections.length > 0 ? (
              <div className="grid gap-4 md:grid-cols-2 mt-8">
                {ready.ai_sections.map((s, i) => (
                  <div key={i} className="bg-muted/20 rounded-xl p-5 border border-border/50" data-testid={`section-analysis-${channel.id}-${i}`}>
                    {s.title && (
                      <div className="text-[11px] font-bold text-primary uppercase tracking-widest mb-3 flex items-center gap-2">
                        <Sparkles className="w-3.5 h-3.5" /> {s.title}
                      </div>
                    )}
                    {s.body && <p className="text-sm text-foreground/90 leading-relaxed mb-4">{s.body}</p>}
                    {s.bullets.length > 0 && (
                      <ul className="space-y-2.5 text-sm text-foreground/80">
                        {s.bullets.map((b, j) => {
                          const ci = b.indexOf(": ");
                          const label = ci > 0 && ci < 60 ? b.slice(0, ci) : null;
                          return (
                            <li key={j} className="flex gap-3">
                              <span className="text-primary mt-0.5 shrink-0 text-[10px]">❖</span>
                              <span className="leading-relaxed">
                                {label ? (
                                  <>
                                    <span className="font-semibold text-foreground">{label}:</span>
                                    {b.slice(ci + 1)}
                                  </>
                                ) : (
                                  b
                                )}
                              </span>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              (ready.ai_summary || ready.ai_recommendations.length > 0) && (
                <div className="space-y-4 mt-8 bg-muted/20 rounded-xl p-6 border border-border/50">
                  {ready.ai_summary && <p className="text-sm text-foreground/90 leading-relaxed">{ready.ai_summary}</p>}
                  {ready.ai_recommendations.length > 0 && (
                    <ul className="space-y-3 text-sm text-foreground/90">
                      {ready.ai_recommendations.map((r, i) => (
                        <li key={i} className="flex gap-3">
                          <Lightbulb className="w-4 h-4 mt-0.5 shrink-0 text-amber-400" />
                          <span className="leading-relaxed">{r}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )
            )}

            {(ready.avg_views != null || ready.engagement_rate != null) && (
              <div className="space-y-4 mt-8">
                <div className="text-[11px] font-bold tracking-widest uppercase text-muted-foreground flex items-center gap-2">
                  <Activity className="w-4 h-4" /> Last 10 uploads (avg)
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  {([
                    ["Views", ready.avg_views, (v: number) => fmt(Math.round(v))],
                    ["Likes", ready.avg_likes, (v: number) => fmt(Math.round(v))],
                    ["Comments", ready.avg_comments, (v: number) => fmt(Math.round(v))],
                    ["Engagement", ready.engagement_rate, (v: number) => `${v.toFixed(2)}%`],
                  ] as const).map(([label, v, f]) => (
                    <div key={label} className="border border-border/50 rounded-xl p-4 bg-background shadow-sm">
                      <div className="text-[11px] font-bold text-muted-foreground uppercase tracking-widest mb-1">{label}</div>
                      <div className="text-xl font-bold tabular-nums">{v != null ? f(v) : "—"}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {ready.top_videos.length > 0 && (
              <div className="space-y-4 mt-8">
                <div className="text-[11px] font-bold tracking-widest uppercase text-muted-foreground flex items-center gap-2">
                  <TrendingUp className="w-4 h-4 text-primary" /> Top performing content
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {ready.top_videos.map((v, i) => (
                    <div key={i} className="group relative flex items-center gap-4 border border-border/50 rounded-xl p-3 bg-background hover:border-primary/50 hover:shadow-lg transition-all" data-testid={`row-top-video-${channel.id}-${i}`}>
                      {v.thumbnail ? (
                        <div className="relative h-16 w-28 shrink-0 rounded-lg overflow-hidden border border-border">
                          <img src={v.thumbnail} alt="" className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105" loading="lazy" />
                          <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/20 to-transparent" />
                          <div className="absolute bottom-1.5 left-2 text-[10px] font-bold text-white tabular-nums tracking-wider">#{i + 1}</div>
                        </div>
                      ) : (
                        <div className="h-16 w-28 shrink-0 rounded-lg bg-muted flex items-center justify-center border border-border text-muted-foreground font-bold">
                          #{i + 1}
                        </div>
                      )}
                      <div className="flex-1 min-w-0 pr-2">
                        <div className="truncate text-sm font-semibold group-hover:text-primary transition-colors">
                          {v.url && /^https?:\/\//.test(v.url) ? (
                            <a href={v.url} target="_blank" rel="noreferrer" className="before:absolute before:inset-0">{v.title}</a>
                          ) : (
                            v.title
                          )}
                        </div>
                        <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground tabular-nums font-bold">
                          {v.views != null && <span className="flex items-center gap-1.5"><Eye className="w-3.5 h-3.5" />{fmt(v.views)}</span>}
                          {v.likes != null && <span className="flex items-center gap-1.5"><TrendingUp className="w-3.5 h-3.5" />{fmt(v.likes)}</span>}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="space-y-4 mt-8 pt-8 border-t border-border">
              <div className="text-[11px] font-bold tracking-widest uppercase text-muted-foreground flex items-center gap-2">
                <BadgeDollarSign className="w-4 h-4" /> Profitability
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Card className="bg-background shadow-sm border-border/50">
                  <CardContent className="p-5 flex items-center gap-5">
                    <div className="relative h-14 w-14 flex-shrink-0 flex items-center justify-center rounded-full bg-emerald-500/10 text-emerald-500">
                      <TrendingUp className="h-6 w-6" />
                    </div>
                    <div>
                      <div className="text-2xl font-bold tabular-nums tracking-tight">{money(ready.est_monthly_revenue)}</div>
                      <p className="text-[11px] font-bold text-muted-foreground mt-1 uppercase tracking-widest">Est. Revenue</p>
                    </div>
                  </CardContent>
                </Card>

                <Card className="bg-background shadow-sm border-border/50">
                  <CardContent className="p-5 flex items-center gap-5">
                    <Donut frac={ready.margin_percent / 100} className="h-14 w-14 text-primary">
                      <span className="text-[11px]">{ready.margin_percent.toFixed(0)}%</span>
                    </Donut>
                    <div>
                      <div className="text-xl font-bold leading-tight">Margin</div>
                      <p className="text-[11px] font-bold text-muted-foreground mt-1 uppercase tracking-widest">Profitability</p>
                    </div>
                  </CardContent>
                </Card>

                <Card className="bg-background shadow-sm border-border/50">
                  <CardContent className="p-5 flex items-center gap-5">
                    <Donut frac={ready.mcn_share_percent / 100} className="h-14 w-14 text-primary">
                      <span className="text-[11px]">{ready.mcn_share_percent}%</span>
                    </Donut>
                    <div>
                      <div className="text-xl font-bold leading-tight">MCN Share</div>
                      <p className="text-[11px] font-bold text-muted-foreground mt-1 uppercase tracking-widest">Network Cut</p>
                    </div>
                  </CardContent>
                </Card>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

type PostSortKey = "views" | "likes" | "comments" | "published_at";

function ChannelDetail({ channel }: { channel: SocialChannelOverview }) {
  const { data: history } = useGetSocialChannelHistory(channel.id, { days: 90 });
  const { data: posts } = useListSocialChannelPosts(channel.id, { limit: 50 });
  const meta = PLATFORM_META[channel.platform] ?? PLATFORM_META.youtube;
  const [sortKey, setSortKey] = useState<PostSortKey>("published_at");
  const [sortDesc, setSortDesc] = useState(true);

  const toggleSort = (key: PostSortKey) => {
    if (key === sortKey) setSortDesc((d) => !d);
    else { setSortKey(key); setSortDesc(true); }
  };

  const sortedPosts = [...(posts ?? [])].sort((a, b) => {
    const va = sortKey === "published_at"
      ? (a.published_at ? new Date(a.published_at).getTime() : -Infinity)
      : (a[sortKey] ?? -Infinity);
    const vb = sortKey === "published_at"
      ? (b.published_at ? new Date(b.published_at).getTime() : -Infinity)
      : (b[sortKey] ?? -Infinity);
    return sortDesc ? (vb as number) - (va as number) : (va as number) - (vb as number);
  });

  const SortHeader = ({ label, k, className }: { label: string; k: PostSortKey; className?: string }) => (
    <th className={`font-bold tracking-wide px-5 py-3 ${className ?? ""}`}>
      <button
        type="button"
        onClick={() => toggleSort(k)}
        className={`inline-flex items-center gap-1 hover:text-foreground transition-colors ${sortKey === k ? "text-foreground" : ""}`}
        data-testid={`sort-posts-${k}`}
      >
        {label}
        {sortKey === k && (sortDesc ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />)}
      </button>
    </th>
  );

  const chartData = (history ?? []).map((s) => ({
    date: new Date(s.fetched_at).toLocaleDateString("en", { month: "short", day: "numeric" }),
    followers: s.followers ?? 0,
  }));

  return (
    <div className="space-y-8">
      {channel.platform === "youtube" && <ChannelAnalysis channel={channel} />}
      
      {chartData.length > 1 && (
        <div className="h-64 border border-border rounded-2xl bg-card p-4 shadow-sm">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id={`grad-${channel.id}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))", fontWeight: 600 }} tickLine={false} axisLine={false} minTickGap={40} />
              <YAxis tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))", fontWeight: 600 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => fmt(v)} width={48} domain={["auto", "auto"]} />
              <ChartTooltip
                contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12, fontWeight: 600 }}
                formatter={(v: number) => [new Intl.NumberFormat().format(v), "Followers"]}
              />
              <Area type="monotone" dataKey="followers" stroke="hsl(var(--primary))" strokeWidth={2.5} fill={`url(#grad-${channel.id})`} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      <div>
        <h4 className="text-lg font-bold mb-4 flex items-center gap-2">
          <meta.icon className={`w-5 h-5 ${meta.color}`} /> Recent posts
        </h4>
        {!posts?.length ? (
          <p className="text-sm text-muted-foreground font-medium">No post data yet — sync to fetch recent posts.</p>
        ) : (
          <div className="border border-border rounded-2xl overflow-hidden bg-card shadow-sm">
            <table className="w-full text-sm">
              <thead className="bg-muted/30 text-muted-foreground text-[11px] uppercase tracking-widest">
                <tr>
                  <th className="text-left font-bold px-5 py-3">Post</th>
                  <SortHeader label="Views" k="views" className="text-right w-24" />
                  <SortHeader label="Likes" k="likes" className="text-right w-24" />
                  <SortHeader label="Comments" k="comments" className="text-right w-28 hidden sm:table-cell" />
                  <SortHeader label="Published" k="published_at" className="text-right w-32" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {sortedPosts.map((p) => (
                  <tr key={p.id} className="hover:bg-muted/20 transition-colors group">
                    <td className="px-5 py-3 max-w-0">
                      <div className="flex items-center gap-4 min-w-0">
                        {p.thumbnail_url ? (
                          <div className="relative h-12 w-20 shrink-0 rounded-lg overflow-hidden border border-border/50">
                            <img
                              src={p.thumbnail_url}
                              alt=""
                              loading="lazy"
                              className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
                              onError={(e) => { (e.target as HTMLImageElement).style.visibility = "hidden"; }}
                            />
                          </div>
                        ) : (
                          <div className="w-20 h-12 rounded-lg bg-muted/60 flex items-center justify-center shrink-0 border border-border/50">
                            <meta.icon className={`w-5 h-5 opacity-50 ${meta.color}`} />
                          </div>
                        )}
                        <div className="truncate font-semibold group-hover:text-primary transition-colors pr-2">
                          {p.title ?? p.external_id}
                        </div>
                        {p.url && (
                          <a href={p.url} target="_blank" rel="noreferrer" className="text-muted-foreground hover:text-primary shrink-0 opacity-0 group-hover:opacity-100 transition-all ml-auto">
                            <ExternalLink className="w-4 h-4" />
                          </a>
                        )}
                      </div>
                    </td>
                    <td className="px-5 py-3 text-right font-bold tabular-nums">{fmt(p.views)}</td>
                    <td className="px-5 py-3 text-right font-bold tabular-nums">{fmt(p.likes)}</td>
                    <td className="px-5 py-3 text-right font-bold tabular-nums hidden sm:table-cell">{fmt(p.comments)}</td>
                    <td className="px-5 py-3 text-right text-muted-foreground whitespace-nowrap text-xs font-bold tracking-wide">
                      {p.published_at ? new Date(p.published_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

export default function Socials() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const canEdit = useCanEdit();

  const { data: overview, isLoading } = useGetSocialsOverview();

  const { data: jobs } = useListJobs(
    { limit: 25 },
    { query: { queryKey: getListJobsQueryKey({ limit: 25 }), refetchInterval: (q) => {
      const j = q.state.data?.find((x) => x.job_type === "social_sync");
      return j && (j.status === "pending" || j.status === "running") ? 3000 : false;
    } } },
  );
  const syncJob = jobs?.find((j) => j.job_type === "social_sync");
  const activeSync = syncJob && (syncJob.status === "pending" || syncJob.status === "running");

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: getGetSocialsOverviewQueryKey() });
    queryClient.invalidateQueries({ queryKey: [`/api/socials`], exact: false });
  };

  const wasSyncing = useRef(false);
  useEffect(() => {
    if (wasSyncing.current && !activeSync) invalidate();
    wasSyncing.current = !!activeSync;
  }, [activeSync]); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = useRefreshSocials({
    mutation: {
      onSuccess: () => {
        toast({ title: "Sync started", description: "Fetching latest channel and post metrics." });
        queryClient.invalidateQueries({ queryKey: [`/api/jobs`], exact: false });
      },
      onError: () => toast({ title: "Could not start sync", variant: "destructive" }),
    },
  });

  const createProgram = useCreateSocialProgram({ mutation: { onSuccess: invalidate } });
  const updateProgram = useUpdateSocialProgram({ mutation: { onSuccess: invalidate } });
  const deleteProgram = useDeleteSocialProgram({ mutation: { onSuccess: invalidate } });
  const createChannel = useCreateSocialChannel({
    mutation: {
      onSuccess: () => { invalidate(); setChannelDialog(null); },
      onError: () => toast({ title: "Could not add channel", variant: "destructive" }),
    },
  });
  const updateChannel = useUpdateSocialChannel({
    mutation: { onSuccess: () => { invalidate(); setChannelDialog(null); } },
  });
  const deleteChannel = useDeleteSocialChannel({ mutation: { onSuccess: invalidate } });

  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [insightsPolling, setInsightsPolling] = useState(false);
  const insights = useGenerateSocialsInsights({
    mutation: {
      onSuccess: (data) => {
        if (data.status === "running") {
          setInsightsPolling(true);
          pollTimer.current = setTimeout(() => insights.mutate(), 5000);
        } else {
          setInsightsPolling(false);
          queryClient.invalidateQueries({ queryKey: getGetSocialsInsightsQueryKey() });
        }
      },
      onError: () => {
        if (pollTimer.current) clearTimeout(pollTimer.current);
        setInsightsPolling(false);
        toast({ title: "Could not generate insights", variant: "destructive" });
      },
    },
  });
  useEffect(() => () => { if (pollTimer.current) clearTimeout(pollTimer.current); }, []);
  const savedInsights = useGetSocialsInsights({
    query: {
      queryKey: getGetSocialsInsightsQueryKey(),
      retry: false,
      refetchOnWindowFocus: false,
    },
  });
  const insightsBusy = insights.isPending || insightsPolling;
  const insightsReady =
    (!insightsPolling && insights.data?.status === "ready" ? insights.data : null)
    ?? (savedInsights.data?.status === "ready" ? savedInsights.data : null);

  const [programDialog, setProgramDialog] = useState<{ id?: string; name: string } | null>(null);
  const [channelDialog, setChannelDialog] = useState<{
    id?: string; program_id: string; platform: SocialChannelInputPlatform; handle: string; url: string;
  } | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const configWarnings: string[] = [];
  if (overview && !overview.youtube_configured) configWarnings.push("YouTube (YOUTUBE_API_KEY)");
  if (overview && !overview.meta_configured) configWarnings.push("Instagram/Facebook (META_ACCESS_TOKEN)");
  if (overview && !overview.tiktok_configured) configWarnings.push("TikTok (TIKTOK_ACCESS_TOKEN)");

  const totalFollowers = overview?.programs.reduce((sum, p) => 
    sum + p.channels.reduce((cs, c) => cs + (c.latest?.followers ?? 0), 0)
  , 0) ?? 0;
  
  const totalViews = overview?.programs.reduce((sum, p) => 
    sum + p.channels.reduce((cs, c) => cs + (c.latest?.total_views ?? 0), 0)
  , 0) ?? 0;

  const animFollowers = useCountUp(totalFollowers);
  const animViews = useCountUp(totalViews);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="relative border-b border-border bg-gradient-to-b from-primary/10 via-background to-background overflow-hidden">
        <div
          className="absolute inset-0 opacity-[0.35] pointer-events-none"
          style={{
            backgroundImage:
              "radial-gradient(circle at 20% 0%, hsl(var(--primary) / 0.25), transparent 45%), radial-gradient(circle at 80% 10%, hsl(280 80% 60% / 0.15), transparent 40%)",
          }}
        />
        <div className="relative max-w-7xl mx-auto px-8 pt-16 pb-12 flex flex-col md:flex-row md:items-end justify-between gap-6">
          <div>
            <h1 className="text-4xl font-bold tracking-tight flex items-center gap-3">
              <Share2 className="w-8 h-8 text-primary" /> Socials
            </h1>
            <p className="mt-3 text-muted-foreground text-lg font-medium" data-testid="text-hero-stats">
              <strong className="text-foreground tabular-nums">{fmt(animFollowers)}</strong> total audience · <strong className="text-foreground tabular-nums">{fmt(animViews)}</strong> views this week
            </p>
            {overview?.last_synced_at && (
              <p className="text-[11px] font-bold tracking-widest uppercase text-muted-foreground mt-3">
                Last synced {new Date(overview.last_synced_at).toLocaleString()}
              </p>
            )}
          </div>
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              className="h-10 rounded-xl font-bold tracking-wide"
              onClick={() => insights.mutate()}
              disabled={insightsBusy}
              data-testid="button-ai-insights"
            >
              <Sparkles className={`w-4 h-4 mr-2 text-primary ${insightsBusy ? "animate-pulse" : ""}`} />
              {insightsBusy ? "Analyzing…" : "AI Insights"}
            </Button>
            {canEdit && (
              <Button variant="outline" className="h-10 rounded-xl font-bold tracking-wide" onClick={() => setProgramDialog({ name: "" })} data-testid="button-add-program">
                <Plus className="w-4 h-4 mr-2" /> Program
              </Button>
            )}
            {canEdit && (
              <Button
                className="h-10 rounded-xl font-bold tracking-wide"
                onClick={() => refresh.mutate()}
                disabled={refresh.isPending || !!activeSync}
                data-testid="button-refresh-socials"
              >
                <RefreshCw className={`w-4 h-4 mr-2 ${activeSync ? "animate-spin" : ""}`} />
                {activeSync ? "Syncing…" : "Refresh"}
              </Button>
            )}
          </div>
        </div>
      </div>

      <div className="p-8 max-w-7xl mx-auto space-y-12">
        {configWarnings.length > 0 && (
          <div className="flex items-start gap-3 text-sm text-amber-400/90 bg-amber-400/10 border border-amber-400/20 rounded-xl px-5 py-4 font-medium">
            <AlertTriangle className="w-5 h-5 mt-0.5 shrink-0" />
            <span className="leading-relaxed">Not configured: {configWarnings.join(", ")} — those channels won't sync until the credentials are set on the server.</span>
          </div>
        )}

        {insightsReady && (
          <section>
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-2xl font-bold tracking-tight flex items-center gap-2">
                <Sparkles className="h-6 w-6 text-primary/70" />
                AI Insights
              </h2>
              <span className="text-[11px] font-bold uppercase tracking-widest text-muted-foreground">
                {insightsReady.model_used ? "AI analysis" : "Metrics analysis (AI model unavailable)"} · {new Date(insightsReady.generated_at).toLocaleDateString()}
              </span>
            </div>
            <div className="grid gap-4 md:grid-cols-3 auto-rows-fr">
              <div className="h-full rounded-2xl border border-border bg-gradient-to-br from-emerald-500/10 to-teal-600/5 hover:border-emerald-500/30 transition-all hover:shadow-lg p-6 flex flex-col">
                <h3 className="text-sm font-bold uppercase tracking-widest mb-4 flex items-center gap-2 text-emerald-400">
                  <CheckCircle2 className="w-5 h-5" /> What's working
                </h3>
                {insightsReady.working.length ? (
                  <ul className="space-y-3 text-sm text-foreground/90 font-medium flex-1">
                    {insightsReady.working.map((s, i) => (
                      <li key={i} className="flex gap-3 leading-relaxed">
                        <span className="text-emerald-400 mt-0.5 shrink-0 text-[10px]">❖</span>
                        <span>{s}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground font-medium">Nothing stands out yet.</p>
                )}
              </div>

              <div className="h-full rounded-2xl border border-border bg-gradient-to-br from-red-500/10 to-rose-600/5 hover:border-red-500/30 transition-all hover:shadow-lg p-6 flex flex-col">
                <h3 className="text-sm font-bold uppercase tracking-widest mb-4 flex items-center gap-2 text-red-400">
                  <XCircle className="w-5 h-5" /> What's not working
                </h3>
                {insightsReady.not_working.length ? (
                  <ul className="space-y-3 text-sm text-foreground/90 font-medium flex-1">
                    {insightsReady.not_working.map((s, i) => (
                      <li key={i} className="flex gap-3 leading-relaxed">
                        <span className="text-red-400 mt-0.5 shrink-0 text-[10px]">❖</span>
                        <span>{s}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground font-medium">No problems detected.</p>
                )}
              </div>

              <div className="h-full rounded-2xl border border-border bg-gradient-to-br from-amber-500/10 to-orange-600/5 hover:border-amber-500/30 transition-all hover:shadow-lg p-6 flex flex-col">
                <h3 className="text-sm font-bold uppercase tracking-widest mb-4 flex items-center gap-2 text-amber-400">
                  <Lightbulb className="w-5 h-5" /> Recommendations
                </h3>
                {insightsReady.recommendations.length ? (
                  <ul className="space-y-3 text-sm text-foreground/90 font-medium flex-1">
                    {insightsReady.recommendations.map((s, i) => (
                      <li key={i} className="flex gap-3 leading-relaxed">
                        <span className="text-amber-400 mt-0.5 shrink-0 text-[10px]">❖</span>
                        <span>{s}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground font-medium">Keep up the good work.</p>
                )}
              </div>
            </div>
          </section>
        )}

        <section className="space-y-10">
          {isLoading ? (
            <div className="space-y-6">
              <div className="h-40 rounded-2xl bg-muted/30 animate-pulse border border-border" />
              <div className="h-40 rounded-2xl bg-muted/30 animate-pulse border border-border" />
            </div>
          ) : overview?.programs.length === 0 ? (
            <div className="text-center py-20 border border-dashed border-border rounded-2xl bg-card/30">
              <Share2 className="w-16 h-16 text-muted-foreground/50 mx-auto mb-5" />
              <p className="text-muted-foreground font-medium text-lg">No social programs configured.</p>
              {canEdit && (
                <Button variant="outline" className="mt-6 font-bold tracking-wide" onClick={() => setProgramDialog({ name: "" })}>
                  <Plus className="w-4 h-4 mr-2" /> Add your first program
                </Button>
              )}
            </div>
          ) : (
            overview?.programs.map((program) => (
              <div key={program.id} data-testid={`program-${program.id}`}>
                <div className="flex items-center justify-between mb-5">
                  <div className="flex items-center gap-4">
                    <h2 className="text-2xl font-bold tracking-tight">{program.name}</h2>
                    <Badge variant="outline" className="bg-primary/10 text-primary border-primary/20 rounded-full px-3 font-bold tracking-wide">
                      {program.channels.length} channel{program.channels.length === 1 ? "" : "s"}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-2">
                    {canEdit && (
                      <Button variant="outline" size="sm" className="font-bold tracking-wide rounded-lg" onClick={() => setChannelDialog({ program_id: program.id, platform: "youtube", handle: "", url: "" })} data-testid={`button-add-channel-${program.id}`}>
                        <Plus className="w-4 h-4 mr-1.5" /> Channel
                      </Button>
                    )}
                    {canEdit && (
                      <Button variant="ghost" size="icon" className="h-9 w-9 rounded-lg text-muted-foreground hover:text-foreground" onClick={() => setProgramDialog({ id: program.id, name: program.name })} data-testid={`button-edit-program-${program.id}`}>
                        <Pencil className="w-4 h-4" />
                      </Button>
                    )}
                    {canEdit && (
                      <Button variant="ghost" size="icon" className="h-9 w-9 rounded-lg text-muted-foreground hover:text-red-400" onClick={() => { if (confirm("Delete program?")) deleteProgram.mutate({ id: program.id }); }} data-testid={`button-delete-program-${program.id}`}>
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    )}
                  </div>
                </div>

                {program.channels.length === 0 ? (
                  <div className="border border-dashed border-border rounded-2xl p-8 text-center bg-card/30">
                    <p className="text-sm font-medium text-muted-foreground">No channels in this program.</p>
                  </div>
                ) : (
                  <div className="grid gap-4">
                    {program.channels.map((channel) => {
                      const isExpanded = expanded === channel.id;
                      const meta = PLATFORM_META[channel.platform] ?? PLATFORM_META.youtube;
                      
                      const baselineViews = 100000;
                      const viewFrac = Math.min(1, (channel.latest?.total_views ?? 0) / baselineViews);
                      const ringDeg = viewFrac * 360;
                      
                      return (
                        <div key={channel.id} className="relative border border-border rounded-2xl bg-card hover:border-primary/50 transition-colors overflow-hidden shadow-sm group/channel">
                          <div className="flex flex-col md:flex-row md:items-center justify-between px-6 py-5 gap-6">
                            <div className="flex items-center gap-5 cursor-pointer flex-1" onClick={() => setExpanded(x => x === channel.id ? null : channel.id)} data-testid={`trigger-channel-${channel.id}`}>
                              <div
                                className="rounded-full p-[3px] shrink-0 transition-transform duration-500"
                                style={{ background: `conic-gradient(hsl(var(--primary)) ${ringDeg}deg, hsl(var(--muted)) ${ringDeg}deg)` }}
                              >
                                <div className="rounded-full overflow-hidden bg-muted w-14 h-14 border-[3px] border-background flex items-center justify-center">
                                  <meta.icon className={`w-6 h-6 ${meta.color}`} />
                                </div>
                              </div>
                              <div>
                                <div className="font-bold text-xl tracking-tight">{channel.handle}</div>
                                <div className="text-[11px] font-bold uppercase tracking-widest text-muted-foreground flex items-center gap-1.5 mt-1">
                                  <meta.icon className={`w-3.5 h-3.5 ${meta.color}`} />
                                  {meta.label}
                                </div>
                              </div>
                            </div>

                            <div className="flex items-center gap-8 md:gap-12 pl-[84px] md:pl-0">
                              <div className="text-left md:text-right">
                                <div className="text-2xl font-bold tabular-nums tracking-tight">{fmt(channel.latest?.followers)}</div>
                                <div className="text-[11px] font-bold uppercase tracking-widest text-muted-foreground mt-1">followers</div>
                              </div>
                              <div className="text-left md:text-right hidden sm:block">
                                <div className="text-2xl font-bold tabular-nums tracking-tight">{fmt(channel.latest?.total_views)}</div>
                                <div className="text-[11px] font-bold uppercase tracking-widest text-muted-foreground mt-1">total views</div>
                              </div>
                              
                              <div className="flex items-center gap-3 ml-auto md:ml-0">
                                {canEdit && (
                                  <div className="flex items-center gap-1 mr-2 opacity-0 group-hover/channel:opacity-100 transition-opacity md:opacity-100">
                                    <Button variant="ghost" size="icon" className="h-9 w-9 rounded-full text-muted-foreground hover:bg-muted hover:text-foreground" onClick={(e) => { e.stopPropagation(); setChannelDialog({ id: channel.id, program_id: program.id, platform: channel.platform as any, handle: channel.handle, url: channel.url ?? "" }); }} data-testid={`button-edit-channel-${channel.id}`}>
                                      <Pencil className="w-4 h-4" />
                                    </Button>
                                    <Button variant="ghost" size="icon" className="h-9 w-9 rounded-full text-muted-foreground hover:bg-red-500/10 hover:text-red-400" onClick={(e) => { e.stopPropagation(); if (confirm("Delete channel?")) deleteChannel.mutate({ id: channel.id }); }} data-testid={`button-delete-channel-${channel.id}`}>
                                      <Trash2 className="w-4 h-4" />
                                    </Button>
                                  </div>
                                )}
                                <button className="p-2.5 -mr-2 rounded-full hover:bg-muted transition-colors" onClick={() => setExpanded(x => x === channel.id ? null : channel.id)}>
                                  <ChevronDown className={`w-5 h-5 text-muted-foreground transition-transform ${isExpanded ? "rotate-180" : ""}`} />
                                </button>
                              </div>
                            </div>
                          </div>

                          {isExpanded && (
                            <div className="px-6 pb-6 pt-3 border-t border-border/50 bg-background/30">
                              <ChannelDetail channel={channel} />
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            ))
          )}
        </section>
      </div>

      {/* Modals */}
      <Dialog open={!!programDialog} onOpenChange={(o) => !o && setProgramDialog(null)}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{programDialog?.id ? "Edit Program" : "Add Program"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label className="font-bold tracking-wide">Name</Label>
              <Input
                value={programDialog?.name ?? ""}
                onChange={(e) => setProgramDialog((p) => p ? { ...p, name: e.target.value } : null)}
                placeholder="e.g. Main Channel, Clips Network"
                data-testid="input-program-name"
                className="font-medium"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              className="font-bold tracking-wide"
              disabled={!programDialog?.name.trim() || createProgram.isPending || updateProgram.isPending}
              onClick={() => {
                if (!programDialog?.name.trim()) return;
                if (programDialog.id) updateProgram.mutate({ id: programDialog.id, data: { name: programDialog.name.trim() } });
                else createProgram.mutate({ data: { name: programDialog.name.trim() } });
              }}
              data-testid="button-save-program"
            >
              {createProgram.isPending || updateProgram.isPending ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!channelDialog} onOpenChange={(o) => !o && setChannelDialog(null)}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{channelDialog?.id ? "Edit Channel" : "Add Channel"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-5 py-4">
            <div className="space-y-2">
              <Label className="font-bold tracking-wide">Platform</Label>
              <Select
                value={channelDialog?.platform}
                onValueChange={(v: any) => setChannelDialog((c) => c ? { ...c, platform: v } : null)}
                disabled={!!channelDialog?.id}
              >
                <SelectTrigger data-testid="select-platform" className="font-medium">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="youtube" className="font-medium"><span className="flex items-center gap-2"><Youtube className="w-4 h-4 text-red-500" /> YouTube</span></SelectItem>
                  <SelectItem value="instagram" className="font-medium"><span className="flex items-center gap-2"><Instagram className="w-4 h-4 text-pink-500" /> Instagram</span></SelectItem>
                  <SelectItem value="facebook" className="font-medium"><span className="flex items-center gap-2"><Facebook className="w-4 h-4 text-blue-500" /> Facebook</span></SelectItem>
                  <SelectItem value="tiktok" className="font-medium"><span className="flex items-center gap-2"><Music2 className="w-4 h-4 text-teal-400" /> TikTok</span></SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label className="font-bold tracking-wide">Handle / Name</Label>
              <Input
                value={channelDialog?.handle ?? ""}
                onChange={(e) => setChannelDialog((c) => c ? { ...c, handle: e.target.value } : null)}
                placeholder="@channel"
                data-testid="input-channel-handle"
                className="font-medium"
              />
            </div>
            <div className="space-y-2">
              <Label className="font-bold tracking-wide">Profile URL <span className="text-muted-foreground font-normal">(Optional)</span></Label>
              <Input
                value={channelDialog?.url ?? ""}
                onChange={(e) => setChannelDialog((c) => c ? { ...c, url: e.target.value } : null)}
                placeholder="https://..."
                data-testid="input-channel-url"
                className="font-medium"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              className="font-bold tracking-wide"
              disabled={!channelDialog?.handle.trim() || createChannel.isPending || updateChannel.isPending}
              onClick={() => {
                if (!channelDialog) return;
                const data = {
                  program_id: channelDialog.program_id,
                  platform: channelDialog.platform,
                  handle: channelDialog.handle.trim(),
                  url: channelDialog.url.trim() || undefined,
                };
                if (channelDialog.id) updateChannel.mutate({ id: channelDialog.id, data });
                else createChannel.mutate({ data });
              }}
              data-testid="button-save-channel"
            >
              {createChannel.isPending || updateChannel.isPending ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
