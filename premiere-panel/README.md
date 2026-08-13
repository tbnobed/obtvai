# OBTV AI — Premiere Pro panel (UXP)

Delivers Studio cuts straight into the open Premiere project.

Sign in with your obtv-ai account, pick a Studio project, and hit
**Import cut into Premiere**. The panel:

1. Fetches the cut as FCP7 XML from the server (same exporter as the web app,
   so `EXPORT_PATH_MAP` relinking and Curator hi-res source paths apply).
2. Imports it into a bin named after the cut.
3. Applies house sequence settings by cloning them from a donor sequence
   named **OBTV HOUSE** (see below) — Premiere ignores sequence format
   declared in FCP7 XML, so this is the only reliable way.
4. Best-effort sets **Scale-to-Frame-Size** on imported footage and reports
   anything still offline (usually a missing media mount on the workstation).

## One-time setup: the "OBTV HOUSE" donor sequence

Create one sequence from the house preset (AVC-Intra 100 1080i, 29.97,
upper field first, AVC-Intra Class100 previews, Rec.709) and name it exactly
`OBTV HOUSE`. Keep it in your project template so every project has it.
The panel copies its full settings — editing mode, previews, color — onto
each imported cut sequence. If it's missing, the import still works but the
panel warns that settings were not applied.

Requirements: Premiere Pro 25.0 (2025) or newer with UXP panel support; the
workstation must reach the obtv-ai server URL and mount the media paths
produced by `EXPORT_PATH_MAP`.

## Load during development

1. Install Adobe's **UXP Developer Tool** (Creative Cloud app).
2. Add Plugin → select `premiere-panel/manifest.json`.
3. With Premiere running, click **Load**. The panel appears under
   Window → UXP Plugins → OBTV AI.

For permanent installs, package with UDT (**Package** button → `.ccx`) and
double-click the `.ccx` on each workstation.

## Notes

- Auth is a 30-day bearer token (issued by `POST /api/auth/login` with
  `return_token: true`), stored in panel localStorage, revoked on sign-out.
- The temp XML is written to the plugin temp folder.
- Premiere's UXP API surface is still evolving; scale-to-frame and offline
  detection are feature-detected, so on older builds the import still works
  and the fix-ups quietly skip.
