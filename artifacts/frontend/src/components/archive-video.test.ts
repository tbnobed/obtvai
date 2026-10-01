import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { after, afterEach, beforeEach, test } from "node:test";
import React, { act, createElement, createRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { JSDOM } from "jsdom";
import type { ErrorData, HlsConfig } from "hls.js";

// Mock only the transport: exercise the real component/effects/DOM lifecycle.
class TestHls {
  static instances: TestHls[] = [];
  static supported = true;
  static Events = { ERROR: "error" };
  static DefaultConfig = {
    manifestLoadPolicy: { default: {} }, playlistLoadPolicy: { default: {} },
    fragLoadPolicy: { default: {} }, keyLoadPolicy: { default: {} },
  };
  static isSupported() { return TestHls.supported; }
  source?: string;
  media?: HTMLVideoElement;
  destroys = 0;
  listener?: (event: string, data: Partial<ErrorData>) => void;
  constructor(public config: HlsConfig) { TestHls.instances.push(this); }
  on(_event: string, listener: TestHls["listener"]) { this.listener = listener; }
  loadSource(url: string) { this.source = url; }
  attachMedia(video: HTMLVideoElement) { this.media = video; }
  destroy() { this.destroys++; }
  emitError(code: number | undefined, details = "fragLoadError", fatal = false, retryAfter?: string) {
    const network = new dom.window.XMLHttpRequest();
    Object.defineProperty(network, "status", { value: code ?? 0 });
    network.getResponseHeader = () => retryAfter ?? null;
    this.listener?.("error", {
      fatal, details: details as ErrorData["details"],
      response: code === undefined ? undefined : { url: this.source!, code },
      networkDetails: network,
    });
  }
}

const globals = globalThis as typeof globalThis & {
  __ArchiveTestHls?: typeof TestHls;
  IS_REACT_ACT_ENVIRONMENT?: boolean;
  React?: typeof React;
};
globals.__ArchiveTestHls = TestHls;
globals.IS_REACT_ACT_ENVIRONMENT = true;
// tsx's direct test transform uses the classic JSX runtime, unlike Vite.
globals.React = React;
const hooks = registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "hls.js" && context.parentURL?.endsWith("/archive-video.tsx")) {
      return { shortCircuit: true, url: "data:text/javascript,export default globalThis.__ArchiveTestHls" };
    }
    return nextResolve(specifier, context);
  },
});
const { ArchiveVideo } = await import("./archive-video");
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "https://archive.example/base/" });
Object.defineProperty(globalThis, "window", { configurable: true, value: dom.window });
Object.defineProperty(globalThis, "document", { configurable: true, value: dom.window.document });
let pauses = 0;
let loads = 0;
let plays = 0;
dom.window.HTMLMediaElement.prototype.pause = () => { pauses++; };
dom.window.HTMLMediaElement.prototype.load = () => { loads++; };
dom.window.HTMLMediaElement.prototype.play = async () => { plays++; };

let container: HTMLDivElement;
let root: Root;
let unmounted: boolean;
beforeEach(() => {
  TestHls.instances = [];
  TestHls.supported = true;
  pauses = loads = plays = 0;
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  unmounted = false;
});
afterEach(async () => {
  if (!unmounted) await act(async () => root.unmount());
  container.remove();
});
after(() => {
  hooks.deregister();
  dom.window.close();
  delete globals.__ArchiveTestHls;
  delete globals.IS_REACT_ACT_ENVIRONMENT;
  delete globals.React;
});

async function render(src: string, extra: Record<string, unknown> = {}) {
  await act(async () => { root.render(createElement(ArchiveVideo, { src, ...extra })); });
}
async function tick(t: { mock: { timers: { tick: (ms: number) => void } } }, ms: number) {
  await act(async () => { t.mock.timers.tick(ms); });
}
function playback() {
  return Response.json({ type: "hls", url: "/base/api/media/id/hls/index.m3u8?token=preserved" });
}

test("preserves base path, auth, forwarded DOM ref, events, and timed playback", async (t) => {
  let init: RequestInit | undefined;
  t.mock.method(globalThis, "fetch", async (url: string, options: RequestInit) => {
    assert.equal(url, "/base/api/media/id/playback");
    init = options;
    return playback();
  });
  const ref = createRef<HTMLVideoElement>();
  let metadata = 0;
  await render("/base/api/media/id/stream#t=12,18", { ref, autoPlay: true, controls: true, onLoadedMetadata: () => { metadata++; } });
  const video = container.querySelector("video")!;
  assert.equal(ref.current, video);
  assert.equal(video.controls, true);
  assert.equal(init?.credentials, "same-origin");
  const owned = TestHls.instances[0];
  assert.equal(owned.media, video);
  assert.equal(owned.source, "/base/api/media/id/hls/index.m3u8?token=preserved");
  assert.equal(owned.config.startPosition, 12);
  await act(async () => { video.dispatchEvent(new dom.window.Event("loadedmetadata")); });
  assert.equal(metadata, 1);
  assert.equal(video.currentTime, 12);
  assert.equal(plays, 1);
  video.currentTime = 18;
  video.dispatchEvent(new dom.window.Event("timeupdate"));
  assert.equal(pauses, 1);
});

test("nonfatal/fatal HLS manifest, playlist, and fragment overloads share one finite budget", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  t.mock.method(Math, "random", () => 0);
  const fetch = t.mock.method(globalThis, "fetch", async () => playback());
  await render("/api/media/id/stream#t=12,18", { autoPlay: true });
  const video = container.querySelector("video")!;
  video.currentTime = 15;
  const errors = [
    [503, "manifestLoadError", true],
    [429, "levelLoadError", false],
    [504, "fragLoadError", false],
  ] as const;
  for (const [index, [code, details, fatal]] of errors.entries()) {
    const owned = TestHls.instances[index];
    await act(async () => {
      owned.emitError(code, details, fatal);
      // Late callbacks from the destroyed instance must not schedule more work.
      owned.emitError(code, details, fatal);
    });
    assert.equal(owned.destroys, 1);
    assert.match(container.querySelector('[role="status"]')!.textContent!, /Archive busy/);
    await tick(t, (1000 * 2 ** index) - 1);
    assert.equal(TestHls.instances.length, index + 1);
    await tick(t, 1);
    assert.equal(TestHls.instances.length, index + 2);
    assert.equal(TestHls.instances[index + 1].config.startPosition, 15);
    video.currentTime = 0;
    await act(async () => { video.dispatchEvent(new dom.window.Event("loadedmetadata")); });
    assert.equal(video.currentTime, 15);
  }
  await act(async () => { TestHls.instances[3].emitError(503); });
  assert.match(container.querySelector('[role="alert"]')!.textContent!, /503/);
  assert.equal(TestHls.instances[3].destroys, 1);
  assert.ok(container.querySelector('[data-testid="retry-archive-playback"]'));
  await tick(t, 1_000_000);
  assert.equal(TestHls.instances.length, 4);
  assert.equal(fetch.mock.callCount(), 1);
});

test("HLS Retry-After delays recovery and aborting the pending recovery prevents reconstruction", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  t.mock.method(Math, "random", () => 0);
  t.mock.method(globalThis, "fetch", async () => playback());
  await render("/api/media/id/stream");
  await act(async () => { TestHls.instances[0].emitError(503, "manifestLoadError", true, "5"); });
  await tick(t, 4999);
  assert.equal(TestHls.instances.length, 1);
  await tick(t, 1);
  assert.equal(TestHls.instances.length, 2);
  await act(async () => { TestHls.instances[1].emitError(503); });
  await act(async () => root.unmount());
  unmounted = true;
  await tick(t, 1_000_000);
  assert.equal(TestHls.instances.length, 2);
  assert.equal(TestHls.instances[0].destroys, 1);
  assert.equal(TestHls.instances[1].destroys, 1);
});

test("401/403/404 HLS failures never retry; Retry re-negotiates and owns a fresh player", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const fetch = t.mock.method(globalThis, "fetch", async () => playback());
  await render("/api/media/id/stream");
  for (const [index, code] of [401, 403, 404].entries()) {
    const owned = TestHls.instances[index];
    await act(async () => { owned.emitError(code, "fragLoadError", false); });
    assert.match(container.querySelector('[role="alert"]')!.textContent!, new RegExp(String(code)));
    await tick(t, 1_000_000);
    assert.equal(TestHls.instances.length, index + 1);
    assert.equal(owned.destroys, 1);
    await act(async () => { (container.querySelector("button") as HTMLButtonElement).click(); });
    assert.equal(TestHls.instances.length, index + 2);
    assert.equal(fetch.mock.callCount(), index + 2);
    assert.equal(container.querySelector('[role="alert"]'), null);
    assert.equal(TestHls.instances[index + 1].media, container.querySelector("video"));
    assert.equal(owned.destroys, 1);
  }
});

test("sustained negotiation 503 is terminal, but its Retry action reinitializes playback", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  t.mock.method(Math, "random", () => 0);
  let requests = 0;
  t.mock.method(globalThis, "fetch", async () => {
    requests++;
    return requests <= 4 ? new Response(null, { status: 503 }) : playback();
  });
  await render("/api/media/id/stream");
  for (const delay of [1000, 2000, 4000]) await tick(t, delay);
  assert.equal(requests, 4);
  assert.match(container.querySelector('[role="alert"]')!.textContent!, /Playback unavailable \(503\)/);
  assert.equal(TestHls.instances.length, 0);
  await act(async () => { (container.querySelector("button") as HTMLButtonElement).click(); });
  assert.equal(requests, 5);
  assert.equal(TestHls.instances.length, 1);
  assert.equal(container.querySelector('[role="alert"]'), null);
});

test("unmount aborts negotiation and clears timers, media source, listeners, and owned player", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let signal: AbortSignal | undefined;
  const fetch = t.mock.method(globalThis, "fetch", async (_url: string, init: RequestInit) => {
    signal = init.signal as AbortSignal;
    return new Response(null, { status: 503 });
  });
  await render("/api/media/id/stream#t=12,18");
  const video = container.querySelector("video")!;
  await act(async () => root.unmount());
  unmounted = true;
  assert.equal(signal?.aborted, true);
  assert.equal(video.getAttribute("src"), null);
  assert.equal(pauses, 1);
  assert.equal(loads, 1);
  video.currentTime = 20;
  video.dispatchEvent(new dom.window.Event("loadedmetadata"));
  video.dispatchEvent(new dom.window.Event("timeupdate"));
  assert.equal(video.currentTime, 20);
  assert.equal(pauses, 1);
  await tick(t, 1_000_000);
  assert.equal(fetch.mock.callCount(), 1);
  assert.equal(TestHls.instances.length, 0);
});

test("legacy negotiation, image rendering, and rendered/dubbed native URLs stay intact", async (t) => {
  let status = 404;
  const fetch = t.mock.method(globalThis, "fetch", async () => {
    return status === 200 ? Response.json({ type: "image", url: "/base/image.jpg?auth=retained" }) : new Response(null, { status });
  });
  await render("/api/media/legacy/stream#t=2,4");
  assert.equal(container.querySelector("video")!.getAttribute("src"), "/api/media/legacy/stream#t=2,4");
  assert.equal(fetch.mock.callCount(), 1);
  status = 501;
  await render("/api/media/older/stream");
  assert.equal(container.querySelector("video")!.getAttribute("src"), "/api/media/older/stream");
  status = 200;
  await render("/api/media/image/stream");
  assert.equal(container.querySelector("img")!.getAttribute("src"), "/base/image.jpg?auth=retained");
  assert.equal(container.querySelector("video")!.hidden, true);
  await render("/api/media/id/dub/en/stream", { className: "native-player" });
  assert.equal(container.querySelector("img"), null);
  assert.equal(container.querySelector("video")!.hidden, false);
  assert.equal(container.querySelector("video")!.getAttribute("src"), "/api/media/id/dub/en/stream");
  assert.equal(fetch.mock.callCount(), 3);
  await render("/api/projects/id/render.mp4");
  assert.equal(container.querySelector("video")!.getAttribute("src"), "/api/projects/id/render.mp4");
  assert.equal(fetch.mock.callCount(), 3);
});

test("Safari's native HLS fallback keeps the negotiated URL without creating Hls.js", async (t) => {
  TestHls.supported = false;
  t.mock.method(dom.window.HTMLMediaElement.prototype, "canPlayType", () => "probably");
  t.mock.method(globalThis, "fetch", async () => playback());
  await render("/api/media/id/stream");
  assert.equal(container.querySelector("video")!.getAttribute("src"), "/base/api/media/id/hls/index.m3u8?token=preserved");
  assert.equal(TestHls.instances.length, 0);
});

test("an in-flight negotiation cannot revive the player after unmount", async (t) => {
  let resolveResponse!: (response: Response) => void;
  let signal: AbortSignal | undefined;
  t.mock.method(globalThis, "fetch", (_url: string, init: RequestInit) => {
    signal = init.signal as AbortSignal;
    return new Promise<Response>((resolve) => { resolveResponse = resolve; });
  });
  await render("/api/media/id/stream");
  await act(async () => root.unmount());
  unmounted = true;
  assert.equal(signal?.aborted, true);
  await act(async () => { resolveResponse(playback()); });
  assert.equal(TestHls.instances.length, 0);
});

test("changing src cancels an overload wait, destroys ownership, and ignores stale errors", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  t.mock.method(Math, "random", () => 0);
  const signals: AbortSignal[] = [];
  t.mock.method(globalThis, "fetch", async (_url: string, init: RequestInit) => {
    signals.push(init.signal as AbortSignal);
    return playback();
  });
  await render("/api/media/first/stream");
  const first = TestHls.instances[0];
  await act(async () => { first.emitError(503); });
  await render("/api/media/second/stream");
  assert.equal(signals[0].aborted, true);
  assert.equal(first.destroys, 1);
  assert.equal(TestHls.instances.length, 2);
  assert.equal(container.querySelector('[role="status"]'), null);
  await act(async () => { first.emitError(403); });
  assert.equal(container.querySelector('[role="alert"]'), null);
  await tick(t, 1_000_000);
  assert.equal(TestHls.instances.length, 2);
  await act(async () => root.unmount());
  unmounted = true;
  assert.equal(signals[1].aborted, true);
  assert.equal(TestHls.instances[1].destroys, 1);
});