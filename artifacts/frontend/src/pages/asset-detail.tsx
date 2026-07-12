import { useEffect, useRef, useState } from "react";
import { useParams, useSearch } from "wouter";
import { 
  useGetMedia, getGetMediaQueryKey,
  useGetMediaScenes, getGetMediaScenesQueryKey,
  useGetMediaTranscript, getGetMediaTranscriptQueryKey,
  useListJobs, getListJobsQueryKey
} from "@workspace/api-client-react";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";

export default function AssetDetail() {
  const { id } = useParams<{ id: string }>();
  const searchString = useSearch();
  const searchParams = new URLSearchParams(searchString);
  const timeParam = searchParams.get('t');
  
  const videoRef = useRef<HTMLVideoElement>(null);

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
            <h1 className="text-2xl font-bold mb-2">{asset.filename}</h1>
            <div className="flex gap-4 text-sm text-muted-foreground mb-6">
              <span>{asset.codec}</span>
              <span>{asset.width}x{asset.height}</span>
              <span>{asset.fps} fps</span>
            </div>

            <Tabs defaultValue="scenes">
              <TabsList>
                <TabsTrigger value="scenes">Scenes</TabsTrigger>
                <TabsTrigger value="jobs">Pipeline Jobs</TabsTrigger>
              </TabsList>
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
