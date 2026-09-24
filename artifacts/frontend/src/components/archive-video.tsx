import { forwardRef, useCallback, useEffect, useRef, useState, type VideoHTMLAttributes } from "react";
import Hls from "hls.js";

/** Drop-in video element: preserves DOM refs, events and media time semantics.
 * Every original-media player negotiates here; rendered/dubbed URLs stay native.
 */
export const ArchiveVideo = forwardRef<HTMLVideoElement, VideoHTMLAttributes<HTMLVideoElement>>(
  function ArchiveVideo({ src, ...props }, forwardedRef) {
    const local = useRef<HTMLVideoElement | null>(null);
    const [error, setError] = useState("");
    const [image, setImage] = useState<string>();
    const match = src?.match(/^(\/api\/media\/[^/]+)\/stream(?:#t=([\d.]+)(?:,([\d.]+))?)?$/);
    const nativeSrc = match ? undefined : src;
    const ref = useCallback((node: HTMLVideoElement | null) => {
      local.current = node;
      if (typeof forwardedRef === "function") forwardedRef(node);
      else if (forwardedRef) forwardedRef.current = node;
    }, [forwardedRef]);

    useEffect(() => {
      const video = local.current;
      if (!video || !match || !src) return;
      const abort = new AbortController();
      let hls: Hls | undefined;
      let disposed = false;
      const start = Number(match[2] || 0);
      const stop = match[3] ? Number(match[3]) : undefined;
      setError("");
      setImage(undefined);
      const onTime = () => {
        if (stop != null && video.currentTime >= stop) video.pause();
      };
      const onMetadata = () => {
        if (start) video.currentTime = start;
        if (video.autoplay) void video.play().catch(() => {});
      };
      video.addEventListener("timeupdate", onTime);
      video.addEventListener("loadedmetadata", onMetadata);
      void (async () => {
        try {
          const response = await fetch(`${match[1]}/playback`, {
            credentials: "same-origin", signal: abort.signal,
          });
          // Old backend / development preview: preserve the native route.
          if (response.status === 404 || response.status === 501) {
            video.src = src;
            return;
          }
          if (!response.ok) throw new Error(`Playback unavailable (${response.status})`);
          const info = await response.json();
          if (disposed) return;
          if (info.type === "image") {
            setImage(info.url);
          } else if (info.type !== "hls") {
            video.src = src;
          } else if (Hls.isSupported()) {
            hls = new Hls({
              startPosition: start, maxBufferLength: 18, maxMaxBufferLength: 30,
              backBufferLength: 6, maxBufferSize: 24 * 1024 * 1024,
              fragLoadingTimeOut: 60000, manifestLoadingTimeOut: 20000,
              enableWorker: true,
            });
            hls.on(Hls.Events.ERROR, (_, data) => {
              if (data.fatal) {
                setError(`Archive playback failed: ${data.details}. Retry by reopening the player.`);
                hls?.destroy();
              }
            });
            hls.loadSource(info.url);
            hls.attachMedia(video);
          } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
            video.src = info.url;
          } else {
            throw new Error("This browser does not support archive HLS playback.");
          }
        } catch (e) {
          if (!disposed) setError(e instanceof Error ? e.message : "Playback unavailable");
        }
      })();
      return () => {
        disposed = true;
        abort.abort();
        hls?.destroy();
        video.removeEventListener("timeupdate", onTime);
        video.removeEventListener("loadedmetadata", onMetadata);
        video.pause();
        video.removeAttribute("src");
        video.load();
      };
    }, [src]); // The negotiated source is the only playback lifecycle dependency.

    return <>
      <video {...props} src={nativeSrc} ref={ref} hidden={!!image || props.hidden}
        style={image ? { ...props.style, display: "none" } : props.style} />
      {image && <img src={image} alt="Archive asset" className={props.className} />}
      {error && <p role="alert" className="p-2 text-sm text-destructive">{error}</p>}
    </>;
  },
);