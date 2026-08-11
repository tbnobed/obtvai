---
name: Premiere FCP7 XML (xmeml) interchange limits
description: What survives xmeml import into Premiere and what needs a panel/preference instead
---

- "Scale to Frame Size" does NOT round-trip through FCP7 XML — Premiere neither writes nor reads it (confirmed via Adobe forums). Never bake a Basic Motion scale % as a substitute: it sticks after a proxy→hi-res relink and blows the frame out (e.g. 200% on a 960×540 proxy becomes 200% on 1080p hi-res).
- **How to apply:** declare each file's TRUE width/height in samplecharacteristics and leave scaling alone. The flag is set either by Premiere's Preferences → Media → Default Media Scaling, or by a panel (CEP/UXP `projectItem.setScaleToFrameSize()`) — only code inside Premiere can touch it.
- xmeml timebase must be an integer; fractional NTSC rates (29.97/23.976/59.94) = rounded timebase + `<ntsc>TRUE</ntsc>`. Frame math must use the actual fps, per-asset.
- Curator's Premiere panel matches assets by the clip's Log Note, formatted `assetId=<curator asset UUID>`.
