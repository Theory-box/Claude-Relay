# OpenGOAL Trigger Systems — Full Research Reference

**Research date:** April 2026
**Sources:** Full source crawl of jak-project — cam-master.gc, vol.gc, vol-h.gc,
  entity.gc, entity-h.gc, load-boundary.gc, load-boundary-h.gc,
  load-boundary-data.gc, build_level/jak1/*, build_level/common/Entity.cpp

---

## The Core Question

The addon currently implements three trigger types as custom GOAL deftypes
(emitted into obs.gc) that poll player position each frame:

| Type | Function |
|---|---|
| `camera-trigger` | AABB poll → `send-event *camera* 'change-to-entity-by-name` |
| `checkpoint-trigger` | AABB/sphere poll → `set-continue!` |
| `aggro-trigger` | AABB poll → `send-event enemy 'cue-chase` |

The question: can/should we replace these with native engine systems?

---

## 1. Camera Trigger — Native System EXISTS but NOT REACHABLE

### How the engine does it

`camera-master` runs `master-check-regions` every frame (cam-master.gc:950).
It walks `*camera-engine*` alive-list (a connectable engine list). For each entry
it calls `in-cam-entity-volume?(player-pos, entity, tolerance, 'vol)`.

`in-cam-entity-volume?` iterates all `vol` lump tags on the entity. Each tag
contains N planes as `vector4f` where `xyz = world-space normal, w = signed offset
distance`. A point is inside the volume when `dot(pos, normal) - w <= 0` for ALL
planes in a convex set. Multiple `vol` tags = multiple convex regions (OR logic).
`cutoutvol` = exclusion zones. `pvol` = priority volume used for hysteresis.

When the player enters a vol-region, `master-switch-to-entity` fires automatically,
spawning a `camera-slave` process using the camera state inferred from the entity's
lumps (fixed/orbit/string/spline). No custom code. No polling process.

**Critically: `entity-camera` objects enter `*camera-engine*` via `birth!`**
(entity.gc:787): `(add-connection *camera-engine* *camera* nothing this #f #f)`.
This is called from `activate-entities! → bsp-header.birth! → cameras array loop`.
The `cameras` array is populated by the C++ level builder from the bsp-header.

### Why it's not reachable for custom levels

The C++ builder's cameras section is **a stub — completely unimplemented**:

```cpp
// goalc/build_level/jak1/LevelFile.h
struct EntityCamera {};  // empty struct, never populated

// goalc/build_level/jak1/LevelFile.cpp  
//(cameras (array entity-camera) :offset-assert 116)  ← commented out entirely
```

```cpp
// goalc/build_level/jak1/build_level.cpp
// cameras
// nodes       ← just comments, zero implementation
// boxes
```

The JSONC builder reads `actors` and `ambients` but never reads camera entities
into the bsp-header `cameras` array. So `entity-camera.birth!` is never called for
custom levels. `*camera-engine*` stays empty. `master-check-regions` finds nothing.

### What `vector-vol` lump format looks like (for future reference)

When the builder eventually supports cameras, the vol lump format is:
```jsonc
"vol": ["vector-vol", [nx, ny, nz, d_meters], [nx, ny, nz, d_meters], ...]
```
Builder: xyz = raw floats (normals), w = `d_meters * METER_LENGTH (4096)`.
Engine: point P is inside when `dot(P, normal) - w <= 0` for all planes.
Normals point **inward** (into the volume). w is the plane offset from origin.

### Verdict

**Keep our `camera-trigger` custom deftype.** The native system cannot be fed
camera entities from the JSONC builder. Our approach is the only working option
until `build_level/jak1/LevelFile.cpp` gains camera population support (an
upstream contribution opportunity).

Future upstream fix path:
1. Add `add_cameras_from_json()` in `build_level/jak1/Entity.cpp`
2. Wire it in `build_level/jak1/build_level.cpp`  
3. Populate `bsp-header cameras` array in `LevelFile.cpp`
4. Then use `vol` lumps directly on `camera-marker` entities — no custom GOAL needed

---

## 2. Checkpoint Trigger — Replace with `static-load-boundary`

### How `load-boundary` works

Defined in `load-boundary-h.gc`. Static data declared in `load-boundary-data.gc`
via the `static-load-boundary` macro. Linked into `*load-boundary-list*` at
startup via `(doarray (i *static-load-boundary-list*) (load-boundary-from-template i))`.

Checked every frame in `render-boundaries` (load-boundary.gc:740):
```lisp
(defun render-boundaries ()
  (when (-> *level* border?)
    ;; update camera/player positions into *load-boundary-target*
    (let ((gp-2 *load-boundary-list*))
      (while gp-2
        (check-boundary gp-2)
        (set! gp-2 (-> gp-2 next))))))
```

`render-boundaries` is called from the level render hook every frame.
`check-boundary` does a point-in-polygon test, fires commands on crossing.

### `checkpt` command fires `set-continue!`

```lisp
((= (-> s4-0 cmd) (load-boundary-cmd checkpt))
 (set-continue! *game-info* (-> s4-0 lev0)))  ; lev0 = the continue-name string
```

This is **exactly** what our `checkpoint-trigger` GOAL code does, but:
- No born process
- No per-frame polling loop in GOAL
- No deftype definition in obs.gc
- No JSONC actor entry
- The crossing detection is a proper XZ polygon test (not just AABB)
- Has fwd/bwd direction support built in
- Global — works across all levels, no level-specific process

### `static-load-boundary` macro format

```lisp
(static-load-boundary
  :flags (player)           ; 'player' = trigger on player pos; '()' = camera pos
  :top  top_y_raw_units     ; Y ceiling (raw game units, multiply meters × 4096)
  :bot  bot_y_raw_units     ; Y floor
  :points (x0 z0 x1 z1 ...) ; XZ vertex pairs — RAW GAME UNITS (no auto-conversion)
  :fwd (checkpt "continue-name" #f)  ; command on forward crossing
  :bwd (invalid #f #f))              ; command on backward crossing (invalid = no-op)
```

**CRITICAL: points are raw game units, NOT meters.** No auto-conversion.
Multiply Blender meters × 4096 manually.

**Coordinate system mapping (Blender → game boundary):**
- Blender X → game X  (same)
- Blender Y → game Z  (depth) — Blender Y is game Z
- Blender Z → game Y  (height) — but boundaries use XZ plane only
- So boundary X = Blender X × 4096, boundary Z = -Blender Y × 4096

**Top/bot Y:** boundary Y top/bot = Blender Z world coords × 4096

**Polygon topology:** The boundary is an open or closed XZ polygon.
- Open (default `:flags ()` or `:flags (player)`): a line/polyline, fires on crossing
- Closed (`:flags (closed)`): area, fires on entering/exiting enclosed region

For a VOL_ mesh from Blender, extract the XZ footprint (ignore Y) and emit it
as the :points list. Use `:flags (player closed)` for an enclosed area trigger.

**IMPORTANT:** `load-boundary-data.gc` is a GLOBAL file compiled into `ENGINE.CGO`.
Any boundaries we emit go into obs.gc as GOAL code that appends to `*load-boundary-list*`
at level load time, OR we patch `load-boundary-data.gc`. Either works, but
patching obs.gc is simpler — just call `load-boundary-from-template` with our data.

Actually the cleanest approach: emit `static-load-boundary` forms directly in obs.gc.
These create their own local static arrays and call `load-boundary-from-template`
on load, linking into `*load-boundary-list*`.

Wait — `static-load-boundary` creates a boxed-array at compile-time but doesn't
call `load-boundary-from-template`. That's done by the `doarray` at the bottom of
`load-boundary-data.gc`. So to use `static-load-boundary` from obs.gc we need to
also call `(load-boundary-from-template <our-data>)` at level load time.

The simplest approach: emit raw `(new 'global 'load-boundary ...)` calls in obs.gc,
populate them, and link them into `*load-boundary-list*`. Or use the template macro
and add a matching `doarray` call.

### Verdict

**Replace `checkpoint-trigger` with `static-load-boundary` GOAL emission.**

Changes needed:
1. `write_gc`: remove `checkpoint-trigger` deftype and state; add function that
   creates load-boundary objects from checkpoint data at level load time
2. `collect_actors` / checkpoint section: stop emitting `checkpoint-trigger` JSONC
   actors; instead return raw XZ polygon data from the VOL_ mesh
3. New function: `collect_load_boundaries(scene)` → list of boundary dicts
4. `_bg_build`: call `collect_load_boundaries`, pass data to `write_gc`
5. `write_gc`: emit `(defun setup-level-boundaries () ...)` that creates and links
   boundaries, called from a top-level `(setup-level-boundaries)` form

### Boundary shape from VOL_ mesh

For a CHECKPOINT_ + linked VOL_ mesh:
- Extract all unique XZ vertex pairs from the VOL_ mesh world vertices
- Convert to hull or footprint (convex hull of XZ coords)
- Emit as :points list with `* 4096` conversion
- top = max Blender Z of mesh vertices × 4096
- bot = min Blender Z of mesh vertices × 4096
- Use `:flags (player closed)` for area-style checkpoint

For a CHECKPOINT_ without VOL_ mesh (sphere mode):
- Emit a small circular closed boundary approximated as an N-gon (e.g. 8 vertices)
- Radius from `og_checkpoint_radius` (default 3m)

---

## 3. Enemy Aggro Trigger — Keep Custom

No native equivalent for "volume entry → send event to specific named enemy."

`battlecontroller` uses `actor-group` + wave-based spawning, which is tightly
coupled to its own type. There's no data-driven "trigger → named process event"
mechanism in the engine.

Our `aggro-trigger` approach (vol AABB → `process-by-ename` → `send-event 'cue-chase`)
is the correct custom solution. Keep as-is.

---

## 4. Load Boundary Coordinate System — Complete Reference

```
Blender coord  →  boundary :points  →  check-boundary uses
X              →  x * 4096          →  lbvtx.x
Y (depth)      →  -y * 4096         →  lbvtx.z  (note negation — Blender Y is game -Z)
Z (up)         →  z * 4096          →  not used in :points; used for :top/:bot
```

Wait — need to verify sign. Our Blender→game conversion: game_x = bl_x, game_y = bl_z, game_z = -bl_y.
So boundary x = bl_x * 4096, boundary z = -bl_y * 4096. Top/bot = bl_z * 4096.

**Rejector (bounding circle):** auto-computed from points in `find-bounding-circle`.
No manual setup needed.

**Direction (fwd/bwd):** The boundary is directional. Crossing in one direction fires
`:fwd`, the reverse fires `:bwd`. Direction is determined by the winding order of
the polygon vertices and the player's movement vector. For a checkpoint that should
fire in both directions, set both `:fwd` and `:bwd` to the same checkpt command.

---

## 5. `render-boundaries` Gating — `border?` flag

`render-boundaries` only runs when `(-> *level* border?)` is true.
`border?` is set to `#f` by `start` (logic-target.gc) at spawn time, then set to
`#t` again by `target-continue` after the level loads and the player is ready.

Custom levels: `border?` should become true automatically after `target-continue`
completes. If boundaries aren't firing, check that `border?` is being set.

---

## 6. Summary Table

| Trigger | Native system | Reachable? | Verdict |
|---|---|---|---|
| Camera switch on vol enter | `entity-camera` + `vol` lump + `master-check-regions` | ❌ C++ builder stub | Keep custom `camera-trigger` |
| Checkpoint on vol/area enter | `static-load-boundary` + `load-boundary-cmd checkpt` | ✅ Pure GOAL | Replace with load-boundary |
| Enemy aggro on vol enter | None | — | Keep custom `aggro-trigger` |

---

## 7. Future Upstream Work (not for addon)

To make camera triggers native:
1. `goalc/build_level/jak1/Entity.cpp`: implement `add_cameras_from_json()`
   - Read `"cameras"` array from JSONC
   - Each entry: trans, quat, lump data (including `vol`/`pvol`/`cutoutvol` planes)
   - Populate `EntityCamera` struct and `bsp-header cameras` array
2. `goalc/build_level/jak1/LevelFile.cpp`: uncomment cameras section,
   call `generate_entity_camera_array(gen, cameras)` 
3. Then `camera-marker` entities with `vol` lumps would auto-register with
   `*camera-engine*` and trigger natively

The `vol` lump data format (already supported by builder via `vector-vol`):
```jsonc
"vol": ["vector-vol", [nx, ny, nz, d_meters], ...]
```
Each entry is one plane of the convex volume. nx/ny/nz = inward-pointing normal
(unit vector), d_meters = signed distance from origin (multiply by 4096).

Generating correct half-space planes from a Blender mesh:
- For each face of the VOL_ mesh: normal = face normal (inward), d = dot(normal, face_center)
- Result is a convex polyhedron defined by N half-spaces
