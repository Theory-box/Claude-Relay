# Session Notes: Photon Splat Prepass (Blender Addon)
**Branch:** `restructure/offtopic-blender`  
**Status:** Research complete. Ready to build.

---

## What This Project Is

A Blender 4.4 Cycles addon that bakes an irradiance cache into a VDB emission volume
to reduce noise in dark indirect-lit interiors (basements, corridors, rooms lit through
doorways). The volume is invisible to the camera; bounce rays hit it instead of having
to trace all the way back to the original light source.

---

## Current State

All research phases are complete. No code written yet.

### Files in `offtopic/Blender/`
| File | Contents |
|---|---|
| `research-photon-splat-prepass.md` | Algorithm landscape, full technical design, resolved unknowns |
| `research-phase2-implementation.md` | Implementation specifics: addon structure, operator model, VDB transform math, gaussian blur, full code sketches |
| `bug-audit.md` | 19 pre-identified bugs with exact fixes (5 critical, 5 high, 5 medium, 4 low) |
| `DOCUMENTATION.md` | User-facing docs: settings, workflow, limitations, troubleshooting |
| `knowledge-base/gpu-rendering.md` | GPU rendering notes (pre-existing) |
| `install/` | Blender 4.4.3 binary parts |

---

## Key Decisions Made During Research

### Algorithm
- Probe positions → mini Cycles renders → VDB emission volume
- Not photon mapping, BDPT, or VCM — those require integrator access we don't have
- Closest analogues: Lumen's world-space radiance cache, Jones & Reinhart (2014)

### Blender 4.4 Specifics
- `import openvdb` (NOT `pyopenvdb`) after `bpy.utils.expose_bundled_modules()`
- Ray visibility: `obj.visible_camera = False` (NOT `cycles_visibility.camera`)
- Pixel readback: CompositorNodeViewer, `foreach_get` on `'Viewer Node'` image
- Render blocking: `bpy.ops.render.render()` no args = EXEC_DEFAULT = blocking, reliable
- INVOKE_DEFAULT unreliable from inside an operator (T52258)

### Critical Design Choices
- **Volume is camera-invisible:** `obj.visible_camera = False`, `obj.visible_shadow = False`
  — solves double-counting cleanly without bounce clamping
- **Persistent Data:** `scene.render.use_persistent_data = True` during probe loop
  — BVH built once, reused for all 256+ probe renders
- **Single reusable camera:** Create once, reposition per probe, delete in finally block
- **VDB transform:** 4×4 matrix `[voxel_size on diagonal, bbox_min in last row]`
  — places volume correctly at scene position, volume object at world origin
- **Gaussian blur:** Separable 1D `np.convolve` along each axis — no scipy needed
- **Engine override:** Force `CYCLES` during prepass regardless of user setting

### State Restore Strategy
All prepass changes wrapped in `try/finally`:
- Direct restore: engine, camera, resolution, samples, persistent_data, filepath
- Compositor: `bpy.ops.ed.undo_push` before touching, undo on failure

---

## 19 Pre-Identified Bugs (All Have Fixes)

See `bug-audit.md` for full details.

**Critical (5):**
- BUG-01: VDB at wrong world position → fixed by 4×4 matrix transform
- BUG-02: EEVEE probe renders give wrong irradiance → fixed by engine override
- BUG-03: Crash destroys compositor → fixed by try/finally + undo push
- BUG-04: Second bake contaminates from first bake's volume → hide existing volume before prepass
- BUG-05: float64 breaks copyFromArray → explicit `dtype=np.float32` everywhere

**High (5):**
- BUG-06: Probe cameras leak on crash → single reusable camera, deleted in finally
- BUG-07: Viewer Node missing before first render → `.get()` with error
- BUG-08: Persistent Data left on → included in state restore
- BUG-09: Interior test fails on non-manifold meshes → Zone Object recommended workflow
- BUG-10: Dark voxels silently dropped → `tolerance=0.0` in copyFromArray

---

## What Needs to Be Built

### File Structure
```
photon_splat/
    __init__.py       ← bl_info, register/unregister, imports
    state.py          ← save/restore all scene settings
    probe_grid.py     ← bbox calculation, interior test, grid generation
    capture.py        ← compositor setup, probe render loop, pixel readback
    vdb_builder.py    ← openvdb grid construction, gaussian blur, world transform
    injector.py       ← volume object creation, emission shader, ray visibility
    ui.py             ← N-panel, operator button, status display
```

### Build Order (dependency order)
1. `state.py` — no dependencies, needed by everything
2. `probe_grid.py` — needs mathutils only
3. `vdb_builder.py` — needs numpy + openvdb only
4. `capture.py` — needs state.py + probe_grid.py
5. `injector.py` — needs vdb_builder.py output
6. `ui.py` — needs all operators registered
7. `__init__.py` — wires everything together

### Addon Properties (on `bpy.types.Scene`)
```
psp_grid_x         IntProperty  default=8
psp_grid_y         IntProperty  default=8
psp_grid_z         IntProperty  default=4
psp_samples        IntProperty  default=8
psp_bounces        IntProperty  default=4
psp_strength       FloatProperty default=1.0
psp_blur_radius    FloatProperty default=1.5
psp_zone_object    PointerProperty(bpy.types.Object)
psp_status         StringProperty default="Ready"
psp_cache_path     StringProperty default=""
```

### Operators
```
psp.bake_cache     ← main bake operator
psp.clear_cache    ← remove volume + delete VDB file
```

---

## Reference

### Key Papers
- Hachisuka et al. 2008 — Progressive Photon Mapping
- Georgiev et al. 2012 — VCM (SmallVCM at github.com/SmallVCM/SmallVCM)
- Bitterli et al. 2020 — ReSTIR
- Jones & Reinhart 2014 — Parallel Multi-Bounce Irradiance Caching (closest analogue)

### Key APIs
```python
# openvdb import (Blender 4.4)
bpy.utils.expose_bundled_modules()
import openvdb as vdb

# VDB transform with world offset
matrix = [[vs,0,0,0],[0,vs,0,0],[0,0,vs,0],[tx,ty,tz,1]]
grid.transform = vdb.createLinearTransform(matrix=matrix)

# Ray visibility (4.4 API)
obj.visible_camera = False
obj.visible_shadow = False

# Pixel readback
img = bpy.data.images.get('Viewer Node')
buf = np.empty(w*h*4, dtype=np.float32)
img.pixels.foreach_get(buf)

# Render loop (blocking)
result = bpy.ops.render.render()
if 'CANCELLED' in result:
    raise RuntimeError("Cancelled")
```

---

## Paused State

Research complete. Nothing started in code yet.

To resume: check out `restructure/offtopic-blender`, read this file, then begin with
`state.py` following the patterns in `research-phase2-implementation.md`.
