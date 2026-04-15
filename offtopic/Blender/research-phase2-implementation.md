# Phase 2 Research: Implementation Specifics
**Status:** Pre-build  
**Last Updated:** 2026-04-15

This document covers the implementation-level unknowns: addon structure, operator
execution model, the gaussian blur without scipy, and the exact VDB transform math.

---

## 1. Addon Structure — Blender 4.4 / Extension Format

### The Two Formats

**Legacy (still works in 4.4):** `bl_info` dict in `__init__.py`
```python
bl_info = {
    "name": "Photon Splat Prepass",
    "author": "...",
    "version": (0, 1, 0),
    "blender": (4, 4, 0),
    "category": "Render",
}
```
Works but is considered deprecated from 4.2 onward.

**Extension format (4.2+, recommended):** `blender_manifest.toml` + `__init__.py`
```toml
# blender_manifest.toml
schema_version = "1.0.0"
id = "photon_splat_prepass"
version = "0.1.0"
name = "Photon Splat Prepass"
tagline = "Bake irradiance cache for Cycles interior renders"
maintainer = "..."
type = "add-on"
blender_version_min = "4.4.0"
license = ["SPDX:GPL-3.0-or-later"]
```

**Verdict for this project:** Use `bl_info` for now. Simpler, still functional in 4.4.
The manifest format requires installing via Extensions → Install From Disk rather than
just dropping a folder in the addons directory. Use `bl_info` for development, convert
to manifest format for distribution.

### Multi-file Addon Structure

```
photon_splat/
    __init__.py         ← register/unregister, bl_info, imports
    probe_grid.py       ← interior point generation
    capture.py          ← probe render loop + state management
    vdb_builder.py      ← openvdb grid construction + blur
    injector.py         ← volume object creation + shader
    ui.py               ← N-panel
    state.py            ← save/restore scene state helpers
```

The reload pattern for development (required in multi-file addons):
```python
# __init__.py
if "bpy" in locals():
    import importlib
    importlib.reload(probe_grid)
    importlib.reload(capture)
    # ... etc
else:
    from . import probe_grid, capture, vdb_builder, injector, ui, state

import bpy

def register():
    ui.register()
    # ... register operators, properties

def unregister():
    ui.unregister()
    # ...
```

### Property Storage

Addon properties should live on `bpy.types.Scene` not on a global:
```python
# In register():
bpy.types.Scene.psp_grid_x = bpy.props.IntProperty(name="Grid X", default=8, min=2, max=32)
bpy.types.Scene.psp_grid_y = bpy.props.IntProperty(name="Grid Y", default=8, min=2, max=32)
bpy.types.Scene.psp_grid_z = bpy.props.IntProperty(name="Grid Z", default=4, min=2, max=16)
bpy.types.Scene.psp_samples = bpy.props.IntProperty(name="Capture Samples", default=8, min=1, max=64)
bpy.types.Scene.psp_bounces = bpy.props.IntProperty(name="Capture Bounces", default=4, min=1, max=12)
bpy.types.Scene.psp_strength = bpy.props.FloatProperty(name="Emission Strength", default=1.0, min=0.0, soft_max=5.0)
bpy.types.Scene.psp_blur_radius = bpy.props.FloatProperty(name="Blur Radius", default=1.5, min=0.0, max=8.0)
bpy.types.Scene.psp_zone_object = bpy.props.PointerProperty(
    name="Zone Object",
    type=bpy.types.Object,
    description="Mesh object defining the interior volume. Leave empty to use scene bounds."
)
bpy.types.Scene.psp_status = bpy.props.StringProperty(name="Status", default="Ready")
bpy.types.Scene.psp_cache_path = bpy.props.StringProperty(name="Cache Path", default="")

# In unregister():
del bpy.types.Scene.psp_grid_x
# ... etc
```

### User Data Directory (for the VDB file)

In 4.2+ extension format, addons must NOT write to their own directory.
Use the provided utility:
```python
user_dir = bpy.utils.extension_path_user(__package__, path="cache", create=True)
# Returns: ~/.config/blender/4.4/extensions/user_default/photon_splat_prepass/cache/
```

For `bl_info` format, use:
```python
addon_prefs = bpy.context.preferences.addons[__package__].preferences
# or simply use the blend file directory (see state.py pattern)
```

---

## 2. Operator Execution Model — UI Freezing is Acceptable

### The Decision

`bpy.ops.render.render()` is **blocking only in EXEC_DEFAULT** (which is the default
when called with no execution context argument). The UI will freeze during the prepass.

This is **acceptable** because:
- Blender's own baking operations (lightmap bake, fluid sim, etc.) all block the UI
- The progress bar still updates during EXEC_DEFAULT renders via `wm.progress_begin/update`
- Attempting non-blocking renders (INVOKE_DEFAULT) from another operator causes race
  conditions and CANCELLED returns (confirmed in bug report T52258)

**Do not attempt modal/async render loop.** It is not reliably achievable from Python.

### The Operator Pattern

```python
class PSP_OT_BakeCache(bpy.types.Operator):
    bl_idname = "psp.bake_cache"
    bl_label = "Bake Irradiance Cache"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        wm = context.window_manager

        # Collect all state to restore
        saved = state.save(scene)
        
        try:
            probes = probe_grid.generate(scene)
            n = len(probes)
            wm.progress_begin(0, n)

            for i, pos in enumerate(probes):
                scene.psp_status = f"Capturing probe {i+1}/{n}..."
                # Force status to show in UI (works even in blocking operators)
                bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
                
                result = capture.render_probe(scene, pos)
                if result is None:
                    raise RuntimeError(f"Probe render {i+1} failed")
                
                wm.progress_update(i + 1)

            grid_data = vdb_builder.build(scene, probes)
            injector.inject(scene, grid_data)
            scene.psp_status = f"Done. {n} probes baked."

        except Exception as e:
            scene.psp_status = f"Error: {e}"
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        finally:
            state.restore(scene, saved)
            wm.progress_end()

        return {'FINISHED'}
```

### Progress During a Blocking Operator

The `bpy.ops.wm.redraw_timer` trick is the documented way to force a UI redraw inside
a blocking operator. It works because it pumps the event loop for one iteration.
Combined with `wm.progress_begin/update/end`, the progress bar at the bottom of the
Blender window updates visibly between probe renders.

---

## 3. State Save/Restore Pattern

Everything we change must be captured before and restored after, unconditionally.

```python
# state.py

def save(scene):
    """Capture all scene state we'll modify during prepass."""
    tree = scene.node_tree
    
    saved = {
        # Render settings
        'engine':          scene.render.engine,
        'camera':          scene.camera,
        'res_x':           scene.render.resolution_x,
        'res_y':           scene.render.resolution_y,
        'res_percent':     scene.render.resolution_percentage,
        'samples':         scene.cycles.samples if hasattr(scene, 'cycles') else None,
        'persistent_data': scene.render.use_persistent_data,
        'filepath':        scene.render.filepath,

        # Compositor
        'use_nodes':       scene.use_nodes,
        'node_tree_data':  _serialize_node_tree(tree) if tree else None,
    }
    return saved


def restore(scene, saved):
    """Restore all scene state. Must not raise exceptions."""
    try:
        scene.render.engine = saved['engine']
        scene.camera = saved['camera']
        scene.render.resolution_x = saved['res_x']
        scene.render.resolution_y = saved['res_y']
        scene.render.resolution_percentage = saved['res_percent']
        if saved['samples'] is not None:
            scene.cycles.samples = saved['samples']
        scene.render.use_persistent_data = saved['persistent_data']
        scene.render.filepath = saved['filepath']
        scene.use_nodes = saved['use_nodes']
        
        if saved['node_tree_data'] is not None:
            _restore_node_tree(scene.node_tree, saved['node_tree_data'])
    except Exception as e:
        print(f"[PSP] Warning: state restore partial failure: {e}")
```

### Node Tree Serialization

The compositor node tree can be complex. Rather than trying to recreate arbitrary
node trees, we use a simpler approach: **Blender's own undo system**.

Before modifying the compositor, push an undo step:
```python
bpy.ops.ed.undo_push(message="PSP: pre-bake state")
```

Then after the prepass, call undo:
```python
bpy.ops.ed.undo()
```

**Caveat:** This pops back the entire undo state, not just compositor changes.
Acceptable for a bake operation — the user expects a bake to be undoable anyway.

**Alternative (more surgical):** Save compositor nodes as a text blob to a temp
scene, delete and recreate them. More code but cleaner. Implement in v2.

---

## 4. VDB World Transform — Exact Math

### The Problem

`copyFromArray` places `arr[0,0,0]` at voxel index `(0,0,0)`.
By default, voxel `(0,0,0)` maps to world position `(0,0,0)`.

Our probe grid spans from `bbox_min` to `bbox_max` in world space.
We need voxel `(0,0,0)` to map to `bbox_min`.

### The Solution — 4×4 Matrix Transform

The `createLinearTransform` function accepts a full 4×4 affine matrix where
the **last row is the translation**:

```
[[scale_x, 0,       0,       0],
 [0,       scale_y, 0,       0],
 [0,       0,       scale_z, 0],
 [tx,      ty,      tz,      1]]   ← translation in last row
```

For our case (uniform voxel size, translation to bbox_min):
```python
voxel_size = (bbox_max - bbox_min) / np.array([nx, ny, nz])  # per-axis voxel size
# Use uniform voxel size (largest of the three) for simplicity:
vs = float(max(voxel_size))

tx, ty, tz = float(bbox_min[0]), float(bbox_min[1]), float(bbox_min[2])

matrix = [
    [vs, 0,  0,  0],
    [0,  vs, 0,  0],
    [0,  0,  vs, 0],
    [tx, ty, tz, 1],   # translation = bbox_min
]
grid.transform = vdb.createLinearTransform(matrix=matrix)
```

After this, voxel `(0,0,0)` → world `(tx, ty, tz)` = `bbox_min`. ✓

The volume object itself should be placed at world origin `(0,0,0)` — the transform
is entirely encoded in the VDB. Do not also apply a location offset to the object.

### Verify Transform is Correct

After setting the transform, verify it:
```python
# Index (0,0,0) should map to bbox_min
test_world = grid.transform.indexToWorld((0, 0, 0))
print(f"Voxel (0,0,0) → world {test_world}")  # should be near bbox_min

# Index (nx,ny,nz) should map near bbox_max
test_world = grid.transform.indexToWorld((nx, ny, nz))
print(f"Voxel ({nx},{ny},{nz}) → world {test_world}")  # should be near bbox_max
```

---

## 5. 3D Gaussian Blur — Pure NumPy, No Scipy

Scipy is not bundled with Blender. A 3D Gaussian is separable — it decomposes into
three independent 1D Gaussians applied sequentially along each axis.

### 1D Gaussian Kernel

```python
def gaussian_kernel_1d(sigma, truncate=2.0):
    """Generate normalized 1D Gaussian kernel. No scipy needed."""
    radius = max(1, int(sigma * truncate + 0.5))
    x = np.arange(-radius, radius + 1, dtype=np.float32)
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    kernel /= kernel.sum()   # normalize so it sums to 1
    return kernel
```

### Separable 3D Convolution via np.apply_along_axis

```python
def gaussian_blur_3d(arr, sigma):
    """
    Apply separable 3D Gaussian blur to array of shape (nx, ny, nz) or (nx, ny, nz, c).
    Works per-channel for 4D arrays. No scipy needed.
    """
    if sigma <= 0:
        return arr.copy()
    
    k = gaussian_kernel_1d(sigma)
    
    def convolve_axis(arr, axis):
        """Convolve along one axis using np.apply_along_axis."""
        def convolve_1d(row):
            return np.convolve(row, k, mode='same')
        return np.apply_along_axis(convolve_1d, axis, arr)
    
    out = arr.astype(np.float32)
    
    if arr.ndim == 4:
        # (nx, ny, nz, channels) — blur spatial dims only
        for c in range(arr.shape[3]):
            channel = out[..., c]
            channel = convolve_axis(channel, 0)  # X axis
            channel = convolve_axis(channel, 1)  # Y axis
            channel = convolve_axis(channel, 2)  # Z axis
            out[..., c] = channel
    else:
        out = convolve_axis(out, 0)
        out = convolve_axis(out, 1)
        out = convolve_axis(out, 2)
    
    return out
```

### Performance Note

`np.apply_along_axis` is not the fastest path — it calls a Python function per row.
For an 8×8×4 grid (our default), this is 8*8 + 8*4 + 8*4 = 128 rows across 3 passes.
Trivially fast. For a 16×16×8 grid: 640 rows. Still fast.

For much larger grids (32×32×16+), profile and consider using `np.convolve` on
flattened slices directly for speed. At our expected scales this is not needed.

### Border Handling

`np.convolve(row, k, mode='same')` uses zero-padding at borders (the default for
`mode='full'` cropped back to input size, which is `mode='same'`).

For irradiance data, zero-pad borders are fine — probe data is sparse and the edges
of the grid are already at the scene boundary. Any bleed beyond the boundary is
acceptable since the volume won't extend past it anyway.

---

## 6. Scene Bounding Box Calculation

Getting the probe zone from the scene or a user-specified object:

```python
def get_probe_bbox(scene):
    """
    Return (min_xyz, max_xyz) as numpy arrays.
    Uses psp_zone_object if set, otherwise all visible mesh objects.
    """
    zone_obj = scene.psp_zone_object
    
    if zone_obj is not None:
        # Use the zone object's bounding box in world space
        corners = [zone_obj.matrix_world @ Vector(c) for c in zone_obj.bound_box]
        corners = np.array([[c.x, c.y, c.z] for c in corners])
        return corners.min(axis=0), corners.max(axis=0)
    
    # Fall back to all visible mesh objects
    all_verts = []
    for obj in scene.objects:
        if obj.type == 'MESH' and obj.visible_get():
            for corner in obj.bound_box:
                world_corner = obj.matrix_world @ Vector(corner)
                all_verts.append([world_corner.x, world_corner.y, world_corner.z])
    
    if not all_verts:
        raise RuntimeError("No visible mesh objects found in scene")
    
    arr = np.array(all_verts)
    return arr.min(axis=0), arr.max(axis=0)
```

---

## 7. Probe Grid Generation

Generate probe candidate positions and filter by interior test:

```python
def generate(scene):
    """Return list of (x,y,z) world positions inside the scene interior."""
    bbox_min, bbox_max = get_probe_bbox(scene)
    
    nx = scene.psp_grid_x
    ny = scene.psp_grid_y
    nz = scene.psp_grid_z
    
    # Generate grid positions with half-voxel offset (cell-centered)
    xs = np.linspace(bbox_min[0], bbox_max[0], nx + 1)
    ys = np.linspace(bbox_min[1], bbox_max[1], ny + 1)
    zs = np.linspace(bbox_min[2], bbox_max[2], nz + 1)
    
    # Use midpoints of cells
    xs = 0.5 * (xs[:-1] + xs[1:])
    ys = 0.5 * (ys[:-1] + ys[1:])
    zs = 0.5 * (zs[:-1] + zs[1:])
    
    positions = []
    
    # Interior test: use zone object if available, otherwise skip test
    zone_obj = scene.psp_zone_object
    if zone_obj is not None:
        bvh = BVHTree.FromObject(zone_obj, bpy.context.evaluated_depsgraph_get())
        use_test = True
    else:
        use_test = False
    
    for x in xs:
        for y in ys:
            for z in zs:
                if use_test:
                    if not _is_inside(bvh, Vector((x, y, z))):
                        continue
                positions.append((x, y, z))
    
    if not positions:
        raise RuntimeError(
            "No interior probe positions found. "
            "Check that Zone Object is a closed mesh, or try increasing grid resolution."
        )
    
    return positions


def _is_inside(bvh, point):
    """Parity test: odd number of ray hits = inside."""
    direction = Vector((1, 0, 0))
    origin = Vector(point)
    count = 0
    while True:
        hit, loc, normal, idx = bvh.ray_cast(origin, direction)
        if hit is None:
            break
        count += 1
        origin = loc + direction * 1e-4
    return (count % 2) == 1
```

---

## 8. Pixel Readback — Full Compositor Setup

```python
def setup_compositor_for_readback(scene):
    """Set up minimal compositor for pixel access. Returns for cleanup."""
    scene.use_nodes = True
    tree = scene.node_tree
    
    # Store existing nodes to reconnect later (but undo handles this)
    tree.nodes.clear()
    
    rl = tree.nodes.new('CompositorNodeRLayers')
    rl.layer = scene.view_layers[0].name   # explicitly first view layer
    
    viewer = tree.nodes.new('CompositorNodeViewer')
    viewer.use_alpha = False
    
    tree.links.new(rl.outputs['Image'], viewer.inputs['Image'])
    return viewer


def read_probe_pixels(scene):
    """Read average RGB from the last render. Returns np.ndarray shape (3,)."""
    img = bpy.data.images.get('Viewer Node')
    if img is None:
        raise RuntimeError("Viewer Node image not found — render may have failed")
    
    w, h = img.size[0], img.size[1]
    if w == 0 or h == 0:
        raise RuntimeError(f"Viewer Node image has zero size ({w}×{h})")
    
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    rgba = buf.reshape(h, w, 4)
    
    # Average all pixels → mean irradiance at this probe position
    rgb = rgba[:, :, :3]
    return rgb.mean(axis=(0, 1))   # shape (3,)
```

---

## 9. Full Capture Loop

```python
def capture_all_probes(scene, positions):
    """
    Render one probe per position, collect average irradiance.
    Returns list of (position, rgb) tuples.
    """
    # Override render engine to Cycles
    scene.render.engine = 'CYCLES'
    
    # Minimal probe render settings
    scene.render.resolution_x = 32
    scene.render.resolution_y = 16
    scene.render.resolution_percentage = 100
    scene.cycles.samples = scene.psp_samples
    scene.render.use_persistent_data = True
    scene.render.filepath = ''   # prevent file writes
    
    # Create ONE reusable probe camera
    cam_data = bpy.data.cameras.new('__psp_probe__')
    cam_data.type = 'PANO'
    cam_data.cycles.panorama_type = 'EQUIRECTANGULAR'
    cam_data.clip_start = 0.001
    cam_data.clip_end = 10000.0
    cam_obj = bpy.data.objects.new('__psp_probe__', cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    scene.camera = cam_obj
    
    # Hide existing irradiance cache volume from probe renders
    existing = scene.objects.get('IrradianceCache')
    if existing:
        existing.hide_render = True
    
    results = []
    
    try:
        setup_compositor_for_readback(scene)
        
        for pos in positions:
            cam_obj.location = pos
            
            result = bpy.ops.render.render()
            if 'CANCELLED' in result:
                raise RuntimeError("Render cancelled by user")
            
            rgb = read_probe_pixels(scene)
            results.append((pos, rgb))
    
    finally:
        # Clean up probe camera
        bpy.context.scene.collection.objects.unlink(cam_obj)
        bpy.data.objects.remove(cam_obj, do_unlink=True)
        bpy.data.cameras.remove(cam_data)
        
        # Restore hidden volume
        if existing:
            existing.hide_render = False
    
    return results
```

---

## 10. Summary of Implementation Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Addon format | `bl_info` (legacy) | Simpler for dev, convert to manifest for distribution |
| Property storage | `bpy.types.Scene.*` | Persists with .blend file |
| Render execution | Blocking EXEC_DEFAULT | Async/modal unreliable with render.render() |
| UI freeze handling | Progress bar + status string | Acceptable; same as Blender baking |
| State restore strategy | try/finally + undo push | Compositor undo; direct restore for render settings |
| Scipy-free blur | Separable 1D np.convolve | Correct, dependency-free, fast enough at expected scales |
| VDB world transform | 4×4 matrix with translation | Encodes bbox_min offset directly, volume object stays at origin |
| Float dtype | Explicit float32 everywhere | Required by copyFromArray and foreach_get |
| Interior test | BVH parity + Zone Object fallback | Non-manifold safe via Zone Object recommendation |
