---
name: Replit preview iframe blocks SameSite=Lax cookies
description: Session cookies in the Replit preview must be SameSite=None; Secure or login silently fails
---

The Replit preview pane renders the app inside a cross-site iframe (top-level site is replit.com). Browsers treat every request from that iframe as third-party, so `SameSite=Lax` (or `Strict`) cookies are silently dropped — the login POST returns 200 but the cookie is never stored, and the next authenticated request 401s. The symptom is "clicking sign-in does nothing": the auth gate flips and immediately bounces back.

**Why:** SameSite is evaluated against the top-level site, not the iframe's own origin. Same-origin XHR inside a cross-site iframe still counts as cross-site.

**How to apply:** any cookie the dev/mock server sets must be `SameSite=None; Secure` (the preview proxy serves HTTPS, so Secure is fine). Keep production cookies `SameSite=Lax` where the app is not iframed — in this project the FastAPI prod server runs on plain HTTP LAN and must NOT get the Secure flag.

Debugging tip: server logs showing login 200 followed by /auth/me 401 from the browser — while the same sequence works via curl — is the signature of this issue.
