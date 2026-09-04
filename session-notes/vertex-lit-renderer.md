# Vertex Lit Renderer — Session Notes

## Branch
`feature/blender-vertex-lighting`

## Files
- `addons/vertex_lit_renderer/` — installable Blender addon (zip: `addons/vertex_lit_renderer.zip`)

## What it is
A custom Blender 4.4 render engine (`bpy.types.RenderEngine`) that implements:
- **Gouraud (per-vertex) shading** — classic vertex-lit look matching PS1/N64-era game engines
- **Shadow maps** — per-vertex shadow sampling from primary Sun light
- **Hemisphere ambient** — sky/ground colour blend based on world-space normal
- **Texture support** — reads Principled BSDF Base Color texture from material node tree
- **Vertex colour support** — POINT domain colour attributes
- **Progressive GI** — optional one-bounce Monte Carlo GI in background thread

## Architecture
```
engine.py   — RenderEngine subclass, mesh/light management, draw loop
shaders.py  — GLSL vertex + fragment shaders
gi.py       — BVHTree-accelerated GI, ProgressiveGI thread class
props.py    — Scene PropertyGroup
ui.py       — Render Properties panel
```

## Key Implementation Notes

### Mesh Extraction
- Must use `bpy.data.meshes.new_from_object()` not `to_mesh()` — geo nodes objects
  return invalidated handles from `to_mesh()`
- Must call `mesh.calc_loop_triangles()` explicitly — not guaranteed on `new_from_object` meshes
- Use `mesh.corner_normals[loop_index]` not `tri.split_normals` (removed in Blender 4.1)
- Convert `bpy_prop_array` to `tuple()` immediately — they are views into C memory
  that become dangling pointers after `bpy.data.meshes.remove(mesh)`

### Rebuild Loop Prevention
- `new_from_object` + `remove` fires `bpy.types.Mesh:is_updated_geometry` updates
- `view_update` checks `self._rebuilding` guard flag set during `_rebuild`
- Only `bpy.types.Object` and `bpy.types.Mesh` geo updates trigger dirty (not Collection)
- `bpy.types.Light` updates → `_lights_dirty` flag → re-cache lights without full rebuild

### Performance
- Lights, sun, light-space matrix cached in `_rebuild`, read by `view_draw` (Bug 3 fix)
- `uNormalMat` (transpose-inverse) computed on CPU per-object, not per-vertex in shader (Bug 4)
- GI world-space vertex data built from cached local data + matrix_world (no second `new_from_object`)
- GI thread yields via `time.sleep(0.005)` every 100 vertices to keep viewport responsive

### Energy Scaling
- `energy_scale = 0.1` default — works for Blender 4.4 default sun (1 W/m²)
- Point lights use 20m falloff radius (not `shadow_soft_size` which is shadow softness ~0.25m)
- GI bounce scale = `cos_in` (not `2π·cos` which overwhelms direct light by 6x)

### Known Limits (v0.1)
- Viewport only — F12 render is a no-op stub
- Single shadow caster (first Sun light)
- CORNER-domain vertex colours not yet supported (POINT only)
- GI disabled by default (use_gi=False) — enable for static geo, disable for geo nodes

## Tested on
- Blender 4.4.0 Linux x64 (via Xvfb)
- 1 rebuild per 10 frames confirmed ✓
- 3.3ms min frame time confirmed ✓
- All 5 API bugs fixed and regression-tested ✓
