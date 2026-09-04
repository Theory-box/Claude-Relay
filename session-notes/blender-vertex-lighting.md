# Blender Realtime Vertex Light Baking — Session Notes

## Branch
`feature/blender-vertex-lighting`

## Target
Blender 4.4 add-on (offtopic / standalone, not related to jak modding)

## Status
**Phase: Research complete. No code written yet.**

---

## What We're Building

A Blender add-on that does two things:
1. **Realtime GI vertex light baker** — bakes lighting (with shadows + GI bounces) to vertex colors automatically whenever lights or geometry change
2. **GLSL viewport overlay** — composites those vertex colors multiplicatively over existing materials in the viewport, without touching any material

Goal: looks like a realtime vertex-lit game engine preview, all inside Blender, zero material edits.

---

## Architecture (Planned)

```
depsgraph_update_post fires
        ↓
Throttle check (time delta, dirty flag)
        ↓
Extract mesh verts + normals + light data from scene
        ↓
trimesh + embreex: batch ray cast (shadows + GI hemisphere)
        ↓
Accumulate per-vertex lighting → numpy float32 array
        ↓
Expand per-vertex → per-loop (Blender's internal storage)
        ↓
color_attributes[...].data.foreach_set("color", flat_array)
        ↓
tag_redraw() → viewport redraws
        ↓
draw_handler (POST_VIEW or POST_PIXEL) fires
        ↓
gpu.state.blend_set('MULTIPLY') + draw mesh with vertex colors
        ↓
gpu.state.blend_set('NONE') → restore state
```

## Planned File Structure
```
blender_vertex_lighting/
├── __init__.py       — registration, UI panel, preferences
├── bake.py           — embreex GI solver + depsgraph handler
├── overlay.py        — GLSL viewport composite draw handler
└── deps.py           — pip dependency installer (trimesh, embreex)
```

---

## Next Steps (Start Here Next Session)

1. Scaffold `__init__.py` — register panel, toggle operator, preferences (GI samples, bounce count, throttle ms)
2. Write `deps.py` — auto pip install trimesh + embreex into blender user scripts/modules
3. Write `bake.py` — start with direct light only (no GI), get the loop working first
4. Write `overlay.py` — draw_handler with MULTIPLY blend
5. Test on simple scene
6. Add GI hemisphere sampling pass
7. Add multi-bounce

---

## Key Decisions To Make

- **POST_VIEW vs POST_PIXEL for overlay** — POST_PIXEL avoids depth z-fighting, needs vertex projection. POST_VIEW is simpler but needs depth test disabled.
- **Per-object BVH or combined scene BVH** — combined is correct for inter-object GI/shadows but expensive to rebuild. Probably combined with smart dirty tracking.
- **GI sample count** — user-configurable. Default suggestion: 8 samples, 1 bounce for "fast preview" mode.
- **Throttle interval** — user-configurable. Default: 200ms.
