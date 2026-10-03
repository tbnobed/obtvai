---
name: Production multihomed routing
description: Preserve internal Curator connectivity when repairing external access.
---

Keep the internal-network default route and DNS behavior intact when changing external access. Use source-based return routing on the external-facing LAN, preserving specific internal and directly connected destinations rather than exempting all private destinations.

**Why:** External SSH requests reached the production server, but its replies left through the internal-network interface. Curator HTTPS also depends on an internal address reached through that preferred default route, so swapping default gateways would risk breaking it.

**How to apply:** Inspect the live NetworkManager profiles and routing rules before changes. Protect remote changes with a timed rollback, validate a fresh SSH session and actual Curator/storage access, then cancel the rollback. Do not rely on a temporary route to the agent's current outbound IP as a permanent access solution. Persistent rules were configured on the server, not in this repository.

Do not rely on automatic NetworkManager route metrics to preserve the preferred default gateway across reboots.

**Why:** After a reboot, automatic metrics reordered the two Ethernet defaults. External SSH still worked through its policy table, but Curator HTTPS followed the wrong main-table default. A successful pre-reboot check does not establish stable route priority.

**How to apply:** Use explicit route priorities and/or explicit internal destination routes, preserving the source-based SSH policy. Verify both main-table internal routing and external return routing after changes and after reboot.

The user requires access from any 192.168.x.x address, not just the server's local subnet.

**Why:** A blanket 192.168.0.0/16 main-table exception sent replies to routed LAN clients through the internal default gateway instead of the external-facing gateway.

**How to apply:** Route external-interface replies to routed 192.168.x.x clients through that interface's gateway. Preserve narrower exceptions for directly connected Spark/node networks. Those overlapping subnets remain reserved for the physical links; reaching identically numbered remote clients would require a separate network design.