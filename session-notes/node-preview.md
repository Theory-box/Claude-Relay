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
