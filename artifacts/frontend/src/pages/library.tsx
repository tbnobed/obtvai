import { useRef, useState } from "react";
import { useListMedia, getListMediaQueryKey, useIngestMedia } from "@workspace/api-client-react";
import { Link } from "wouter";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { Film, Upload, Plus } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";

// fetch() cannot report upload progress — use XHR so large uploads show a
// real progress bar instead of an indefinite "uploading..." state.
function uploadFileWithProgress(
  file: File,
  title: string | undefined,
  onProgress: (percent: number) => void,
): { promise: Promise<void>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<void>((resolve, reject) => {
    const formData = new FormData();
    formData.append("file", file);
    if (title) formData.append("title", title);

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`HTTP ${xhr.status}`));
    });
    xhr.addEventListener("error", () => reject(new Error("Network error during upload")));
    xhr.addEventListener("abort", () => reject(new Error("Upload cancelled")));

    xhr.open("POST", "/api/media/upload");
    xhr.send(formData);
  });
  return { promise, abort: () => xhr.abort() };
}

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

  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const abortUploadRef = useRef<(() => void) | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const VIDEO_EXTENSIONS = [".mp4", ".mov", ".mkv", ".avi", ".mxf", ".ts", ".m2ts", ".wmv", ".flv", ".webm"];

  const pickFile = (file: File | undefined | null) => {
    if (!file) return;
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!VIDEO_EXTENSIONS.includes(ext)) {
      setUploadError(`Unsupported file type: ${ext || "unknown"}`);
      setUploadFile(null);
      return;
    }
    setUploadError(null);
    setUploadFile(file);
  };

  const resetUpload = () => {
    abortUploadRef.current?.();
    abortUploadRef.current = null;
    setUploadFile(null);
    setUploadTitle("");
    setUploadError(null);
    setDragActive(false);
    setUploading(false);
    setUploadProgress(0);
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile || uploading) return;
    setUploadError(null);
    setUploading(true);
    setUploadProgress(0);
    const { promise, abort } = uploadFileWithProgress(uploadFile, uploadTitle || undefined, setUploadProgress);
    abortUploadRef.current = abort;
    try {
      await promise;
      abortUploadRef.current = null;
      setUploadOpen(false);
      resetUpload();
      queryClient.invalidateQueries({ queryKey: getListMediaQueryKey() });
    } catch (err) {
      abortUploadRef.current = null;
      setUploading(false);
      if (err instanceof Error && err.message === "Upload cancelled") return;
      setUploadError("Upload failed. Check the file and try again.");
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
    if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
    return `${(bytes / 1024).toFixed(0)} KB`;
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
          <Dialog open={uploadOpen} onOpenChange={(open) => { setUploadOpen(open); if (!open) resetUpload(); }}>
            <DialogTrigger asChild>
              <Button variant="secondary" className="gap-2">
                <Upload className="h-4 w-4" />
                Upload File
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Upload Media</DialogTitle>
              </DialogHeader>
              <form onSubmit={handleUpload} className="space-y-4 pt-4">
                <div
                  className={`border-2 border-dashed rounded-md p-8 text-center cursor-pointer transition-colors ${dragActive ? "border-primary bg-primary/5" : "border-border hover:border-primary/50"}`}
                  onClick={() => fileInputRef.current?.click()}
                  onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
                  onDragLeave={() => setDragActive(false)}
                  onDrop={(e) => { e.preventDefault(); setDragActive(false); pickFile(e.dataTransfer.files?.[0]); }}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept={VIDEO_EXTENSIONS.join(",")}
                    className="hidden"
                    onChange={(e) => pickFile(e.target.files?.[0])}
                  />
                  {uploadFile ? (
                    <div className="space-y-1">
                      <Film className="h-8 w-8 mx-auto text-primary" />
                      <p className="text-sm font-medium break-all">{uploadFile.name}</p>
                      <p className="text-xs text-muted-foreground">{formatSize(uploadFile.size)}</p>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      <Upload className="h-8 w-8 mx-auto text-muted-foreground" />
                      <p className="text-sm">Drag & drop a video file here, or click to browse</p>
                      <p className="text-xs text-muted-foreground">MP4, MOV, MKV, AVI, MXF and more</p>
                    </div>
                  )}
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Title (Optional)</label>
                  <Input
                    value={uploadTitle}
                    onChange={e => setUploadTitle(e.target.value)}
                    placeholder="Interview setup"
                  />
                </div>
                {uploadError && <p className="text-sm text-destructive">{uploadError}</p>}
                {uploading && (
                  <div className="space-y-1.5">
                    <Progress value={uploadProgress} />
                    <div className="flex justify-between text-xs text-muted-foreground">
                      <span>
                        {uploadProgress < 100
                          ? `Uploading... ${uploadFile ? formatSize(uploadFile.size * uploadProgress / 100) : ""} of ${uploadFile ? formatSize(uploadFile.size) : ""}`
                          : "Processing upload on server..."}
                      </span>
                      <span className="tabular-nums font-medium">{uploadProgress}%</span>
                    </div>
                  </div>
                )}
                <Button type="submit" className="w-full" disabled={!uploadFile || uploading}>
                  {uploading ? (uploadProgress < 100 ? `Uploading... ${uploadProgress}%` : "Finalizing...") : "Upload & Process"}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
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
