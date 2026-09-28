---
name: Conversation result ownership
description: Why conversational replies and empty searches must remain distinct through storage and rendering.
---

A conversational reply preserves the prior result set; an empty search replaces it. Preserve this distinction across persisted and optimistic messages.

**Why:** The archive assistant originally treated scope questions as searches, invented visual evidence, and replaced useful results. A nullable JSON field with a list default also converted explicit nulls into empty lists during insertion, breaking restoration and follow-up context despite correct responses.

**How to apply:** Verify database round-trip semantics, not just serialized responses. Keep date refinements grounded in the executed prior result date range, not just the last raw user question (which may itself be “only September”). Conversation-routing failure must clarify rather than silently search.