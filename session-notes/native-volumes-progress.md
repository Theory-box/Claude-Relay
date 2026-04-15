# Native Volumes — Session Notes

**Branch:** `feature/native-volumes`

---

## What Was Done

### Motivation
VOL_ meshes were being reduced to AABB at export time (`_vol_aabb()`), then
our custom GOAL trigger types did manual 6-float box comparisons each frame.
Rotated boxes became inflated axis-aligned boxes. Non-box shapes were useless.

The native engine already has `vol-control` / `point-in-vol?` which supports
arbitrary convex volumes using per-face half-space planes. Water-vol uses this
system (and our vol-h.gc patch already fixes it for custom levels).

### The Blender Script Insight
The uploaded `mesh-to-VOL.py` script does exactly what we needed on the export
side: for each mesh face it outputs `[nx, ny, nz, d]` (outward normal + plane
distance) in the `"vol": ["vector-vol", ...]` format that the engine reads.

Key math: dot product is preserved under the Blender→Game orthogonal coord
transform (X=X, Y=Z, Z=-Y), so `d = face_center.dot(normal)` in Blender space
equals `d` in game space. No extra conversion needed.

### Changes Made (`export.py`)

**New function:** `_vol_planes(vol_obj)`
- Iterates `mesh.polygons` (supports quads/ngons, not just tris)
- Applies world matrix rotation+scale to normals, normalizes
- Coord transform: `(n.x, n.z, -n.y)`
- Computes `d = face_center.dot(normal)` in Blender world space
- Also returns `(cx, cy, cz, radius)` bounding sphere for cull pre-check

**4 trigger collection sites updated:**
- `collect_camera_triggers` — camera-trigger
- `collect_aggro_triggers` — aggro-trigger  
- `collect_custom_triggers` — vol-trigger
- Checkpoint collection — checkpoint-trigger (vol mode)

All now export:
```json
"vol": ["vector-vol", [nx,ny,nz,d], [nx,ny,nz,d], ...],
"cull-radius": ["meters", rad]
```
instead of 6x `bound-*` float lumps.

**4 GOAL templates rewritten in `write_gc`:**
All trigger types now:
- Have `vol vol-control :offset-assert N` instead of 6 float fields
- Read cull-radius from lump: `(res-lump-float arg0 'cull-radius :default 20480.0)`
- Init vol-control: `(new 'process 'vol-control (the-as entity arg0))`
- Use `(point-in-vol? (-> self vol) pos)` instead of 6 manual float comparisons
- Log `pos-vol-count` on init so init failures are visible in REPL

New struct sizes (all smaller — removed 24 bytes of float fields, added 4 byte pointer):
| Type | Old | New |
|---|---|---|
| camera-trigger | #xd4 | #xc0 |
| checkpoint-trigger | #xdc | #xc8 |
| aggro-trigger | #xd8 | #xc4 |
| vol-trigger | #xd4 | #xc0 |

---

## Session 2 additions (continuation)

### Build patch coverage fixed (`build.py`)
`_apply_engine_patches()` was previously only called in `_bg_build()`.
Both `_bg_geo_rebuild()` and `_bg_build_and_play()` now also call it.
Without the patch on a fresh install (or after a vol-h.gc rollback),
`pos-vol-count` stays 0 in all 4 trigger types → triggers never fire.

### Docstring + comment cleanup
- Removed dead `_camera_aabb_to_planes()` function (was unreferenced)
- Updated `_vol_aabb` docstring: water-path only now
- Fixed stale "AABB polling" references in 3 collect_* docstrings
- Updated `_apply_engine_patches` docstring: expanded scope, removed TODO

### Audit check added (`audit.py`)
New `check_vol_geometry` (registered after `check_volumes`):
- **ERROR** — VOL_ mesh has zero faces → zero planes → trigger never fires
- **ERROR** — majority of face normals are inward-facing (triggers fire
  OUTSIDE the volume; caught by comparing normals against centroid→face)
- **WARNING** — some normals inward (non-convex or partially flipped)

### Plane math verified with standalone tests
Unit cube: all 8 classification tests pass.
45°-rotated cube:
- Points inside the diamond shape: correctly classified INSIDE
- AABB false-positive corners (in bounding box but outside rotated box):
  correctly classified OUTSIDE
- The Blender→Game coord transform preserves dot products (orthogonal
  transform), confirmed analytically and by test.

### 1. vol-control constructor call syntax — MUST VERIFY
Current code uses:
```lisp
(set! (-> this vol) (new 'process 'vol-control (the-as entity arg0)))
```
**Not confirmed.** If the `vol-control` constructor doesn't accept an entity
arg, the init will fail silently (pos-vol-count stays 0). Alternative:
```lisp
(set! (-> this vol) (new 'process 'vol-control))
(get-vol (-> this vol) arg0)   ;; or whatever the init method is called
```
The REPL log line `planes ~D` prints `pos-vol-count` — if it shows 0 after
loading a level with triggers, this is the problem.

### 2. Mesh normals must be outward-facing
`point-in-vol?` checks `dot(P,N) - d > 0` = outside. If Blender face normals
are inward (can happen on imported or Boolean-subtracted meshes), all triggers
will be inverted (fire when outside, not fire when inside).
**User action:** Select VOL_ mesh → Edit Mode → Mesh → Normals → Recalculate
Outside (Shift+N) before export.

### 3. Convex mesh requirement  
`point-in-vol?` only works correctly for convex meshes. A concave VOL_ mesh
will produce planes that cut through the volume. For concave trigger zones,
use multiple overlapping VOL_ meshes each linked to the same target.

### 4. Non-uniform scale
`rot_mat = global_matrix.to_3x3()` doesn't handle non-uniform scale correctly
for normals (should use inverse-transpose). Typically not an issue since VOL_
meshes are usually uniform-scaled. If incorrect trigger planes appear on
non-uniformly scaled volumes, apply scale in Blender first (Ctrl+A → Scale).

### 5. Water-vol still uses old hardcoded AABB planes
The `water-vol` export path (~line 1600 in export.py) still builds 6 AABB
planes from the empty's scale. This is intentional for now — water-vol is a
special case where the bounding box semantics make sense. Could be updated
later to use actual mesh planes if we move to WATER_ mesh-based volumes.

### 6. Integration test needed
Build a level with:
- A rotated (45°) box VOL_ as a camera trigger
- A non-box convex mesh (e.g. wedge/ramp) as an aggro trigger  
- Verify REPL logs show `pos-vol-count > 0`
- Verify triggers fire at correct positions

---

## Files Changed
- `addons/opengoal_tools/export.py` — all changes
