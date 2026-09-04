# Blender Vertex Lighting Add-on — Research & Knowledge Doc

**Blender target: 4.4**
**Date researched: April 2026**

---

## 1. GLSL Viewport Overlay

### How It Works
`bpy.types.SpaceView3D.draw_handler_add(callback, (), 'WINDOW', 'POST_VIEW')` injects a custom draw call after Blender renders the scene but before UI elements. Use `POST_PIXEL` for 2D screen-space drawing.

### Blend Mode
`gpu.state.blend_set('MULTIPLY')` is a native Blender API call. Confirmed available. Multiplies custom draw output against the existing framebuffer — exactly what we need to composite vertex-lit darkness/lightness over materials.

Always restore after drawing:
```python
gpu.state.blend_set('MULTIPLY')
batch.draw(shader)
gpu.state.blend_set('NONE')
```

### Drawing Mesh Geometry
```python
import gpu
from gpu_extras.batch import batch_for_shader

shader = gpu.types.GPUShader(vert_src, frag_src)
batch = batch_for_shader(shader, 'TRIS', {
    "pos": vert_positions,   # (N, 3) float32
    "color": vert_colors     # (N, 4) float32
})
```

Rebuild batch when vertex data or vertex colors change. Batch construction is not free — dirty-flag it.

### POST_VIEW vs POST_PIXEL
| | POST_VIEW | POST_PIXEL |
|---|---|---|
| Coord space | 3D world space | 2D screen pixels |
| Depth test | Active by default — z-fighting risk | No depth, draws on top of everything |
| Effort | Simpler (use object matrix directly) | Need `bpy_extras.view3d_utils.location_3d_to_region_2d` |
| Recommended? | Disable depth test first | Cleaner, no z-fight |

**Recommendation:** Start with POST_VIEW + `gpu.state.depth_test_set('NONE')`. Switch to POST_PIXEL if issues arise.

### Color Space Warning
Blender's viewport has two internal textures:
- Main color texture: linear scene reference space (materials draw here)
- Overlay texture: linear display space, SRGB encoded (draw_handler writes here)

Multiplying across these two spaces gives wrong results. The vertex color values written by the baker (linear) need to be gamma-corrected in the GLSL fragment shader before blending to match display space:
```glsl
// Approximate sRGB conversion in frag shader
fragColor = pow(vertColor, vec4(1.0 / 2.2));
```

---

## 2. Vertex Color Read/Write

### Modern API (Blender 3.2+ / 4.x)
Use `color_attributes`, not the old `vertex_colors`:
```python
attr = mesh.color_attributes.get("VtxLight")
if attr is None:
    attr = mesh.color_attributes.new("VtxLight", 'FLOAT_COLOR', 'CORNER')
```
`'CORNER'` domain = per loop (face corner). `'POINT'` = per vertex.

### Fast Bulk Write (numpy)
```python
import numpy as np
flat = colors_per_loop.astype(np.float32).flatten()  # shape (N*4,)
attr.data.foreach_set("color", flat)
mesh.update()
```
This is dramatically faster than per-element Python assignment. Use this exclusively.

### Per-Vertex → Per-Loop Expansion
Blender stores colors per loop (face corner), not per vertex. A vertex shared by 4 faces has 4 loop entries. Expand before writing:
```python
loop_verts = np.empty(len(mesh.loops), dtype=np.int32)
mesh.loops.foreach_get("vertex_index", loop_verts)
colors_per_loop = colors_per_vertex[loop_verts]  # numpy fancy indexing, fast
```

---

## 3. Ray Casting: trimesh + embreex

### Stack
- `trimesh` — mesh utility library, pure Python, pip installable
- `embreex` — Python wrapper for Intel Embree (binary wheels on PyPI, no compilation)
- `embreex` is the maintained trimesh fork of old `pyembree`

### Install Into Blender
```python
import subprocess, sys, bpy

modules_path = bpy.utils.user_resource("SCRIPTS", path="modules", create=True)
if modules_path not in sys.path:
    sys.path.append(modules_path)

subprocess.check_call([
    sys.executable, "-m", "pip", "install",
    "--upgrade", "--target", modules_path,
    "trimesh", "embreex"
])
```
Run once on add-on enable if packages are missing. Use background thread to avoid freezing Blender.

### Usage Pattern
```python
import trimesh
import numpy as np

# Build scene mesh (all objects combined for correct inter-object GI)
scene_mesh = trimesh.Trimesh(vertices=verts, faces=faces)

# Batch cast all rays at once
origins    = vert_positions + normals * 1e-4   # offset to avoid self-hit
directions = hemisphere_samples                  # (N_verts * N_gi_rays, 3)

hits = scene_mesh.ray.intersects_any(origins, directions)  # bool array
```

### BVH Rebuild Cost
- Rebuild BVH only when geometry changes (`depsgraph.id_type_updated("MESH")`)
- BVH is cached inside the trimesh intersector object — keep it alive between bakes
- Only lights changed → skip BVH rebuild, re-cast rays on existing BVH (fast)

### Performance Notes
- embreex is 50-100x faster than pure numpy ray checks
- Sweet spot batch size: ~100k–500k rays per call
- 10k verts × 16 GI rays = 160k rays → well within sweet spot
- 18M+ rays at once has Python overhead issues — keep batches moderate
- embreex operates internally in float32

### GI Algorithm (Hemisphere Sampling)
```python
def hemisphere_samples(normals, n_samples):
    # Generate random unit vectors in upper hemisphere relative to each normal
    # Use cosine-weighted sampling for better quality
    phi = np.random.uniform(0, 2*np.pi, (len(normals), n_samples))
    cos_theta = np.sqrt(np.random.uniform(0, 1, (len(normals), n_samples)))
    sin_theta = np.sqrt(1 - cos_theta**2)
    # Transform to world space using normal as up axis
    # ... (TBN matrix construction)
```

### Light Types
| Type | Ray Strategy |
|---|---|
| Sun | Single shadow ray per vertex in light direction |
| Point/Spot | Ray from vertex toward light position, check occlusion |
| Area | Monte Carlo sample light surface → more rays, noisier |
| Emissive mesh | Sample emissive triangles as area lights — complex, v2 feature |

---

## 4. depsgraph Update Handler

### Hook
```python
from bpy.app.handlers import persistent

@persistent
def on_scene_update(scene, depsgraph):
    # Check what changed
    if depsgraph.id_type_updated("LIGHT") or depsgraph.id_type_updated("MESH"):
        trigger_bake()

bpy.app.handlers.depsgraph_update_post.append(on_scene_update)
```

`@persistent` decorator keeps handler alive across file loads.

### Throttling (Critical)
depsgraph fires on nearly every user interaction. Without throttling, bakes spam every frame.

```python
import time

_last_bake_time = 0.0
_THROTTLE_MS = 200  # configurable

def trigger_bake():
    global _last_bake_time
    now = time.time()
    if (now - _last_bake_time) * 1000 < _THROTTLE_MS:
        return
    _last_bake_time = now
    run_bake()
```

### Python GIL Warning
All Python in Blender is single-threaded. A bake that takes 300ms will freeze Blender's UI for 300ms. For acceptable feel, keep bake under ~150ms. This is achievable for game-scale meshes with embreex.

`bpy.app.timers.register()` can defer work to idle time, which helps perceived responsiveness.

### Safe Mesh Modification in Handler
- Write vertex colors via `foreach_set` from `depsgraph_update_post` — safe
- Do NOT use bmesh inside depsgraph handlers — crash risk
- Do NOT modify mesh in `depsgraph_update_pre` — crash risk

---

## 5. Known Issues / Risks

| Issue | Notes |
|---|---|
| Color space mismatch in overlay | Overlay buffer is display-space SRGB, materials draw in linear. Must gamma-correct in frag shader. |
| depsgraph fires constantly | Must throttle. 200ms default. |
| GIL blocks UI | Keep bake fast. Aim for <150ms for typical scenes. |
| GPU batch rebuild on mesh change | Dirty flag required. |
| embreex not on all platforms | Pure numpy fallback needed. No Embree for ARM Mac until recently — check wheel availability. |
| Per-vertex → per-loop expansion | Required step before foreach_set. Fast with numpy indexing. |
| Combined scene BVH for multi-object GI | Rebuild on any geometry change. Track per-object hash to know which changed. |
| emissive mesh bounces | Out of scope for v1. |
| `color_attributes` API | Target 3.2+ API only. Do not use old `vertex_colors`. |
| Blender restart to remove draw handlers | `draw_handler_remove` must be called in `unregister()`. If add-on crashes without cleanup, Blender may need restart. |
