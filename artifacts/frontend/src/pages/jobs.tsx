import { useState } from "react";
import { useListJobs, getListJobsQueryKey, useGetJobStats, getGetJobStatsQueryKey, useRetryJob, useRetryFailedJobs, useCancelJob, useCleanupJobs, useReindexLibrary, useResumeStalledMedia } from "@workspace/api-client-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Play, Square, Trash2, DatabaseZap } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

export default function Jobs() {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const listParams = statusFilter ? { status: statusFilter } : undefined;
  const { data: jobs, isLoading } = useListJobs(listParams, { query: { queryKey: getListJobsQueryKey(listParams), refetchInterval: 3000 } });
  const { data: stats } = useGetJobStats({ query: { queryKey: getGetJobStatsQueryKey(), refetchInterval: 5000 } });
  const retryMutation = useRetryJob();
  const retryFailedMutation = useRetryFailedJobs();
  const cancelMutation = useCancelJob();
  const cleanupMutation = useCleanupJobs();
  const reindexMutation = useReindexLibrary();
  const resumeStalledMutation = useResumeStalledMedia();
  const [reindexMessage, setReindexMessage] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const handleReindex = () => {
    if (!window.confirm("Rebuild the search index for the whole library? This re-embeds every ready asset (transcript + visual vectors).")) return;
    reindexMutation.mutate(undefined, {
      onSuccess: (result) => {
        setReindexMessage(
          result.assets_queued > 0
            ? `Queued ${result.jobs_created} indexing jobs across ${result.assets_queued} assets.`
            : "Nothing to reindex — all assets are already queued or processing."
        );
        queryClient.invalidateQueries({ queryKey: getListJobsQueryKey() });
      },
      onError: () => setReindexMessage("Reindex request failed — check the API server."),
    });
  };

  const handleRetry = (id: string) => {
    retryMutation.mutate({ id }, { onSuccess: () => queryClient.invalidateQueries({ queryKey: getListJobsQueryKey() }) });
  };

  const handleCancel = (id: string) => {
    cancelMutation.mutate({ id }, { onSuccess: () => queryClient.invalidateQueries({ queryKey: getListJobsQueryKey() }) });
  };

  const handleCleanup = (statuses?: string[]) => {
    cleanupMutation.mutate(
      { data: statuses ? { statuses } : {} },
      { onSuccess: () => queryClient.invalidateQueries({ queryKey: getListJobsQueryKey() }) }
    );
  };

  const filtered = jobs;
  const finishedCount = jobs?.filter(j => j.status === "success" || j.status === "error" || j.status === "cancelled").length ?? 0;
  const errorCount = jobs?.filter(j => j.status === "error").length ?? 0;

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <div className="flex justify-between items-center mb-8 flex-wrap gap-3">
        <h1 className="text-3xl font-bold tracking-tight">Processing Pipeline</h1>
        <div className="flex gap-3 items-center">
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="h-9 px-3 py-1 rounded-md border border-input bg-background text-sm"
          >
            <option value="">All Statuses</option>
            <option value="running">Running</option>
            <option value="pending">Pending</option>
            <option value="success">Success</option>
            <option value="error">Error</option>
            <option value="cancelled">Cancelled</option>
          </select>
          <Button
            size="sm"
            variant="outline"
            className="gap-1.5"
            onClick={handleReindex}
            disabled={reindexMutation.isPending}
          >
            <DatabaseZap className="h-3.5 w-3.5" />
            {reindexMutation.isPending ? "Queuing..." : "Rebuild Search Index"}
          </Button>
          {(stats?.jobs_error ?? 0) > 0 && (
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5"
              onClick={() =>
                retryFailedMutation.mutate(undefined, {
                  onSuccess: () => {
                    queryClient.invalidateQueries({ queryKey: getListJobsQueryKey() });
                    queryClient.invalidateQueries({ queryKey: getGetJobStatsQueryKey() });
                  },
                })
              }
              disabled={retryFailedMutation.isPending}
            >
              <Play className="h-3.5 w-3.5" />
              {retryFailedMutation.isPending ? "Queuing..." : `Retry All Failed (${stats?.jobs_error ?? 0})`}
            </Button>
          )}
          {errorCount > 0 && (
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5"
              onClick={() => handleCleanup(["error"])}
              disabled={cleanupMutation.isPending}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Clear Errors ({errorCount})
            </Button>
          )}
          {finishedCount > 0 && (
            <Button
              size="sm"
              variant="secondary"
              className="gap-1.5"
              onClick={() => handleCleanup()}
              disabled={cleanupMutation.isPending}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Clear Finished ({finishedCount})
            </Button>
          )}
        </div>
      </div>

      {stats && (stats.jobs_pending > 0 || stats.jobs_running > 0 || stats.assets_processing > 0) && (
        <div className="mb-6 border border-border bg-card rounded-md p-5">
          <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
            <div className="font-semibold">Pipeline Progress</div>
            <div className="text-sm text-muted-foreground">
              {stats.assets_ready} of {stats.assets_total} assets ready
              {stats.assets_error > 0 && <span className="text-destructive"> · {stats.assets_error} failed</span>}
            </div>
          </div>
          <div className="w-full bg-secondary h-2.5 rounded-full overflow-hidden mb-4">
            <div
              className="bg-primary h-full transition-all"
              style={{ width: `${stats.assets_total ? Math.round((stats.assets_ready / stats.assets_total) * 100) : 0}%` }}
            />
          </div>
          <div className="flex items-center gap-4 text-sm text-muted-foreground mb-3">
            <span><span className="text-foreground font-medium">{stats.jobs_running}</span> running</span>
            <span><span className="text-foreground font-medium">{stats.jobs_pending}</span> queued</span>
            {stats.jobs_error > 0 && <span className="text-destructive font-medium">{stats.jobs_error} errors</span>}
            {stats.assets_processing > 0 && stats.jobs_pending === 0 && stats.jobs_running === 0 && (
              <Button
                size="sm"
                variant="outline"
                className="gap-1.5"
                onClick={() =>
                  resumeStalledMutation.mutate(undefined, {
                    onSuccess: (result) => {
                      setReindexMessage(
                        result.jobs_created > 0
                          ? `Resumed ${result.assets_resumed} stalled assets (${result.jobs_created} jobs queued${result.assets_marked_ready > 0 ? `, ${result.assets_marked_ready} marked ready` : ""}).`
                          : result.assets_marked_ready > 0
                            ? `${result.assets_marked_ready} assets were already complete and are now marked ready.`
                            : "No stalled assets found."
                      );
                      queryClient.invalidateQueries({ queryKey: getListJobsQueryKey() });
                      queryClient.invalidateQueries({ queryKey: getGetJobStatsQueryKey() });
                    },
                    onError: () => setReindexMessage("Resume request failed — check the API server."),
                  })
                }
                disabled={resumeStalledMutation.isPending}
              >
                <Play className="h-3.5 w-3.5" />
                {resumeStalledMutation.isPending ? "Resuming..." : `Resume Stalled (${stats.assets_processing})`}
              </Button>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {stats.stages
              .filter(s => s.pending + s.running > 0)
              .map(s => (
                <div key={s.job_type} className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-secondary text-xs">
                  <span className="font-medium">{s.job_type}</span>
                  {s.running > 0 && <span className="text-primary">{s.running} active</span>}
                  <span className="text-muted-foreground">{s.pending} queued</span>
                  {s.error > 0 && <span className="text-destructive">{s.error} failed</span>}
                </div>
              ))}
          </div>
        </div>
      )}

      {reindexMessage && (
        <div className="mb-6 px-4 py-3 rounded-md border border-border bg-card text-sm text-muted-foreground">
          {reindexMessage}
        </div>
      )}

      {isLoading ? (
        <div className="space-y-4">
          {[...Array(5)].map((_, i) => <div key={i} className="h-16 bg-muted animate-pulse rounded-md" />)}
        </div>
      ) : (
        <div className="space-y-4">
          {filtered?.map(job => (
            <div key={job.id} className="border border-border bg-card rounded-md p-4">
              <div className="flex items-center justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-1">
                    <span className="font-semibold">{job.job_type}</span>
                    <Badge variant={job.status === 'success' ? 'default' : job.status === 'error' ? 'destructive' : 'secondary'}>
                      {job.status}
                    </Badge>
                  </div>
                  <div className="text-sm text-muted-foreground font-mono truncate max-w-md" title={job.filename || "Unknown file"}>
                    {job.filename || job.media_id || "Library-wide"}
                  </div>
                </div>

                <div className="w-64 mx-4">
                  {job.status === 'running' && (
                    <div className="w-full bg-secondary h-2 rounded-full overflow-hidden">
                      <div className="bg-primary h-full transition-all" style={{ width: `${job.progress || 0}%` }} />
                    </div>
                  )}
                </div>

                <div className="flex gap-2">
                  {(job.status === 'success' || job.status === 'error' || job.status === 'cancelled') && (
                    <Button size="sm" variant="outline" onClick={() => handleRetry(job.id)} disabled={retryMutation.isPending}>
                      <Play className="h-4 w-4 mr-1" /> {job.status === 'success' ? 'Re-run' : 'Retry'}
                    </Button>
                  )}
                  {(job.status === 'running' || job.status === 'pending') && (
                    <Button size="sm" variant="destructive" onClick={() => handleCancel(job.id)} disabled={cancelMutation.isPending}>
                      <Square className="h-4 w-4 mr-1" /> Cancel
                    </Button>
                  )}
                </div>
              </div>
              {job.error_message && (
                <div className="mt-4 p-2 bg-destructive/10 text-destructive text-sm rounded font-mono">
                  {job.error_message}
                </div>
              )}
            </div>
          ))}
          {!filtered?.length && (
            <div className="text-center text-muted-foreground py-12">
              {statusFilter ? `No ${statusFilter} jobs.` : "No processing jobs found."}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
