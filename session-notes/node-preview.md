# Node Preview Live — session notes

**Branch:** `feature/node-preview` (off `main`)
**Blender target:** 4.4

## Goal
Let procedural shader nodes (Brick, Noise, ColorRamp, Hue/Sat, etc.) be seen
as an image while editing, since the final render is Workbench, which only
shows the active image-texture node and never evaluates the node graph.

## Approach (decided)
Fork the mechanism of `node-preview-reborn` (GPLv3), but change its output
sink: instead of drawing a GPU overlay above the node, write the rendered
swatch into a `bpy.data.images` datablock. That datablock is what the Image
Editor shows now (Milestone 1) and what a shader Image Texture node will
sample for the Workbench viewport later (Milestone 2).

## Milestones
1. **DONE (untested on device):** live render -> image datablock -> Image
   Editor. Resolution + tiling + debounce controls in Shader Editor N-panel.
   Manual "Refresh" (guaranteed) + "Start Live" (debounced modal auto-refresh).
2. **TODO:** route the same datablock onto the object via a shader Image
   Texture node; solve active-vs-selected node so Workbench Solid+Texture
   keeps showing it while a procedural node is being edited; viewport GPU
   texture refresh nudge.
3. **TODO:** "Finalize" high-res bake button.

## Milestone 1 implementation notes (`addons/node_preview_live.py`)
- Renders a COPY of the material on a temp plane in a temp scene; real
  material is never touched.
- Engine chosen at runtime (prefers Cycles) to dodge the EEVEE identifier
  change across 4.2-4.4.
- Temp plane/camera built from raw data (no bpy.ops), 1x1 ortho framing.
- Tiling = numpy np.tile post-step (coordinate-source agnostic; seamless iff
  the 0..1 swatch is seamless). Resolution is per-tile; final capped 4096/side.
- Live loop = depsgraph_update_post sets a dirty flag; a modal timer renders
  after `debounce` seconds of quiet, guarded by a rendering flag + 0.15s
  cooldown to avoid self-triggering.

## Known risks / where to look if it misbehaves (NOT runtime-tested here)
- `bpy.ops.render.render` under `temp_override` from a modal timer is the
  single highest-risk call; there is a window.scene-swap fallback.
- Colour round-trips linear->linear through the PNG; both images default sRGB
  so it should match, minor risk of a slight shift.
- Group-interior nodes and World/Light trees are intentionally unsupported in
  M1 (reports a friendly message).

## Next actions
- Get device test result (does Refresh produce a correct swatch on 4.4?).
- Decide colour-management handling if any shift appears.
- Then start Milestone 2 (viewport routing).
