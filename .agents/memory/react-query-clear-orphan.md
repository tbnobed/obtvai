---
name: queryClient.clear() orphans mounted observers
description: Why auth-gate flips silently fail in production builds when clear() is used in login/logout callbacks
---

Rule: never call `queryClient.clear()` while a component is mounted that renders from a query you are about to re-set. `clear()` destroys every Query instance; mounted observers stay bound to the destroyed instance, and a following `setQueryData` creates a NEW instance with zero subscribers — no notification, no re-render.

**Why:** production "Sign in does nothing" bug — POST /login returned 200 but the auth gate never flipped and the browser made zero follow-up requests. Dev mode (StrictMode double renders / HMR) masks the bug completely: extra renders rebind the observer via `setOptions`, so it only reproduces in production builds.

**How to apply:** to purge caches on login/logout, use `removeQueries({ predicate: q => q.queryKey[0] !== keepKey[0] })` to spare the live entry, then `setQueryData(keepKey, value)` so subscribers are notified. Purge mutations separately with `queryClient.getMutationCache().clear()` if needed. Symptom signature: mutation succeeds server-side, UI frozen, works in dev but not prod.
