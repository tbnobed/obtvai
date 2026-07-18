import { Film } from "lucide-react";

export function ClipThumb({ url, className = "h-9 w-14" }: { url?: string | null; className?: string }) {
  return (
    <div className={`relative shrink-0 overflow-hidden rounded bg-black/60 border border-border/50 ${className}`}>
      {url ? (
        <img src={`/api/thumbnails/${url}`} alt="" className="h-full w-full object-cover" loading="lazy" />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-muted-foreground/40">
          <Film className="h-4 w-4" />
        </div>
      )}
    </div>
  );
}
