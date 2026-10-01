import type { HlsConfig } from "hls.js";

export const ARCHIVE_MAX_RETRIES = 3;
export const ARCHIVE_MAX_RETRY_DELAY_MS = 30_000;

export function isArchiveOverload(status: number | undefined): boolean {
  return status === 429 || status === 503 || status === 504;
}

/** A server's Retry-After is a minimum, not a value to clamp and retry early.
 * If it exceeds our bounded wait, leave recovery to the user's Retry action.
 */
export function archiveRetryDelay(
  retry: number,
  retryAfter: string | null,
  now = Date.now(),
  random = Math.random(),
): number | null {
  if (retry >= ARCHIVE_MAX_RETRIES) return null;
  let serverDelay = 0;
  if (retryAfter) {
    const value = retryAfter.trim();
    if (/^\d+(?:\.\d+)?$/.test(value)) {
      serverDelay = Number(value) * 1000;
    } else {
      const date = Date.parse(value);
      if (Number.isFinite(date)) serverDelay = Math.max(0, date - now);
    }
  }
  if (serverDelay > ARCHIVE_MAX_RETRY_DELAY_MS) return null;
  const backoff = 1000 * 2 ** retry;
  const minimum = Math.max(backoff, serverDelay);
  return Math.round(minimum + Math.max(0, Math.min(1, random)) *
    Math.min(backoff, ARCHIVE_MAX_RETRY_DELAY_MS - minimum));
}

export function waitForArchiveRetry(delay: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(signal.reason);
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, delay);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

export async function fetchArchivePlayback(
  url: string,
  signal: AbortSignal,
  onRetry?: (retry: number) => void,
): Promise<Response> {
  for (let retry = 0; ; retry++) {
    signal.throwIfAborted();
    const response = await fetch(url, { credentials: "same-origin", signal });
    signal.throwIfAborted();
    if (!isArchiveOverload(response.status)) return response;
    const delay = archiveRetryDelay(retry, response.headers.get("Retry-After"));
    if (delay === null) return response;
    // Release the previous response before starting another request.
    await response.body?.cancel();
    onRetry?.(retry + 1);
    await waitForArchiveRetry(delay, signal);
  }
}

/** Hls.js 1.7 uses load policies. Disable implicit HTTP error retries so our
 * single, session-wide jittered recovery budget cannot multiply loader retries.
 * Keep one bounded timeout retry; HTTP overloads are handled by the owner.
 */
export function archiveHlsLoadPolicies(defaults: HlsConfig) {
  const policy = (name: "manifestLoadPolicy" | "playlistLoadPolicy" | "fragLoadPolicy" | "keyLoadPolicy") => ({
    default: {
      ...defaults[name].default,
      maxLoadTimeMs: name === "fragLoadPolicy" ? 60_000 : 20_000,
      errorRetry: null,
      timeoutRetry: {
        maxNumRetry: 1,
        retryDelayMs: 1000,
        maxRetryDelayMs: 1000,
        backoff: "exponential" as const,
      },
    },
  });
  return {
    manifestLoadPolicy: policy("manifestLoadPolicy"),
    playlistLoadPolicy: policy("playlistLoadPolicy"),
    fragLoadPolicy: policy("fragLoadPolicy"),
    keyLoadPolicy: policy("keyLoadPolicy"),
  };
}

/** Default XHR loader and optional Fetch loader expose headers differently. */
export function archiveNetworkResponse(details: unknown): { status?: number; retryAfter: string | null } {
  const network = details as {
    status?: number;
    getResponseHeader?: (name: string) => string | null;
    headers?: { get: (name: string) => string | null };
  } | null;
  return {
    status: network?.status,
    retryAfter: network?.getResponseHeader?.("Retry-After") ?? network?.headers?.get("Retry-After") ?? null,
  };
}