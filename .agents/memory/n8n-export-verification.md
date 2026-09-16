---
name: n8n export verification
description: Why workflow exports need branch-aware execution tests rather than helper-only tests.
---

**Rule:** Test the actual exported node code and model n8n's missing-node access as an exception, not an undefined property.

**Why:** A parallel helper can pass while JSON-escaped inline code behaves differently. Optional branches also leave nodes unexecuted; referencing those nodes can throw before the workflow reaches its response node, even when an ordinary JavaScript object mock would allow a fallback.

**How to apply:** Execute inline code extracted from the deliverable JSON, use throwing node-access mocks, and cover success, empty inputs, malformed upstream bodies, and non-success HTTP responses. Preserve structured upstream error bodies before classifying HTTP status; never treat an empty response as a successful report.