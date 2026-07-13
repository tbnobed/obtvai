import { useListJobs, getListJobsQueryKey, useRetryJob, useCancelJob } from "@workspace/api-client-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Play, Square } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

export default function Jobs() {
  const { data: jobs, isLoading } = useListJobs(undefined, { query: { queryKey: getListJobsQueryKey(), refetchInterval: 3000 } });
  const retryMutation = useRetryJob();
  const cancelMutation = useCancelJob();
  const queryClient = useQueryClient();

  const handleRetry = (id: string) => {
    retryMutation.mutate({ id }, { onSuccess: () => queryClient.invalidateQueries({ queryKey: getListJobsQueryKey() }) });
  };

  const handleCancel = (id: string) => {
    cancelMutation.mutate({ id }, { onSuccess: () => queryClient.invalidateQueries({ queryKey: getListJobsQueryKey() }) });
  };

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <h1 className="text-3xl font-bold tracking-tight mb-8">Processing Pipeline</h1>

      {isLoading ? (
        <div className="space-y-4">
          {[...Array(5)].map((_, i) => <div key={i} className="h-16 bg-muted animate-pulse rounded-md" />)}
        </div>
      ) : (
        <div className="space-y-4">
          {jobs?.map(job => (
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
                    {job.filename || job.media_id}
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
          {!jobs?.length && (
            <div className="text-center text-muted-foreground py-12">No processing jobs found.</div>
          )}
        </div>
      )}
    </div>
  );
}
