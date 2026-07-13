import { useEffect, useRef, useState } from "react";
import { useParams, useSearch, useLocation } from "wouter";
import { 
  useGetMedia, getGetMediaQueryKey,
  useGetMediaScenes, getGetMediaScenesQueryKey,
  useGetMediaTranscript, getGetMediaTranscriptQueryKey,
  useListJobs, getListJobsQueryKey,
  useDeleteMedia, getListMediaQueryKey
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Trash2, Sparkles } from "lucide-react";

function formatTimecode(seconds: number): string {
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

export default function AssetDetail() {
  const { id } = useParams<{ id: string }>();
  const searchString = useSearch();
  const searchParams = new URLSearchParams(searchString);
  const timeParam = searchParams.get('t');
  
  const videoRef = useRef<HTMLVideoElement>(null);
  const [, navigate] = useLocation();
  const queryClient = useQueryClient();
  const deleteMutation = useDeleteMedia();
  const [confirmDelete, setConfirmDelete] = useState(false);

  const handleDelete = () => {
    if (!id) return;
    deleteMutation.mutate({ id }, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListMediaQueryKey() });
        navigate("/library");
      }
    });
  };

  const { data: asset, isLoading } = useGetMedia(id!, { 
    query: { 
      enabled: !!id, 
      queryKey: getGetMediaQueryKey(id!),
      refetchInterval: (data) => data?.state?.data?.status === 'processing' ? 3000 : false
    } 
  });

  const { data: scenes } = useGetMediaScenes(id!, { query: { enabled: !!id, queryKey: getGetMediaScenesQueryKey(id!) } });
  const { data: transcript } = useGetMediaTranscript(id!, { query: { enabled: !!id, queryKey: getGetMediaTranscriptQueryKey(id!) } });
  const { data: jobs } = useListJobs({ media_id: id! }, { query: { enabled: !!id, queryKey: getListJobsQueryKey({ media_id: id! }), refetchInterval: 3000 } });

  useEffect(() => {
    if (timeParam && videoRef.current && asset?.status === 'ready') {
      const t = parseFloat(timeParam);
      if (!isNaN(t)) {
        videoRef.current.currentTime = t;
        // Optionally auto-play
        // videoRef.current.play().catch(() => {});
      }
    }
  }, [timeParam, asset?.status]);

  const seekTo = (time: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = time;
      videoRef.current.play();
    }
  };

  if (isLoading) {
    return <div className="p-8">Loading asset...</div>;
  }

  if (!asset) {
    return <div className="p-8">Asset not found.</div>;
  }

  const hasAnalysis = Boolean(
    asset.synopsis ||
    (asset.key_moments && asset.key_moments.length > 0) ||
    (asset.topics && asset.topics.length > 0)
  );

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      <div className="flex-1 flex overflow-hidden">
        {/* Main Content Area */}
        <div className="flex-1 flex flex-col overflow-y-auto">
          <div className="p-6 bg-black flex-shrink-0 relative">
            {asset.status === 'ready' ? (
              <video 
                ref={videoRef}
                src={`/api/media/${id}/stream`} 
                controls 
                className="w-full max-h-[60vh] object-contain bg-black"
              />
            ) : (
              <div className="w-full h-64 bg-muted flex flex-col items-center justify-center">
                <p className="text-muted-foreground mb-2">Media is {asset.status}</p>
                {asset.processing_stage && (
                  <Badge variant="outline">{asset.processing_stage} {asset.processing_progress}%</Badge>
                )}
              </div>
            )}
          </div>
          
          <div className="p-6">
            <div className="flex items-start justify-between gap-4 mb-2">
              <h1 className="text-2xl font-bold">{asset.filename}</h1>
              <Button 
                variant="outline" 
                size="sm" 
                className="gap-2 text-destructive hover:text-destructive shrink-0"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 className="h-4 w-4" />
                Remove from Library
              </Button>
            </div>
            <div className="flex gap-4 text-sm text-muted-foreground mb-6">
              <span>{asset.codec}</span>
              <span>{asset.width}x{asset.height}</span>
              <span>{asset.fps} fps</span>
            </div>

            <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Remove from library?</DialogTitle>
                </DialogHeader>
                <p className="text-sm text-muted-foreground">
                  This removes <span className="font-medium text-foreground">{asset.filename}</span> from 
                  the index — its transcript, scenes, and search entries. The source video file on disk 
                  is never touched and can be re-ingested later.
                </p>
                <div className="flex justify-end gap-2 pt-2">
                  <Button variant="outline" onClick={() => setConfirmDelete(false)}>Cancel</Button>
                  <Button variant="destructive" onClick={handleDelete} disabled={deleteMutation.isPending}>
                    {deleteMutation.isPending ? "Removing..." : "Remove"}
                  </Button>
                </div>
              </DialogContent>
            </Dialog>

            <Tabs defaultValue={hasAnalysis ? "analysis" : "scenes"}>
              <TabsList>
                <TabsTrigger value="analysis" className="gap-1.5">
                  <Sparkles className="h-3.5 w-3.5" />
                  AI Analysis
                </TabsTrigger>
                <TabsTrigger value="scenes">Scenes</TabsTrigger>
                <TabsTrigger value="jobs">Pipeline Jobs</TabsTrigger>
              </TabsList>
              <TabsContent value="analysis" className="mt-4">
                {hasAnalysis ? (
                  <div className="space-y-6 max-w-3xl">
                    {asset.synopsis && (
                      <div>
                        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">Synopsis</h3>
                        <p className="text-sm text-muted-foreground leading-relaxed">{asset.synopsis}</p>
                      </div>
                    )}
                    {asset.key_moments && asset.key_moments.length > 0 && (
                      <div>
                        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">Key Moments</h3>
                        <div className="space-y-1">
                          {asset.key_moments.map((moment, i) => (
                            <div
                              key={i}
                              className="flex gap-3 items-baseline p-2 -mx-2 rounded cursor-pointer hover:bg-muted transition-colors"
                              onClick={() => seekTo(moment.time)}
                            >
                              <span className="text-xs font-mono text-primary shrink-0 w-12 text-right">
                                {formatTimecode(moment.time)}
                              </span>
                              <div>
                                <div className="text-sm font-medium">{moment.title}</div>
                                {moment.description && (
                                  <div className="text-xs text-muted-foreground">{moment.description}</div>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {asset.topics && asset.topics.length > 0 && (
                      <div>
                        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">Topics</h3>
                        <div className="flex flex-wrap gap-1.5">
                          {asset.topics.map(topic => (
                            <Badge key={topic} variant="secondary" className="text-xs">{topic}</Badge>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground py-8 text-center">
                    No AI analysis yet. It is generated automatically after indexing completes —
                    or re-run the index job from the Pipeline Jobs tab.
                  </div>
                )}
              </TabsContent>
              <TabsContent value="scenes" className="mt-4">
                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
                  {scenes?.map(scene => (
                    <div 
                      key={scene.id} 
                      className="cursor-pointer group"
                      onClick={() => seekTo(scene.start_time)}
                    >
                      <div className="aspect-video bg-muted rounded overflow-hidden mb-2 relative">
                        {scene.thumbnail_url && (
                          <img src={`/api/thumbnails/${scene.thumbnail_url}`} className="w-full h-full object-cover group-hover:scale-105 transition-transform" />
                        )}
                        <div className="absolute bottom-1 right-1 bg-black/80 px-1 py-0.5 rounded text-[10px] text-white">
                          {Math.floor(scene.start_time)}s
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </TabsContent>
              <TabsContent value="jobs" className="mt-4">
                <div className="space-y-2">
                  {jobs?.map(job => (
                    <div key={job.id} className="p-3 border border-border rounded flex justify-between items-center">
                      <div>
                        <div className="font-medium">{job.job_type}</div>
                        <div className="text-xs text-muted-foreground">{new Date(job.created_at).toLocaleString()}</div>
                      </div>
                      <Badge variant={job.status === 'success' ? 'default' : job.status === 'error' ? 'destructive' : 'secondary'}>
                        {job.status}
                      </Badge>
                    </div>
                  ))}
                </div>
              </TabsContent>
            </Tabs>
          </div>
        </div>

        {/* Right Sidebar - Transcript */}
        <div className="w-80 border-l border-border flex flex-col bg-card shrink-0">
          <div className="p-4 border-b border-border font-medium flex justify-between items-center">
            Transcript
          </div>
          <ScrollArea className="flex-1 p-4">
            <div className="space-y-4">
              {transcript?.map(segment => (
                <div 
                  key={segment.id} 
                  className="group cursor-pointer hover:bg-muted p-2 -mx-2 rounded transition-colors"
                  onClick={() => seekTo(segment.start_time)}
                >
                  <div className="flex gap-2 items-baseline mb-1">
                    <span className="text-xs font-medium text-primary">{segment.speaker || 'Unknown'}</span>
                    <span className="text-[10px] text-muted-foreground">{Math.floor(segment.start_time)}s</span>
                  </div>
                  <p className="text-sm">{segment.text}</p>
                </div>
              ))}
              {!transcript?.length && (
                <div className="text-sm text-muted-foreground text-center mt-10">No transcript available</div>
              )}
            </div>
          </ScrollArea>
        </div>
      </div>
    </div>
  );
}
