# Bug Audit: Photon Splat Prepass Addon
**Status:** Pre-build review  
**Last Updated:** 2026-04-15

Issues are categorized by severity. CRITICAL = wrong output or crash. HIGH = significant
misbehavior. MEDIUM = edge case or degraded quality. LOW = minor annoyance.

---

## CRITICAL

### BUG-01: VDB volume appears in wrong world position
**Stage:** VDB construction → Volume injection  
**Cause:** `copyFromArray` places voxels at index coordinates starting at (0,0,0).
By default a VDB voxel at index (0,0,0) maps to world position (0,0,0). Our probe grid
covers the scene bounding box which may start at, say, (-8, -5, 0). Without a matching
world transform, the injected volume will be centered at the world origin instead of
over the scene.

**Blender specifics:** Blender applies BOTH the volume object's transform AND the VDB's
internal transform matrix. Both must be accounted for.

**Fix:** Encode the full world-space mapping into the VDB grid transform before writing:
```python
# voxel_size = world units per voxel
# bbox_min = (min_x, min_y, min_z) of the probe grid in world space
transform = vdb.createLinearTransform(voxel_size)
transform.preTranslate(bbox_min)   # shift origin to bbox corner
grid.transform = transform
# Then place volume object at world origin (0,0,0) — transform is in the VDB
```

---

### BUG-02: Probe renders use whatever engine the user has selected
**Stage:** Capture (probe render loop)  
**Cause:** `bpy.ops.render.render()` uses `scene.render.engine`. If the user is working
in EEVEE (the default), all probe renders will be EEVEE renders. EEVEE's irradiance
isn't baked by default, so dark areas won't be sampled correctly. Probe colors will be
wrong, and the injected volume will misrepresent the actual lighting.

**Fix:** During prepass, temporarily force Cycles:
```python
orig_engine = scene.render.engine
scene.render.engine = 'CYCLES'
# ... probe renders ...
scene.render.engine = orig_engine  # in finally block
```

---

### BUG-03: Compositor state is permanently corrupted if prepass crashes
**Stage:** Pixel readback setup  
**Cause:** We clear the user's compositor node tree to set up the Viewer Node.
If any exception is thrown during the probe loop (render failure, out of memory,
interrupt), the user's compositor is left destroyed with no recovery path.

**Fix:** The entire prepass must be in a `try/finally` block that unconditionally
restores all scene state:
```python
saved_state = save_scene_state(scene)
try:
    run_prepass(scene, probes)
finally:
    restore_scene_state(scene, saved_state)
```

`save_scene_state` must capture: engine, camera, resolution X/Y, samples, use_nodes,
compositor node tree structure, persistent_data, render filepath.

---

### BUG-04: Existing irradiance cache volume included in probe renders (feedback loop)
**Stage:** Capture  
**Cause:** If the user runs "Bake Cache" a second time (to update after moving lights),
the volume from the first bake is still in the scene. The probe renders will include
that volume's emission in the captured irradiance. The new bake will be influenced by
the old bake, which was influenced by the original scene. Second bake ≠ first bake.

**Fix:** Before running probe renders, hide or delete any existing irradiance cache
volume object. The addon tracks which object it created (by name or custom property),
so it can specifically find and temporarily hide it.

---

### BUG-05: numpy dtype for `copyFromArray` must be float32
**Stage:** VDB construction  
**Cause:** `numpy.zeros()` defaults to float64. The OpenVDB C bindings expect float32
for `Vec3SGrid`. Passing float64 may produce a `TypeError` or silently produce a
wrong-dtype grid depending on the OpenVDB build.

**Fix:** Always explicitly specify dtype:
```python
arr = np.zeros((nx, ny, nz, 3), dtype=np.float32)
```
And when blurring, ensure the blur output stays float32:
```python
arr = scipy_or_manual_blur(arr).astype(np.float32)
```

---

## HIGH

### BUG-06: Probe camera left in scene after crash; scene camera not restored
**Stage:** Capture  
**Cause:** Each probe creates a temporary camera object linked to the scene. If an
exception interrupts mid-loop, probe cameras accumulate in the scene and the original
camera is not restored.

**Fix:** Create one reusable probe camera at the start of the loop, reposition it per
probe, delete it in the `finally` block. Never create N cameras:
```python
probe_cam_data = bpy.data.cameras.new('__probe_cam__')
probe_cam_obj = bpy.data.objects.new('__probe_cam__', probe_cam_data)
scene.collection.objects.link(probe_cam_obj)
orig_camera = scene.camera
scene.camera = probe_cam_obj
try:
    for pos in probe_positions:
        probe_cam_obj.location = pos
        bpy.ops.render.render()
        # ... read pixels ...
finally:
    scene.camera = orig_camera
    bpy.data.objects.remove(probe_cam_obj, do_unlink=True)
    bpy.data.cameras.remove(probe_cam_data)
```

---

### BUG-07: `bpy.data.images['Viewer Node']` doesn't exist before first render
**Stage:** Pixel readback  
**Cause:** The 'Viewer Node' image is only created by Blender when the first render
through a compositor Viewer Node completes. Accessing it before that throws a `KeyError`.

**Fix:** Use `.get()` with a clear error:
```python
img = bpy.data.images.get('Viewer Node')
if img is None:
    raise RuntimeError("Viewer Node image not created — render may have failed")
```

---

### BUG-08: Persistent Data must be reset after prepass
**Stage:** Capture  
**Cause:** `scene.render.use_persistent_data = True` is set to skip BVH rebuilds
between probe renders. If not restored, the final render keeps stale Cycles render
data in memory — potentially including probe camera BVH data — wasting VRAM and
potentially causing render artifacts if scene geometry changed.

**Fix:** Include in the saved/restored state block:
```python
orig_persistent = scene.render.use_persistent_data
scene.render.use_persistent_data = True
# ... prepass ...
scene.render.use_persistent_data = orig_persistent  # in finally
```

---

### BUG-09: Interior/exterior parity test fails on non-manifold meshes
**Stage:** Probe grid generation  
**Cause:** The parity (ray cast + intersection count) test assumes a closed, manifold
mesh. Open meshes, meshes with holes, imported geometry with duplicate faces, or
architectural meshes with intentional openings (windows, doors) will give incorrect
inside/outside classifications.

The basement door opening is a direct example: the door frame is an opening, meaning
the parity test may classify some probe positions as "outside" when they should be inside.

**Fix (v1):** When no Zone Object is provided, fall back to using the full scene bbox
with no interior test — place probes uniformly. The Zone Object workflow (user draws
a box around the interior explicitly) completely sidesteps this problem and should be
the recommended workflow.

**Fix (v2):** Implement multi-direction voting: cast rays in 6 axis directions, take
majority vote. This handles single-face holes much better than a single-direction cast.

---

### BUG-10: Background value silently drops low-irradiance probe voxels
**Stage:** VDB construction  
**Cause:** `copyFromArray` marks values equal to the background value as INACTIVE.
Background is `(0.0, 0.0, 0.0)`. A probe in a nearly-dark area returns very-near-zero
RGB. After Gaussian blur, neighbouring voxels get fractional values. These get silently
set to background (0,0,0) and discarded as inactive voxels.

The resulting volume has voids — regions where the cache is empty — and camera bounce
rays that hit those voids get black instead of the expected dim ambient color.

**Fix:** Use `tolerance=0.0` in copyFromArray to disable background pruning:
```python
grid.copyFromArray(arr, tolerance=0.0)
```

Or pre-clip all values to a small minimum (e.g. `arr = np.maximum(arr, 1e-5)`) before
writing so no value ever equals the background exactly.

---

## MEDIUM

### BUG-11: Compositor RenderLayers node uses wrong view layer
**Stage:** Pixel readback  
**Cause:** If the user has multiple view layers, the CompositorNodeRLayers node defaults
to the active view layer, which might not be the one rendering. Probe captures might
read the wrong view layer's pixels.

**Fix:** Explicitly assign the first view layer to the RenderLayers node:
```python
rl_node.layer = scene.view_layers[0].name
```

---

### BUG-12: Pixel buffer size mismatch with actual rendered image
**Stage:** Pixel readback  
**Cause:** We set `scene.render.resolution_x = 32` before probes. After rendering,
`bpy.data.images['Viewer Node'].size` should be (32, 16). But if the render was
interrupted and a previous higher-resolution render result is still cached, `foreach_get`
with the wrong buffer size causes a Python crash.

**Fix:** Read actual image dimensions rather than trusting the scene resolution setting:
```python
img = bpy.data.images.get('Viewer Node')
w, h = img.size[0], img.size[1]
buf = np.empty(w * h * 4, dtype=np.float32)
img.pixels.foreach_get(buf)
```

---

### BUG-13: Output filepath side effect during probe renders
**Stage:** Capture  
**Cause:** If `scene.render.filepath` is set to a real output directory (user configured
for their main render), and we call `bpy.ops.render.render()` without `write_still=False`,
Blender may write a 32×16 probe render image to that filepath, potentially corrupting the
user's output sequence. Even with `write_still=False`, Blender's compositing output nodes
may fire if the user has File Output nodes in their compositor.

**Fix:** Temporarily clear the render filepath and disable compositor file output nodes
during prepass:
```python
orig_filepath = scene.render.filepath
scene.render.filepath = ''
# Also: disable any CompositorNodeOutputFile nodes temporarily
```

---

### BUG-14: Probe renders capture the probe camera's own clipping artifacts
**Stage:** Capture  
**Cause:** A panoramic equirectangular camera has a clip_start value. If probe_cam_obj
is placed very close to a wall (near-interior probe), geometry behind clip_start is
clipped and that direction reads as sky/background instead of wall color. This gives
the probe an artificially bright or wrong color.

**Fix:** Set clip_start very small for probe cameras:
```python
probe_cam_data.clip_start = 0.001
probe_cam_data.clip_end = 1000.0
```

---

### BUG-15: Attribute node type mismatch for Vec3SGrid in Blender 4.4
**Stage:** Volume injection  
**Cause:** The `ShaderNodeAttribute` node has an `attribute_type` property. In Blender
4.4, for VDB volumes, the correct type is `'GEOMETRY'`. If this defaults to `'OBJECT'`
or `'INSTANCER'`, the attribute lookup fails and the emission is black.

Additionally, in Blender 4.4, the Attribute node output for a Vec3SGrid connects to
the `'Color'` output, not `'Vector'`. Both exist on the node; using `'Vector'` as the
color source produces grayscale-converted values.

**Fix:** Explicitly set both:
```python
attr_node.attribute_name = 'emission'
attr_node.attribute_type = 'GEOMETRY'
links.new(attr_node.outputs['Color'], emit_node.inputs['Color'])  # NOT 'Vector'
```

---

## LOW

### BUG-16: No progress reporting during long probe loops
**Stage:** Capture  
**Issue:** A 256-probe prepass runs silently. Blender UI appears frozen. User has no
way to know how long is left or if it's stuck.

**Fix:** Use `wm.progress_begin` / `wm.progress_update` / `wm.progress_end`:
```python
wm = bpy.context.window_manager
wm.progress_begin(0, len(probe_positions))
for i, pos in enumerate(probe_positions):
    wm.progress_update(i)
    # ... render probe ...
wm.progress_end()
```
Also update a string property on the addon that the N-panel reads for status display.

---

### BUG-17: Cancellation during prepass leaves partial state
**Stage:** Capture  
**Issue:** If the user presses Escape mid-prepass, `bpy.ops.render.render()` returns
`{'CANCELLED'}` rather than `{'FINISHED'}`. The loop may continue trying to read pixel
data from a render that didn't complete, producing garbage probe colors.

**Fix:** Check the return value:
```python
result = bpy.ops.render.render()
if 'CANCELLED' in result:
    raise RuntimeError("Render cancelled by user")
```
This falls into the `finally` cleanup naturally.

---

### BUG-18: VDB file stale if .blend is moved after baking
**Stage:** Volume injection / persistence  
**Issue:** The VDB filepath is stored as a custom property. If the user saves the
.blend to a different directory, the relative path breaks. The volume object loads
but shows empty.

**Fix:** Store filepath as blend-relative (using `//` prefix):
```python
import bpy
rel_path = bpy.path.relpath(abs_path)  # converts to // relative
vol_obj.data.filepath = rel_path
vol_obj['irradiance_cache_path'] = rel_path
```
And on re-open, resolve back to absolute with `bpy.path.abspath(rel_path)`.

---

### BUG-19: render_engine string may vary in future Blender versions
**Stage:** Capture  
**Issue:** We force `scene.render.engine = 'CYCLES'` and restore the original.
Engine string identifiers (e.g. 'BLENDER_EEVEE' changed in 4.4 from 'BLENDER_EEVEE_NEXT')
can change between Blender versions.

**Fix:** Capture and restore the original engine string verbatim without hardcoding
any expected values. Only hardcode `'CYCLES'` when forcing it for the prepass.

---

## Summary Table

| ID | Severity | Stage | One-liner |
|---|---|---|---|
| BUG-01 | CRITICAL | VDB build | Volume spawns at world origin instead of scene position |
| BUG-02 | CRITICAL | Capture | EEVEE probe renders give wrong irradiance |
| BUG-03 | CRITICAL | Compositor | Crash destroys user's compositor permanently |
| BUG-04 | CRITICAL | Capture | Second bake self-contaminates from first bake's volume |
| BUG-05 | CRITICAL | VDB build | float64 array silently wrong or errors in copyFromArray |
| BUG-06 | HIGH | Capture | Crash leaves probe cameras in scene, original camera lost |
| BUG-07 | HIGH | Readback | KeyError before first render completes |
| BUG-08 | HIGH | Capture | Persistent Data left on after prepass wastes VRAM |
| BUG-09 | HIGH | Probe grid | Parity test fails on non-manifold meshes (every door/window) |
| BUG-10 | HIGH | VDB build | Dark-area voxels silently dropped by background pruning |
| BUG-11 | MEDIUM | Readback | Wrong view layer pixels with multi-layer scenes |
| BUG-12 | MEDIUM | Readback | Stale image size → buffer mismatch crash |
| BUG-13 | MEDIUM | Capture | Probe images written to user's output filepath |
| BUG-14 | MEDIUM | Capture | Clip start too large → wrong probe colors near walls |
| BUG-15 | MEDIUM | Injection | Attribute node type/output mismatch → black emission |
| BUG-16 | LOW | Capture | No progress feedback, UI appears frozen |
| BUG-17 | LOW | Capture | User cancel mid-loop produces garbage probe colors |
| BUG-18 | LOW | Persistence | Relative filepath breaks if .blend is moved |
| BUG-19 | LOW | Capture | Render engine string hardcoding fragile across versions |
