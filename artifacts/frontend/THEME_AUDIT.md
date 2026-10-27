# Theme audit: light, dark, and system

## How it works
- Storage key: `obtv-theme`. Stored values: `light`, `dark`, or `system`. Logic lives in `src/lib/theme.ts`.
- No stored value, or an invalid one, gives **dark**. This keeps the old default for returning users. Only an explicit `system` choice follows the OS.
- An inline script in `index.html` applies `html.dark` or `html.light` and sets `color-scheme` before the first paint, so the wrong theme never flashes. It uses the same rules as `theme.ts`.
- `src/components/theme-provider.tsx` wraps next-themes (`attribute="class"`, `enableSystem`). It saves the choice and updates the page when the OS setting changes while `system` is selected.
- `src/components/theme-toggle.tsx` is a radio group (`role=radiogroup`, `aria-checked`, roving tabindex, arrow keys). Test IDs: `theme-toggle`, `button-theme-{light|dark|system}`. It appears:
  - in the sidebar footer when signed in
  - in the mobile header
  - at the top right of the login page, with text labels
- Removed: the forced `document.documentElement.classList.add('dark')` in `layout.tsx`, and the forced `dark` class on the login root.
- Tests: `node --experimental-strip-types --test artifacts/frontend/src/lib/theme.test.ts` (6 passing).

## Tokens (`src/index.css`)
- `:root` holds the light tokens: cool paper surfaces and a darker primary at 212 100% 41% so it passes AA on light backgrounds.
- `.dark` holds the original dark values, unchanged.
- Both modes define every shadcn token (background, card, popover, muted, border, input, ring, destructive, chart 1-5, sidebar) plus new ambient backdrop tokens (`--ambient-*`).
- Any subtree with the `dark` class renders with dark tokens. Intentional exceptions use this.

## Audit of hard-coded colors (all of `src/`)
- **Status and accent text** (`text-{red,emerald,amber,green,blue,sky,teal,rose,cyan,yellow,...}-100..500`, about 150 uses): in light mode, one CSS block remaps these to 600-800 shades. That covers every page's badges, status pills, error text and warnings. Also covered:
  - the opacity variants `text-amber-400/80`, `text-amber-400/90` and `text-amber-100/90`
  - hover `-200` and `-300` text
  - the `:not(.dark *)` guard, so exceptions keep their original colors
- **Washes:** in light mode, `bg-white/5`, `bg-white/10` and `bg-sky-950/40` become foreground-tinted equivalents.
- **Tinted backgrounds** (`bg-*-500/10..15`, `border-*-500/30..50`): left as-is. They work on both surfaces.
- **Charts** in `ratings.tsx` and `socials.tsx`: grid, axes and tooltips already use `hsl(var(--border|muted-foreground|popover|card))`, so they follow the theme. `chart.tsx` uses tokens.
- **Emotion and person hex colors** (`dashboard`, `asset-detail`, `search-shelf`, `cut-strips`): these are data colors, kept as-is. They appear as fills, bars or bordered chips, not as body text.
- **Files fixed:**
  - `not-found.tsx`: gray-* replaced with tokens
  - `cut-strips.tsx`: zinc text, white/5 track and black divider replaced with tokens
  - `cut-preview-dialog.tsx` inline container: `bg-muted/40`
  - `studio-tab.tsx` and `project-detail.tsx` cut timeline bar and blocks: `bg-muted`
  - `media-pool-tab.tsx` progress track: `bg-muted`
  - `login.tsx`
  - `layout.tsx`
- **Toasts, dialogs, menus, tooltips, popovers and selects** are all shadcn components using tokens, so they follow the theme. The overlay `bg-black/80` stays as a scrim in both modes.
- **Sonner:** already reads next-themes, but it is not mounted. The app uses the Radix toaster.

## Intentional dark exceptions (search for `data-theme-exception`, or the media classes listed below)
1. `asset-detail.tsx` video player stage: `data-theme-exception="media-player"`, `dark bg-black`. This includes the Original / Dub / Preview switch overlaid on the video.
2. `asset-detail.tsx` NLE timeline band (`MomentsTimeline`, `PeopleTracks`, dialogue and AI-tag lanes): `data-theme-exception="nle-timeline"`, `dark` with zinc-950. The heatmap colors are tuned for a dark surface.
3. `bg-black` on `<video>`/`<img>` elements: letterboxing in `clip-player-dialog`, `cut-preview-dialog`, `trim-player`, `project-detail` reel preview, `person-detail` lipsync and preview, `asset-detail` exports, and the `graphics.tsx` lightbox. These are media, not themed.
4. Thumbnail overlays (`bg-black/60..80 text-white` duration badges, hover play scrims, the people card edit and delete chips, desk and desk-lists checkbox chips): these sit on images, so they stay dark in both modes for contrast.
5. Scrubber playhead and markers (`bg-white`, `bg-white/50..80`) inside exceptions 1 and 2.
6. The drag ghost in `library.tsx` (inline style, primary blue with white text) works in both modes.

No media is inverted or filtered.

## Routed pages covered by tokens and remaps
Login, `/` Dashboard, `/desk`, `/desk/favorites`, `/desk/projects`, `/desk/collections`, `/library`, `/library/:id`, `/studio`, `/studio/:id` (studio, refine, media pool, chat), `/campaigns`, `/campaigns/:id`, `/people`, `/people/:id`, `/insights`, `/ratings`, `/socials`, `/jobs`, `/ai`, `/search`, `/curator`, `/users`, `/training`, `/audit`, and 404.

`/graphics` is not routed (hidden). Its source uses tokens, apart from its media lightbox.

## Initial implementation audit limitations
- I took no screenshots of any route in light mode. Main agent's `scripts/test-theme-browser.mjs` covers these.
- Remap coverage for dynamically built class strings is assumed to work because Tailwind sees the literal class names. Any color built at runtime from string pieces would not be caught.
- Gradient hero washes on dashboard, insights, people and socials (`hsl(280 80% 60% / .15)` and primary at .25) are untouched. They are probably fine on light but not checked.
- The `insights.tsx` heatmap uses inline `hsl(20 90% 55% / alpha)`. Low-alpha cells may look faint on a light card.
- `co-appearance-map.tsx` SVG uses `currentColor` and tokens. Its light-mode look is not checked.
- Light-mode states that are only visible after interaction (open dialogs, toasts, menus, skeletons, error and empty states) are not checked.

## Completed browser verification

The main agent subsequently ran `scripts/test-theme-browser.mjs` against the authenticated development preview using normal mock login, with no auth bypass:

- 23 route visits including Studio and person detail; legacy AI/search routes correctly redirect to the library. All retained light mode, with no runtime exceptions or desktop horizontal overflow.
- Visual screenshots inspected for login, My Desk, library, ratings charts, ratings import dialog, library filters popover, and mobile My Desk.
- Real theme buttons verified preference persistence. Reload persistence, explicit dark mode, System selection and live OS appearance changes passed.
- Mobile My Desk had no horizontal overflow.
- Logo readability was corrected and visually rechecked.
- Seven theme unit tests, workspace typechecks, and frontend production build passed.

These checks do not claim every possible dialog/data/error combination was individually rendered. Campaign detail had no preview fixture; hidden Graphics is not routed. Their styling was statically audited. Toasts, uncommon error states, heatmap/co-appearance data variations, and every Studio sub-tab were not individually screenshot-tested.

## Follow-up fixes
- **Brand logo** (exception 7, `data-theme-exception="brand-logo"`): the wordmark's white lettering was invisible on light surfaces. In light mode the logo now sits on a deep-navy `.logo-plate`, both in the sidebar and mobile header and as a larger plate on the login page. The image itself is unchanged and not inverted. In dark mode the plate is transparent.
- **Invalid stored preference:** the inline script in `index.html` and `normalizeStoredPreference()`, called from `main.tsx` before the provider mounts, remove any invalid `obtv-theme` value. next-themes therefore never applies an invalid class, and the app falls back to dark. Covered by a unit test (7 tests passing).
