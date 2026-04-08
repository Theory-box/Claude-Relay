# OpenGOAL Navmesh System — Knowledge Base

**Source:** jak-project repo, Jak 1  
**Key Files:**
- `goal_src/jak1/engine/nav/navigate-h.gc` — All type definitions
- `goal_src/jak1/engine/nav/navigate.gc` — All navmesh/nav-control implementation
- `goal_src/jak1/engine/common-obs/nav-enemy-h.gc` — nav-enemy type & nav-enemy-info
- `goal_src/jak1/engine/common-obs/nav-enemy.gc` — nav-enemy behavior implementation

---

## 1. Core Data Structures

### `nav-poly` (8 bytes, packed)
The fundamental triangle of a navmesh.
```
(deftype nav-poly (structure)
  ((id       uint8)        ;; index in poly array
   (vertex   uint8 3)      ;; indices into nav-mesh vertex array
   (adj-poly uint8 3)      ;; adjacent triangle indices (255 = no neighbor = boundary)
   (pat      uint8)        ;; poly attribute flags (see PAT FLAGS below)
  )
  :pack-me)
```
**PAT Flags (nav-poly.pat):**
| Bit | Meaning |
|-----|---------|
| 1 (0x01) | **Gap poly** — passable but triggers gap/jump event. Skipped in pathfinding but reachable. Drawn gray/cyan in debug. |
| 2 (0x02) | Unknown surface type (drawn yellow-green in debug) |
| 4 (0x04) | Unknown surface type (drawn green in debug) |
| 8 (0x08) | Unknown surface type (drawn blue in debug) |
| 16 (0x10) | Unknown surface type (drawn blue in debug) |
| 0 (none set) | Normal walkable poly (drawn cyan in debug) |

`adj-poly[i] = 255` means no neighbor on that edge → mesh boundary.

---

### `nav-vertex` (extends `vector`)
Just a 4-float vector. Stored in **local/mesh-space** (relative to `nav-mesh.origin`).

---

### `nav-sphere` (contains an inline `sphere` at field `trans`)
Obstacle spheres embedded in the mesh as static blockers.

---

### `nav-node`
Binary tree nodes used to spatially accelerate poly lookup. The tree is traversed by `recursive-inside-poly`. Leaf nodes store up to ~8 triangle indices (`first-tris` + `last-tris`). Interior nodes have `left-offset` / `right-offset` to children. Used by `find-poly-fast` before falling back to linear scan.

---

### `nav-ray`
Transient working structure for ray-marching through the mesh:
```
(deftype nav-ray (structure)
  ((current-pos  vector)     ;; current position in mesh-local space
   (dir          vector)     ;; normalised xz direction
   (dest-pos     vector)     ;; destination in mesh-local space
   (current-poly nav-poly)   ;; triangle we're currently in
   (next-poly    nav-poly)   ;; triangle we're crossing into (may be gap)
   (len          meters)     ;; total distance traveled so far
   (last-edge    int8)       ;; which edge we exited on (0/1/2)
   (terminated   symbol)     ;; ray is done
   (reached-dest symbol)     ;; made it to destination
   (hit-boundary symbol)     ;; hit an edge with adj-poly=255
   (hit-gap      symbol)     ;; hit a gap poly (pat&1 set)
  ))
```
Ray marching is capped at **15 triangle crossings** per call.

---

### `nav-route-portal`
A portal between two adjacent triangles, used by the pathfinder. Contains the two shared vertices and the `next-poly` to step into.
```
(deftype nav-route-portal (structure)
  ((next-poly  nav-poly)
   (vertex     nav-vertex 2)   ;; the shared edge verts
   (edge-index int8)           ;; which edge index (0/1/2) on the source poly
  ))
```

---

### `nav-mesh` (basic)
The complete navmesh for an entity/level region:
```
(deftype nav-mesh (basic)
  ((user-list           engine)                    ;; nav-engine: list of nav-controls using this mesh
   (poly-lookup-history uint8 2)                   ;; LRU cache indices
   (debug-time          uint8)
   (static-sphere-count uint8)
   (static-sphere       (inline-array nav-sphere)) ;; fixed obstacle spheres in this mesh
   (bounds              sphere)                    ;; bounding sphere for quick rejection
   (origin              vector)                    ;; WORLD position of mesh origin; all verts are relative to this
   (cache               nav-lookup-elem 4)         ;; 4-entry LRU poly lookup cache
   (node-count          int32)
   (nodes               (inline-array nav-node))   ;; BVH acceleration structure
   (vertex-count        int32)
   (vertex              (inline-array nav-vertex)) ;; mesh-local vertices
   (poly-count          int32)
   (poly                (inline-array nav-poly))   ;; triangles
   (route               (inline-array vector4ub))  ;; precomputed route table: poly-count² entries, 2 bits each
  ))
```
**Hard limits enforced by `initialize-mesh!`:**
- Max **255 triangles** (`poly-count <= 255`)
- Max **255 vertices** (`vertex-count <= 255`)

**Route table:** `route` is a packed 2-bits-per-entry matrix of size `poly-count × poly-count`. Entry `[src][dst]` gives the edge index (0/1/2) to follow from `src` toward `dst`. Value `3` means no route. Built by `update-route-table`.

---

### `nav-control` (basic)
Per-entity navigation controller. Created per process that uses navmesh movement.
```
(deftype nav-control (basic)
  ((flags               nav-control-flags)
   (process             basic)              ;; owning process
   (shape               collide-shape)
   (mesh                nav-mesh)           ;; the mesh this controller is connected to
   (gap-event           basic)              ;; symbol sent when crossing a gap poly (default 'jump)
   (block-event         basic)              ;; symbol sent when blocked
   (current-poly        nav-poly)           ;; triangle we're currently in
   (next-poly           nav-poly)           ;; next triangle en route to target
   (target-poly         nav-poly)           ;; triangle containing destination
   (portal              nav-route-portal 2) ;; current and next portals for steering
   (nearest-y-threshold meters)             ;; max Y-distance to snap to mesh
   (event-temp          vector)
   (old-travel          vector)
   (blocked-travel      vector)
   (prev-pos            vector)
   (extra-nav-sphere    vector)             ;; extra avoidance sphere (used during jumps)
   (travel              vector)             ;; output: movement vector for this frame
   (target-pos          vector)             ;; intermediate target (portal vertex or destination)
   (destination-pos     vector)             ;; final destination
   (block-time          time-frame)
   (block-count         float)              ;; accumulates when blocked; >2.0 triggers new patrol point
   (user-poly           nav-poly)           ;; user-settable override poly
   (nav-cull-radius     float)              ;; default 40960.0 (~10m); culling distance for sphere checks
   (num-spheres         int16)
   (max-spheres         int16)              ;; set at construction (16 for nav-enemy)
   (sphere              sphere :dynamic)    ;; dynamic-sized array of obstacle spheres
  ))
```

---

## 2. Key Methods

### `nav-mesh` Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `initialize-mesh!` | `(nav-mesh)` | Validates mesh (warnings for zero-area tris, inverted normals, limit violations). Called once on first use. |
| `update-route-table` | `(nav-mesh)` | Builds the packed 2-bit route matrix via BFS + ray tests between all poly centroids. Expensive — done once at level load. |
| `find-poly-fast` | `(nav-mesh vector meters) → nav-poly` | Fast lookup using BVH (`recursive-inside-poly`) and 4-entry LRU cache. Returns `#f` if not found. |
| `find-poly` | `(nav-mesh vector meters flags*) → nav-poly` | Accurate lookup: tries `find-poly-fast` first, then linear scan of all polys measuring minimum distance. Sets `navcf20` flag if fast path hit. |
| `point-in-poly?` | `(nav-mesh nav-poly vector) → symbol` | VU-accelerated point-in-triangle test (2D/XZ). Uses vector cross products. |
| `is-in-mesh?` | `(nav-mesh vector float meters) → symbol` | Circle-vs-triangle intersection for all polys within bounds. Used for `notice-nav-radius` checks. |
| `move-along-nav-ray!` | `(nav-mesh nav-ray)` | Advances a nav-ray one triangle at a time. Updates `current-poly`, sets `hit-boundary`/`hit-gap`/`reached-dest`. Capped at 15 crossings per full traversal. |
| `try-move-along-ray` | `(nav-mesh nav-poly vector vector float) → meters` | Runs a ray from position+direction for a given distance; returns how far it got. |
| `setup-portal` | `(nav-mesh nav-poly nav-poly nav-route-portal)` | Looks up route table to find next poly toward target; fills portal struct with shared edge vertices. |
| `get-adj-poly` | `(nav-mesh nav-poly nav-poly symbol) → nav-poly` | Uses route table to get the adjacent poly on the path from poly-A to poly-B. |
| `nav-mesh-method-16` | `(nav-mesh vector nav-poly vector symbol float clip-travel-vector-to-mesh-return-info)` | Core travel clipping: clips a travel vector to stay within mesh boundaries. Handles reflection off boundaries and identifies gaps. |
| `tri-centroid-world` | `(nav-mesh nav-poly vector) → vector` | Returns world-space centroid of a triangle. |
| `project-point-into-tri-2d` | `(nav-mesh nav-poly vector vector) → vector` | Projects a point into the triangle (2D/XZ). If outside, moves to closest boundary point. |
| `project-point-into-tri-3d` | `(nav-mesh nav-poly vector vector)` | Full 3D closest-point-on-triangle. |
| `closest-point-on-boundary` | `(nav-mesh nav-poly vector vector) → vector` | Finds closest point on triangle's perimeter edges. |
| `debug-draw-poly` | `(nav-mesh nav-poly rgba)` | Draws the three edges of a triangle with debug lines. |

### `nav-control` Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `nav-control-method-11` | `(nav-control vector)` | **Main per-frame update.** Updates current poly, gathers obstacle spheres, computes travel vector toward target. Called every frame in nav-enemy's travel-post. |
| `nav-control-method-13` | `(nav-control vector vector) → vector` | **Pathfinding + steering.** Uses route table to find next portal, steers toward portal vertex to navigate around corners. Also invokes sphere avoidance. Returns travel vector. |
| `nav-control-method-16` | `(nav-control vector) → nav-poly` | Fast poly lookup for a world-space position. |
| `nav-control-method-19` | `(nav-control vector collide-shape-moving vector float)` | Sets `target-pos` by rotating toward destination at `rotate-speed`. Used in `nav-enemy-patrol-post`. |
| `nav-control-method-24` | `(nav-control float clip-travel-vector-to-mesh-return-info)` | Clips `travel` vector against mesh boundary. Used in `nav-enemy-flee-post`. |
| `nav-control-method-27` | `(nav-control)` | Updates `current-poly` by ray-marching from `prev-pos` to current position. Called every frame by `nav-control-method-11`. |
| `nav-control-method-28` | `(nav-control collide-kind)` | Gathers dynamic obstacle spheres from nearby collide-shapes on the nav-engine user list. Includes target (player) if within range. Also gathers static spheres. |
| `nav-control-method-32` | `(nav-control vector vector vector vector float) → symbol` | **Sphere avoidance.** Finds best travel direction that avoids all gathered obstacle spheres. Uses tangent lines and ray intersection tests. |
| `nav-control-method-33` | `(nav-control vector vector vector vector float) → symbol` | Wrapper for method-32 that also sets `blocked-travel` and fires `block-event` if movement is heavily restricted. |
| `find-poly` | `(nav-control vector) → nav-poly` | Finds poly for a world-space point, delegates to mesh. |
| `project-onto-nav-mesh` | `(nav-control vector vector) → vector` | Projects a world-space point onto the mesh surface. |
| `is-in-mesh?` | `(nav-control vector float) → symbol` | Circle-in-mesh check using world space. |
| `point-in-bounds?` | `(nav-control vector) → symbol` | Checks if point is within mesh bounding sphere. |
| `set-current-poly!` | `(nav-control nav-poly)` | Override current poly; also sets `navcf9` flag. |
| `set-target-pos!` | `(nav-control vector)` | Set target position. |
| `debug-draw` | `(nav-control)` | Draws mesh debug overlays. Enabled via nav-control-flags. |

---

## 3. Nav-Control Flags (`nav-control-flags`)

| Flag | Bit | Meaning |
|------|-----|---------|
| `display-marks` | 0 | Draw debug overlays for this controller |
| `navcf1` | 1 | Draw mesh bounds sphere |
| `navcf2` | 2 | Draw vertices |
| `navcf3` | 3 | Draw all polys |
| `navcf4` | 4 | Draw poly IDs |
| `navcf5` | 5 | Draw current/next/target polys |
| `navcf6` | 6 | Draw travel vector and portal |
| `navcf7` | 7 | Draw spheres |
| `navcf8` | 8 | Enable obstacle sphere gathering (always set on nav-enemy by default) |
| `navcf9` | 9 | Current poly was manually set |
| `navcf10` | 10 | Used in patrol to force new patrol point |
| `navcf11` | 11 | Include player as obstacle even if not being attacked |
| `navcf12` | 12 | Disable boundary reflection (used for fleeing enemies like rolling-lightning-mole) |
| `navcf13` | 13 | Include static mesh spheres in obstacle gathering |
| `navcf17` | 17 | Entity is currently blocked |
| `navcf18` | 18 | (set alongside 17/19) |
| `navcf19` | 19 | Entity has no valid path (stuck/at boundary) |
| `navcf20` | 20 | find-poly-fast cache hit (set by find-poly) |
| `navcf21` | 21 | Facing-aligned with target (used in rotate toward destination) |

**Default flags on nav-enemy:** `display-marks, navcf3, navcf5, navcf6, navcf7` (visual debug) + `navcf8, navcf13` (sphere gathering).

---

## 4. Nav-Enemy-Info Parameters

All movement tuning is in a `nav-enemy-info` struct (a `basic`). Each enemy type defines one statically.

```
(deftype nav-enemy-info (basic)
  ((idle-anim                 int32)
   (walk-anim                 int32)
   (turn-anim                 int32)
   (notice-anim               int32)
   (run-anim                  int32)
   (jump-anim                 int32)
   (jump-land-anim            int32)
   (victory-anim              int32)
   (taunt-anim                int32)
   (die-anim                  int32)
   (neck-joint                int32)           ;; joint index for head tracking, -1 to disable
   (player-look-at-joint      int32)
   (run-travel-speed          meters)          ;; XZ speed when chasing
   (run-rotate-speed          degrees)         ;; rotation rate when chasing
   (run-acceleration          meters)          ;; accel when chasing
   (run-turn-time             seconds)
   (walk-travel-speed         meters)          ;; XZ speed when patrolling
   (walk-rotate-speed         degrees)
   (walk-acceleration         meters)
   (walk-turn-time            seconds)
   (attack-shove-back         meters)
   (attack-shove-up           meters)
   (shadow-size               meters)
   (notice-nav-radius         meters)          ;; radius used in is-in-mesh? to verify player is on same mesh
   (nav-nearest-y-threshold   meters)          ;; max Y snap to mesh (passed to nav-control constructor)
   (notice-distance           meters)          ;; distance at which enemy notices player
   (proximity-notice-distance meters)          ;; distance for touch-notice (bypasses line-of-sight check)
   (stop-chase-distance       meters)          ;; if player goes beyond this, give up chase
   (frustration-distance      meters)          ;; if stuck within this distance of player, frustration triggers
   (frustration-time          time-frame)
   (die-anim-hold-frame       float)
   (jump-anim-start-frame     float)
   (jump-land-anim-end-frame  float)
   (jump-height-min           meters)          ;; minimum jump apex height
   (jump-height-factor        float)           ;; scales jump height by horizontal distance
   (jump-start-anim-speed     float)
   (shadow-max-y              meters)
   (shadow-min-y              meters)
   (shadow-locus-dist         meters)
   (use-align                 symbol)          ;; #t = use align-control for velocity
   (draw-shadow               symbol)
   (move-to-ground            symbol)          ;; #t = apply gravity / ground snapping
   (hover-if-no-ground        symbol)          ;; #t = hover when ground not found
   (use-momentum              symbol)          ;; #t = smooth acceleration/deceleration
   (use-flee                  symbol)          ;; #t = enable nav-enemy-flee state
   (use-proximity-notice      symbol)          ;; #t = notice player on close proximity too
   (use-jump-blocked          symbol)          ;; #t = go to nav-enemy-jump-blocked if path is blocked
   (use-jump-patrol           symbol)          ;; #t = jump during patrol if blocked
   (gnd-collide-with          collide-kind)    ;; what geometry to snap to ground against
   (debug-draw-neck           symbol)
   (debug-draw-jump           symbol)
  ))
```

---

## 5. `nav-enemy` State Machine

Standard states (all `:virtual #t` — overridable):

```
nav-enemy-idle          → nav-enemy-patrol (after timeout)
nav-enemy-patrol        → nav-enemy-notice (player enters notice-distance)
                        → nav-enemy-flee (player in flee-distance with racer mode)
                        → nav-enemy-idle (after drawn timeout)
nav-enemy-notice        → nav-enemy-chase
nav-enemy-chase         → nav-enemy-stop-chase (player too far)
                        → nav-enemy-give-up (if player has do-not-notice flag)
                        → nav-enemy-attack (close enough)
                        → nav-enemy-stare (stopped near player)
nav-enemy-stare         → nav-enemy-chase / nav-enemy-patrol
nav-enemy-stop-chase    → nav-enemy-patrol
nav-enemy-flee          → (back to patrol on timeout)
nav-enemy-attack        → nav-enemy-victory / die
nav-enemy-jump          → nav-enemy-jump-land (on ground)
                        → nav-enemy-jump-blocked (if 'use-jump-blocked)
nav-enemy-jump-blocked  → nav-enemy-jump-to-point
```

**Events processed:**
- `'jump` → go to `nav-enemy-jump` with destination point
- `'cue-jump-to-point` → clears navenmf11 flag to authorize jump-to-point  
- `'cue-chase` → go to `nav-enemy-chase`
- `'cue-patrol` → go to `nav-enemy-patrol`
- `'go-wait-for-cue` → go to `nav-enemy-wait-for-cue`

---

## 6. Per-Frame Nav Update Flow

Every frame in a moving nav-enemy:

```
nav-enemy-travel-post
  └─ nav-enemy-method-40
       └─ nav-control-method-11 (-> self nav) (-> self nav target-pos)
            ├─ seek! block-count toward 0
            ├─ logclear navcf9, navcf17, navcf18, navcf19
            ├─ nav-control-method-27       ;; update current-poly via ray march from prev-pos
            ├─ nav-control-method-28       ;; gather obstacle spheres
            └─ nav-control-method-13       ;; compute travel vector
                 ├─ find target-poly
                 ├─ setup-portal (route table lookup)
                 ├─ steer through portal vertices
                 ├─ nav-control-method-33  ;; sphere avoidance
                 └─ nav-mesh-method-16     ;; clip travel to mesh boundary
  └─ nav-enemy-method-41
       └─ apply travel → collide-info.transv (velocity)
  └─ nav-enemy-method-37
       └─ rotate toward target (seek-to-point-toward-point! or seek-toward-heading-vec!)
  └─ nav-enemy-method-38
       └─ integrate-for-enemy-with-move-to-ground! (or collide-shape-moving-method-58)
```

---

## 7. Obstacle Avoidance System

`nav-control-method-28` gathers spheres each frame:

1. **Player sphere** (if: `navcf11` set, OR player is currently being attacked/invulnerable) — uses `*target* control root-prim` and `nav-radius`
2. **Player extra-nav-sphere** (if navf1 on target's collide-shape) — used during player jump
3. **Static mesh spheres** (if `navcf13` set) — stored in `nav-mesh.static-sphere`
4. **Other entities on nav-engine** — any process on the same `nav-mesh.user-list` engine

Culling distance: **40960.0** (10 meters) beyond nav-radius sum.

`nav-control-method-32` then finds a travel direction that clears all gathered spheres using tangent lines on each sphere. Falls back to a random direction if deeply inside a sphere.

---

## 8. Gap / Jump System

**Gap polys** are triangles with `pat & 1` set. The mesh pathfinder can route through them but won't walk into them normally.

When `nav-mesh-method-16` (travel clipping) detects crossing into a gap poly, it sets `gap-poly` in the return info. `nav-control-method-24` checks this and sets `nav-control.next-poly` to the gap poly.

`nav-control-method-12` is called when `next-poly` is a gap:
1. Follows the route table beyond the gap poly to find the landing poly
2. Finds the closest point on its boundary → `nav-gap-info.dest`
3. Returns `#t` → triggers `send-event 'jump dest poly`

Jump trajectory (`nav-enemy-initialize-custom-jump`):
- Uses `setup-from-to-height!` to compute a parabolic arc
- Height = `max(jump-height-min, jump-height-factor * horizontal-distance)`
- Detects **standing jump** (facing wrong way or slow) and **drop-jump** (falling downward)
- Sets `extra-nav-sphere` on `nav-control` during airtime so other enemies avoid the jumper

---

## 9. Mesh Connection / Level Loading

`nav-mesh-connect` (called from `nav-control` constructor):
1. Checks `entity.nav-mesh` field directly
2. If empty, looks for `'nav-mesh-actor` in res-lump → redirects to that actor's nav-mesh
3. On first use of a mesh: allocates the `engine` (user-list), calls `initialize-mesh!` and `update-route-table`
4. Adds the process as a connection on the nav-engine
5. If no mesh found → falls back to `*default-nav-mesh*` (a small 2-triangle fallback)

**Important res-lump keys on entity-actor:**
| Key | Type | Purpose |
|-----|------|---------|
| `'nav-mesh-actor` | `structure` | Reference to another actor that owns the nav-mesh |
| `'nav-max-users` | `int` | Engine size (default 32) |
| `'nearest-y-threshold` | `float` | Overrides nav-control's Y snap distance |
| `'nav-mesh-sphere` | array | Static obstacle spheres for this mesh |

`entity-nav-login` is called during level load to pre-initialize meshes before enemies spawn.

`has-nav-mesh?` checks if an actor has a mesh (directly or via res-lump).

---

## 10. `nav-radius` and `nav-flags`

`nav-radius` lives in `trsqv` (offset 8) — the base transform type for `collide-shape`. Default for most objects: `(* 0.75 root-prim-local-sphere-radius)`. For `babak`: explicitly `6144.0` (~1.5m).

`nav-flags` (on `collide-shape`):
| Flag | Bit | Meaning |
|------|-----|---------|
| `navf0` | 0 | This shape participates as a nav-sphere obstacle for others |
| `navf1` | 1 | Use `extra-nav-sphere` instead of root-prim (active during jumps) |

---

## 11. Coordinate System

All navmesh vertices are stored in **mesh-local space** — relative to `nav-mesh.origin` (a world-space vector). Every query that takes a world-space point must subtract `mesh.origin` first:

```scheme
(vector-! local-pos world-pos (-> mesh origin))
(find-poly mesh local-pos threshold flags)
```

`nav-control` methods that accept world-space positions do this conversion internally. Direct `nav-mesh` method calls require mesh-local coordinates.

---

## 12. Debugging / Visualization

Global toggles:
- `*display-nav-marks*` — master switch for all nav debug drawing
- `*nav-timer-enable*` — enable performance timers
- `*nav-patch-route-table*` — enable route table computation

Per-controller flags (enable individual overlays):
- `navcf1` → bounds sphere
- `navcf2` → vertices
- `navcf3` → **all polys** (color-coded by pat bits)
- `navcf4` → poly ID labels
- `navcf5` → current/next/target poly highlights
- `navcf6` → travel vector + portal line
- `navcf7` → obstacle spheres

Poly color coding in debug draw:
- `pat & 1` = gap → gray/cyan
- `pat & 2` → yellow-green
- `pat & 4` → green
- `pat & 8` or `pat & 16` → blue
- normal → cyan

`debug-nav-validate-current-poly` — verifies an entity is actually inside its `current-poly`.

---

## 13. Implementation Patterns for the Addon

### Detecting navmesh presence
```scheme
;; Does this actor have a navmesh?
(has-nav-mesh? entity-actor)

;; Does this process have a nav-control with a valid mesh?
(and (nonzero? (-> proc nav)) (nonzero? (-> proc nav mesh)))
```

### Reading mesh geometry
```scheme
;; Iterate all polys
(dotimes (i (-> mesh poly-count))
  (let ((poly (-> mesh poly i)))
    ;; vertices in world space:
    (vector+! world-v0 (-> mesh origin) (the-as vector (-> mesh vertex (-> poly vertex 0))))
    ;; gap poly?
    (logtest? (-> poly pat) 1)
    ;; boundary edge?
    (= (-> poly adj-poly 0) 255)))

;; Total vertex count
(-> mesh vertex-count)
```

### Querying mesh at a world position
```scheme
;; Find which poly a world-space point is in
(let ((local-pos (vector-! (new 'stack-no-clear 'vector) world-pos (-> mesh origin))))
  (find-poly mesh local-pos nearest-y-threshold flags-ptr))

;; Is a world point within radius of the mesh?
(is-in-mesh? nav-ctrl world-pos radius)

;; Project a world point onto the mesh surface
(project-onto-nav-mesh nav-ctrl result-vec world-pos)
```

### Nav-control construction
```scheme
;; Standard nav-enemy construction (16 spheres, custom Y threshold)
(new 'process 'nav-control collide-shape 16 (-> nav-info nav-nearest-y-threshold))

;; Enable debug visualization
(logior! (-> nav flags) (nav-control-flags display-marks navcf3 navcf5 navcf6 navcf7))

;; Set gap event
(set! (-> nav gap-event) 'jump)
```

### Setting a navigation target
```scheme
;; Set destination
(set! (-> self nav destination-pos quad) (-> target-position quad))
;; Set target (intermediate) position — usually same as destination initially
(set-target-pos! (-> self nav) target-position)
;; Drive nav update
(nav-control-method-11 (-> self nav) (-> self nav target-pos))
;; Apply resulting travel to velocity
(let ((travel-len (vector-xz-length (-> self nav travel))))
  (vector-normalize-copy! (-> self collide-info transv) (-> self nav travel) travel-len))
```

### Reading travel output
```scheme
;; After nav-control-method-11:
(-> self nav travel)          ;; movement vector for this frame
(-> self nav target-pos)      ;; intermediate waypoint
(-> self nav destination-pos) ;; final destination

;; Status flags
(logtest? (-> self nav flags) (nav-control-flags navcf19))  ;; no valid path
(logtest? (-> self nav flags) (nav-control-flags navcf17))  ;; blocked
(> (-> self nav block-count) 2.0)                           ;; stuck (>2 frames blocked)
```

### Checking line-of-sight on mesh
```scheme
;; Can entity reach destination via ray?
(nav-ray-test mesh start-poly start-world-pos dest-world-pos)  ;; returns distance

;; Local-space version returning bool
(nav-ray-test-local? mesh start-poly local-start local-dest)
```

### Route table queries
```scheme
;; What edge to cross going from poly-A toward poly-B?
(nav-mesh-lookup-route mesh (-> poly-a id) (-> poly-b id))
;; Returns 0/1/2 = edge index, 3 = no route

;; Get next poly on path from A to B
(get-adj-poly mesh poly-a poly-b #f)
```

### Obstacle spheres (manual)
```scheme
;; Add a custom obstacle sphere at world position
(add-nav-sphere nav-ctrl world-pos-with-radius-in-w)

;; Add all shapes of a collide-shape as obstacles
(add-collide-shape-spheres nav-ctrl other-collide-shape temp-vec)
```

---

## 14. Known Constraints / Gotchas

1. **255 poly / 255 vertex hard limit.** `initialize-mesh!` only warns, it doesn't fail — but IDs are `uint8` so index 255 = `adj-poly` sentinel. Plan meshes accordingly.

2. **Route table is O(n²) memory** (`poly-count² × 2 bits / 8`). For 255 polys that's ~8KB. Route computation is also O(n²) + ray tests. Done at level load, not runtime.

3. **All mesh coordinates are mesh-local.** Always subtract `mesh.origin` before passing to direct `nav-mesh` methods. `nav-control` methods handle this internally.

4. **Ray march caps at 15 triangle crossings.** Long paths through many small triangles may not reach destination in one frame. Route table compensates by giving next-poly hints.

5. **`nav-flags navf0` is required** on a `collide-shape` for that shape to register as an obstacle for neighboring nav-enemies. Set at construction time.

6. **`nav-mesh.user-list` engine** controls which processes share obstacle awareness. Only entities connected to the same nav-mesh engine see each other as obstacles.

7. **Gap polys (pat&1) are NOT skipped by the route table BFS** — they are included but treated specially by the travel-clipping code. This is how enemies know to jump over them.

8. **`block-count` threshold is 2.0** — after 2+ consecutive blocked frames, `navcf10` is set and `nav-enemy-get-new-patrol-point` is called to pick a new waypoint.

9. **NaN guard in nav-control-method-28** — OG added an explicit NaN check for enemies with invalid positions (occurs during spawn/despawn). If implementing sphere gathering, always check for NaN.

10. **`*default-nav-mesh*`** is a tiny 2-triangle fallback mesh at y=-200704. If an entity ends up on this, it means `nav-mesh-connect` failed to find a real mesh. Check res-lump `'nav-mesh-actor` linkage.

