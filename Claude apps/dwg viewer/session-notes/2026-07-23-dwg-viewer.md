# DWG Viewer — Session Notes

Browser-based DWG viewer + JPG exporter. Single self-contained `dwg-viewer.html`, no build step.
Validated end-to-end in real headless Chrome (puppeteer) against six real AutoCAD 2018 architectural
sheets (428 KB – 1.8 MB, 966 – 3,446 entities each).

---

## Stack (all verified working)

- **Parser:** `@mlightcad/libredwg-web@0.7.8` (LibreDWG → WASM, ~9.5 MB wasm blob).
- **Browser load:** dynamic `import()` of the dist bundle from jsDelivr, then
  `LibreDwg.create(<wasm dir url>)` — the argument sets Emscripten's `locateFile` so the wasm is
  fetched from the CDN. The dist bundle is browser-clean (no node globals).
- **API shape:** `dwg_read_data(arrayBuffer, Dwg_File_Type.DWG)` → ptr; `dwg_get_version_type(ptr)`;
  `convert(ptr)` → database (`.entities`, `.tables.BLOCK_RECORD.entries[].entities`);
  `dwg_to_svg(db)` → SVG string; `dwg_free(ptr)`.
- **ZIP:** JSZip via script tag, loaded on demand.

Converter output: root `<g stroke="#000000" stroke-width="0.1%" transform="matrix(1,0,0,-1,0,0)">`
(note the Y-flip). `viewBox` is in drawing units. Per-entity ACI colors including white/color-7.

---

## Bugs found and fixed

Each was reproduced first, then fixed, then re-verified in a real browser.

### 1. Unescaped ampersand broke whole files (the big one)

**Symptom:** a file failed with error detail `thumb` and could not be viewed or exported.

**Cause:** the SVG converter does **not** escape text content. A sheet label containing `&`
(e.g. "PLANS & ELEVATIONS") emits a raw `&`, producing invalid XML. Invalid XML is rejected by
*both* `<img>` rasterization (used for thumbnails and export) and `DOMParser` (used for the viewer) —
so a single character in a text label killed the entire file.

**Confirmed in-browser:** raw `&` → `img.onerror` + `parsererror`; escaped → both fine.

**Fix:** `sanitizeSvg()` at the parse boundary (both worker and main thread) — escapes bare `&` via
negative-lookahead regex (preserving already-valid entities) and strips XML-illegal control chars.

**Scale of it:** **five of the six** real sheets contained bare ampersands. This was not an edge case.

**Second fix, same bug:** a failing thumbnail was marking the whole document as errored. Thumbnail
generation is now non-fatal — a preview failure leaves the drawing fully usable with a placeholder icon.

### 2. ACAD_TABLE entities crash the SVG converter

`dwg_to_svg` throws `Cannot read properties of undefined (reading 'topBorderVisibility')` on
`ACAD_TABLE` entities inside block records. This is a converter bug, *not* a parse failure — the
drawing data is fine.

**Fix:** `convertResilient()` — on throw, cumulatively strip entity types (TABLE/ACAD_TABLE first)
from `dwg.tables.BLOCK_RECORD.entries[].entities` and retry. Recovered files render with an amber
"partial" marker listing which types were dropped. (None of the six real sheets needed this; the
r14 sample file does.)

### 3. WASM memory leak across batches

`dwg_free(ptr)` only ran on the success path, so every failed conversion leaked WASM memory —
which then caused *cascading* failures later in a batch. Fix: `try { ... } finally { dwg_free(ptr) }`.

---

## Architecture decisions

**Line weight in user units, not percent.** The converter's `0.1%` stroke scales *with* the drawing,
so raising DPI never revealed more detail — lines just got thicker. Now stroke width is computed in
user units to hit a target pixel width: `strokeUser = lineWeight * srcW / outW`. Constant pixel
thickness means higher DPI genuinely resolves finer detail. No `vector-effect` dependency, so it
works across renderers.

**Real DPI in the JPEG.** Output px = `units × DPI/96`; the DPI is then patched into the JFIF APP0
segment (units=1, Xdensity/Ydensity) so downstream tools see the true value.

**White-on-white.** White/color-7 strokes and fills are remapped to near-black when exporting or
viewing on a light background, otherwise they're invisible.

**Workers must be classic, not module.** `new Worker(url, {type:"module"})` is blocked in many
environments; classic workers support dynamic `import()` and work fine. Built from a Blob URL with a
startup ping probe (4 s timeout) and graceful fallback to main-thread parsing if workers or the CDN
are blocked.

**Parsing parallelizes, rendering doesn't.** Parse-in-worker works and is a real speedup. Export-in-
worker via OffscreenCanvas fails on Chrome — SVG images throw `InvalidStateError` in workers — so a
probe detects this and falls back to main-thread rendering.

**Preview-first memory model.** Each document holds only `{File handle, thumbnail dataURL, metadata,
regions}`. Full SVGs are discarded after the thumbnail and re-parsed on demand through a 6-entry LRU
(never evicting the active doc). This matters: one of the real sheets produces a **16.9 MB** SVG.

**Sidebar uses raster thumbnails, not live SVG.** Live SVG in the list was the O(n) DOM killer.
Cards also update incrementally (`appendCard`/`patchCard` + a `cardEls` Map) rather than rebuilding
the whole list, which was O(n²) and caused progressive slowdown on large batches. `mapLimit()` bounds
concurrency on both load and export so memory stays flat.

---

## Regions (crop boxes)

Feature request: sheets often have content spread miles apart, so even a high-DPI whole-page export
is blurry because nearly all pixels land on empty space.

**Model:** a region is `{id, x, y, w, h}` in viewBox coordinates. Export sets
`viewBox="x y w h"` plus width/height from the region size — so the region renders **natively at its
own extent**, not cropped out of a whole-page raster.

**Interaction:** screen-space overlay that is a sibling of the transformed world (not a child), so
handles stay a constant screen size at any zoom. Recomputed on every `applyTransform`. In region mode:
drag = draw/move/resize, Space+drag = pan, wheel = zoom, Delete or × = remove. A sub-4px drag is
treated as a click, not a degenerate box. Regions are stored per document and survive switching files.

**Export modes:** *merged* (tiles composited into one image, row or column, gaps removed) or
*separate* (one JPG per region, zipped when >1). `docExportEntries()` produces the entry list for a
document, so **Export all** honors each file's regions automatically — regioned files export only
their regions, un-regioned files export whole.

**Region resolution multiplier (1×/2×/4×/8×, default 4×).** The reason regions still looked soft:
pixel count follows `units × DPI/96`, and on drawings with small unit extents a typical content box
lands around **~900 px at 300 DPI**. Measured on a real sheet: full viewBox 1775 × 9092 units, so a
~1/6-width box is only ~296 units wide → 924 px. The multiplier raises density for regions only, and
the JPEG DPI metadata scales with it. Verified: 1× → 7279 px @ 300 DPI, 4× → 16000 px @ 1200 DPI,
8× → 16000 px @ 2400 DPI.

**Composite clamp.** Individual images clamp to 16000 px, but the *merged* composite sums tile widths
and can exceed canvas limits (first test produced 18222 × 9098). The merged path now scales the whole
composite by `s = min(1, MAX_PX / max(W,H))` and the readout warns when it clamps.

---

## Validation performed

All in real headless Chrome, not simulated:

- All six real sheets: load, preview, view, export — **0 errors**, valid JPEGs with correct DPI.
- Export-all → valid ZIP, six correctly-named JPEGs.
- Injected-ampersand test proving the sanitizer recovers an otherwise-fatal file.
- Regions: draw 2 → merged export (valid JPEG, clamped correctly) and separate export (ZIP of 2);
  delete works.
- Regression: panning still works with region mode off (no stray boxes); regions stay isolated
  per file across switching; whole-drawing export unchanged when a file has no regions.
- Mixed Export-all: file A (2 regions + full page) + file B (no regions) → exactly 4 images.
- Memory: LRU cache stays ≤6 with 12 files loaded; zero live SVG nodes in the sidebar.

---

## Gotchas for future sessions

- Don't switch workers to `{type:"module"}` — it breaks in sandboxed environments.
- Don't remove `sanitizeSvg` — most real-world architectural sheets contain `&` in text.
- Don't move `dwg_free` out of a `finally` — leaks compound across a batch.
- Don't render the sidebar with live SVG — use raster thumbnails.
- `<img>`-based SVG rasterization is strict about XML validity; inline rendering is more forgiving.
  If something renders on screen but fails to export, suspect invalid XML first.

## Possible next steps

- Raster "fast view" mode for very large drawings (the 16.9 MB sheet pans sluggishly).
- Persist regions across reloads.
- Auto-detect content clusters and propose regions automatically.
