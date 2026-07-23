import { useEffect, useRef, useState } from "react";
import {
  useGetSocialsOverview,
  getGetSocialsOverviewQueryKey,
  useGetSocialChannelHistory,
  getGetSocialChannelHistoryQueryKey,
  useListSocialChannelPosts,
  useCreateSocialProgram,
  useUpdateSocialProgram,
  useDeleteSocialProgram,
  useCreateSocialChannel,
  useUpdateSocialChannel,
  useDeleteSocialChannel,
  useRefreshSocials,
  useGenerateSocialsInsights,
  useListJobs,
  getListJobsQueryKey,
  type SocialChannelOverview,
  type SocialProgramOverview,
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
  Users,
  Eye,
  Sparkles,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  XCircle,
  Lightbulb,
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
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";
import { useCanEdit } from "@/lib/auth";

const PLATFORM_META: Record<string, { label: string; icon: typeof Youtube; color: string }> = {
  youtube: { label: "YouTube", icon: Youtube, color: "text-red-400" },
  instagram: { label: "Instagram", icon: Instagram, color: "text-pink-400" },
  facebook: { label: "Facebook", icon: Facebook, color: "text-blue-400" },
  tiktok: { label: "TikTok", icon: Music2, color: "text-teal-300" },
};

function fmt(v: number | null | undefined): string {
  if (v == null) return "—";
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(v);
}

function Delta({ now, before }: { now?: number | null; before?: number | null }) {
  if (now == null || before == null || before === 0) return null;
  const diff = now - before;
  if (diff === 0) return <span className="text-xs text-muted-foreground">±0 this week</span>;
  const pct = (diff / before) * 100;
  const up = diff > 0;
  const Icon = up ? TrendingUp : TrendingDown;
  return (
    <span className={`inline-flex items-center gap-1 text-xs ${up ? "text-emerald-400" : "text-red-400"}`}>
      <Icon className="w-3 h-3" />
      {up ? "+" : ""}{fmt(diff)} ({pct.toFixed(1)}%) this week
    </span>
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
    <th className={`font-medium px-3 py-2 ${className ?? ""}`}>
      <button
        type="button"
        onClick={() => toggleSort(k)}
        className={`inline-flex items-center gap-1 hover:text-foreground ${sortKey === k ? "text-foreground" : ""}`}
        data-testid={`sort-posts-${k}`}
      >
        {label}
        {sortKey === k && (sortDesc ? <ChevronDown className="w-3 h-3" /> : <ChevronUp className="w-3 h-3" />)}
      </button>
    </th>
  );

  const chartData = (history ?? []).map((s) => ({
    date: new Date(s.fetched_at).toLocaleDateString("en", { month: "short", day: "numeric" }),
    followers: s.followers ?? 0,
  }));

  return (
    <div className="space-y-4">
      {chartData.length > 1 && (
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id={`grad-${channel.id}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} minTickGap={40} />
              <YAxis tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} tickFormatter={(v: number) => fmt(v)} width={48} domain={["auto", "auto"]} />
              <ChartTooltip
                contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                formatter={(v: number) => [new Intl.NumberFormat().format(v), "Followers"]}
              />
              <Area type="monotone" dataKey="followers" stroke="hsl(var(--primary))" strokeWidth={2} fill={`url(#grad-${channel.id})`} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      <div>
        <h4 className="text-sm font-medium mb-2 flex items-center gap-2">
          <meta.icon className={`w-4 h-4 ${meta.color}`} /> Recent posts
        </h4>
        {!posts?.length ? (
          <p className="text-sm text-muted-foreground">No post data yet — sync to fetch recent posts.</p>
        ) : (
          <div className="border border-border rounded-md overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-muted-foreground">
                <tr>
                  <th className="text-left font-medium px-3 py-2">Post</th>
                  <SortHeader label="Views" k="views" className="text-right w-20" />
                  <SortHeader label="Likes" k="likes" className="text-right w-20" />
                  <SortHeader label="Comments" k="comments" className="text-right w-24" />
                  <SortHeader label="Published" k="published_at" className="text-right w-24" />
                </tr>
              </thead>
              <tbody>
                {sortedPosts.map((p) => (
                  <tr key={p.id} className="border-t border-border hover:bg-muted/20">
                    <td className="px-3 py-2 max-w-0">
                      <div className="flex items-center gap-3 min-w-0">
                        {p.thumbnail_url ? (
                          <img
                            src={p.thumbnail_url}
                            alt=""
                            loading="lazy"
                            className="w-16 h-9 rounded object-cover bg-muted shrink-0"
                            onError={(e) => { (e.target as HTMLImageElement).style.visibility = "hidden"; }}
                          />
                        ) : (
                          <div className="w-16 h-9 rounded bg-muted/60 flex items-center justify-center shrink-0">
                            <meta.icon className={`w-4 h-4 opacity-50 ${meta.color}`} />
                          </div>
                        )}
                        <span className="truncate">{p.title ?? p.external_id}</span>
                        {p.url && (
                          <a href={p.url} target="_blank" rel="noreferrer" className="text-muted-foreground hover:text-foreground shrink-0" data-testid={`link-post-${p.id}`}>
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{fmt(p.views)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{fmt(p.likes)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{fmt(p.comments)}</td>
                    <td className="px-3 py-2 text-right text-muted-foreground whitespace-nowrap">
                      {p.published_at ? new Date(p.published_at).toLocaleDateString() : "—"}
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

  // Poll jobs while a social sync is active so the page refreshes when done.
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

  // When a sync finishes, pull in the fresh metrics (overview, history, posts).
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

  // Insights are generated asynchronously server-side (the LLM can take a few
  // minutes): a POST returning status "running" means keep polling by
  // re-POSTing until status is "ready".
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
  const insightsBusy = insights.isPending || insightsPolling;
  const insightsReady =
    !insightsPolling && insights.data?.status === "ready" ? insights.data : null;

  const [programDialog, setProgramDialog] = useState<{ id?: string; name: string } | null>(null);
  const [channelDialog, setChannelDialog] = useState<{
    id?: string; program_id: string; platform: SocialChannelInputPlatform; handle: string; url: string;
  } | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const configWarnings: string[] = [];
  if (overview && !overview.youtube_configured) configWarnings.push("YouTube (YOUTUBE_API_KEY)");
  if (overview && !overview.meta_configured) configWarnings.push("Instagram/Facebook (META_ACCESS_TOKEN)");
  if (overview && !overview.tiktok_configured) configWarnings.push("TikTok (TIKTOK_ACCESS_TOKEN)");

  return (
    <div className="flex-1 p-6 space-y-6 overflow-y-auto">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <Share2 className="w-6 h-6 text-primary" /> Socials
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Channel growth and post performance per program
            {overview?.last_synced_at && (
              <> · last synced {new Date(overview.last_synced_at).toLocaleString()}</>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={() => insights.mutate()}
            disabled={insightsBusy}
            data-testid="button-ai-insights"
          >
            <Sparkles className={`w-4 h-4 mr-2 text-primary ${insightsBusy ? "animate-pulse" : ""}`} />
            {insightsBusy ? "Analyzing…" : "AI Insights"}
          </Button>
          {canEdit && (
            <Button variant="outline" onClick={() => setProgramDialog({ name: "" })} data-testid="button-add-program">
              <Plus className="w-4 h-4 mr-2" /> Program
            </Button>
          )}
          {canEdit && (
            <Button
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

      {configWarnings.length > 0 && (
        <div className="flex items-start gap-2 text-sm text-amber-400/90 bg-amber-400/10 border border-amber-400/20 rounded-md px-3 py-2">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span>Not configured: {configWarnings.join(", ")} — those channels won't sync until the credentials are set on the server.</span>
        </div>
      )}

      {insightsReady && (
        <section className="border border-border rounded-lg bg-card">
          <div className="flex items-center justify-between px-4 py-3 border-b border-border">
            <h2 className="font-medium flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-primary" /> AI insights
            </h2>
            <span className="text-xs text-muted-foreground">
              {insightsReady.model_used ? "AI analysis" : "Metrics analysis (AI model unavailable)"} · {new Date(insightsReady.generated_at).toLocaleTimeString()}
            </span>
          </div>
          <div className="p-4 grid gap-6 md:grid-cols-3">
            <div>
              <h3 className="text-sm font-medium mb-2 flex items-center gap-2 text-emerald-400">
                <CheckCircle2 className="w-4 h-4" /> What's working
              </h3>
              {insightsReady.working.length ? (
                <ul className="space-y-2 text-sm text-foreground/90">
                  {insightsReady.working.map((s, i) => (
                    <li key={i} className="flex gap-2"><span className="text-emerald-400/60 shrink-0">•</span><span>{s}</span></li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">Nothing stands out yet.</p>
              )}
            </div>
            <div>
              <h3 className="text-sm font-medium mb-2 flex items-center gap-2 text-red-400">
                <XCircle className="w-4 h-4" /> What's not working
              </h3>
              {insightsReady.not_working.length ? (
                <ul className="space-y-2 text-sm text-foreground/90">
                  {insightsReady.not_working.map((s, i) => (
                    <li key={i} className="flex gap-2"><span className="text-red-400/60 shrink-0">•</span><span>{s}</span></li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">No problems detected.</p>
              )}
            </div>
            <div>
              <h3 className="text-sm font-medium mb-2 flex items-center gap-2 text-amber-300">
                <Lightbulb className="w-4 h-4" /> Recommendations
              </h3>
              {insightsReady.recommendations.length ? (
                <ul className="space-y-2 text-sm text-foreground/90">
                  {insightsReady.recommendations.map((s, i) => (
                    <li key={i} className="flex gap-2"><span className="text-amber-300/60 shrink-0">•</span><span>{s}</span></li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">No recommendations right now.</p>
              )}
            </div>
          </div>
        </section>
      )}

      {isLoading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : !overview?.programs.length ? (
        <div className="text-center py-16 text-muted-foreground">
          <Share2 className="w-10 h-10 mx-auto mb-3 opacity-40" />
          <p>No programs yet.</p>
          {canEdit && <p className="text-sm mt-1">Add a program (e.g. “Praise”), then attach its social channels.</p>}
        </div>
      ) : (
        overview.programs.map((program: SocialProgramOverview) => (
          <section key={program.id} className="border border-border rounded-lg bg-card">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <h2 className="font-medium" data-testid={`text-program-${program.id}`}>{program.name}</h2>
              {canEdit && (
                <div className="flex items-center gap-1">
                  <Button
                    size="sm" variant="ghost"
                    onClick={() => setChannelDialog({ program_id: program.id, platform: "youtube", handle: "", url: "" })}
                    data-testid={`button-add-channel-${program.id}`}
                  >
                    <Plus className="w-4 h-4 mr-1" /> Channel
                  </Button>
                  <Button size="icon" variant="ghost" onClick={() => setProgramDialog({ id: program.id, name: program.name })} data-testid={`button-edit-program-${program.id}`}>
                    <Pencil className="w-4 h-4" />
                  </Button>
                  <Button
                    size="icon" variant="ghost"
                    onClick={() => {
                      if (confirm(`Delete program "${program.name}" and its ${program.channels.length} channel(s)? Collected metrics are removed too.`)) {
                        deleteProgram.mutate({ id: program.id });
                      }
                    }}
                    data-testid={`button-delete-program-${program.id}`}
                  >
                    <Trash2 className="w-4 h-4 text-muted-foreground" />
                  </Button>
                </div>
              )}
            </div>

            {!program.channels.length ? (
              <p className="text-sm text-muted-foreground px-4 py-6">No channels yet.</p>
            ) : (
              <>
                <div className="p-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {program.channels.map((c) => {
                    const meta = PLATFORM_META[c.platform] ?? PLATFORM_META.youtube;
                    const Icon = meta.icon;
                    const open = expanded === c.id;
                    return (
                      <button
                        key={c.id}
                        className={`text-left border rounded-lg overflow-hidden bg-background/40 hover:bg-muted/20 transition-colors ${open ? "border-primary" : "border-border"}`}
                        onClick={() => setExpanded(open ? null : c.id)}
                        data-testid={`row-channel-${c.id}`}
                      >
                        <div className="relative aspect-video bg-muted/40">
                          {c.latest_post_thumbnail ? (
                            <img
                              src={c.latest_post_thumbnail}
                              alt=""
                              loading="lazy"
                              className="absolute inset-0 w-full h-full object-cover"
                              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                            />
                          ) : null}
                          <div className={`absolute inset-0 flex items-center justify-center ${c.latest_post_thumbnail ? "bg-gradient-to-t from-black/70 via-black/10 to-transparent" : ""}`}>
                            {!c.latest_post_thumbnail && <Icon className={`w-8 h-8 opacity-40 ${meta.color}`} />}
                          </div>
                          <Badge variant="outline" className="absolute top-2 right-2 text-xs bg-background/70 backdrop-blur-sm">
                            {meta.label}
                          </Badge>
                          <div className="absolute bottom-2 left-3 right-3 flex items-center gap-2">
                            <Icon className={`w-4 h-4 shrink-0 ${meta.color} drop-shadow`} />
                            <span className="font-medium text-sm text-white drop-shadow truncate">{c.display_name ?? c.handle}</span>
                          </div>
                        </div>
                        <div className="p-3 space-y-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="text-xs text-muted-foreground truncate">{c.handle}</span>
                            {c.url && (
                              <a href={c.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="text-muted-foreground hover:text-foreground shrink-0">
                                <ExternalLink className="w-3.5 h-3.5" />
                              </a>
                            )}
                          </div>
                          <div className="flex items-center gap-5">
                            <div>
                              <div className="text-sm font-medium tabular-nums flex items-center gap-1">
                                <Users className="w-3.5 h-3.5 text-muted-foreground" /> {fmt(c.latest?.followers)}
                              </div>
                              <div className="text-[11px] text-muted-foreground">followers</div>
                            </div>
                            {c.latest?.total_views != null && (
                              <div>
                                <div className="text-sm font-medium tabular-nums flex items-center gap-1">
                                  <Eye className="w-3.5 h-3.5 text-muted-foreground" /> {fmt(c.latest.total_views)}
                                </div>
                                <div className="text-[11px] text-muted-foreground">total views</div>
                              </div>
                            )}
                          </div>
                          {c.last_error ? (
                            <span className="text-xs text-amber-400/90 inline-flex items-center gap-1">
                              <AlertTriangle className="w-3 h-3 shrink-0" /> <span className="truncate">{c.last_error}</span>
                            </span>
                          ) : (
                            <Delta now={c.latest?.followers} before={c.week_ago?.followers} />
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
                {program.channels.filter((c) => expanded === c.id).map((c) => {
                  const meta = PLATFORM_META[c.platform] ?? PLATFORM_META.youtube;
                  return (
                    <div key={c.id} className="border-t border-border px-4 py-4">
                      <div className="flex items-center justify-between gap-2 mb-2">
                        <span className="text-sm font-medium flex items-center gap-2">
                          <meta.icon className={`w-4 h-4 ${meta.color}`} /> {c.display_name ?? c.handle}
                        </span>
                        {canEdit && (
                          <div className="flex gap-1">
                            <Button size="sm" variant="ghost" onClick={() => setChannelDialog({ id: c.id, program_id: c.program_id, platform: c.platform as SocialChannelInputPlatform, handle: c.handle, url: c.url ?? "" })} data-testid={`button-edit-channel-${c.id}`}>
                              <Pencil className="w-3.5 h-3.5 mr-1" /> Edit
                            </Button>
                            <Button
                              size="sm" variant="ghost"
                              onClick={() => {
                                if (confirm(`Remove ${meta.label} channel "${c.handle}"? Its collected metrics are removed too.`)) {
                                  deleteChannel.mutate({ id: c.id });
                                }
                              }}
                              data-testid={`button-delete-channel-${c.id}`}
                            >
                              <Trash2 className="w-3.5 h-3.5 mr-1" /> Remove
                            </Button>
                          </div>
                        )}
                      </div>
                      <ChannelDetail channel={c} />
                    </div>
                  );
                })}
              </>
            )}
          </section>
        ))
      )}

      {/* Program dialog */}
      <Dialog open={!!programDialog} onOpenChange={(o) => !o && setProgramDialog(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>{programDialog?.id ? "Rename program" : "New program"}</DialogTitle></DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="program-name">Program name</Label>
            <Input
              id="program-name"
              value={programDialog?.name ?? ""}
              onChange={(e) => setProgramDialog((d) => d && { ...d, name: e.target.value })}
              placeholder="e.g. Praise"
              data-testid="input-program-name"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setProgramDialog(null)}>Cancel</Button>
            <Button
              disabled={!programDialog?.name.trim() || createProgram.isPending || updateProgram.isPending}
              onClick={() => {
                if (!programDialog) return;
                const name = programDialog.name.trim();
                if (programDialog.id) {
                  updateProgram.mutate({ id: programDialog.id, data: { name } });
                } else {
                  createProgram.mutate({ data: { name } });
                }
                setProgramDialog(null);
              }}
              data-testid="button-save-program"
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Channel dialog */}
      <Dialog open={!!channelDialog} onOpenChange={(o) => !o && setChannelDialog(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>{channelDialog?.id ? "Edit channel" : "Add channel"}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            {!channelDialog?.id && (
              <div className="space-y-2">
                <Label>Platform</Label>
                <Select
                  value={channelDialog?.platform}
                  onValueChange={(v) => setChannelDialog((d) => d && { ...d, platform: v as SocialChannelInputPlatform })}
                >
                  <SelectTrigger data-testid="select-channel-platform"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {Object.entries(PLATFORM_META).map(([k, m]) => (
                      <SelectItem key={k} value={k}>{m.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="channel-handle">Handle / page name</Label>
              <Input
                id="channel-handle"
                value={channelDialog?.handle ?? ""}
                onChange={(e) => setChannelDialog((d) => d && { ...d, handle: e.target.value })}
                placeholder="@praisetv"
                data-testid="input-channel-handle"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="channel-url">URL (optional)</Label>
              <Input
                id="channel-url"
                value={channelDialog?.url ?? ""}
                onChange={(e) => setChannelDialog((d) => d && { ...d, url: e.target.value })}
                placeholder="https://youtube.com/@praisetv"
                data-testid="input-channel-url"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setChannelDialog(null)}>Cancel</Button>
            <Button
              disabled={!channelDialog?.handle.trim() || createChannel.isPending || updateChannel.isPending}
              onClick={() => {
                if (!channelDialog) return;
                const handle = channelDialog.handle.trim();
                const url = channelDialog.url.trim() || null;
                if (channelDialog.id) {
                  updateChannel.mutate({ id: channelDialog.id, data: { handle, url } });
                } else {
                  createChannel.mutate({
                    data: { program_id: channelDialog.program_id, platform: channelDialog.platform, handle, url },
                  });
                }
              }}
              data-testid="button-save-channel"
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
