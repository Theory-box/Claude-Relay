# Jak 1 Custom Level — Entity Spawning & NavMesh Reference
*Everything learned the hard way. Every rule here cost a crash to discover.*
*Last updated: April 10 2026. Tpage numbers verified against game.gp copy-textures calls.*

Rockpool reference mod (real working custom level example):
https://github.com/dallmeyer/OG-ModBase-Rockpool

---

## 1. JSONC Actor Format

### Actor `trans` — exactly 3 elements
```json
"trans": [x, y, z]
```
`vectorm3_from_json` asserts `size == 3`. A 4th element crashes the builder.

### Ambient `trans` — exactly 4 elements
```json
"trans": [x, y, z, w]
```
Ambients use `vectorm4_from_json` which asserts `size == 4`. The 4th value is activation radius, not a position component. `10.0` is a safe default.

### `bsphere` — always 4 elements, reasonable radius
```json
"bsphere": [x, y, z, radius]
```
Use `10.0` as radius. Do NOT use large values (120m+) — the merc renderer tries to draw the entity constantly and overflows.

### `quat` — always 4 elements
```json
"quat": [0, 0, 0, 1]
```

### `vector4m` lump entries — **nested** arrays
```json
"nav-mesh-sphere": ["vector4m", [x, y, z, radius]]
"path": ["vector4m", [x, y, z, 1.0], [x, y, z, 1.0], ...]
```
Each point is a nested array `[x, y, z, w]`. Flat values like `["vector4m", x, y, z, r]` crash the builder.

---

## 2. The DGO File (.gd)

### Correct format
```lisp
;; DGO for my-level
("MYL.DGO"
 (
  "my-level-obs.o"
  "tpage-398.go"    ← village1 sky tpages (always needed)
  "tpage-400.go"
  "tpage-399.go"
  "tpage-401.go"
  "tpage-1470.go"
  "tpage-212.go"    ← entity tpages (see Section 4)
  "tpage-214.go"
  "tpage-213.go"
  "tpage-215.go"
  "babak-ag.go"     ← art groups
  "my-level.go"
  )
 )
```
The opening paren for the inner list must be on its own line. Concatenating it with the first file entry produces malformed S-expression that crashes GOALC.

### game.gp entries
```lisp
(build-custom-level "my-level")
(custom-level-cgo "MYL.DGO" "my-level/myl.gd")
(goal-src "levels/my-level/my-level-obs.gc" "process-drawable")
```

---

## 3. Art Groups and the GOAL Linker — The Duplicate-Link Crash

This is the most subtle and dangerous bug. When loading a custom level:

1. Game boots → hub level (village1) loads → beach (BEA.DGO) loads
2. BEA.DGO links `babak-ag.go` → `*babak-sg*` defined on the BEA heap
3. `(bg-custom 'my-level-vis)` → BEA unloads → `*babak-sg*` now points to **freed memory**
4. Custom DGO loads → babak-ag.go is in the DGO but linker sees it was already linked → **skips re-linking** → `*babak-sg*` stays as a dangling pointer
5. Babak spawns → `initialize-skeleton this *babak-sg*` → **crash**

### The fix: use `(bg)` not `(bg-custom)`
```lisp
(bg 'my-level-vis)        ; correct — loads directly, no hub level
(bg-custom 'my-level-vis) ; WRONG — routes through village1, pre-loads BEA.DGO
```

`(bg)` loads the level without any prerequisite hub levels. BEA never loads, so babak-ag links fresh into clean heap space. Use this in startup.gc and any REPL commands.

### Art groups in GAME.CGO (never need to be in your DGO)
fuel-cell-ag, money-ag, buzzer-ag, crate-ag, eichar-ag, sidekick-ag, racer-ag, flut-saddle-ag, ef-plane-ag

### Art groups NOT in GAME.CGO (must be in your DGO)
babak-ag, lurkercrab-ag, lurkerpuppy-ag, lurkerworm-ag, hopper-ag, kermit-ag, swamp-bat-ag, swamp-rat-ag, snow-bunny-ag, yeti-ag, double-lurker-ag, double-lurker-top-ag, puffer-ag, bully-ag, flying-lurker-ag, driller-lurker-ag, gnawer-ag, muse-ag, quicksandlurker-ag, bonelurker-ag, balloonlurker-ag, evilplant-ag, and most other enemy/NPC art groups.

---

## 4. Texture Pages (tpages)

Art groups need their source level's tpages in the DGO so the GOAL texture system can resolve texture IDs at runtime. Without them the merc renderer reads null/garbage and crashes when the entity is drawn.

**CRITICAL: These numbers are taken directly from `copy-textures` calls in game.gp. Do not use approximations — wrong tpages cause crashes or corrupt rendering.**

The FR3 file (PC renderer) gets textures automatically from the ISO via `extract_merc`. The GOAL-side renderer needs tpages in the DGO separately.

| Enemy / Entity | Source Level | DGO | Tpages (in order) |
|---|---|---|---|
| babak, lurkercrab, lurkerpuppy, lurkerworm | Beach | BEA | 212, 214, 213, 215 |
| hopper, junglesnake | Jungle | JUN | 385, 531, 386, 388, 765 |
| kermit, swamp-bat, swamp-rat, swamp-rat-nest | Swamp | SWA | 358, 659, 629, 630 |
| yeti, snow-bunny | Snow | SNO | 710, 842, 711, 712 |
| bully, double-lurker, puffer | Sunken A | SUN | 661, 663, 714, 662, 766 |
| (sunken city B entities) | Sunken B | SUB | 163, 164, 166, 162, 764 |
| flying-lurker, plunger-lurker | Ogre | OGR | 875, 967, 884, 1117 |
| dark-crystal, gnawer, driller-lurker, baby-spider, mother-spider | Maincave | MAI | 1313, 1315, 1314, 1312, 767 |
| cavecrusher | Robocave | ROB | 1318, 1319, 1317, 1316 |
| muse, quicksandlurker, bonelurker, balloonlurker | Misty | MIS | 516, 521, 518, 520 |
| evilplant, starfish, villa-starfish | Village 1 | VI1 | 398, 400, 399, 401, 1470 |

Tpage order in the .gd must match the vanilla level's `copy-textures` order for that level.

### Heap memory limit — do not mix too many source levels

The game kheap has approximately 4MB free during level load. Each tpage set costs ~200–250KB. **Mixing entities from more than 2 source levels at once risks an OOM crash.**

The crash looks like:
```
kmalloc: !alloc mem data-segment (50480 bytes)
dkernel: unable to malloc 50480 bytes for data-segment
```
It happens mid-DGO-load, often while linking tpages. The fix is to only use enemies from 1–2 source levels per scene. Beach enemies (babak + lurkercrab etc.) all share one tpage set, so you can have many of them. Adding a bully (Sunken) + a hopper (Jungle) on top of beach enemies would be 3 tpage sets = likely OOM.

---

## 5. Enemy Code — GAME.CGO vs Level DGO

All of the following have their `.gc` compiled into GAME.CGO. You only need to add the art group (and tpages) to your DGO — no `goal-src` entry needed in game.gp.

**In GAME.CGO (code available globally):**

| Entity | .gc location | Art group needed in DGO? |
|---|---|---|
| babak | `common-obs/babak.gc` | yes — babak-ag |
| lurkercrab | `levels/beach/lurkercrab.gc` | yes — lurkercrab-ag |
| lurkerpuppy | `levels/beach/lurkerpuppy.gc` | yes — lurkerpuppy-ag |
| lurkerworm | `levels/beach/lurkerworm.gc` | yes — lurkerworm-ag |
| hopper | `levels/jungle/hopper.gc` | yes — hopper-ag |
| junglesnake | compiled with JUN | yes — junglesnake-ag |
| evilplant | compiled with VI1 (`village-obs.gc`) | yes — evilplant-ag |
| kermit | compiled with SWA | yes — kermit-ag |
| swamp-bat | compiled with SWA | yes — swamp-bat-ag |
| swamp-rat | compiled with SWA | yes — swamp-rat-ag |
| muse | compiled with MIS | yes — muse-ag |
| bonelurker | compiled with MIS | yes — bonelurker-ag |
| quicksandlurker | compiled with MIS | yes — quicksandlurker-ag |
| balloonlurker | compiled with MIS | yes — balloonlurker-ag |
| bully | compiled with SUN | yes — bully-ag |
| double-lurker | compiled with SUN | yes — double-lurker-ag, double-lurker-top-ag |
| puffer | compiled with SUN | yes — puffer-ag |
| yeti | compiled with SNO | yes — yeti-ag |
| snow-bunny | compiled with SNO | yes — snow-bunny-ag |
| flying-lurker | compiled with OGR | yes — flying-lurker-ag |
| gnawer | compiled with MAI | yes — gnawer-ag |
| driller-lurker | compiled with MAI | yes — driller-lurker-ag |
| green-eco-lurker | compiled with FIN | yes — green-eco-lurker-ag |

**Note:** babak and the beach lurkers are compiled directly into GAME.CGO. All others are compiled as part of their source level's DGO sequence, which GAME.CGO also includes. In practice all are available at runtime — no `goal-src` needed for any of them.

---

## 6. Complete Entity Database — Behavior, Requirements, AI Type

### Category A — nav-enemy (requires navmesh + entity.gc patch)

These extend `nav-enemy` and use the full nav-mesh pathfinding system. Without a proper navmesh assigned via the entity.gc patch, they idle forever and never chase or attack.

**How notice works for nav-enemies:** `target-in-range?` checks that Jak's `shadow-pos` (ground contact point) is inside a polygon of the navmesh. If Jak is not standing on navmesh-covered ground, the enemy never notices him regardless of distance. The navmesh must cover the area where Jak walks, not just where the enemy stands.

**idle → patrol → notice flow:** All nav-enemies go through `nav-enemy-idle` first, which transitions to `nav-enemy-patrol` after `idle-distance` (default 80m) and `was-drawn` checks pass. Notice is checked from patrol, not idle. So the enemy must be drawn by the renderer AND Jak must be within 80m before the notice check even runs.

| Entity | States | Special lumps | Notes |
|---|---|---|---|
| `babak` | idle, notice, chase, attack, victory, die | none | Reference case. Pure nav-enemy. |
| `lurkercrab` | idle, notice, chase, attack, die | none | 3-prim collision (group + 2 attack spheres at joints 16 & 21) |
| `lurkerpuppy` | idle, notice, chase, attack, die | none | Simplest beach lurker |
| `hopper` | idle, patrol, notice, chase, die | none | `use-proximity-notice #f` — only notices via `target-in-range?` (Jak must be on navmesh). Custom jump AI. `notice-distance` = 30m. |
| `kermit` | idle, notice, chase, attack, victory, die | none | Tongue joint controller, neck tracker. |
| `swamp-rat` | idle, notice, chase, attack, victory, die | none | Standard nav-enemy |
| `bonelurker` | nav-enemy states | none | Misty nav-enemy |
| `double-lurker` | nav-enemy states | none | Two stacked nav-enemy actors. Spawns `double-lurker-top` child. |
| `baby-spider` | nav-enemy states | none | Can be placed directly or spawned by `mother-spider` |
| `muse` | nav-enemy states | `path` lump optional | Works without path, patrols better with one |
| `snow-bunny` | idle, notice, chase, jump, die | **`path` required** | Errors "no path" if missing. `notice-distance` = 30m. |
| `starfish` | idle, patrol | none | Village1 nav-enemy. Place directly or spawned by `villa-starfish`. |

### Category B — process-drawable (custom AI, no navmesh, may need path)

These extend `process-drawable` and implement their own movement. **Do NOT patch entity.gc navmesh for these** — it will be ignored and wastes space.

| Entity | Behavior | Required lumps | Notes |
|---|---|---|---|
| `lurkerworm` | Stationary ambush. Idles underground, rises when Jak is close, strikes, sinks. | none | No path. Place with Y slightly below floor. |
| `junglesnake` | Stationary ambush. Sleeps, wakes when Jak nearby, tracks, attacks. | none | No path. Can be killed. |
| `quicksandlurker` | Stationary. Buries, pops up, fires missile projectiles at Jak. | none | No path. Place in flat area. |
| `bully` | Spins and charges using physics. No path. | none | **Idles until Jak is within 80m** (`idle-distance` default), then jumps and starts spinning. Does NOT damage Jak on idle contact — only damages during spin. Uses `nav-control` for wall bouncing, not navmesh. Do not add navmesh. |
| `swamp-bat` | Flies patrol paths, spawns slave bats. | **`path` AND `pathb` both required** | Two path lumps. `num-lurkers` sets slave count (default 6, range 2–8). Errors "need 2 paths" if either missing. |
| `puffer` | Patrols path, inflates/deflates, rams Jak. | **`path` required**, `notice-dist` optional, `distance` optional | Errors "no path". `notice-dist` controls AI activation range (default 57344 ≈ 14m). `distance` is a **two-float array** `[top_y_offset, bottom_y_offset]` for vertical patrol range (internal units, not meters). Uses `nav-control` not navmesh. |
| `flying-lurker` | Flies patrol path. | **`path` required** | Path defines flight route. |
| `driller-lurker` | Drills along path underground, pops up to attack. | **`path` required (min 2 verts)** | Errors "bad path" if fewer than 2 path points. |
| `gnawer` | Multi-segment worm travels along path. | **`path` required** | Multiple body segments. |
| `yeti` | Controller that spawns `yeti-slave` nav-enemy children at path points. | **`path` required** | `num-lurkers` = slave count (default = path vert count). `notice-dist` = spawn trigger (default 204800.0 = 50m). Does NOT chase Jak itself. |
| `balloonlurker` | Floats on path, drops bombs. | **`path` required** | `rigid-body-platform` subtype. |
| `villa-starfish` | Controller that spawns `starfish` nav-enemy children. | **`path` required**, `num-lurkers` optional | Spawns 1–8 starfish (default 3). Each starfish needs navmesh. |

### Category C — Decorative props (no combat, idle animation only)

**Do not expect these to attack or respond to Jak. They are animated set dressing.**

| Entity | What it does | Notes |
|---|---|---|
| `evilplant` | Plays looping idle animation only. | Defined in `village-obs.gc`. Has NO chase, NO attack, NO collision offense. Only has `idle` state. If you want a stationary plant-like attacker, use `junglesnake` instead. |
| `darkvine` | Animated jungle decoration | No AI |

---

## 7. Path Lump Format

Any entity that requires a `path` lump needs this in its JSONC actor entry:

```json
"path": ["vector4m", [x1, y1, z1, 1.0], [x2, y2, z2, 1.0], [x3, y3, z3, 1.0]]
```

Rules:
- Each point is a **nested array** `[x, y, z, w]` — flat values crash the builder
- `w` should always be `1.0`
- Minimum point counts: `snow-bunny` ≥ 1, `driller-lurker` ≥ 2, others ≥ 1
- `swamp-bat` needs **two** separate path entries: `"path"` and `"pathb"`

For `swamp-bat`:
```json
"path":  ["vector4m", [x1, y1, z1, 1.0], [x2, y2, z2, 1.0]],
"pathb": ["vector4m", [x3, y3, z3, 1.0], [x4, y4, z4, 1.0]]
```

---

## 8. Optional Lump Reference

| Lump | Type | Used by | Default | Notes |
|---|---|---|---|---|
| `num-lurkers` | int | swamp-bat, yeti, villa-starfish | 6 / path-vert-count / 3 | Child spawn count |
| `notice-dist` | float | puffer, yeti | 57344.0 / 204800.0 | Distance to trigger AI |
| `distance` | float[2] | puffer | none | Vertical patrol range: [top_y_offset, bottom_y_offset] in internal units |
| `alt-actor` | actor-ref | puffer | none | Links to buddy puffer |
| `height-info` | float | reflector-middle | 0.0 | Y offset for beam attach |

---

## 9. Waypoints — Must Not Be Exported as Actors

Waypoint empties in Blender are named `ACTOR_<etype>_<uid>_wp_00` etc.

**These must be filtered out of actor collection.** If `collect_actors` picks them up, each waypoint spawns as a separate enemy → crash on load.

**Filter rule:** skip any object whose name contains `_wp_` or `_wpb_`.

The JSONC actor count directly tells you if this is happening — you should see exactly 1 entry per enemy, regardless of how many waypoints it has.

---

## 10. Actor IDs (base_id) and AID Ordering

`base_id` in the JSONC sets the starting actor ID. The engine tracks entities globally across level loads.

- Default `100` is used by test-zone and many example levels — collides easily
- Use a unique `base_id` per level: `10000`, `20000` etc.
- Actor AIDs = `base_id + 1`, `base_id + 2`, ... assigned in **alphabetical order by Blender object name**
- Colliding IDs cause ghost entity spawns — old entities from a prior level load get resurrected

### AID ordering must be deterministic

The entity.gc navmesh patch keys each nav-mesh struct to a specific AID. If the actor list is built in a different order than the JSONC (which determines runtime AIDs), the wrong enemy gets the wrong navmesh and `target-in-range?` always returns false — the enemy idles forever.

**Fix:** both `collect_actors` and `_collect_navmesh_actors` must sort actors by Blender object name before assigning indices. This is `_canonical_actor_objects()` in the addon. Without this, Blender's arbitrary internal object order can cause AID mismatches between exports.

Example with `base_id = 10000`:
- `ACTOR_babak_0` → alphabetically first → idx=0 → AID 10001
- `ACTOR_hopper_0` → alphabetically second → idx=1 → AID 10002

---

## 11. NavMesh System

### Who needs a navmesh

Only **Category A** enemies (nav-enemy subclass) use the navmesh. Category B enemies (process-drawable) have their own movement and ignore it. Do not add navmesh for puffer, bully, swamp-bat, flying-lurker, driller-lurker, gnawer, etc.

### Why nav-mesh-sphere doesn't enable chase

`nav-mesh-sphere` is just a decoration on an existing nav-mesh. Without a real nav-mesh assigned via the entity.gc patch, `nav-mesh-connect` falls back to `*default-nav-mesh*` which is at `y = -200704.0` (49 meters underground). `is-in-mesh?` subtracts the mesh origin from Jak's position then checks bounds — Jak is always 250m above the underground mesh, so `target-in-range?` always returns false, the enemy never enters chase, and just idles indefinitely.

### How target-in-range? works

```lisp
(defmethod target-in-range? ((this nav-enemy) (arg0 float))
  (and *target*
       (not (logtest? (-> *target* state-flags) ...dying...))
       (nav-enemy-test-point-near-nav-mesh? (-> *target* control shadow-pos))))
```

`shadow-pos` is Jak's **ground contact point** (where his shadow touches the floor), not his trans position. `is-in-mesh?` checks if this point lies inside a polygon of the navmesh. This means:

- The navmesh must cover the area **where Jak walks**, not just where the enemy stands
- Jak must be standing on navmesh-covered ground for the enemy to notice him
- `notice-nav-radius` for hopper is only 1 meter — Jak must be solidly inside the mesh, not near the edge

### The real nav-mesh approach (what works)

The addon patches `engine/entity/entity.gc` to add `custom-nav-mesh-check-and-setup`, called from `birth!`. It checks the entity's AID and assigns a full nav-mesh struct before `nav-control` is constructed.

**Workflow:**
1. Create a flat mesh quad in Blender covering the full area where both the enemy AND Jak will walk
2. Select the enemy actor(s) + the navmesh quad (any order)
3. Click **Link NavMesh** in the addon
4. **Export & Compile** — the addon triangulates, computes BVH nodes/adjacency/routing, injects into entity.gc

The navmesh object is never exported to the GLB or DGO.

### nav-mesh-connect and the update-route-table crash

When `nav-control` is constructed (inside `init-defaults!` → `init-from-entity!`), it calls `nav-mesh-connect` which checks `user-list`. If `user-list` is zero, it calls `update-route-table` — which **writes to the static nav-mesh in read-only memory → crash**.

The entity.gc patch runs in `birth!` before `init-from-entity!`, so it sets `user-list` first. `nav-mesh-connect` then sees a non-zero `user-list` and skips `update-route-table`. This is why the patch must run in `birth!` and not later.

### Critical nav-mesh fields — all required

```lisp
(new 'static 'nav-mesh
  :bounds  (new 'static 'sphere ...)
  :origin  (new 'static 'vector ...)
  :node-count N
  :nodes   (new 'static 'inline-array nav-node N ...)  ; REQUIRED — null crashes find-poly-fast
  :vertex-count V
  :vertex  (new 'static 'inline-array nav-vertex V ...)
  :poly-count P
  :poly    (new 'static 'inline-array nav-poly P ...)
  :route   (new 'static 'inline-array vector4ub R ...)
)
```

`find-poly-fast` (called every frame during chase) dereferences `mesh.nodes[0]`. If `nodes` is null → address 0 dereference → crash. The crash appears after the enemy enters chase state, a second or two after it first notices Jak.

### nav-node structure (leaf)

```lisp
(new 'static 'nav-node
  :center-x (meters cx) :center-y (meters cy) :center-z (meters cz)
  :type #x1              ; #x1 = leaf node
  :parent-offset #x0
  :radius-x (meters rx) :radius-y (meters ry) :radius-z (meters rz)
  :num-tris N
  :first-tris (new 'static 'array uint8 4 #x0 #x1 ...)  ; poly indices 0-3
  :last-tris  (new 'static 'array uint8 4 #x0 #x0 ...)  ; poly indices 4-7
)
```

### Route table format

2-bit-per-entry NxN matrix (N = poly count):
- `route[from][to]` = adjacency slot (0, 1, or 2) to take from poly `from` toward poly `to`, or `3` = no route
- Bit index: `(from * poly_count + to) * 2`
- Array size: `ceil(poly_count² * 2 / 32)` vector4ub entries

### adj-poly values

Each nav-poly has 3 adjacency slots (one per edge):
- `#xff` = boundary (no neighbor)
- `#x0`, `#x1`, etc. = index of the neighboring poly

### Flags that must NOT be used

- `:custom-hacky? #t` — Rockpool-only field, compile error on vanilla OpenGOAL
- Do not call `entity-nav-login` on static nav-meshes — calls `update-route-table` → crash

---

## 12. entity.gc Patching

The addon patches `engine/entity/entity.gc` to inject nav-mesh setup. The patch:

1. Adds `(defun custom-nav-mesh-check-and-setup ...)` keyed by actor AID before `birth!`
2. Adds a call `(custom-nav-mesh-check-and-setup this)` at the top of `(defmethod birth! entity-actor ...)`
3. Is idempotent — strips old injected block before re-injecting, safe to re-export
4. Only needed for Category A enemies (nav-enemy). Do not add for Category B.

**Binary read/write required on Windows.** Python's text-mode `read_text`/`write_text` converts `\r\n` → `\n` → `\r\n`, producing mixed line endings in the injected block that crash the GOAL compiler. Use `read_bytes`/`write_bytes`.

**`custom-nav-mesh-check-and-setup` is not in vanilla OpenGOAL** — it's a Rockpool addition. The addon adds it from scratch.

---

## 13. Compiler / game.gp Patterns

### user.gc — safe declarations only

Do NOT declare externs for types not loaded at compile time:
```lisp
;; SAFE:
(define-extern bg (function symbol int))
(define-extern *artist-all-visible* symbol)

;; UNSAFE — game-info type not loaded yet:
;; (define-extern set-continue! (function game-info object object))
```

### game.gp strip regex — must use plain quotes

```python
# CORRECT:
re.sub(r'\(goal-src "levels/' + name + r'/[^"]+"[^)]*\)\n', '', txt)

# WRONG — \" never matches, leaves duplicate entries:
re.sub(r'\(goal-src "levels/' + name + r'/[^"]+\"[^)]*\)\n', '', txt)
```

---

## 14. GOAL Hex Literal Format

GOAL uses `#x` prefix, not `0x`:

```lisp
#x0    ; correct
#xff   ; correct
0x1    ; WRONG — compile error
```

Python's `hex()` returns `"0x..."`. Use `f"#x{n:x}"` instead.

---

## 15. Healthy DGO Load Log

```
Got DGO file header for MYL.DGO with N objects
link finish: my-level-obs
link finish: tpage-398
...
link finish: tpage-212
link finish: tpage-213
link finish: tpage-214
link finish: tpage-215
link finish: babak-ag       ← art group MUST appear here
link finish: babak          ← enemy code (from GAME.CGO, re-linked)
link finish: my-level
```

**Red flags:**
- Missing `link finish: babak-ag` → art group not in DGO → null skeleton → crash on draw
- `babak-ag` only appears during BEA.DGO load, not your DGO → duplicate-link bug → use `(bg)` not `(bg-custom)`
- More babak actors than enemies in scene → waypoint filter missing
- DGO load stops mid-tpage with `kmalloc: !alloc mem data-segment` → too many source levels, OOM
- `ERROR<GMJ>: tracking spline used count N actual M` → harmless nav bookkeeping warning

---

## 16. Sanity Checklist Before Building

- [ ] Actor `trans` has exactly 3 elements
- [ ] Ambient `trans` has exactly 4 elements
- [ ] All `bsphere` entries have 4 elements, radius ≤ 20
- [ ] All `vector4m` lump entries use nested arrays
- [ ] `base_id` is unique per level (≥ 5000)
- [ ] No waypoint objects (`_wp_`, `_wpb_`) exported as actors
- [ ] Entities from ≤ 2 source levels (heap OOM risk with more)
- [ ] `.gd` has entity tpages before art groups, numbers match game.gp exactly
- [ ] Art group appears in DGO link-finish log
- [ ] Using `(bg 'level-vis)` not `(bg-custom ...)`
- [ ] Category A enemies have navmesh linked and AID correctly assigned
- [ ] Navmesh covers the area where Jak walks, not just the enemy position
- [ ] Category B enemies do NOT have navmesh (bully, puffer, swamp-bat, flying-lurker, driller-lurker, gnawer, etc.)
- [ ] Actor ordering is alphabetical by Blender object name (both collect_actors and navmesh AID assignment)
- [ ] Path-requiring enemies have `path` lump (snow-bunny, flying-lurker, driller-lurker, gnawer, puffer, yeti, balloonlurker)
- [ ] swamp-bat has BOTH `path` and `pathb` lumps
- [ ] driller-lurker path has at least 2 points
- [ ] No `:custom-hacky? #t` in nav-mesh struct
- [ ] No call to `entity-nav-login` on static nav-mesh
- [ ] Nav-mesh includes `:nodes` inline-array (crash if missing)
- [ ] evilplant is a prop — no combat, no attack. Use `junglesnake` for stationary ambush instead.
- [ ] bully will idle until Jak is within 80m — this is correct behavior, not a bug

---

## 17. Enemy Compatibility Status (live testing results)

Results from testing in `april-2026` custom level. Updated as tests are run.

### ✅ Confirmed Working
| Enemy | Type | Tpage Group | Notes |
|---|---|---|---|
| `babak` | nav-enemy | Beach | Reference case. Chases + attacks with navmesh. |
| `lurkercrab` | process-drawable | Beach | Works. Stationary ambush. |
| `lurkerpuppy` | nav-enemy | Beach | Works. Needs navmesh for chase. |
| `lurkerworm` | process-drawable | Beach | Stationary ambush, no path needed. |
| `hopper` | nav-enemy | Jungle | Chases + attacks with navmesh. |
| `junglesnake` | process-drawable | Jungle | Stationary ambush, no path needed. |
| `swamp-rat` | nav-enemy | Swamp | Works. Needs navmesh for chase. |
| `swamp-bat` | process-drawable | Swamp | Works. Needs both `path` and `pathb`. |
| `kermit` | nav-enemy | Swamp | **Works with caveat** — must be placed slightly above floor level (Y+) or fails to spawn. Once spawned correctly, chases and attacks. Waypoint following unconfirmed. Needs navmesh for chase. |
| `snow-bunny` | nav-enemy | Snow | Works. Needs navmesh + path lump (errors without path). |
| `yeti` | process-drawable | Snow | Works. Needs path (defines spawn points for yeti-slave children). |
| `bully` | process-drawable | Sunken A | Works. No navmesh needed. Idles until Jak within 80m, then spins. |
| `puffer` | process-drawable | Sunken A | **Partially works** — spawns and activates, but does not follow path points correctly. Passes through walls. Uses `nav-control` for movement not navmesh, but path following appears broken. Avoid until investigated. |
| `double-lurker` | process-drawable | Sunken A | **Unreliable** — spawned once then immediately despawned; failed to spawn on subsequent loads. Root cause unknown. Moved to partial/issues. |
| `flying-lurker` | process-drawable | Ogre | Needs path. Patrols correctly. |
| `quicksandlurker` | process-drawable | Misty | Works. Stationary, no path needed. |
| `muse` | nav-enemy | Misty | Works. Needs navmesh for chase. |
| `bonelurker` | nav-enemy | Misty | **Cannot be entity-spawned.** Source confirmed: `bonelurker.gc` has no `init-from-entity!` method. It is exclusively spawned programmatically by `misty-battlecontroller`. Placing a `ACTOR_bonelurker_*` empty does nothing — the engine finds no init handler. Remove from ENTITY_DEFS spawn picker. |
| `balloonlurker` | process-drawable | Misty | Works. Needs `path` lump. |

### ⚠️ Partial / Known Issues
| Enemy | Type | Status | Notes |
|---|---|---|---|
| `baby-spider` | nav-enemy | Spawns but idles, no chase/collision | Nav-enemy without navmesh — needs entity.gc navmesh patch to activate. Spawning itself works. |
| `plunger-lurker` | process-drawable | Idles only, no player interaction | **Task-gated**: `init-from-entity!` checks `(get-task-status (game-task plunger-lurker-hit))` — if task is `invalid` (never completed), immediately goes to `plunger-lurker-die` and deactivates. If task is active/completed, goes to `plunger-lurker-idle` which DOES trigger on proximity (`distance² < 6710886400` = ~81m). Needs game task to be set to make it activate. |
| `cavecrusher` | process-drawable | Idles only, collision but no attack | `cavecrusher-idle` only has one state. The `:event` handler responds to `'touch`/`'attack` with `deadlyup` knockback — but only if Jak's collision shape triggers it. In the maincave level it moves on a scripted path triggered by a `maincavecam` entity. Without that camera/trigger setup it just idles. It is a **set-piece obstacle**, not a free-roaming enemy. |
| `gnawer` | process-drawable | Partially works | Animates, damages Jak, travels path. Spawns slightly off-position and path-following causes circular motion rather than clean point-to-point. Functional for use but path tuning needed. |
| `swamp-bat` | process-drawable | Swamp | Works when both paths are present. Errors "need 2 paths" if either `path` or `pathb` is missing or empty. num-lurkers sets slave bats (2–8, default 6). Previously listed as broken — re-check with explicit pathb lump. |
| `mother-spider` | process-drawable | Broken — does not spawn children | Loads but does not spawn `baby-spider` children. Root cause unknown — may be task-gated or require a `spider-vent` actor to function. Do not use until investigated. |
| `dark-crystal` | process-drawable | Decorative only | Spawns and displays animated texture correctly. No collision, no behaviour, no AI. Usable purely as a visual prop. |
| `double-lurker` | process-drawable | Unreliable — spawns then immediately despawns | Observed spawning once then vanishing instantly. Did not spawn at all on subsequent loads. Cause unknown — may be a missing `double-lurker-top` art group issue or AID conflict. Moved from confirmed working. |
| `puffer` | process-drawable | Path following unreliable | Spawns and activates. `distance` lump = two-float vertical patrol range (top_y_offset, bottom_y_offset in internal units). Path following appears broken in custom levels — puffer ignores path points and passes through geometry. Underlying issue: uses nav-control for movement, which may not initialize correctly without a full nav-mesh environment. |
| `fireboulder` | process-drawable | Decorative only | Spawns with no collision and no behaviour. Likely scripted/triggered in vanilla and not self-activating. |
| `green-eco-lurker` | nav-enemy | Spawns but no interaction | Idles, no collision, does not react to player. Likely needs navmesh patch to activate — untested with navmesh. |
| `ram` | process-drawable | Untested | `ram` extends `process-drawable` (not nav-enemy). Reads `extra-id` (int, instance index) and `mode` (uint, state variant). Self-contained movement — no waypoints or navmesh. Confirm spawns correctly before using in custom level. `ram-boss` is a completely separate type (nav-enemy) — do not confuse the two. |
| `lightning-mole` / `peeper` | fleeing-nav-enemy | Untested with navmesh | `lightning-mole` extends `fleeing-nav-enemy` (a nav-enemy subclass). Has a proper `init-from-entity!`. Should work with navmesh. `peeper` is an alias using the same art group. No path required — uses flee AI. Test with navmesh before shipping. |

### 🔲 Untested
| Enemy | Group | Notes |
|---|---|---|
| `cavecrusher` (fully) | Robocave | Needs `maincavecam` trigger setup |

### ❌ Known Broken / Not Viable for Custom Levels
| Enemy | Type | Status | Notes |
|---|---|---|---|
| `driller-lurker` | process-drawable | **Hard crash on level load** | Game crashes immediately when level loads. Path lump present with ≥ 2 points. Root cause unknown — may be a code init issue or tpage conflict. Do not use. |

---

## 18. Tpage Group Budget — Safe Combinations

The level kheap has ~4MB free during load. Each tpage set is ~200–250KB.
Village1 sky tpages (398, 400, 399, 401, 1470) are always loaded and count toward the budget.
**Safe rule: max 2 enemy source-level tpage sets per scene.**

| Group | Enemies |
|---|---|
| Beach | babak, lurkercrab, lurkerpuppy, lurkerworm |
| Jungle | hopper, junglesnake |
| Swamp | kermit, swamp-bat, swamp-rat |
| Snow | yeti, snow-bunny |
| Sunken A | bully, double-lurker, puffer |
| Ogre | flying-lurker, plunger-lurker |
| Maincave | baby-spider, mother-spider, gnawer, driller-lurker, dark-crystal |
| Robocave | cavecrusher |
| Misty | quicksandlurker, muse, bonelurker, balloonlurker |
| Village1 | evilplant (always loaded — free) |

Mixing 3+ groups in one scene causes `kmalloc: !alloc mem data-segment` crash mid-DGO-load.

---

## 11. Full Actor Coverage — April 2026 Update
_Updated after feature/lumps session. Addon now supports 147 actor types._

### 11.1 Types always in GAME.CGO (no .o injection needed)

These are compiled into the always-loaded game executable. Art groups still need tpages in your DGO.

| Type | Code source | Art needed |
|---|---|---|
| `babak` | `common-obs/babak.gc` | babak-ag + BEACH_TPAGES |
| `sharkey` | `common-obs/sharkey.gc` | sharkey-ag + SWAMP_TPAGES |
| `plat` | `common-obs/plat.gc` | plat-ag |
| `plat-button` | `common-obs/plat-button.gc` | plat-button-ag |
| `plat-eco` | `common-obs/plat-eco.gc` | plat-eco-ag |
| `ropebridge` | `common-obs/ropebridge.gc` | variant-selected by art-name lump |
| `eco-door` | `common-obs/baseplat.gc` | eco-door-ag |
| `warp-gate` | `common-obs/basebutton.gc` | warp-gate-ag |
| `swingpole` | `common-obs/generic-obs.gc` | none (invisible) |
| `water-vol` | `engine/common-obs/water.gc` | none |
| `fuel-cell`, `money`, `buzzer` | `common-obs/collectables.gc` | art in game.gd tpages |
| `crate` | `common-obs/crates.gc` | crate-ag |
| `orb-cache-top` | `common-obs/orb-cache.gc` | orb-cache-top-ag |
| `eco-pill`, `ecovent`, `ventblue`, `ventred`, `ventyellow` | `common-obs/collectables.gc` | vent art |
| `ecovalve` | `common-obs/baseplat.gc` | ecovalve-ag (in game.gd) |

### 11.2 DGO tpage group constants

All constants defined in the addon. HEAP WARNING: each tpage set costs ~200–250KB. Max ~2 groups per scene safely.

| Constant | DGO | Representative actors |
|---|---|---|
| `BEACH_TPAGES` | bea.gd | babak, lurkercrab, lurkerpuppy, lurkerworm, sculptor, pelican, seagull, windmill-one, ecoventrock |
| `JUNGLE_TPAGES` | jun.gd | hopper, junglesnake, darkvine, junglefish, springbox, fisher, accordian, ropebridge |
| `SWAMP_TPAGES` | swa.gd | kermit, swamp-bat, swamp-rat, sharkey, swamp-rat-nest, swampgate, balance-plat, tar-plat, swamp-rock, swamp-spike, billy, flutflut |
| `SNOW_TPAGES` | sno.gd | yeti, snow-bunny, ice-cube, ram |
| `SUNKEN_TPAGES` | sun.gd | bully, double-lurker, puffer, sunkenfisha, orbit-plat, square-platform, shover, launcher, side-to-side-plat, wall-plat, wedge-plat, steam-cap, whirlpool |
| `SUB_TPAGES` | sub.gd | (sunken city B) |
| `CAVE_TPAGES` | mai.gd | baby-spider, mother-spider, gnawer, driller-lurker, dark-crystal, cavecrusher, caveelevator, caveflamepots, cavetrapdoor, cavespatula, cavespatulatwo |
| `DARK_TPAGES` | dar.gd | cavecrystal |
| `ROBOCAVE_TPAGES` | rob.gd | cave-trap, spider-egg, spider-vent |
| `MISTY_TPAGES` | mis.gd | quicksandlurker, muse, bonelurker, balloonlurker, mis-bone-bridge, breakaway-left/mid/right, windturbine, boatpaddle, teetertotter |
| `OGRE_TPAGES` | ogr.gd | flying-lurker, plunger-lurker, ogreboss, ogre-bridge, ogre-bridgeend, tntbarrel, shortcut-boulder |
| `LAVATUBE_TPAGES` | lav.gd | lavafall, lavafallsewera/b, lavabase, lavayellowtarp, chainmine, lavaballoon, darkecobarrel |
| `FIRECANYON_TPAGES` | fic.gd | balloon, crate-darkeco-cluster, spike |
| `VILLAGE1_TPAGES` | vi1.gd | farmer, mayor, yakow, explorer, oracle, fishermans-boat, revcycle, evilplant |
| `VILLAGE2_TPAGES` | vi2.gd | gambler, geologist, warrior, fireboulder, warpgate, pontoon, swamp-blimp, swamp-rope, swamp-tetherrock, ceilingflag |
| `VILLAGE3_TPAGES` | vi3.gd | minershort, minertall, cavegem, gondola |
| `ROLLING_TPAGES` | rol.gd | peeper (lightning-mole), robber, dark-plant, lightning-mole |
| `TRAINING_TPAGES` | tra.gd | tra-pontoon |
| `JUNGLEB_TPAGES` | jub.gd | plant-boss, plat-flip |
| `FINALBOSS_TPAGES` | fin.gd | robotboss, green-eco-lurker, ecoclaw, powercellalt |
| `CITADEL_TPAGES` | cit.gd | (citadel actors) |

### 11.3 Entity link system (alt-actor, water-actor, state-actor)

Many actors reference other actors at runtime via `entity-actor-lookup`. The addon's **Entity Links** sub-panel handles these. Links are stored as string arrays: `"alt-actor": ["string", "target-name-0", "target-name-1"]`.

The engine resolves strings via `entity-by-name` — no index arithmetic needed.

**Actors with required links (must be set or they hang/crash):**

| Actor | Slot | Target type | Notes |
|---|---|---|---|
| `orbit-plat` | `alt-actor 0` | any | Center entity to orbit. Platform waits forever if unset. |
| `ogre-bridge` | `alt-actor 0` | `ogre-bridgeend` | Bridge end piece. |
| `snow-log` | `alt-actor 0` | snow-log-master | Master controller. |
| `snow-log-button` | `alt-actor 0` | `snow-log` | Log to activate. |
| `helix-water` | `alt-actor 0` | `helix-button` | First button (required); 1–3 more optional. |
| `helix-button` | `alt-actor 0,1` | `helix-water`, `helix-slide-door` | Both required. |
| `minershort` | `alt-actor 0` | `minertall` | Partner miner. |

**Actors with optional links:**

| Actor | Slot | Effect if unset |
|---|---|---|
| `quicksandlurker` | `water-actor 0` | No mud surface tracking (still works) |
| `balloonlurker` | `water-actor 0` | No water animation reference |
| `spider-egg` | `alt-actor 0` | No notify message on hatch |
| `cave-trap` | `alt-actor 0–3` | No spider-egg children to spawn |
| `square-platform` | `alt-actor 0` | No water splash effects |
| `eco-door` | `state-actor 0` | Door not locked to any task |
| `ecovent/ventblue/ventred/ventyellow` | `alt-actor 0` | Vent always active (not blocked) |
| `pontoon` | (none — `alt-task` is a lump, not a link) | — |

### 11.4 New actors added — quick reference

**Enemies:** balloonlurker, darkvine, junglefish, peeper, cave-trap, spider-egg, spider-vent, swamp-rat-nest, sunkenfisha, sharkey, villa-starfish, baby-spider, cavecrusher, dark-crystal, mother-spider, fireboulder, green-eco-lurker, ice-cube, lightning-mole, plunger-lurker, ram

**NPCs:** oracle, minershort, minertall, pelican, robber, seagull

**Pickups:** eco-pill, ecovent, ventblue, ventred, ventyellow, ecoventrock

**Platforms:** orbit-plat, square-platform, ropebridge, lavaballoon, darkecobarrel, caveelevator, caveflamepots, cavetrapdoor, cavespatula, cavespatulatwo, ogre-bridge, ogre-bridgeend, pontoon, tra-pontoon, mis-bone-bridge, breakaway-left/mid/right, plat-flip, side-to-side-plat, wall-plat, wedge-plat, tar-plat, balance-plat, teetertotter, revcycle, launcher

> **Note:** `warpgate` (`deftype warpgate (process-hidden) ()`) is NOT entity-spawnable. It must be removed from ENTITY_DEFS. The warp-gate visual is purely a scripted cinematic prop in vanilla.

**Objects:** water-vol, swingpole, springbox, eco-door, launcherdoor, shover, swampgate, ceilingflag, windturbine, boatpaddle, accordian, all lava props, balloon, crate-darkeco-cluster, swamp-tetherrock, fishermans-boat, cavecrystal, cavegem, ecoclaw, gondola, shortcut-boulder, spike, steam-cap, swamp-blimp, swamp-rock, swamp-rope, swamp-spike, tntbarrel, whirlpool, windmill-one

**Props:** dark-plant, evilplant

**Bosses:** ogreboss, plant-boss, robotboss


---

## 12. Source-Verified Lump Data — Objects Without Addon Panels

*Confirmed from `goal_src/jak1` source, April 2026. All defaults in internal units unless noted.*

### Platforms needing settings panels

| Entity | Lumps read | Notes |
|---|---|---|
| `balance-plat` | `distance` float default 20480 (5m), `scale-factor` float default 1.0 | `distance` = max Y travel from rest. `scale-factor` scales responsiveness. Same reads as `tar-plat`. |
| `tar-plat` | `distance` float default 20480 (5m), `scale-factor` float default 1.0 | Identical lump reads to `balance-plat`. |
| `wedge-plat` | `rotspeed` float, `rotoffset` float, `distance` float default 36864 (9m) | Two variant init paths with different distance defaults (36864 and 69632). |
| `wall-plat` | `tunemeters` float | Adjusts Z-depth of wall platform. No default — omit lump to use art default. |
| `cavetrapdoor` | `delay` float (sec), `shove` float default 8192 (2m), `rotoffset` float, `cycle-speed` float[3], `mode` uint | `delay` = seconds before wiggle starts. `shove` = upward launch force. `mode` changes behavior variant. |
| `plat-eco` | `notice-dist` float default -1.0 | -1.0 means "use engine default notice system". Set explicitly to override. |

### Platforms confirmed NO extra lumps needed

| Entity | Reason |
|---|---|
| `side-to-side-plat` | Extends `plat` — inherits `sync` lump. No own lump reads. |
| `revcycle` | No `res-lump` reads at all. Pure visual prop. |
| `teetertotter` | No `res-lump` reads at all. Physics-driven, no config. |
| `swampgate` | Reads only `entity-perm-status`. No lump config needed. |

### Objects confirmed NO extra lumps needed

| Entity | Reason |
|---|---|
| `accordian` | Reads `alt-actor` (via entity-actor-lookup, not res-lump) and `perm-status`. No res-lump calls. |

### Entities that must be REMOVED from ENTITY_DEFS

| Entity | Reason |
|---|---|
| `warpgate` | `(deftype warpgate (process-hidden) ())` — process-hidden, no init-from-entity. Never entity-spawnable. |
| `bonelurker` | No `init-from-entity!` anywhere in source. Only spawned by `misty-battlecontroller`. Placing an entity-actor crashes silently. |

### Entities with wrong category in ENTITY_DEFS

| Entity | Current category | Correct category | Notes |
|---|---|---|---|
| `ram` | Enemies | Objects/Props | Extends `process-drawable` not nav-enemy. Reads `extra-id` (instance index) and `mode` (state variant). Self-contained, no waypoints. |

### Missing entity: `battlecontroller`

The `battlecontroller` type (`common/battlecontroller.gc`) is entirely absent from the addon but is the primary mechanism for multi-wave enemy encounters.

**Lumps read from source:**
- `camera-name` — ResString: camera entity to activate during wave
- `pathspawn` — ResVector (vector4m, multi-point): enemy spawn positions
- `delay` — ResFloat: seconds between spawn waves
- `num-lurkers` — ResInt32: total enemies in this controller
- `lurker-type` — ResType array: enemy type(s) to spawn (e.g. `["type", "babak", "hopper"]`)
- `percent` — ResFloat array: spawn probability per type (parallel to `lurker-type`)
- `final-pickup` — ResUint32 (pickup-type enum): reward after all waves cleared (default = fuel-cell)
- `pickup-type` / `max-pickup-count` / `pickup-percent` — per-creature-type pickup overrides
- `mode` — ResUint32: `1` = prespawn mode

**Subclasses in vanilla:** `misty-battlecontroller`, `swamp-battlecontroller`, `citb-battlecontroller`. All extend `battlecontroller` with custom intro cameras and wave sequences. For custom levels, the base `battlecontroller` type works directly.


---

## 13. Source-Verified Engine Behaviors (goal_src deep dive, April 2026)

### battlecontroller spawned enemies inherit the controller's entity for lump lookups

Confirmed from `nav-enemy-init-by-other` in `nav-enemy.gc`:

```lisp
(set! (-> self entity) (-> arg0 entity))  ; arg0 = battlecontroller instance
```

When battlecontroller spawns a wave enemy it sets the enemy's `entity` pointer to the **controller's own entity-actor**. This means every lump lookup the enemy does during its lifetime (`idle-distance`, `vis-dist`, `nav-mesh-sphere`, etc.) reads from the battlecontroller's lump dict, not a separate entity.

**Practical implication for addon:** You do not need separate lump entries per enemy type in a wave encounter. Put `idle-distance`, `vis-dist`, and any shared enemy config directly on the `battlecontroller` actor — all spawned enemies in that wave will read those values. The only per-type config is via `lurker-type`/`percent` arrays on the controller itself.

---

### one-shot ambient sounds broken in custom levels (source confirmed)

`birth-ambient!` in `ambient.gc` (line 609) uses `'exact 0.0` lookup for `effect-name` and `effect-param` when initialising one-shot sounds (cycle-speed < 0):

```lisp
(let ((s5-1 (-> ((method-of-type res-lump lookup-tag-idx) this 'effect-name 'exact 0.0) lo)))
(let ((v1-28 ((method-of-type res-lump lookup-tag-idx) this 'effect-param 'exact 0.0)))
```

Custom level lumps are stored at key-frame `-1e9`. `'exact 0.0` never matches → entity falls back to `ambient-type-error` silently. The loop path (cycle-speed ≥ 0) works because `res-lump-struct` uses `'interp` internally.

**Fix:** Same pattern as the vol-h.gc patch — change `'exact` to `'base` on both lines. Two-line change in `ambient.gc`.

**Also affected:** `ambient-type-light` (line 481), `ambient-type-dark` (line 507), `ambient-type-weather-off` (line 533) — all use `'exact 0.0` to look up `'vol` planes. Custom mood-light/dark ambients would never find their vol data.

---

### idle-distance is NOT a lump — the addon panel is a no-op

`idle-distance` lives in the static `nav-enemy-info` struct (e.g. `*babak-nav-enemy-info*`), hardcoded per enemy type. There is no lump path that overrides it at the entity level. The addon's "Idle Distance (m)" panel writes an `og_idle_distance` custom prop and emits an `idle-distance` lump — but nothing in the engine reads that lump.

**Fix options:**
1. Remove the idle-distance panel entirely (honest)
2. Implement a proper per-instance override in GOAL code injected via obs.gc — override `nav-enemy-method-48` on the specific type to read `res-lump-float 'idle-distance` and store it into `enemy-info`

**Affected enemies:** All nav-enemies using the panel (babak, lurkercrab, lurkerpuppy, hopper, etc.)

---

### ambient collect radius is always spherical — shape doesn't matter

`collect-ambients` in `ambient.gc` uses only `spheres-overlap?` against the ambient's bsphere. The ambient emitter object's mesh shape, scale, or rotation has zero effect on when it activates. Only the bsphere radius matters. The `vol` lump on light/dark/weather-off ambients controls zone-of-effect *after* activation, not activation itself.

**Practical implication:** For sound emitters, the visual object shape in Blender is irrelevant. Only the bsphere radius (exported from the object's bounding sphere) controls activation distance. This is already correct behavior in the addon — but worth documenting so users don't try to shape sound zones with mesh geometry.

---

## 14. Runtime Entity State Manipulation via perm-status

### process-entity-status! — toggle any perm-status bit on a live entity

```lisp
(defun process-entity-status! ((arg0 process) (arg1 entity-perm-status) (arg2 symbol)) ...)
; arg2 = #t to set, #f to clear
```

Source: `entity.gc:1167`. Works on any process that owns its entity (`(-> arg0 entity extra process) = arg0`).

**entity-perm-status bit reference** (from `process-drawable-h.gc`):

| Bit | Name | Practical meaning |
|---|---|---|
| 6 | `complete` | Entity spawns in completed state (door open, crate already gone) |
| 8 | `real-complete` | Marks entity permanently done in perm table across level reloads |
| 2 | `dead` | Entity is dead / permanently removed |

### Use from startup.gc injection

To pre-complete a named entity when the level loads:

```lisp
; In startup.gc — runs once at level load via (start 'play (get-current-continue-point))
(let ((e (entity-by-name "eco-door-0")))
  (when (and e (-> e extra process))
    (process-entity-status! (-> e extra process) (entity-perm-status complete) #t)))
```

**Requirement:** The target entity's process must already be alive when this runs. Entities birth over multiple frames after level load — run this in a delayed coroutine or use `entity-by-name` polling if timing is an issue.

**Use cases:**
- Make specific eco-doors spawn open without requiring blue eco or a game-task
- Permanently remove a crate from a scene (set `real-complete`)
- Force an oracle to show its "reward already given" state
- Any door, switch, or collectible whose initial state depends on task completion

### Setting perm-status at spawn time (JSONC)

Alternatively, set `complete` before the level even loads via the `perm-status` lump (int32, value 64 = bit 6):

```json
"lump": {
  "perm-status": ["int32", 64]
}
```

This makes the entity spawn in its completed state from frame 1, with no GOAL code needed. Confirmed working for eco-door (spawns open). Value 256 = `real-complete` (bit 8).


---

## 15. Bypassing Entity Vis-Culling (force-actors)

### The problem

By default, entities only birth when their `vis-id` passes an AABB visibility test against the camera frustum. For custom levels with `vis-id = 0`, this check can produce unpredictable results — some entities don't birth even when the player is standing next to them.

### The bypass: `force-actors?` in the PC settings file

In `goal_src/jak1/engine/entity/entity.gc` the activation check is:

```lisp
(or (with-pc (not (-> *pc-settings* ps2-actor-vis?)))
    (is-object-visible? s4-2 (-> sv-32 vis-id)))
```

When `ps2-actor-vis?` is `#f`, the vis check is skipped entirely — ALL entities birth unconditionally regardless of vis-id.

`ps2-actor-vis?` is controlled by `force-actors?` in the PC settings file (the setting is stored as its logical inverse):

```lisp
; from pckernel-common.gc
((\"force-actors?\") (set! (-> obj ps2-actor-vis?) (not (file-stream-read-symbol file))))
```

**To disable vis-culling for all custom levels:**

Add or edit this line in the OpenGOAL settings file (`OpenGOAL/settings/jak1/pc-settings.gs`):
```
(force-actors? #t)
```

This is a user-accessible setting requiring no code changes, no recompile. It persists across sessions. The game's own debug menu has a "PS2 Actor vis" toggle for the same thing.

**Default:** `ps2-actor-vis? = #t` (culling on). The addon should recommend users enable `force-actors?` in its getting-started docs.

**Caveat:** Speedrunner mode forces `ps2-actor-vis? = #t` for PS2 accuracy parity. Custom level runners may need to disable speedrunner mode.

---

## 16. `actor-pause` Mask — Per-Entity AI Distance Control

`run-logic?` in `process-drawable.gc` returns `#f` (pausing all AI/logic) when:
- `actor-pause` is set in the entity's process mask, **AND**
- entity is beyond `*ACTOR-bank*.pause-dist` + `root.pause-adjust-distance` from camera

`process-drawable-from-entity!` sets `actor-pause` on every entity at spawn time. It can be cleared in `init-from-entity!`:

```lisp
(logclear! (-> this mask) (process-mask actor-pause))
```

**Practical use:** Entities with `actor-pause` cleared run their full AI loop at any distance — no distance-based LOD pause. Useful for:
- Enemies that need to be active and patrolling before Jak arrives
- Platform timers that must stay in sync regardless of camera distance
- Any entity whose state machine must not pause at range

Custom GOAL code in `obs.gc` can clear this flag in the `init-from-entity!` override for specific actor types.

**Note:** `pause-adjust-distance` is a per-entity float (`root.pause-adjust-distance`) that extends the pause threshold for individual entities without clearing the flag entirely.

