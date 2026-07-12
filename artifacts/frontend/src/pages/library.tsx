import { useState } from "react";
import { useListMedia, getListMediaQueryKey, useIngestMedia } from "@workspace/api-client-react";
import { Link } from "wouter";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Film, Upload, Plus } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";

export default function Library() {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const { data, isLoading } = useListMedia({ status: statusFilter || undefined }, { query: { queryKey: getListMediaQueryKey({ status: statusFilter || undefined }) } });
  
  const queryClient = useQueryClient();
  const ingest = useIngestMedia();
  const [ingestPath, setIngestPath] = useState("");
  const [ingestTitle, setIngestTitle] = useState("");
  const [ingestOpen, setIngestOpen] = useState(false);

  const handleIngest = (e: React.FormEvent) => {
    e.preventDefault();
    if (!ingestPath) return;
    ingest.mutate({ data: { file_path: ingestPath, title: ingestTitle || undefined } }, {
      onSuccess: () => {
        setIngestOpen(false);
        setIngestPath("");
        setIngestTitle("");
        queryClient.invalidateQueries({ queryKey: getListMediaQueryKey() });
      }
    });
  };

  return (
    <div className="flex-1 p-8 overflow-y-auto flex flex-col">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold tracking-tight">Media Library</h1>
        <div className="flex gap-4 items-center">
          <select 
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="h-9 px-3 py-1 rounded-md border border-input bg-background text-sm"
          >
            <option value="">All Statuses</option>
            <option value="ready">Ready</option>
            <option value="processing">Processing</option>
            <option value="pending">Pending</option>
            <option value="error">Error</option>
          </select>
          <Dialog open={ingestOpen} onOpenChange={setIngestOpen}>
            <DialogTrigger asChild>
              <Button className="gap-2">
                <Plus className="h-4 w-4" />
                Ingest File
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Ingest Media</DialogTitle>
              </DialogHeader>
              <form onSubmit={handleIngest} className="space-y-4 pt-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium">Absolute File Path</label>
                  <Input 
                    value={ingestPath} 
                    onChange={e => setIngestPath(e.target.value)}
                    placeholder="/data/media/video.mp4"
                    required
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Title (Optional)</label>
                  <Input 
                    value={ingestTitle} 
                    onChange={e => setIngestTitle(e.target.value)}
                    placeholder="Interview setup"
                  />
                </div>
                <Button type="submit" className="w-full" disabled={ingest.isPending}>
                  {ingest.isPending ? "Ingesting..." : "Start Ingest"}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {[...Array(10)].map((_, i) => (
            <div key={i} className="animate-pulse bg-muted aspect-video rounded-md" />
          ))}
        </div>
      ) : data?.items.length ? (
        <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {data.items.map(asset => (
            <Link key={asset.id} href={`/library/${asset.id}`}>
              <div className="group border border-border bg-card rounded-md overflow-hidden cursor-pointer hover:border-primary transition-colors flex flex-col h-full">
                <div className="aspect-video bg-muted relative">
                  {asset.thumbnail_url ? (
                    <img src={`/api/thumbnails/${asset.thumbnail_url}`} alt={asset.filename} className="w-full h-full object-cover" />
                  ) : (
                    <div className="absolute inset-0 flex items-center justify-center">
                      <Film className="h-8 w-8 text-muted-foreground/50" />
                    </div>
                  )}
                  <div className="absolute bottom-2 right-2">
                    <Badge variant={asset.status === 'ready' ? 'default' : asset.status === 'error' ? 'destructive' : 'secondary'} className="text-xs">
                      {asset.status}
                    </Badge>
                  </div>
                </div>
                <div className="p-3 flex-1">
                  <p className="text-sm font-medium truncate" title={asset.filename}>{asset.filename}</p>
                  {asset.duration_seconds ? (
                    <p className="text-xs text-muted-foreground mt-1">{Math.floor(asset.duration_seconds / 60)}m {Math.floor(asset.duration_seconds % 60)}s</p>
                  ) : null}
                </div>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground">
          <Upload className="h-12 w-12 mb-4 opacity-50" />
          <p>No media assets found.</p>
        </div>
      )}
    </div>
  );
}
