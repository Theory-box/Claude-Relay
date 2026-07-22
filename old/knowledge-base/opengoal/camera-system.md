# OpenGOAL Camera System — Research Notes

**Status: COMPLETE ✅**
**Branch:** `feature/camera` (merge to main when ready)
**Last updated:** 2026-04-07

---

## 1. Architecture Overview

| Component | Type | Role |
|---|---|---|
| `*camera*` | `camera-master` process | Manages camera slaves, handles events |
| `camera-slave` | sub-process of camera-master | Implements a specific camera mode |
| `*camera-combiner*` | `camera-combiner` process | Blends between two slaves during transitions |

---

## 2. camera-master Event API

| Event | Args | Effect |
|---|---|---|
| `'change-to-entity-by-name` | `"camera-name"` | Switch to named camera entity |
| `'clear-entity` | none | Return to default follow camera |
| `'point-of-interest` | vector or `#f` | Point camera at world position |
| `'set-fov` | float | Change field of view |
| `'teleport` | none | Instant cut, no blend |

---

## 3. Camera States

| Lump present | State | Behaviour |
|---|---|---|
| `pivot` vector | `cam-circular` | Orbits a fixed world point |
| `align` vector | `cam-standoff-read-entity` | Fixed offset from player (side-scroller) |
| `campath`/`campath-k` | `cam-spline` | Follows a spline path |
| `stringMaxLength > 0` | `cam-string` | Normal third-person follow |
| nothing above | `cam-fixed-read-entity` → `cam-fixed` | Locked to entity position/rotation |

---

## 4. JSONC Format

### Camera marker (fixed camera)
```jsonc
{
  "trans": [gx, gy, gz],
  "etype": "camera-marker",
  "game_task": 0,
  "quat": [qx, qy, qz, qw],
  "vis_id": 0,
  "bsphere": [gx, gy, gz, 30.0],
  "lump": {
    "name": "CAMERA_0",
    "interpTime": ["float", 1.0],
    "fov": ["degrees", 75.0]          // optional
  }
}
```

### Camera trigger (AABB volume)
```jsonc
{
  "trans": [cx, cy, cz],
  "etype": "camera-trigger",
  "game_task": 0,
  "quat": [0, 0, 0, 1],
  "vis_id": 0,
  "bsphere": [cx, cy, cz, 30.0],
  "lump": {
    "name": "camtrig-camera_0",
    "cam-name": "CAMERA_0",
    "bound-xmin": ["meters", -5.0],
    "bound-xmax": ["meters",  5.0],
    "bound-ymin": ["meters", -5.0],
    "bound-ymax": ["meters",  5.0],
    "bound-zmin": ["meters", -5.0],
    "bound-zmax": ["meters",  5.0]
  }
}
```

---

## 5. Coordinate System Conversions

### Position
```
game_x =  bl.x
game_y =  bl.z
game_z = -bl.y
```

### Quaternion (CONFIRMED WORKING — hard won)

Four steps, all confirmed empirically via nREPL `inv-camera-rot` readback:

```python
m3 = cam_obj.matrix_world.to_3x3()
bl_look = -m3.col[2]                          # 1. BL camera looks along -local_Z

gl = Vector((bl_look.x, bl_look.z, -bl_look.y))  # 2. Remap: bl(x,y,z)->game(x,z,-y)
gl.normalize()

game_down = Vector((0, -1, 0))                # 3. Build rotation via world-down ref
right = gl.cross(game_down).normalized()      #    (mirrors forward-down->inv-matrix)
if right.length < 1e-6:
    right = Vector((1, 0, 0))                 #    degenerate guard (straight up/down)
up = gl.cross(right).normalized()
game_mat = Matrix([right, up, gl])
gq = game_mat.to_quaternion()

qx, qy, qz, qw = -gq.x, -gq.y, -gq.z, gq.w  # 4. Conjugate (game reads inverse convention)
```

**Why conjugate:** The game's `quaternion->matrix` uses the opposite handedness convention
from standard math. Confirmed by sending `(0,-0.7071,0,0.7071)` for a +X-facing camera
and reading `inv-camera-rot vector 2` = `(-1,0,0)` — exactly backwards. Negating xyz fixes it.

**Why forward-down->inv-matrix style:** Prevents upside-down cameras. The game derives
camera roll from world-down, not from the camera's local up axis.

---

## 6. Why actors array, not bsp.cameras

`LevelFile.cpp` line 155 has the cameras array write commented out:
```cpp
//(cameras  (array entity-camera)  :offset-assert 116)
```
So `reset-cameras()` never runs for custom levels. `entity-by-name` searches `bsp.actors`
first, so camera entities placed in actors array ARE found by `change-to-entity-by-name`.

---

## 7. obs.gc — Two Custom Types

```lisp
;; camera-marker: inert entity, holds position + rotation
(deftype camera-marker (process-drawable) () (:states camera-marker-idle))
(defmethod init-from-entity! ((this camera-marker) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (go camera-marker-idle))

;; camera-trigger: AABB volume, polls player each frame, fires camera events
(deftype camera-trigger (process-drawable)
  ((cam-name string  :offset-assert 176)
   (xmin     float   :offset-assert 180) (xmax float :offset-assert 184)
   (ymin     float   :offset-assert 188) (ymax float :offset-assert 192)
   (zmin     float   :offset-assert 196) (zmax float :offset-assert 200)
   (inside   symbol  :offset-assert 204))
  :heap-base #x60 :size-assert #xd0)
```

---

## 8. nREPL Diagnostics

### Read camera matrix after triggering
```lisp
(format #t "r0: ~f ~f ~f~%" (-> *camera-combiner* inv-camera-rot vector 0 x) (-> *camera-combiner* inv-camera-rot vector 0 y) (-> *camera-combiner* inv-camera-rot vector 0 z))
(format #t "r1: ~f ~f ~f~%" (-> *camera-combiner* inv-camera-rot vector 1 x) (-> *camera-combiner* inv-camera-rot vector 1 y) (-> *camera-combiner* inv-camera-rot vector 1 z))
(format #t "r2: ~f ~f ~f~%" (-> *camera-combiner* inv-camera-rot vector 2 x) (-> *camera-combiner* inv-camera-rot vector 2 y) (-> *camera-combiner* inv-camera-rot vector 2 z))
```
- `vector 2` = camera forward (look direction)
- `vector 1` = camera up
- `vector 0` = camera right

### Read entity quat
```lisp
(let ((e (the entity-actor (entity-by-name "CAMERA_0"))))
  (format #t "~f ~f ~f ~f~%" (-> e quat x) (-> e quat y) (-> e quat z) (-> e quat w)))
```

### Must be in `gc>` mode (run `(lt)` first if in `g>` mode)

---

## 9. Undiscovered Camera Lumps (source-verified, April 2026)

All confirmed from `camera.gc` `cam-slave-get-*` functions and `cam-state-from-entity`.

### Universal camera lumps (all modes)

| Lump | Type | Notes |
|---|---|---|
| `fov` | `float` (degrees constant) | FOV override. Default `11650.845` internal ≈ 75°. Use `["degrees", 75.0]`. |
| `fov-offset` | `float` | Additive bias on top of `fov`. Rarely needed. |
| `interpTime` | `float` (seconds) | Blend duration. Use `["float", 0.5]`. |
| `interpTime-offset` | `float` | Additive bias on `interpTime`. |
| `intro-time` | `float` (seconds) | Startup animation time before camera settles. |
| `tiltAdjust` | `float` | Camera tilt correction, default from `*CAMERA-bank*`. |
| `rot-offset` | quaternion | Additive rotation bias applied after `quat`. |
| `flags` | `uint32` | Bitfield. Bit `0x8000` = use `rot` matrix for tracking instead of default. |

### `cam-spline` mode lumps

Activated when `campath` + `campath-k` lumps are both present on the camera entity.

| Lump | Type | Notes |
|---|---|---|
| `campath` | `vector4m` multi-point | Spline control point positions. |
| `campath-k` | `float` array | Spline knot values, one per control point. |
| `spline-offset` | `vector` | Offset applied to the entire spline path. |
| `spline-follow-dist` | `float` | Distance ahead of Jak to project along spline. `0` = closest-point tracking. |

**Behaviour:** Camera position moves along the spline as Jak moves through the trigger zone. Always aims at Jak unless `flags 0x8000` is set. Supports blending and FOV. Good for scripted flythrough sequences or corridor cameras.

**Not in the addon. Entirely unknown to the current camera panel.**

### `cam-string` mode lumps (rubber-band follow)

Activated when `stringMaxLength > 0.0` on the camera entity.

| Lump | Type | Notes |
|---|---|---|
| `stringMaxLength` | `float` (meters) | Max tether distance. Camera freely follows Jak up to this range. |
| `stringCliffHeight` | `float` | Max upward Y offset the camera will track. |

**Behaviour:** Standard third-person follow camera, triggered only within the camera entity's trigger volume. Useful for zones where free-follow is wanted without any fixed framing. Transitions naturally back to normal camera on exit.

**Not in the addon.**

---

## 10. Source File Reference

| File | Purpose |
|---|---|
| `goal_src/jak1/engine/camera/camera.gc` | `cam-state-from-entity`, `cam-slave-get-rot`, `cam-slave-get-vector-with-offset` |
| `goal_src/jak1/engine/camera/cam-states.gc` | `cam-fixed`, `cam-fixed-read-entity`, all slave states |
| `goal_src/jak1/engine/camera/cam-combiner.gc` | `point-of-interest` event handler |
| `goal_src/jak1/engine/camera/cam-update.gc` | Frustum multiply by `inv-camera-rot` |
| `goal_src/jak1/engine/geometry/geometry.gc:255` | `forward-down->inv-matrix` |
| `goal_src/jak1/engine/math/quaternion.gc:329` | `quaternion->matrix` (VU0 asm) |
| `goalc/build_level/common/Entity.cpp:32` | `vector_from_json` — reads `[x,y,z,w]` straight |
| `goalc/build_level/jak1/Entity.cpp:18` | `EntityActor::generate` — writes quat as x,y,z,w |
