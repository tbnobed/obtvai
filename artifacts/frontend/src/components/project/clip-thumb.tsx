import { Film } from "lucide-react";
import { useEffect, useState } from "react";

type ClipThumbProps = {
  url?: string | null;
  mediaId?: string;
  time?: number;
  className?: string;
};

export function ClipThumb({ url, mediaId, time, className = "h-9 w-14" }: ClipThumbProps) {
  const frameSrc =
    mediaId && time != null
      ? `/api/media/${mediaId}/frame?t=${Math.max(0, time).toFixed(2)}`
      : null;
  const [frameFailed, setFrameFailed] = useState(false);
  const [thumbFailed, setThumbFailed] = useState(false);

  useEffect(() => {
    setFrameFailed(false);
    setThumbFailed(false);
  }, [frameSrc, url]);

  const src =
    frameSrc && !frameFailed
      ? frameSrc
      : url && !thumbFailed
        ? `/api/thumbnails/${url}`
        : null;

  return (
    <div className={`relative shrink-0 overflow-hidden rounded bg-black/60 border border-border/50 ${className}`}>
      {src ? (
        <img
          src={src}
          alt=""
          className="h-full w-full object-cover"
          loading="lazy"
          onError={() => {
            if (frameSrc && !frameFailed) setFrameFailed(true);
            else setThumbFailed(true);
          }}
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-muted-foreground/40">
          <Film className="h-4 w-4" />
        </div>
      )}
    </div>
  );
}
