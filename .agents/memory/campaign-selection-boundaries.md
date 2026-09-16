---
name: Campaign selection boundaries
description: Why campaign clip scope must not be inferred from the shared Studio project pool.
---

**Rule:** Keep a campaign's exact selected windows separate from the shared project's broader source pool. Campaign selection changes may expand that pool, but must not narrow or remove existing project selections.

**Why:** Projects can be shared by multiple campaigns and edited directly in Studio. Destructive synchronization loses unrelated editorial work. A single start/end envelope also spans gaps between disjoint clips, so treating it as generation scope includes footage the campaign did not select.

**How to apply:** Preserve independent, exact window snapshots when passing footage to generation engines. Test both preservation of an existing wider project range and exclusion of gaps between separate campaign clips.