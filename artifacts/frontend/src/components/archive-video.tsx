import { forwardRef, useCallback, useEffect, useRef, useState, type VideoHTMLAttributes } from "react";
import Hls from "hls.js";
import {
  ARCHIVE_MAX_RETRIES, archiveHlsLoadPolicies, archiveNetworkResponse, archiveRetryDelay,
  fetchArchivePlayback, isArchiveOverload, waitForArchiveRetry,
} from "./archive-video-retry";

/** Drop-in video element: preserves DOM refs, events and media time semantics.
 * Every original-media player negotiates here; rendered/dubbed URLs stay native.
 */
export const ArchiveVideo = forwardRef<HTMLVideoElement, VideoHTMLAttributes<HTMLVideoElement>>(
  function ArchiveVideo({ src, ...props }, forwardedRef) {
    const local = useRef<HTMLVideoElement | null>(null);
    const [error, setError] = useState("");
    const [status, setStatus] = useState("");
    const [retryGeneration, setRetryGeneration] = useState(0);
    const [image, setImage] = useState<string>();
    const match = src?.match(/^(\/(?:[^?#]*\/)?api\/media\/[^/?#]+)\/stream(?:#t=([\d.]+)(?:,([\d.]+))?)?$/);
    const nativeSrc = match ? undefined : src;
    const ref = useCallback((node: HTMLVideoElement | null) => {
      local.current = node;
      if (typeof forwardedRef === "function") forwardedRef(node);
      else if (forwardedRef) forwardedRef.current = node;
    }, [forwardedRef]);

    useEffect(() => {
      const video = local.current;
      setError("");
      setStatus("");
      setImage(undefined);
      if (!video || !src) return;
      if (!match) {
        // Restore native src after the previous negotiated player's cleanup.
        if (video.getAttribute("src") !== src) video.src = src;
        return;
      }
      const abort = new AbortController();
      let hls: Hls | undefined;
      let disposed = false;
      const start = Number(match[2] || 0);
      const stop = match[3] ? Number(match[3]) : undefined;
      let resumeAt = start;
      let resumePlayback = video.autoplay;
      let hlsRetries = 0;
      let recoveryPending = false;
      const destroyPlayer = () => {
        const owned = hls;
        hls = undefined;
        owned?.destroy();
      };
      const fail = (message: string) => {
        if (disposed) return;
        setStatus("");
        setError(message);
        destroyPlayer();
      };
      const onTime = () => {
        if (stop != null && video.currentTime >= stop) video.pause();
      };
      const onMetadata = () => {
        if (resumeAt) video.currentTime = resumeAt;
        if (resumePlayback) void video.play().catch(() => {});
      };
      video.addEventListener("timeupdate", onTime);
      video.addEventListener("loadedmetadata", onMetadata);
      const createPlayer = (url: string) => {
        if (disposed || abort.signal.aborted) return;
        const player = new Hls({
          ...archiveHlsLoadPolicies(Hls.DefaultConfig),
          startPosition: resumeAt, maxBufferLength: 18, maxMaxBufferLength: 30,
          backBufferLength: 6, maxBufferSize: 24 * 1024 * 1024,
          enableWorker: true,
        });
        hls = player;
        player.on(Hls.Events.ERROR, (_, data) => {
          if (disposed || hls !== player || recoveryPending) return;
          const network = archiveNetworkResponse(data.networkDetails);
          const code = data.response?.code ?? network.status;
          if (isArchiveOverload(code)) {
            const delay = archiveRetryDelay(hlsRetries, network.retryAfter);
            if (delay !== null) {
              // Handle nonfatal errors too. Destroy aborts all loaders and any
              // Hls.js recovery; only one owner retry can exist.
              recoveryPending = true;
              hlsRetries++;
              resumeAt = Math.max(start, video.currentTime || 0);
              resumePlayback = video.readyState === 0 ? resumePlayback : !video.paused;
              destroyPlayer();
              setStatus(`Archive busy. Retrying playback (${hlsRetries}/${ARCHIVE_MAX_RETRIES})…`);
              void waitForArchiveRetry(delay, abort.signal).then(() => {
                if (disposed) return;
                recoveryPending = false;
                setStatus("");
                try {
                  // Rebuild rather than startLoad(): manifest failures need a
                  // new loadSource(), and fragment failures resume media time.
                  createPlayer(url);
                } catch (e) {
                  fail(e instanceof Error ? e.message : "Playback unavailable");
                }
              }).catch((e: unknown) => {
                if (!disposed && !abort.signal.aborted) {
                  fail(e instanceof Error ? e.message : "Playback unavailable");
                }
              });
              return;
            }
          }
          if (data.fatal || isArchiveOverload(code) || code === 401 || code === 403 || code === 404) {
            fail(`Archive playback failed: ${data.details}${code ? ` (${code})` : ""}.`);
          }
        });
        player.loadSource(url);
        if (hls === player) player.attachMedia(video);
      };
      void (async () => {
        try {
          const response = await fetchArchivePlayback(`${match[1]}/playback`, abort.signal, (retry) => {
            if (!disposed) setStatus(`Archive busy. Retrying playback (${retry}/${ARCHIVE_MAX_RETRIES})…`);
          });
          if (disposed) return;
          setStatus("");
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
            createPlayer(info.url);
          } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
            video.src = info.url;
          } else {
            throw new Error("This browser does not support archive HLS playback.");
          }
        } catch (e) {
          if (!disposed) fail(e instanceof Error ? e.message : "Playback unavailable");
        }
      })();
      return () => {
        disposed = true;
        abort.abort();
        destroyPlayer();
        video.removeEventListener("timeupdate", onTime);
        video.removeEventListener("loadedmetadata", onMetadata);
        video.pause();
        video.removeAttribute("src");
        video.load();
      };
    }, [src, retryGeneration]); // Retry explicitly reinitializes this owned player.

    return <>
      <video {...props} src={nativeSrc} ref={ref} hidden={!!image || props.hidden}
        style={image ? { ...props.style, display: "none" } : props.style} />
      {image && <img src={image} alt="Archive asset" className={props.className} />}
      {status && <p role="status" data-testid="status-archive-playback" className="p-2 text-sm">{status}</p>}
      {error && <div className="p-2 text-sm text-destructive">
        <p role="alert" data-testid="error-archive-playback">{error}</p>
        <button type="button" data-testid="retry-archive-playback" className="underline"
          onClick={() => setRetryGeneration((generation) => generation + 1)}>Retry playback</button>
      </div>}
    </>;
  },
);