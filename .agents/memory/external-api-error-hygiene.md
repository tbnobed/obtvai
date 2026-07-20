---
name: External API error hygiene
description: Never persist or display raw httpx/requests exception text when the request carries a secret in query params
---

Rule: when a worker/task stores an error message for the UI (e.g. a status JSONB column), never store `str(exc)` from an HTTP client call whose URL carries a secret.

**Why:** `httpx.HTTPStatusError` (and requests equivalents) embed the full request URL — including query params like `api_key=...` — in the exception message. A generic `except Exception: store(str(exc))` then writes the secret to the DB and renders it to every logged-in user. Quota/auth 4xx errors are the *most likely* failure mode for keyed APIs, so this path will fire.

**How to apply:** catch `HTTPStatusError` around the keyed call and store a sanitized message (`f"<service> returned HTTP {exc.response.status_code}"`); as a backstop, regex-strip `api_key=...`-style params from any message before persisting. Prefer sending keys in headers over query params when the API allows it.

Related: any async "queue then poll" status stored in DB should include a `queued_at` timestamp so the UI can treat a long-stuck `pending` as retryable — otherwise a dead worker permanently bricks the trigger button.
