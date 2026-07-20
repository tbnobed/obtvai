import {
  useGetRatingsOverview,
  getGetRatingsOverviewQueryKey,
  useListRatings,
  getListRatingsQueryKey,
  useListRatingsImports,
  getListRatingsImportsQueryKey,
  useImportRatings,
  useDeleteRatingsImport,
  useUpdateRating,
  useListMedia,
  type RatingRecord,
  type RatingsImport,
  type ListRatingsParams,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef, useState } from "react";
import { Link } from "wouter";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  BarChart3,
  TrendingUp,
  Tv,
  Trophy,
  Upload,
  Download,
  Trash2,
  Film,
  Link2,
  X,
  Search,
  ChevronLeft,
  ChevronRight,
  History,
} from "lucide-react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  Tooltip as ChartTooltip,
  CartesianGrid,
} from "recharts";
import { useCanEdit } from "@/lib/auth";

const PAGE_SIZE = 25;

const RANGE_OPTIONS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
];

const PROVIDERS = ["nielsen", "comscore", "ispot", "manual"];

const CSV_TEMPLATE = [
  "date,station,program,start,end,rating,share,viewers,market,demo_A25-54,demo_P2+",
  "2026-07-01,OBTV,OBTV Evening News,19:00,19:30,4.2,24.5,52000,\"Columbus, OH\",2.1,4.2",
  "2026-07-01,WKRX,WKRX News at 7,19:00,19:30,3.1,18.2,38000,\"Columbus, OH\",1.4,3.1",
].join("\n");

function fmtNum(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  return v.toLocaleString("en", { maximumFractionDigits: digits });
}

function fmtViewers(v: number | null | undefined): string {
  if (v == null) return "—";
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(v);
}

function isoDaysAgo(days: number): string {
  return new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
}

function downloadTemplate() {
  const blob = new Blob([CSV_TEMPLATE], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "ratings_template.csv";
  a.click();
  URL.revokeObjectURL(url);
}

const chartTooltipStyle = {
  backgroundColor: "hsl(var(--card))",
  border: "1px solid hsl(var(--border))",
  borderRadius: 6,
  fontSize: 12,
};

export default function Ratings() {
  const queryClient = useQueryClient();
  const canEdit = useCanEdit();

  const [range, setRange] = useState("30");
  const from = useMemo(() => isoDaysAgo(parseInt(range, 10) - 1), [range]);

  const overviewParams = { from };
  const { data: overview, isLoading } = useGetRatingsOverview(overviewParams, {
    query: { queryKey: getGetRatingsOverviewQueryKey(overviewParams) },
  });

  const [stationFilter, setStationFilter] = useState<string>("all");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);

  const listParams: ListRatingsParams = {
    from,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    ...(stationFilter !== "all" ? { station: stationFilter } : {}),
    ...(q.trim() ? { q: q.trim() } : {}),
  };
  const { data: list } = useListRatings(listParams, {
    query: { queryKey: getListRatingsQueryKey(listParams) },
  });

  const invalidateRatings = () => {
    queryClient.invalidateQueries({ queryKey: [`/api/ratings`] });
    queryClient.invalidateQueries({ queryKey: getGetRatingsOverviewQueryKey(overviewParams) });
    queryClient.invalidateQueries({ queryKey: getListRatingsImportsQueryKey() });
  };

  const [importOpen, setImportOpen] = useState(false);
  const [linkTarget, setLinkTarget] = useState<RatingRecord | null>(null);

  const updateRating = useUpdateRating();
  const unlink = (rec: RatingRecord) => {
    updateRating.mutate(
      { id: rec.id, data: { asset_id: null } },
      { onSuccess: invalidateRatings },
    );
  };

  const kpis = overview?.kpis;
  const totalPages = list ? Math.max(1, Math.ceil(list.total / PAGE_SIZE)) : 1;
  const stations = overview?.station_shares?.map((s) => s.station) ?? [];

  if (isLoading) {
    return (
      <div className="flex-1 p-8 overflow-y-auto">
        <div className="animate-pulse space-y-4">
          <div className="h-8 w-64 bg-muted rounded" />
          <div className="grid gap-4 md:grid-cols-5">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-24 bg-muted rounded" />
            ))}
          </div>
          <div className="h-64 bg-muted rounded" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <div className="flex flex-wrap justify-between items-center gap-3 mb-2">
        <h1 className="text-3xl font-bold tracking-tight">Ratings</h1>
        <div className="flex items-center gap-2">
          <Select value={range} onValueChange={(v) => { setRange(v); setPage(0); }}>
            <SelectTrigger className="w-40 h-9" data-testid="select-range">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RANGE_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {canEdit && (
            <Button onClick={() => setImportOpen(true)} className="gap-2" data-testid="button-import">
              <Upload className="h-4 w-4" />
              Import CSV
            </Button>
          )}
        </div>
      </div>
      <p className="text-sm text-muted-foreground mb-8">
        {overview?.own_stations?.length
          ? `Tracking ${overview.own_stations.join(", ")} against the market · provider-agnostic (CSV import today, measurement API when available)`
          : "Set OWN_STATIONS to mark your stations — all imported records are treated as competitive until then."}
      </p>

      <div className="grid gap-4 grid-cols-2 md:grid-cols-5 mb-8">
        <div className="border border-border bg-card rounded-md p-4">
          <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
            <BarChart3 className="h-3.5 w-3.5" /> Avg Rating
          </div>
          <p className="text-2xl font-bold" data-testid="kpi-avg-rating">{fmtNum(kpis?.avg_rating)}</p>
          <p className="text-xs text-muted-foreground mt-0.5">household points, own stations</p>
        </div>
        <div className="border border-border bg-card rounded-md p-4">
          <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
            <TrendingUp className="h-3.5 w-3.5" /> Avg Share
          </div>
          <p className="text-2xl font-bold">{fmtNum(kpis?.avg_share)}</p>
          <p className="text-xs text-muted-foreground mt-0.5">% of homes using TV</p>
        </div>
        <div className="border border-border bg-card rounded-md p-4">
          <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
            <Tv className="h-3.5 w-3.5" /> Peak Viewers
          </div>
          <p className="text-2xl font-bold">{fmtViewers(kpis?.peak_viewers)}</p>
          <p className="text-xs text-muted-foreground mt-0.5">best single airing</p>
        </div>
        <div className="border border-border bg-card rounded-md p-4">
          <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
            <Trophy className="h-3.5 w-3.5" /> Programs
          </div>
          <p className="text-2xl font-bold">{kpis?.program_count ?? 0}</p>
        </div>
        <div className="border border-border bg-card rounded-md p-4">
          <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
            <History className="h-3.5 w-3.5" /> Airings
          </div>
          <p className="text-2xl font-bold">{kpis?.record_count ?? 0}</p>
          <p className="text-xs text-muted-foreground mt-0.5">own-station records in range</p>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2 mb-8">
        <div className="border border-border bg-card rounded-md p-4">
          <h2 className="text-sm font-semibold mb-4 flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-primary" />
            Own-Station Trend
          </h2>
          {overview?.trend?.length ? (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={overview.trend} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                  tickFormatter={(d: string) => d.slice(5)}
                  interval="preserveStartEnd"
                />
                <YAxis tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
                <ChartTooltip contentStyle={chartTooltipStyle} />
                <Line type="monotone" dataKey="avg_rating" name="Rating" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="avg_share" name="Share" stroke="hsl(var(--muted-foreground))" strokeWidth={1.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-sm text-muted-foreground py-12 text-center">No records in this range yet.</p>
          )}
        </div>

        <div className="border border-border bg-card rounded-md p-4">
          <h2 className="text-sm font-semibold mb-4 flex items-center gap-2">
            <Tv className="h-4 w-4 text-primary" />
            Station Share Ranking
          </h2>
          {overview?.station_shares?.length ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={overview.station_shares} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
                <YAxis
                  type="category"
                  dataKey="station"
                  width={60}
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                />
                <ChartTooltip contentStyle={chartTooltipStyle} formatter={(v: number) => [fmtNum(v), "Avg share"]} />
                <Bar dataKey="avg_share" radius={[0, 3, 3, 0]}>
                  {overview.station_shares.map((s) => (
                    <Cell key={s.station} fill={s.is_own ? "hsl(var(--primary))" : "hsl(var(--muted-foreground) / 0.35)"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-sm text-muted-foreground py-12 text-center">No records in this range yet.</p>
          )}
        </div>
      </div>

      {overview?.top_programs?.length ? (
        <div className="border border-border bg-card rounded-md p-4 mb-8">
          <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <Trophy className="h-4 w-4 text-primary" />
            Top Own Programs
          </h2>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Program</TableHead>
                <TableHead>Station</TableHead>
                <TableHead className="text-right">Airings</TableHead>
                <TableHead className="text-right">Avg Rating</TableHead>
                <TableHead className="text-right">Avg Share</TableHead>
                <TableHead className="text-right">Best Rating</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {overview.top_programs.map((p) => (
                <TableRow key={`${p.program_title}-${p.station}`}>
                  <TableCell className="font-medium">{p.program_title}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-xs">{p.station}</Badge>
                  </TableCell>
                  <TableCell className="text-right">{p.airings}</TableCell>
                  <TableCell className="text-right">{fmtNum(p.avg_rating)}</TableCell>
                  <TableCell className="text-right">{fmtNum(p.avg_share)}</TableCell>
                  <TableCell className="text-right font-medium">{fmtNum(p.best_rating)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}

      <div className="border border-border bg-card rounded-md p-4">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
          <h2 className="text-sm font-semibold flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-primary" />
            Records
            {list && <span className="text-muted-foreground font-normal">({list.total})</span>}
          </h2>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={q}
                onChange={(e) => { setQ(e.target.value); setPage(0); }}
                placeholder="Filter programs..."
                className="h-8 w-48 pl-8 text-sm"
                data-testid="input-filter-program"
              />
            </div>
            <Select value={stationFilter} onValueChange={(v) => { setStationFilter(v); setPage(0); }}>
              <SelectTrigger className="w-32 h-8 text-sm" data-testid="select-station">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All stations</SelectItem>
                {stations.map((s) => (
                  <SelectItem key={s} value={s}>{s}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {list?.items?.length ? (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Slot</TableHead>
                  <TableHead>Station</TableHead>
                  <TableHead>Program</TableHead>
                  <TableHead className="text-right">Rating</TableHead>
                  <TableHead className="text-right">Share</TableHead>
                  <TableHead className="text-right">Viewers</TableHead>
                  <TableHead>Asset</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.items.map((r) => (
                  <TableRow key={r.id} data-testid={`row-rating-${r.id}`}>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{r.air_date}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground text-xs">
                      {r.start_time ? `${r.start_time}${r.end_time ? `–${r.end_time}` : ""}` : "—"}
                    </TableCell>
                    <TableCell>
                      <Badge variant={r.is_own ? "default" : "outline"} className="text-xs">
                        {r.station}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-medium">{r.program_title}</TableCell>
                    <TableCell className="text-right">{fmtNum(r.rating)}</TableCell>
                    <TableCell className="text-right">{fmtNum(r.share)}</TableCell>
                    <TableCell className="text-right">{fmtViewers(r.viewers)}</TableCell>
                    <TableCell>
                      {r.asset_id ? (
                        <span className="inline-flex items-center gap-1">
                          <Link
                            href={`/library/${r.asset_id}`}
                            className="text-xs text-primary hover:underline inline-flex items-center gap-1 max-w-40 truncate"
                          >
                            <Film className="h-3 w-3 flex-shrink-0" />
                            <span className="truncate">{r.asset_filename ?? r.asset_id}</span>
                          </Link>
                          {canEdit && (
                            <button
                              className="text-muted-foreground hover:text-foreground"
                              title="Unlink asset"
                              onClick={() => unlink(r)}
                              data-testid={`button-unlink-${r.id}`}
                            >
                              <X className="h-3 w-3" />
                            </button>
                          )}
                        </span>
                      ) : canEdit ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 gap-1 text-xs text-muted-foreground"
                          onClick={() => setLinkTarget(r)}
                          data-testid={`button-link-${r.id}`}
                        >
                          <Link2 className="h-3 w-3" />
                          Link
                        </Button>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div className="flex items-center justify-between mt-3">
              <p className="text-xs text-muted-foreground">
                Page {page + 1} of {totalPages}
              </p>
              <div className="flex gap-1">
                <Button size="sm" variant="outline" className="h-7 w-7 p-0" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                  <ChevronLeft className="h-3.5 w-3.5" />
                </Button>
                <Button size="sm" variant="outline" className="h-7 w-7 p-0" disabled={page + 1 >= totalPages} onClick={() => setPage((p) => p + 1)}>
                  <ChevronRight className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          </>
        ) : (
          <p className="text-sm text-muted-foreground py-8 text-center">
            No ratings records match. Import a CSV to get started.
          </p>
        )}
      </div>

      <ImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={invalidateRatings}
      />
      <LinkAssetDialog
        record={linkTarget}
        onClose={() => setLinkTarget(null)}
        onLinked={invalidateRatings}
      />
    </div>
  );
}

function ImportDialog({
  open,
  onClose,
  onImported,
}: {
  open: boolean;
  onClose: () => void;
  onImported: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [provider, setProvider] = useState("nielsen");
  const [market, setMarket] = useState("");
  const [result, setResult] = useState<RatingsImport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const importRatings = useImportRatings();
  const deleteImport = useDeleteRatingsImport();
  const { data: imports } = useListRatingsImports({
    query: { queryKey: getListRatingsImportsQueryKey(), enabled: open },
  });

  const reset = () => {
    setFile(null);
    setResult(null);
    setError(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  const submit = () => {
    if (!file) return;
    setError(null);
    importRatings.mutate(
      { data: { file, provider, ...(market.trim() ? { market: market.trim() } : {}) } },
      {
        onSuccess: (imp) => {
          setResult(imp);
          setFile(null);
          if (fileRef.current) fileRef.current.value = "";
          onImported();
        },
        onError: (e: any) => {
          setError(e?.data?.detail ?? e?.data?.error ?? "Import failed — check the file format.");
        },
      },
    );
  };

  const removeImport = (id: string) => {
    deleteImport.mutate({ id }, { onSuccess: onImported });
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) { reset(); onClose(); } }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Import Ratings CSV</DialogTitle>
          <DialogDescription>
            Columns: date, station, program (required) plus start, end, rating, share, viewers,
            market, and any demo_* columns.{" "}
            <button className="text-primary hover:underline inline-flex items-center gap-1" onClick={downloadTemplate}>
              <Download className="h-3 w-3" /> Download template
            </button>
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            className="block w-full text-sm text-muted-foreground file:mr-3 file:rounded-md file:border-0 file:bg-primary/10 file:px-3 file:py-1.5 file:text-sm file:text-primary hover:file:bg-primary/20"
            onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); setError(null); }}
            data-testid="input-csv-file"
          />
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Provider</label>
              <Select value={provider} onValueChange={setProvider}>
                <SelectTrigger className="h-9" data-testid="select-provider">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PROVIDERS.map((p) => (
                    <SelectItem key={p} value={p}>{p}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Default market (optional)</label>
              <Input value={market} onChange={(e) => setMarket(e.target.value)} placeholder="Columbus, OH" className="h-9" />
            </div>
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}
          {result && (
            <div className="border border-border rounded-md p-3 text-sm bg-muted/30">
              <p>
                Imported <span className="font-semibold">{result.row_count}</span> rows
                {result.error_count > 0 && (
                  <span className="text-muted-foreground"> · {result.error_count} skipped</span>
                )}
              </p>
              {result.errors?.length ? (
                <ul className="mt-1 text-xs text-muted-foreground list-disc pl-4">
                  {result.errors.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          )}

          {imports?.length ? (
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-1.5">Import history</p>
              <div className="space-y-1 max-h-40 overflow-y-auto">
                {imports.map((imp) => (
                  <div key={imp.id} className="flex items-center gap-2 text-xs border border-border rounded px-2 py-1.5">
                    <span className="font-medium truncate flex-1">{imp.filename}</span>
                    <Badge variant="outline" className="text-[10px]">{imp.provider}</Badge>
                    <span className="text-muted-foreground whitespace-nowrap">
                      {imp.row_count} rows · {new Date(imp.created_at).toLocaleDateString()}
                    </span>
                    <button
                      className="text-muted-foreground hover:text-destructive"
                      title="Delete this import and all its records"
                      disabled={deleteImport.isPending}
                      onClick={() => removeImport(imp.id)}
                      data-testid={`button-delete-import-${imp.id}`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => { reset(); onClose(); }}>Close</Button>
          <Button onClick={submit} disabled={!file || importRatings.isPending} data-testid="button-submit-import">
            {importRatings.isPending ? "Importing..." : "Import"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function LinkAssetDialog({
  record,
  onClose,
  onLinked,
}: {
  record: RatingRecord | null;
  onClose: () => void;
  onLinked: () => void;
}) {
  const [search, setSearch] = useState("");
  const updateRating = useUpdateRating();
  const params = { limit: 200, ...(search.trim() ? { search: search.trim() } : {}) };
  const { data: media } = useListMedia(params, {
    query: { queryKey: [`/api/media`, "ratings-link", params], enabled: !!record },
  });

  const link = (assetId: string) => {
    if (!record) return;
    updateRating.mutate(
      { id: record.id, data: { asset_id: assetId } },
      {
        onSuccess: () => {
          onLinked();
          onClose();
        },
      },
    );
  };

  return (
    <Dialog open={!!record} onOpenChange={(o) => { if (!o) { setSearch(""); onClose(); } }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Link to Library Asset</DialogTitle>
          <DialogDescription>
            {record ? `${record.program_title} · ${record.station} · ${record.air_date}` : ""}
          </DialogDescription>
        </DialogHeader>
        <div className="relative">
          <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search library..."
            className="h-9 pl-8"
            data-testid="input-link-search"
          />
        </div>
        <div className="max-h-64 overflow-y-auto space-y-1">
          {media?.items?.length ? (
            media.items.map((a) => (
              <button
                key={a.id}
                className="w-full flex items-center gap-2 text-left text-sm border border-border rounded px-2.5 py-2 hover:border-primary transition-colors disabled:opacity-50"
                disabled={updateRating.isPending}
                onClick={() => link(a.id)}
                data-testid={`button-pick-asset-${a.id}`}
              >
                <Film className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
                <span className="truncate">{a.filename}</span>
              </button>
            ))
          ) : (
            <p className="text-sm text-muted-foreground py-6 text-center">No assets found.</p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
