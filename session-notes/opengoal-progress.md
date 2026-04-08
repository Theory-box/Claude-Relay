# OpenGOAL Blender Addon — Session Progress

## Status: CAMERA ROTATION FIX APPLIED ✅ (needs in-game verification)

## Active Branch: `feature/camera`
Install `addons/opengoal_tools.py` from this branch for camera work.

---

## Camera System — What Works

### Trigger volume ✅
- Walk into CAMVOL mesh → camera switches → walk out → camera reverts
- Entity-based: `camera-trigger` actor births on level load, no nREPL needed
- Works with manual level loading AND Build & Play

### Camera placement ✅
- `camera-marker` entity exports correctly to actors array
- `entity-by-name` finds it → `change-to-entity-by-name` works
- Level doesn't crash

### Blender UI ✅
- Add Camera → places Blender CAMERA object (Numpad-0 to preview)
- Add Volume → places CAMVOL wireframe cube
- Shift-select both → Link Trigger Volume
- Panel shows live rotation wxyz for debugging

### Camera rotation export — FIXED (awaiting verification) ✅
- Previous: applied Y+180 post-multiply WITHOUT axis remap → always wrong
- Now: applies axis remap ONLY (same remap as position: bl.x→x, bl.z→y, -bl.y→z)

---

## Camera Rotation — Root Cause Found

### What the source code confirmed
1. `cam-fixed-read-entity` calls `cam-slave-get-rot(entity, tracking_matrix)`
2. `cam-slave-get-rot` calls `quaternion->matrix(tracking_matrix, entity.quat)` — raw, standard
3. `forward-down->inv-matrix` docstring: `"arg1 is forward (+Z)"` — game camera looks along **+Z** of matrix
4. `vector_from_json` in Entity.cpp: reads `[x, y, z, w]` straight, no reordering
5. `EntityActor::generate` writes quat fields `[0][1][2][3]` → stored as `x,y,z,w` in memory

### Why previous attempts failed
All 6 previous attempts applied Y+180 corrections WITHOUT doing the axis remap.
Position export does: `gx=bl.x, gy=bl.z, gz=-bl.y`  
Quaternion export was doing: `gq.x, gq.y, gq.z, gq.w` — **no remap at all**

This means we were treating Blender's X,Y,Z axes as if they were game's X,Y,Z axes. They're not.

### The correct fix (3 lines)
```python
q = cam_obj.matrix_world.to_quaternion()
qx = round(q.x,  6)   # bl_x → game_x (unchanged)
qy = round(q.z,  6)   # bl_z → game_y
qz = round(-q.y, 6)   # -bl_y → game_z
qw = round(q.w,  6)   # scalar unchanged
```

### Verified by simulation
- Identity Blender camera → game forward = (0, 0, +1) ✓ (game +Z = into level)
- Old Y+180 workaround physically in Blender still works: bl quat (0,1,0,0) remaps to (0,0,-1,0) → game forward = (0,0,1) ✓
- 90° rotations around each axis map correctly to game space

### IMPORTANT: User must reset camera rotation
After updating addon, the Blender camera should be at **natural Blender rotation**
(no more +180 Y compensation). If the user had been physically rotating Y+180 as
a workaround, they should reset the camera and set the rotation they actually want.

---

## What to Test In-Game
1. Install updated addon from `feature/camera`
2. Place camera at zero rotation in Blender → confirm it looks "forward" in game
3. Rotate camera in Blender (e.g. 90° left) → confirm same rotation in game
4. Test non-trivial rotations (looking down, angled, etc.)

---

## Bug History (camera system)

| Bug | Root cause | Fix |
|---|---|---|
| Art group not found | `camera-tracker` etype doesn't exist | Define `camera-marker` in obs.gc |
| Level crash on load | `process-drawable-from-entity!` dereferences null root | `(set! (-> this root) (new 'process 'trsqv))` first |
| Trigger never fires (manual load) | nREPL obs_init call only runs via Build & Play | Replaced with `camera-trigger` entity-actor |
| Volume visible/collidable | dict-style props export as JSON bool, C++ reads as 0 | Use registered `BoolProperty` (`vol.set_invisible = True`) |
| Camera rotation wrong | Missing axis remap on quaternion XYZ components | Apply same remap as position: bl.z→y, -bl.y→z |

---

## Architecture (correct parts)

### obs.gc defines two types:
```lisp
;; camera-marker: inert, holds position/rotation
(deftype camera-marker (process-drawable) () (:states camera-marker-idle))
(defmethod init-from-entity! ((this camera-marker) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (go camera-marker-idle) (none))

;; camera-trigger: AABB volume, polls player position each frame
(deftype camera-trigger (process-drawable)
  ((cam-name string :offset 176) (xmin float :offset 180) ... (inside symbol :offset 204))
  :heap-base #x60 :size-assert #xd0)
(defmethod init-from-entity! ((this camera-trigger) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (set! (-> this cam-name) (res-lump-struct arg0 'cam-name string))
  (set! (-> this xmin) (res-lump-float arg0 'bound-xmin))
  ... go camera-trigger-active)
```

### JSONC format:
```jsonc
// Camera marker (holds position + rotation)
{ "trans": [gx,gy,gz], "etype": "camera-marker", "quat": [qx,qy,qz,qw],
  "lump": { "name": "CAMERA_0", "interpTime": ["float", 1.0] } }

// Camera trigger (AABB volume → switches camera)
{ "trans": [cx,cy,cz], "etype": "camera-trigger",
  "lump": { "name": "camtrig-camera_0", "cam-name": "CAMERA_0",
            "bound-xmin": ["meters", -5.0], "bound-xmax": ["meters", 5.0], ... } }
```

### Key source references:
- `cam-slave-get-rot` → `camera.gc:87` — reads entity-actor.quat, calls quaternion->matrix
- `forward-down->inv-matrix` → `geometry.gc:255` — matrix col[2] = camera forward (+Z)
- `vector_from_json` → `common/Entity.cpp:32` — reads [x,y,z,w] straight, no reorder
- `EntityActor::generate` → `jak1/Entity.cpp:18` — writes quat[0..3] = x,y,z,w
- `cam-combiner` copies `slave[0].tracking.inv-mat` → `self.inv-camera-rot`
- `cam-update` multiplies view frustum corners by `inv-camera-rot`

### Coordinate system:
- Position remap: `gx=bl.x, gy=bl.z, gz=-bl.y`
- Quaternion remap: `game_qx=bl_qx, game_qy=bl_qz, game_qz=-bl_qy, game_qw=bl_qw`

---

## Files
- `addons/opengoal_tools.py` on `feature/camera`
- `knowledge-base/opengoal/camera-system.md` — full research notes
