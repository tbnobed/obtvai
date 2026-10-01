import assert from "node:assert/strict";
import test from "node:test";
import Hls from "hls.js";
import {
  ARCHIVE_MAX_RETRIES, ARCHIVE_MAX_RETRY_DELAY_MS, archiveHlsLoadPolicies,
  archiveNetworkResponse, archiveRetryDelay, fetchArchivePlayback, waitForArchiveRetry,
} from "./archive-video-retry";

async function flush() {
  for (let i = 0; i < 12; i++) await Promise.resolve();
}

test("backoff is jittered, bounded, and never earlier than Retry-After", () => {
  assert.equal(archiveRetryDelay(0, null, 0, 0), 1000);
  assert.equal(archiveRetryDelay(0, null, 0, 1), 2000);
  assert.equal(archiveRetryDelay(1, null, 0, 0.5), 3000);
  assert.equal(archiveRetryDelay(2, null, 0, 1), 8000);
  assert.equal(archiveRetryDelay(ARCHIVE_MAX_RETRIES, null), null);
  assert.equal(archiveRetryDelay(0, "5", 0, 0), 5000);
  assert.equal(archiveRetryDelay(0, "5", 0, 1), 6000);
  assert.equal(archiveRetryDelay(0, "Thu, 01 Jan 1970 00:00:10 GMT", 5000, 0), 5000);
  assert.equal(archiveRetryDelay(0, "Thu, 01 Jan 1970 00:00:01 GMT", 5000, 0), 1000);
  assert.equal(archiveRetryDelay(0, "invalid", 0, 0), 1000);
  assert.equal(archiveRetryDelay(0, "30", 0, 1), ARCHIVE_MAX_RETRY_DELAY_MS);
  assert.equal(archiveRetryDelay(0, "31", 0, 0), null);
  assert.equal(archiveRetryDelay(0, "Thu, 01 Jan 1970 00:01:00 GMT", 0, 0), null);
});

test("negotiation recovers from 429, 503, and 504 with at most four same-origin requests", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  t.mock.method(Math, "random", () => 0);
  const statuses = [429, 503, 504, 200];
  const requests: RequestInit[] = [];
  const retries: number[] = [];
  t.mock.method(globalThis, "fetch", async (url: string, init: RequestInit) => {
    assert.equal(url, "/base/api/media/id/playback");
    requests.push(init);
    return new Response(null, { status: statuses[requests.length - 1] });
  });
  const controller = new AbortController();
  const result = fetchArchivePlayback("/base/api/media/id/playback", controller.signal, (retry) => retries.push(retry));
  await flush();
  for (const delay of [1000, 2000, 4000]) {
    t.mock.timers.tick(delay - 1);
    await flush();
    assert.equal(requests.length, retries.length);
    t.mock.timers.tick(1);
    await flush();
  }
  assert.equal((await result).status, 200);
  assert.deepEqual(retries, [1, 2, 3]);
  assert.equal(requests.length, 4);
  for (const request of requests) {
    assert.equal(request.credentials, "same-origin");
    assert.equal(request.signal, controller.signal);
  }
});

test("sustained overload exhausts its budget and returns the real terminal status", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  t.mock.method(Math, "random", () => 0);
  const fetch = t.mock.method(globalThis, "fetch", async () => new Response(null, { status: 503 }));
  const result = fetchArchivePlayback("/api/media/id/playback", new AbortController().signal);
  await flush();
  for (const delay of [1000, 2000, 4000]) {
    t.mock.timers.tick(delay);
    await flush();
  }
  assert.equal((await result).status, 503);
  t.mock.timers.tick(1_000_000);
  await flush();
  assert.equal(fetch.mock.callCount(), 4);
});

test("Retry-After seconds and dates are honored; excessive delays do not retry early", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  t.mock.method(Math, "random", () => 0);
  t.mock.method(Date, "now", () => Date.parse("2026-01-01T00:00:00Z"));
  for (const header of ["5", "Thu, 01 Jan 2026 00:00:05 GMT"]) {
    let requests = 0;
    const fetch = t.mock.method(globalThis, "fetch", async () => {
      requests++;
      return new Response(null, requests === 1 ? { status: 503, headers: { "Retry-After": header } } : { status: 200 });
    });
    const result = fetchArchivePlayback("/api/media/id/playback", new AbortController().signal);
    await flush();
    t.mock.timers.tick(4999);
    await flush();
    assert.equal(requests, 1);
    t.mock.timers.tick(1);
    await flush();
    assert.equal((await result).status, 200);
    fetch.mock.restore();
  }
  const fetch = t.mock.method(globalThis, "fetch", async () => new Response(null, { status: 429, headers: { "Retry-After": "120" } }));
  assert.equal((await fetchArchivePlayback("/api/media/id/playback", new AbortController().signal)).status, 429);
  assert.equal(fetch.mock.callCount(), 1);
});

test("401, 403, 404, legacy 501, and other errors never trigger negotiation retries", async (t) => {
  for (const status of [401, 403, 404, 501, 500]) {
    const fetch = t.mock.method(globalThis, "fetch", async () => new Response(null, { status }));
    assert.equal((await fetchArchivePlayback("/api/media/id/playback", new AbortController().signal)).status, status);
    assert.equal(fetch.mock.callCount(), 1);
    fetch.mock.restore();
  }
  const fetch = t.mock.method(globalThis, "fetch", async () => { throw new Error("offline"); });
  await assert.rejects(fetchArchivePlayback("/api/media/id/playback", new AbortController().signal), /offline/);
  assert.equal(fetch.mock.callCount(), 1);
});

test("abort cancels the wait, removes its listener, and prevents a subsequent fetch", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const fetch = t.mock.method(globalThis, "fetch", async () => new Response(null, { status: 503 }));
  const controller = new AbortController();
  const result = fetchArchivePlayback("/api/media/id/playback", controller.signal);
  const rejection = assert.rejects(result, { name: "AbortError" });
  await flush();
  controller.abort();
  await rejection;
  t.mock.timers.tick(1_000_000);
  await flush();
  assert.equal(fetch.mock.callCount(), 1);

  const completed = new AbortController();
  const remove = t.mock.method(completed.signal, "removeEventListener");
  const wait = waitForArchiveRetry(10, completed.signal);
  t.mock.timers.tick(10);
  await wait;
  assert.equal(remove.mock.callCount(), 1);
  await assert.rejects(waitForArchiveRetry(10, controller.signal), { name: "AbortError" });
});

test("a late fetch result cannot revive an aborted negotiation", async (t) => {
  const controller = new AbortController();
  t.mock.method(globalThis, "fetch", async () => {
    controller.abort();
    return new Response(null, { status: 200 });
  });
  await assert.rejects(fetchArchivePlayback("/api/media/id/playback", controller.signal), { name: "AbortError" });
});

test("installed Hls.js load policies cannot multiply application overload retries", () => {
  const policies = archiveHlsLoadPolicies(Hls.DefaultConfig);
  for (const policy of Object.values(policies)) {
    assert.equal(policy.default.errorRetry, null);
    assert.equal(policy.default.timeoutRetry.maxNumRetry, 1);
  }
  assert.equal(policies.fragLoadPolicy.default.maxLoadTimeMs, 60_000);
  assert.equal(policies.manifestLoadPolicy.default.maxLoadTimeMs, 20_000);
  assert.notEqual(Hls.DefaultConfig.fragLoadPolicy.default.errorRetry, null);
});

test("HLS retry headers support the installed XHR loader and optional Fetch loader", () => {
  assert.deepEqual(archiveNetworkResponse({ status: 503, getResponseHeader: () => "5" }), { status: 503, retryAfter: "5" });
  assert.deepEqual(archiveNetworkResponse(new Response(null, { status: 429, headers: { "Retry-After": "8" } })), { status: 429, retryAfter: "8" });
  assert.deepEqual(archiveNetworkResponse(null), { status: undefined, retryAfter: null });
});