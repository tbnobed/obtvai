---
name: Production multihomed routing
description: Preserve internal Curator connectivity when repairing external access.
---

Keep the internal-network default route and DNS behavior intact when changing external access. Use source-based return routing on the external-facing LAN, with private destinations continuing through the main routing table.

**Why:** External SSH requests reached the production server, but its replies left through the internal-network interface. Curator HTTPS also depends on an internal address reached through that preferred default route, so swapping default gateways would risk breaking it.

**How to apply:** Inspect the live NetworkManager profiles and routing rules before changes. Protect remote changes with a timed rollback, validate a fresh SSH session and actual Curator/storage access, then cancel the rollback. Do not rely on a temporary route to the agent's current outbound IP as a permanent access solution. Persistent rules were configured on the server, not in this repository.