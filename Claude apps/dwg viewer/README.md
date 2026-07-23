# DWG Viewer & JPG Exporter

A single self-contained `dwg-viewer.html` — open it in a browser, drop in `.dwg` files, view them,
and export high-resolution JPGs. No install, no server, no upload: parsing happens entirely
client-side in WebAssembly.

---

## Use

Open `dwg-viewer.html` in a browser. Drop `.dwg` files anywhere on the page (or **Add files**).
Click a drawing in the sidebar to view it. Scroll to zoom, drag to pan, **Fit** to reframe.

### Export

**Export** opens the drawer:

| Control | What it does |
|---|---|
| DPI | 72–1200. Output px = drawing units × DPI/96. Real DPI is written into the JPEG header. |
| Background | Dark or white. White also remaps white/color-7 linework to dark so it stays visible. |
| Quality | JPEG quality. |
| Line weight | Constant *pixel* thickness, so raising DPI reveals finer detail instead of just scaling lines. |

**Save this drawing** exports the active file. **Export all as ZIP** exports every loaded file.

### Regions (crop boxes)

For sheets whose content is spread far apart — a plan at the top, elevations far below — exporting
the whole extent wastes nearly all the pixels on empty space. Regions fix that.

Click **Regions**, then:

- **Drag** on empty canvas to draw a box
- **Drag a box** to move it; **corner handles** to resize
- **×** button or **Delete** key to remove the selected box
- **Space+drag** to pan, wheel to zoom (so you can move between far-apart areas)

Boxes are per-file and stick to the drawing as you pan/zoom. Go file by file drawing boxes, then export once.

Region export options:

| Option | Behavior |
|---|---|
| **Merged** | All boxes packed into one image, empty space between them removed (Row or Column layout). |
| **Separate** | One JPG per box (zipped when more than one). |
| **Region resolution** | 1× / 2× / 4× / 8× multiplier on DPI, applied *only* to regions. Default 4×. |
| **Also export the full page** | Adds the whole sheet alongside the regions. Off by default. |

**Export all** honors each file's boxes: a file with regions exports only its regions; a file with none
exports whole.

**Why the resolution multiplier exists.** A region renders natively at its own viewBox (it is not cropped
out of a whole-page render), but pixel count still follows `units × DPI/96`. On drawings with small unit
extents a typical content box lands around ~900 px at 300 DPI, which looks soft. The multiplier raises the
density for regions only; the exported JPEG's DPI metadata scales to match. 4× is a good default, 8× for
very tight crops.

---

## Limits

- **16000 px** per edge (browser canvas limit), applied to single images *and* the merged composite.
  The readout warns when a setting would clamp.
- Regions live for the session — reloading the page clears them.
- Very large drawings (multi-MB SVG) view and export fine but may pan/zoom less smoothly.

---

## How it works

| Layer | Detail |
|---|---|
| Parser | `@mlightcad/libredwg-web` (LibreDWG compiled to WASM), loaded from jsDelivr |
| Pipeline | `.dwg` → LibreDWG → SVG → sanitize → canvas raster → JPEG |
| Parallelism | Classic Web Worker pool (`min(hardwareConcurrency, 4)`) for parsing, with main-thread fallback |
| Memory | Preview-first: only a small thumbnail + metadata per file; full SVGs re-parsed on demand via a 6-entry LRU |
| ZIP | JSZip, loaded on demand |

Everything is client-side. Files never leave the machine.

---

## Notes for future work

See `session-notes/` for the detailed engineering log — the bugs found, why they happened, and how each
was verified. Worth reading before changing the parse or export path; several non-obvious constraints are
recorded there (worker type, SVG escaping, WASM memory handling).

Possible next steps:

- Raster "fast view" mode for very large drawings (show the preview until zoomed in)
- Persist regions across reloads
- Auto-detect content clusters and propose regions
