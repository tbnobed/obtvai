import { useEffect, useState } from "react";
import { useListAuditLog, type AuditLogEntry } from "@workspace/api-client-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Loader2, ScrollText } from "lucide-react";

const PAGE_SIZE = 100;

const METHOD_COLORS: Record<string, string> = {
  POST: "bg-blue-500/15 text-blue-400",
  PATCH: "bg-amber-500/15 text-amber-400",
  PUT: "bg-amber-500/15 text-amber-400",
  DELETE: "bg-red-500/15 text-red-400",
};

function statusColor(code: number): string {
  if (code < 300) return "text-green-500";
  if (code < 500) return "text-amber-500";
  return "text-red-500";
}

export default function AuditLogPage() {
  const [q, setQ] = useState("");
  const [method, setMethod] = useState<string>("all");
  const [page, setPage] = useState(0);
  const [acc, setAcc] = useState<AuditLogEntry[]>([]);

  const params = {
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    ...(q.trim() ? { q: q.trim() } : {}),
    ...(method !== "all" ? { method: method as "POST" | "PUT" | "PATCH" | "DELETE" } : {}),
  };
  const { data, isLoading } = useListAuditLog(params);

  // Accumulate pages; page 0 replaces (fresh filters or refetch).
  useEffect(() => {
    if (!data) return;
    setAcc((prev) => (page === 0 ? data.items : [...prev, ...data.items]));
  }, [data, page]);

  const resetAnd = (fn: () => void) => { fn(); setPage(0); setAcc([]); };

  const items = acc;
  const total = data?.total ?? 0;

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center gap-2 mb-1">
        <ScrollText className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-xl font-semibold">Audit Log</h1>
      </div>
      <p className="text-sm text-muted-foreground mb-4">
        Every change made in the system — logins, uploads, edits, deletions — and who made it.
      </p>

      <div className="flex gap-2 mb-4">
        <Input
          placeholder="Filter by user or path (e.g. obtv-admin, /media)…"
          value={q}
          onChange={(e) => resetAnd(() => setQ(e.target.value))}
          className="max-w-sm"
          data-testid="input-audit-search"
        />
        <Select value={method} onValueChange={(v) => resetAnd(() => setMethod(v))}>
          <SelectTrigger className="w-36" data-testid="select-audit-method">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All actions</SelectItem>
            <SelectItem value="POST">POST — create/run</SelectItem>
            <SelectItem value="PATCH">PATCH — edit</SelectItem>
            <SelectItem value="PUT">PUT — replace</SelectItem>
            <SelectItem value="DELETE">DELETE</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {isLoading && items.length === 0 ? (
        <div className="flex items-center gap-2 text-muted-foreground p-8 justify-center">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading audit log…
        </div>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground p-8 text-center">No matching entries.</p>
      ) : (
        <>
          <div className="border border-border rounded-md overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-muted-foreground">
                <tr>
                  <th className="text-left font-medium px-3 py-2 whitespace-nowrap">Time</th>
                  <th className="text-left font-medium px-3 py-2">User</th>
                  <th className="text-left font-medium px-3 py-2">Action</th>
                  <th className="text-left font-medium px-3 py-2">Path</th>
                  <th className="text-left font-medium px-3 py-2">Status</th>
                  <th className="text-left font-medium px-3 py-2">IP</th>
                </tr>
              </thead>
              <tbody>
                {items.map((r) => (
                  <tr key={r.id} className="border-t border-border" data-testid={`row-audit-${r.id}`}>
                    <td className="px-3 py-2 whitespace-nowrap text-muted-foreground">
                      {new Date(r.created_at).toLocaleString()}
                    </td>
                    <td className="px-3 py-2 font-medium">{r.username ?? "—"}</td>
                    <td className="px-3 py-2">
                      <Badge variant="outline" className={`border-0 ${METHOD_COLORS[r.method] ?? ""}`}>
                        {r.method}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs break-all">{r.path}</td>
                    <td className={`px-3 py-2 font-medium ${statusColor(r.status_code)}`}>{r.status_code}</td>
                    <td className="px-3 py-2 text-muted-foreground">{r.ip ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between mt-3">
            <p className="text-xs text-muted-foreground">
              Showing {items.length} of {total} entries
            </p>
            {items.length < total && (
              <Button size="sm" variant="outline" disabled={isLoading} onClick={() => setPage((p) => p + 1)} data-testid="button-audit-load-more">
                {isLoading ? "Loading…" : "Load more"}
              </Button>
            )}
          </div>
        </>
      )}
      </div>
    </div>
  );
}
