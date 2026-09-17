# Audit + load performance (main @ v0.16.6, all hardware-verified)

A full code audit of v0.16.0 found bugs far more serious than the perf work that preceded it.
Five fix rounds + a geometry-first rework followed. Everything below is tested on a 4090.

## Critical bugs found by the audit (all fixed)
1. **Edits silently reverting** (worst). _geo_sig sampled 3 vertices (first/middle/last) + counts +
   modifier types, and it gated a SESSION-LONG linked-duplicate share cache that was consulted
   BEFORE the dirty flag. So vertex paint, UV edits, material-index, smooth/flat, sculpting and
   shape keys could display PRE-EDIT geometry with no error. Now hashes the real buffers
   (positions/UV/material_index/sharp_face/colour) via mesh.attributes. 12/12 edit types detected;
   the old code failed all 12.
2. **F12 hung**: _force_full was cleared only when the queue drained, so every pass restarted with
   the full object set and wiped _geo_share. Ran to the 120s cap drawing 2 of 385 objects
   (re-loading the same two 1,470 times). Now 12.4s with all 382 face-bearing objects.
3. **Scattered instances dropped** when over budget (150 -> 5 loaded). Now 150/150.
4. **Solid-view edits lost**: Blender DESTROYS the RenderEngine when you leave Rendered view, so
   those edits never reach view_update. A @persistent depsgraph_update_post handler records them
   (object name AND 'mesh:<data>', since scatter sources usually aren't in the scene); the instance
   loop consults it too. Guarded by _vlr_viewport_live() -- a 2s timestamp guard had a blind window
   (edit in Rendered -> Solid -> edit within 2s = lost, measured 0/6).
5. **Unified splat sort** marked its cache valid before the sort succeeded.
6. **Splat sort direction** used M^-1 @ fwd; correct is M^T @ fwd (verified numerically: identical
   for rotation+uniform scale, WRONG under non-uniform scale). Fixed at all 4 sites.
7. **Unbounded _geo_share leak**: a full mesh copy + GPU batches per edit. Now cleared when the
   load queue drains (NOT every pass -- that broke cross-pass duplicate sharing: 18.5M tris
   resident instead of 12.3M and entry 5.86 -> 10.77s).

## Geometry-first loading (Claude Code's rework, v0.16.6)
One GPU batch per mesh: per-corner vertex buffers + a material-sorted index buffer drawn per slot
with draw_range; textures stream in after geometry, smallest first; no buffer hash on the load path;
duplicates share by evaluated-mesh pointer, content hash only within cheap groups; 1.5s/frame budget.
Azola: geometry on screen 6.09 -> 2.86s, fully loaded 6.69 -> 5.17s, F12 14.6 -> 12.4s, data
identical to legacy extraction, F12 image identical.

## Current numbers (Azola, 394 objects / 18.6M tris) -- v0.16.6, hardware-verified
geometry on screen 2.76s | fully loaded 4.97s | re-entry 0.05s | clicks 2.5ms |
F12 12.36s all 382 objects, image identical | edits 12/12 | scatter 150/150 |
Solid-view edit immediately after leaving Rendered 6/6 (was 0/6) | delayed 6/6 | scatter source pass

RESIDENT TRIANGLES: **12.76M**, not the 12.26M I kept quoting -- that figure was v0.16.4's. The
geometry-first sharing merges very slightly fewer meshes; the rendered image is identical. Don't
treat 12.26M as a regression target.

## Still open (known, not fixed)
- Objects with no colour attribute get a SNAPSHOT of the material viewport colour at extraction
  time; later material-colour edits don't propagate (pre-existing).
- Viewport colour management (Filmic/AgX, exposure, gamma) doesn't apply; Film Transparent gives an
  opaque F12 background; node-group type-coercion bug falls back silently; bakes are 8-bit in the
  wrong colour space; splat conversion ignores texture alpha; splat IDs restart at 1 each session
  so a stale saved anchor can adopt a new cloud. ~20 medium items in REVIEW_v0.16.0.md.
- Splats are runtime-only (not saved in the .blend).
- Unified splat path ignores Backface Cull + the compute pre-pass.

## Latent hazard worth remembering (flagged by Claude Code)
_vlr_viewport_live() references _ENGINE_ID inside a broad try/except. If that name were ever missing
or renamed, the NameError would be SWALLOWED and the function would always return False. Checked:
_ENGINE_ID is defined (line ~2288) before use (~2325), and the failure direction is fail-safe -- a
False result means the handler records edits even while live (the set grows a little), NOT that
edits are lost. Still: broad try/except around a name lookup hides typos, and this pattern recurs
throughout the engine.

## Process notes
- Version numbers MUST be monotonic across contributors. Claude Code branched from v0.16.4 and
  labelled its build v0.16.5; only engine.py differed, so a straight copy would have silently
  reverted three fixes (two of which it had itself reported). Caught by diffing, not by the number.
- Two of my stated verification targets were themselves wrong (a stale triangle count, and a
  runtime-ordering claim I had only checked statically). Claude Code re-derived both. State targets
  with the version they came from, and mark static-only checks as unverified.
- My code reading finds structural bugs but NOT cost bugs, and anything I cannot execute (Blender
  API shapes, threading/lifecycle assumptions) is unreliable: across these rounds roughly every fix
  I shipped introduced one new bug -- a gate on a flag that is always true, a memo on an object
  Blender rejects attributes on, a NameError from a variable used ~50 lines before assignment, a
  cache cleared at the wrong moment. Treat my output as a proposal that needs a test run.
