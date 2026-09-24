import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useIsAdmin } from "@/lib/auth";
import { Loader2, RefreshCw } from "lucide-react";

type Stats = Record<string, number | string>;
type Run = {
  id: string;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  stats: Stats;
  options: { dry_run: boolean };
};
type CatalogStatus = {
  automatic_discovery: boolean;
  cutoff: string;
  counts: Record<string, number>;
  checkpoint: { cursor: Record<string, unknown>; last_error: string | null; updated_at: string } | null;
  runs: Run[];
  runner?: { cursor: { paused?: boolean; state?: string; max_inflight?: number }; last_error: string | null; updated_at: string } | null;
  runner_heartbeat_fresh?: boolean;
};
type ReviewItem = {
  asset_id: string;
  asset_type: string;
  error: string | null;
  metadata_snapshot: Record<string, unknown>;
};
type ReviewPage = { items: ReviewItem[]; next: string | null };
type RunResult = { run_id: string; stats: Stats; cursor: Record<string, unknown>; error: string | null };

const KEY = ["curator-catalog"];
const CONFIRM = "QUEUE_BOUNDED_CATALOG";
const GIB = 1024 ** 3;

async function catalogRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/curator/catalog${path}`, {
    credentials: "same-origin",
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const detail = body && typeof body === "object" && "detail" in body ? body.detail : null;
    const text = typeof detail === "string" ? detail :
      Array.isArray(detail) ? detail.map((e: { msg?: string }) => e.msg ?? "Invalid option").join("; ") : response.statusText;
    throw new Error(`HTTP ${response.status}: ${text || "Catalog request failed"}`);
  }
  return response.json() as Promise<T>;
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : "Catalog request failed";
}

function summary(stats: Stats): string {
  return Object.entries(stats).map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`).join(" · ");
}

function date(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "In progress";
}

/** Admin-only, explicitly bounded catalog discovery/admission controls. */
export function CuratorCatalogPanel() {
  const isAdmin = useIsAdmin();
  const client = useQueryClient();
  const submitting = useRef(false);
  const [after, setAfter] = useState("");
  const [pages, setPages] = useState(1);
  const [assets, setAssets] = useState(1);
  const [inflight, setInflight] = useState(1);
  const [paths, setPaths] = useState("/artifacts/audio\n/artifacts/thumbnails");
  const [minFree, setMinFree] = useState(20);
  const [reserve, setReserve] = useState(1);
  const [confirm, setConfirm] = useState("");
  const [result, setResult] = useState<RunResult | null>(null);
  const [actionError, setActionError] = useState("");
  const status = useQuery({
    queryKey: [...KEY, "status"],
    queryFn: () => catalogRequest<CatalogStatus>(""),
    enabled: isAdmin,
    retry: false,
    refetchInterval: 15000,
  });
  const review = useQuery({
    queryKey: [...KEY, "review", after],
    queryFn: () => catalogRequest<ReviewPage>(`/assets?status=review&after=${encodeURIComponent(after)}&limit=100`),
    enabled: isAdmin && status.isSuccess,
    retry: false,
  });
  const run = useMutation({
    mutationFn: (apply: boolean) => catalogRequest<RunResult>("/run", {
      method: "POST",
      body: JSON.stringify({
        dry_run: !apply,
        max_pages: pages,
        max_assets: assets,
        max_inflight: inflight,
        storage_paths: paths.split(/\r?\n/).map(p => p.trim()).filter(Boolean),
        min_free_bytes: minFree * GIB,
        reserve_per_asset_bytes: reserve * GIB,
        confirm: apply ? CONFIRM : "",
      }),
    }),
    onSuccess: (data) => {
      setResult(data);
      setConfirm("");
      void client.invalidateQueries({ queryKey: KEY });
    },
    onError: (error) => setActionError(message(error)),
    onSettled: () => { submitting.current = false; },
  });

  if (!isAdmin) return null;
  const optionsValid = Number.isInteger(pages) && pages >= 1 && pages <= 5 &&
    Number.isInteger(assets) && assets >= 1 && assets <= 10 &&
    Number.isInteger(inflight) && inflight >= 1 && inflight <= 10 &&
    Number.isFinite(minFree) && minFree >= 1 &&
    Number.isFinite(reserve) && reserve >= 0.1;
  const storagePaths = paths.split(/\r?\n/).map(p => p.trim()).filter(Boolean);
  const applyValid = optionsValid && storagePaths.length > 0 && storagePaths.every(p => p.startsWith("/")) && confirm === CONFIRM;
  const submit = (apply: boolean) => {
    if (submitting.current || run.isPending || !status.isSuccess || (apply ? !applyValid : !optionsValid)) return;
    submitting.current = true;
    setActionError("");
    setResult(null);
    run.mutate(apply);
  };

  return (
    <section className="rounded-lg border border-border p-4 space-y-4" aria-label="Bounded catalog">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h2 className="font-semibold">Bounded catalog</h2>
          <p className="text-xs text-muted-foreground">Bounded ingestion by IngestCompleteDate. {status.data ? `Assets before ${status.data.cutoff} are excluded from new admission; existing media is preserved.` : "Loading effective date policy…"}</p>
        </div>
        <Button variant="outline" size="sm" disabled={status.isFetching || review.isFetching || run.isPending}
          onClick={() => { void status.refetch(); void review.refetch(); }}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Refresh
        </Button>
      </div>
      {status.isLoading && <p className="text-sm text-muted-foreground flex gap-2"><Loader2 className="h-4 w-4 animate-spin" /> Loading catalog status...</p>}
      {status.isError && <Alert variant="destructive"><AlertDescription>{message(status.error)}</AlertDescription></Alert>}
      {status.data && (
        <>
          <div className="text-sm space-y-1">
            <p>Automatic discovery: <Badge variant="secondary">{status.data.automatic_discovery ? "On" : "Off"}</Badge> · Cutoff: {status.data.cutoff}</p>
            {status.data.runner && <p>Managed runner: {status.data.runner_heartbeat_fresh ? status.data.runner.cursor.state : "Heartbeat stale / stopped"} · last heartbeat {date(status.data.runner.updated_at)} · maximum inflight {status.data.runner.cursor.max_inflight ?? "unknown"}</p>}
            {status.data.runner?.last_error && <p role="alert" className="text-destructive">Runner: {status.data.runner.last_error}</p>}
            {status.data.runner?.cursor.paused && <Button variant="outline" size="sm" onClick={async () => {
              if (!window.confirm("Resume bounded automatic ingestion after reviewing the reported failure?")) return;
              try {
                await catalogRequest("/runner/resume", { method: "POST" });
                await status.refetch();
              } catch (error) { setActionError(message(error)); }
            }}>Resume managed runner</Button>}
            <p>Counts: {Object.entries(status.data.counts).length ? Object.entries(status.data.counts).map(([key, count]) => `${key}: ${count}`).join(" · ") : "No catalog assets yet"}</p>
            <p className="text-muted-foreground">Checkpoint: {status.data.checkpoint ? `${JSON.stringify(status.data.checkpoint.cursor)} · ${date(status.data.checkpoint.updated_at)}` : "Not started"}</p>
            {status.data.checkpoint?.last_error && <p className="text-destructive">Checkpoint error: {status.data.checkpoint.last_error}</p>}
          </div>
          <div className="border-t pt-4 space-y-3">
            <h3 className="text-sm font-medium">Next bounded batch</h3>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {([
                ["Max pages (1–5)", pages, setPages, 1, 5],
                ["Max assets (1–10)", assets, setAssets, 1, 10],
                ["Max inflight (1–10)", inflight, setInflight, 1, 10],
                ["Min free / volume (GiB)", minFree, setMinFree, 1, 100000],
                ["Reserve / asset (GiB)", reserve, setReserve, 0.1, 100000],
              ] as const).map(([label, value, setter, min, max]) => (
                <label key={label} className="text-xs text-muted-foreground space-y-1">
                  <span>{label}</span>
                  <Input type="number" min={min} max={max} step={min === 0.1 ? 0.1 : 1} value={value}
                    disabled={run.isPending} onChange={e => setter(Number(e.target.value))} className="h-9" />
                </label>
              ))}
            </div>
            <label className="block text-xs text-muted-foreground space-y-1">
              <span>Storage watermark paths (one absolute server directory per line; required for queueing)</span>
              <textarea className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm" rows={2}
                disabled={run.isPending} value={paths} onChange={e => setPaths(e.target.value)} />
            </label>
            <div className="flex flex-wrap gap-2 items-center">
              <Button variant="outline" disabled={run.isPending || !optionsValid} onClick={() => submit(false)}>
                {run.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />} Preview next batch
              </Button>
              <label className="text-xs text-muted-foreground">
                <span className="block mb-1">Type {CONFIRM} to allow queueing</span>
                <Input value={confirm} disabled={run.isPending} onChange={e => setConfirm(e.target.value)}
                  className="h-9 w-64" autoComplete="off" />
              </label>
              <Button disabled={run.isPending || !applyValid} onClick={() => submit(true)}>Queue bounded batch</Button>
            </div>
            <p className="text-xs text-muted-foreground">Preview scans and records a bounded catalog page but queues no jobs. Queueing requires confirmed limits and available storage; neither action enables automatic discovery.</p>
            {actionError && <Alert variant="destructive"><AlertDescription>{actionError}</AlertDescription></Alert>}
            {result && <Alert variant={result.error ? "destructive" : "default"}><AlertDescription>
              Run {result.run_id}: {summary(result.stats)}{result.error && ` · Error: ${result.error}`}
            </AlertDescription></Alert>}
          </div>
          <div className="border-t pt-4 space-y-2">
            <h3 className="text-sm font-medium">Review items</h3>
            {review.isLoading && <p className="text-xs text-muted-foreground">Loading review items...</p>}
            {review.isError && <p className="text-sm text-destructive">{message(review.error)}</p>}
            {review.data?.items.length === 0 && <p className="text-sm text-muted-foreground">No review items in this page.</p>}
            {review.data?.items.map(item => (
              <div key={item.asset_id} className="border rounded-md px-3 py-2 text-xs break-words">
                <strong>{item.asset_id}</strong> · {item.asset_type} · {String(item.metadata_snapshot?.Name ?? "Unnamed")}
                {item.error && <p className="text-destructive mt-1">{item.error}</p>}
              </div>
            ))}
            {after && <Button size="sm" variant="outline" onClick={() => setAfter("")}>First page</Button>}
            {review.data?.next && review.data.items.length === 100 && <Button size="sm" variant="outline" className="ml-2" onClick={() => setAfter(review.data!.next!)}>Next page</Button>}
          </div>
          <div className="border-t pt-4 space-y-2">
            <h3 className="text-sm font-medium">Recent runs</h3>
            {!status.data.runs.length && <p className="text-sm text-muted-foreground">No catalog runs yet.</p>}
            {status.data.runs.map(item => (
              <div key={item.id} className="border rounded-md px-3 py-2 text-xs space-y-1">
                <p><strong>{item.options.dry_run ? "Preview" : "Queued batch"}</strong> · {date(item.started_at)} → {date(item.finished_at)}</p>
                <p className="text-muted-foreground">{summary(item.stats)}</p>
                {item.error && <p className="text-destructive">{item.error}</p>}
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}