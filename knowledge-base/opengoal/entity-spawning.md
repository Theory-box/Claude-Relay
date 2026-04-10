# Jak 1 Custom Level — Entity Spawning & NavMesh Reference
*Everything learned the hard way. Every rule here cost a crash to discover.*
*Last updated: April 2026. Tpage numbers verified against game.gp copy-textures calls.*

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
| `puffer` | Patrols path, inflates/deflates, rams Jak. | **`path` required**, `alt-actor` optional, `notice-dist` optional | Errors "no path". `alt-actor` links buddy puffer. `notice-dist` default = 57344.0 (14m). Uses `nav-control` not navmesh. |
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
| `kermit` | nav-enemy | Swamp | Works. Needs navmesh for chase. |
| `snow-bunny` | nav-enemy | Snow | Works. Needs navmesh + path lump (errors without path). |
| `yeti` | process-drawable | Snow | Works. Needs path (defines spawn points for yeti-slave children). |
| `bully` | process-drawable | Sunken A | Works. No navmesh needed. Idles until Jak within 80m, then spins. |
| `puffer` | process-drawable | Sunken A | Works. Needs `path` lump. |
| `double-lurker` | process-drawable | Sunken A | Works. Spawns `double-lurker-top` child automatically. |
| `flying-lurker` | process-drawable | Ogre | Needs path. Patrols correctly. |
| `quicksandlurker` | process-drawable | Misty | Works. Stationary, no path needed. |
| `muse` | nav-enemy | Misty | Works. Needs navmesh for chase. |
| `bonelurker` | nav-enemy | Misty | Works. Needs navmesh for chase. Needs bonelurker.o in DGO. |
| `balloonlurker` | process-drawable | Misty | Works. Needs `path` lump. |

### ⚠️ Partial / Known Issues
| Enemy | Type | Status | Notes |
|---|---|---|---|
| `baby-spider` | nav-enemy | Spawns but idles, no chase/collision | Nav-enemy without navmesh — needs entity.gc navmesh patch to activate. Spawning itself works. |
| `plunger-lurker` | process-drawable | Idles only, no player interaction | **Task-gated**: `init-from-entity!` checks `(get-task-status (game-task plunger-lurker-hit))` — if task is `invalid` (never completed), immediately goes to `plunger-lurker-die` and deactivates. If task is active/completed, goes to `plunger-lurker-idle` which DOES trigger on proximity (`distance² < 6710886400` = ~81m). Needs game task to be set to make it activate. |
| `cavecrusher` | process-drawable | Idles only, collision but no attack | `cavecrusher-idle` only has one state. The `:event` handler responds to `'touch`/`'attack` with `deadlyup` knockback — but only if Jak's collision shape triggers it. In the maincave level it moves on a scripted path triggered by a `maincavecam` entity. Without that camera/trigger setup it just idles. It is a **set-piece obstacle**, not a free-roaming enemy. |

### 🔲 Untested
| Enemy | Group | Notes |
|---|---|---|
| `gnawer` | Maincave | Needs path |
| `driller-lurker` | Maincave | Needs path (min 2 points) |
| `dark-crystal` | Maincave | Unknown trigger requirements |
| `mother-spider` | Maincave | Spawns baby-spider children |
| `cavecrusher` (fully) | Robocave | Needs `maincavecam` trigger setup |

### ❌ Known Broken / Not Viable for Custom Levels
*(none confirmed permanently broken yet)*

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

**Platforms:** orbit-plat, square-platform, ropebridge, lavaballoon, darkecobarrel, caveelevator, caveflamepots, cavetrapdoor, cavespatula, cavespatulatwo, ogre-bridge, ogre-bridgeend, pontoon, tra-pontoon, mis-bone-bridge, breakaway-left/mid/right, plat-flip, side-to-side-plat, wall-plat, wedge-plat, tar-plat, balance-plat, teetertotter, revcycle, launcher, warpgate

**Objects:** water-vol, swingpole, springbox, eco-door, launcherdoor, shover, swampgate, ceilingflag, windturbine, boatpaddle, accordian, all lava props, balloon, crate-darkeco-cluster, swamp-tetherrock, fishermans-boat, cavecrystal, cavegem, ecoclaw, gondola, shortcut-boulder, spike, steam-cap, swamp-blimp, swamp-rock, swamp-rope, swamp-spike, tntbarrel, whirlpool, windmill-one

**Props:** dark-plant, evilplant

**Bosses:** ogreboss, plant-boss, robotboss

