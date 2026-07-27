# Node Preview Live — session notes

**Branch:** `feature/node-preview` (off `main`)
**Blender target:** 4.4 (tested against a local 4.4.0 build)

## Goal
See procedural shader nodes (Brick, Noise, ColorRamp, Hue/Sat...) as an image
while editing, since the final render is Workbench (which never evaluates the
node graph, only shows the active image-texture node).

## Architecture (v0.2 — REWRITTEN after a freeze bug)
v0.1 rendered in-process on the main thread -> **froze the whole UI for the
render duration** (verified: a 256px render took ~2 min under software EEVEE;
also mangled the output path). Replaced with a **background-process** design:

1. Build a tiny temp scene in the main Blender: a COPY of the user's material,
   its target-node output rewired through an Emission to a fresh Output, on a
   1x1 UV plane under an orthographic camera. (Real material never touched.)
2. `bpy.data.libraries.write({scene})` -> a small temp .blend (only that scene
   + deps). Then the temp datablocks are removed from the main file.
3. Spawn a headless `blender -b job.blend --python np_worker.py -- SCENE OUT`
   via `subprocess.Popen` (non-blocking). The worker forces Cycles (1 sample,
   CPU), renders to PNG.
4. A `bpy.app.timers` poll (0.1s) loads the PNG when ready, tiles it (numpy
   np.tile NxN), writes it into a persistent image datablock, shows it in any
   open Image Editor. Temp files cleaned up.

Live mode: `depsgraph_update_post` sets a dirty flag; the timer starts a job
after `debounce` seconds of quiet (guarded by a busy flag + 0.1s cooldown so
our own datablock churn doesn't self-trigger).

## Verified on local Blender 4.4 (headless + xvfb)
- start_job returns in ~0.003s (non-blocking; no UI freeze).
- Full round-trip ~1-2s on a 1-core/no-GPU VM (spawn + render + load).
- Brick + Noise render correctly; tiling=2 -> 512x512 as expected.
- Live auto-render fires on edit and updates the image (brick -> noise).
- Temp files cleaned; timer unregisters when idle.
- `_find_target` resolves material+node via the active-object-material
  fallback even when space.id/edit_tree are unpopulated.

## Known remaining costs / limitations
- Fresh Blender spawn per render (~1-2s launch overhead each). NEXT OPTIMISATION:
  a persistent worker to cut this to <0.5s.
- Colour round-trips linear->linear through the PNG (both images default sRGB;
  should match, minor risk of a slight shift).
- Top-level Material nodes only (not groups, not World/Light).
- Materials using packed/relative image textures may not resolve in the worker.

## Milestones
1. **DONE + tested:** live render -> image datablock -> Image Editor.
2. **TODO:** viewport (Workbench) routing via a shader Image Texture node +
   active-vs-selected node handling + viewport GPU-texture refresh.
3. **TODO:** persistent worker; "Finalize" high-res bake button.

## Next actions
- User device test on the 4090 (expect much faster than the VM numbers).
- If good, add persistent worker, then start Milestone 2.

## v0.3 — hardening pass (audited on Blender 4.4)
- FIX: live mode now follows the active node (selection doesn't fire a
  depsgraph update, so the timer polls active-node identity). Fixed a deadlock
  where the debounce reset every tick.
- NEW: Lock feature — "Lock to Node" captures the current node; preview stays
  on it while you click/edit other nodes; unlock to resume following.
- Process cleanup verified: children reaped after completion, after 120s
  timeout, and on unregister/close mid-render (0 lingering in all tests).
- Confirmed no self-triggered render loop (the busy flag is the real guard);
  post-render cooldown reduced 0.1 -> 0.05s so live edits aren't dropped.
- No leftover temp files in any tested path.
- All checks pass headless on a local 4.4.0 build.

## v0.4 — GPU + samples + bigger sizes
- Worker now renders on GPU (activates the first available backend: OPTIX/
  CUDA/HIP/METAL/ONEAPI from the user's prefs) with automatic CPU fallback if
  no GPU device is present.
- NEW "Samples" slider (default 1, 1-256) passed through to the worker — raise
  for anti-aliased edges. Denoising stays off (emission has no light noise).
- Resolution cap raised 2048 -> 4096; tiling output cap raised 4096 -> 8192.
- Verified headless on 4.4: samples plumbing, CPU-fallback path, 4096 accepted,
  tiling 4 -> 1024. GPU branch is static-reviewed only (no GPU on the test box).
- Note: fresh-process-per-render means GPU context init each spawn; GPU mainly
  wins on big (4096+) / high-sample renders. A persistent worker would remove
  that per-spawn overhead — still the top future optimisation.

## v0.5 — device preference + status readout
- Add-on Preferences: "Render Device" = Auto / GPU / CPU. GPU uses the backend
  already set in the user's Cycles prefs (OptiX on desktop, Metal on the Mac).
- Worker writes a .status sidecar with the device it actually used; the panel
  shows "Rendered on: GPU (OPTIX)" (checkmark) or "Rendered on: CPU" (error icon
  if GPU/Auto was requested but fell back) — so GPU success/fallback is visible.
- BUGFIX: worker script was cached and only written if missing -> add-on updates
  ran a STALE worker (arg mismatch -> crash). Now always rewritten.
- Verified headless: Auto/CPU/GPU modes all report correctly (CPU on the no-GPU
  test box, incl. visible fallback when GPU requested); status files cleaned up.
  Actual GPU-success path is static-reviewed only (no GPU on the test box).

## v0.6 — Finalize to Object (fixes multi-object sharing)
- ROOT CAUSE of "refreshing one object changes another": there is a single
  shared image datablock (NodePreview_Result); the preview overwrites its
  pixels by NAME every render. Saving-as-JPEG doesn't detach the object's node
  from that datablock (the datablock keeps its name), so later previews clobber
  it. Any object whose node points at NodePreview_Result shares it.
- FIX: "Finalize to Active Object" button. Copies the current preview into a
  new independent, uniquely-named, packed image and repoints the active
  object's image-texture node(s) at it. Object then owns its image; future
  previews never touch it. Removes the manual save/reload workflow.
- Verified headless on 4.4: after finalize, later previews change
  NodePreview_Result but leave the finalized object's image untouched.
