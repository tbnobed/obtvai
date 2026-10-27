---
name: Application-wide appearance
description: Scope of light-mode support and reliable theme interaction checks.
---

Light mode must cover the entire application, not just the navigation or main dashboard.

**Why:** The user explicitly requested light mode for the entire application and emphasized not missing anything.

**How to apply:** Include existing and new editors, admin screens, dialogs, charts and transient UI when auditing appearance. Distinguish intentional dark media-viewing areas from accidental dark application surfaces.

Verify live preference changes through the actual theme selector, not just by changing browser storage while React is mounted.

**Why:** Browser testing observed storage reporting System while the mounted UI retained its prior choice; using the real selector correctly exercised persistence and live OS-change handling.

**How to apply:** Use storage seeding for initial-load tests, and use user-facing controls for live switching tests. A storage write alone does not establish that the theme provider accepted a new selection.
