# Non-Prop Actor Research — Complete Lump Reference
_Researched from OpenGOAL source: goal_src/jak1/ — full init-from-entity! bodies + helper methods_
_Last updated: April 2026_

---

## How to Read This File

Each entry lists:
- **etype** — the entity type string used in ENTITY_DEFS
- **art group stem** — second line of `defskelgroup`, used to build `<stem>-ag.go`
- **lumps** — every lump read in `init-from-entity!` AND any helper methods it calls
- **entity links** — `alt-actor`, `next-actor`, `water-actor`, `state-actor` etc. (entity-actor-lookup calls)
- **notes** — behaviour/gotchas

Lump types use the JSONC type string notation from the lump-system KB.
`float[N]` means N floats in a single `"float"` or `"meters"` array.

---

## Tier 1 Enemies — Standard nav enemy, no special lumps needed

### `balloonlurker`
- **art group**: `balloonlurker`
- **lumps**: none
- **entity links**: `alt-actor 0` → checks `entity-perm-status complete` to decide if dead on spawn (standard kill-on-task pattern)
- **notes**: Calls `rigid-body-platform-method-30/31` for floating physics — no lump reads in those helpers. Spawns `balloonlurker-pilot` child. Standard enemy perm gating.

### `darkvine`
- **art group**: `darkvine`
- **lumps**: none
- **entity links**: none
- **notes**: Pure nav enemy with 4 collision spheres. Uses `nav-mesh-connect`. Checks `game-task jungle-plant` reminder bit — will go to die state if task resolved. No per-instance config.

### `quicksandlurker`
- **art group**: `quicksandlurker`
- **lumps**: none
- **entity links**: `water-actor 0` → optional mud/water surface entity
- **notes**: Standard nav enemy. `mud-entity` link is optional — can be null. Drops eco-pill-random.

### `cave-trap`
- **art group**: none (no skeleton — invisible trigger volume)
- **lumps**: none
- **entity links**: `alt-actor 0..N` → array of `spider-egg` entities this trap manages
- **path**: reads `'path` (path-control) — patrol path for spawned spiders
- **notes**: No mesh. Acts as spawner/controller. Must have alt-actor links pointing to spider-egg empties nearby. Path defines spider patrol area.

### `spider-egg`
- **art group**: `spider-egg` (uses `*spider-egg-unbroken-sg*` + `*spider-egg-broken-sg*` LOD switch)
- **lumps**: none
- **entity links**: `alt-actor 0` → optional notify-actor (sent a message when egg hatches)
- **notes**: Self-aligns to ground on spawn (move-to-ground). Randomises orientation. Spawns `baby-spider` on death. alt-actor is optional.

### `spider-vent`
- **art group**: none (bare `trsqv`, no skeleton)
- **lumps**: none
- **entity links**: none
- **notes**: Invisible spawner. No mesh. Just a position — spawns baby-spiders periodically from its location. Simplest possible entity.

### `peeper`
- **art group**: `lightning-mole` (shares art with lightning-mole)
- **lumps**: none
- **entity links**: none
- **notes**: Uses `*lightning-mole-sg*`. Pops up and fires lightning. No per-instance config.

---

## Tier 2 Enemies

### `junglefish`
- **art group**: `junglefish`
- **lumps**:
  - `water-height` `["float", value]` — y-coordinate of water surface in game units. Fish positions itself at `water_height - 4096` (1m below surface). **Required** — defaults to 0 which puts it underground.
- **entity links**: none
- **notes**: Nav enemy. `water-height` is a raw float (game units, not meters). Use `["float", value]` not `["meters", value]`.

### `swamp-rat-nest`
- **art group**: `swamp-rat-nest` (three dummy variants: a/b/c — selected procedurally)
- **lumps**:
  - `num-lurkers` `["uint32", 3]` — how many rats to spawn. Clamped 1–4. Default 3. Reduced by 1 if player has lost ≥50% health (difficulty scaling).
- **path**: reads `'path` (path-control) — rat patrol path. **Required.**
- **entity links**: none
- **notes**: Invisible controller. Spawns `swamp-rat` children along path. `num-lurkers` sets max active at once, not total.

### `villa-starfish`
- **art group**: none (bare `trsqv`)
- **lumps**:
  - `num-lurkers` `["uint32", 3]` — how many starfish to spawn. Clamped 1–8. Default 3.
- **path**: reads `'path` (path-control) — starfish orbit path. **Required.**
- **entity links**: none
- **notes**: Spawns `lurker-starfish` children along path.

### `sunkenfisha`
- **art group**: none (bare proc — mesh is per-fish child)
- **lumps**:
  - `count` `["uint32", 1]` — number of fish in the school. Spawns count-1 extra children (the entity itself is fish 0). Default 1.
  - `path` — curve-control path. **Required.** Fish orbit this path.
  - `speed` `["float", lo, hi]` — speed range in game-units/frame. Defaults: lo=8192, hi=26624. Two-element float array.
  - `path-max-offset` `["float", x, y]` — maximum wander from path: x=horizontal spread (default 16384=4m), y=vertical spread (default 28672=7m).
  - `path-trans-offset` `["float", x, y, z]` — translate the entire path by this offset. Default 0,0,0.
- **entity links**: none
- **notes**: Schooling fish system. At least 2 path verts required or errors. `speed` values are raw units/frame not meters/sec.

### `sharkey`
- **art group**: `sharkey`
- **lumps**:
  - `scale` `["float", 1.0]` — uniform scale. Default 1.0. Affects collision sphere, y-range, everything.
  - `water-height` `["float", value]` — y-coordinate of water surface. **Required** (defaults to 0). Raw float, not meters.
  - `delay` `["float", 1.0]` — seconds before shark re-engages after losing player. Default 1.0.
  - `distance` `["meters", 30.0]` — spawn distance from player trigger radius. Default 122880 (30m).
  - `speed` `["meters", 12.0]` — chase speed in meters/sec. Default 49152 (12m/s).
- **entity links**: none
- **notes**: All 5 lumps optional but water-height is effectively required. `scale` affects colsphere radius proportionally.

### `babak-with-cannon`
- **art group**: `babak-with-cannon` _(verify — not yet researched in detail)_
- **lumps**: standard enemy lumps + cannon target (Tier 2 pending full research)

---

## Tier 2 Platforms / Moving Objects

### `orbit-plat`
- **art group**: `orbit-plat`
- **lumps**:
  - `scale` `["float", 1.0]` — uniform scale of the platform. Default 1.0.
  - `timeout` `["float", 10.0]` — seconds to wait before beginning orbit. Default 10.0.
- **entity links**: `alt-actor 0` → the entity to orbit around (**required** — this is the center point)
- **notes**: Platform waits `timeout` seconds then orbits the alt-actor entity. alt-actor can be any entity — its position is the orbit center. Spawns an `orbit-plat-bottom` child.

### `square-platform`
- **art group**: `square-platform`
- **lumps**:
  - `distance` `["float", down, up]` — two-element float array. `distance[0]` = down offset from spawn Y (default -8192 = -2m). `distance[1]` = up offset from spawn Y (default 16384 = 4m). Raw game units.
- **entity links**: `alt-actor 0` → water-entity (optional — for splash effects)
- **notes**: Uses `actor-link-info` — multiple square-platform actors linked together act as a group. Linked via standard actor-link chain (not alt-actor). `distance` controls travel range. Platform starts in down position.

### `qbert-plat`
- **art group**: `qbert-plat` _(verify stem)_
- **lumps**: **none** — pure rigid body, all controlled by `qbert-plat-master`
- **entity links**: none
- **notes**: Standalone `qbert-plat` actors are nearly useless without a `qbert-plat-master` controller. The master uses actor-link to find all qbert-plats in range, then drives them as a puzzle. Tier 3 system overall.

### `snow-log`
- **art group**: `snow-log`
- **lumps**: none
- **entity links**: `alt-actor 0` → `snow-log-master` controller entity (**required**)
- **notes**: The log itself has no lumps. Behaviour entirely driven by its master. Needs a `snow-log-master` (not in ENTITY_DEFS yet) to function.

### `snow-log-button`
- **art group**: `snow-switch` (uses snow-switch skeleton)
- **lumps**: none
- **entity links**: `alt-actor 0` → `snow-log` entity to control (**required**)
- **notes**: Activates the linked snow-log when stepped on. Uses snow-switch art.

### `citb-base-plat`
- **art group**: citadel-specific _(verify)_
- **lumps**:
  - `delay` `["float", 1.0]` — delay before platform activates. Default 1.0s.
- **notes**: Part of citadel platform system. Tier 3 for full setup.

### `citb-drop-plat`
- **art group**: citb-drop-plat _(verify)_
- **lumps**:
  - `count` `["int32", x, z]` — grid dimensions: `count[0]` = x-count, `count[1]` = z-count. No default (defaults to whatever struct initialises to — use explicit values).
  - `plat-type` `["int32", c0, c1, ...]` — color/type per cell in the grid, length = x*z. int8 array.
  - `rotoffset` `["degrees", angle]` — Y-axis rotation offset for the grid orientation. Default 0.
- **notes**: Spawns a grid of drop platforms. `count` defines the grid size. `plat-type` colors each cell. Complex Tier 3 setup.

### `ropebridge`
- **art group**: selected by `art-name` lump (see below)
- **lumps**:
  - `art-name` `["string", "ropebridge-32"]` — selects bridge variant. Valid values: `"ropebridge-32"`, `"ropebridge-36"`, `"ropebridge-52"`, `"ropebridge-70"`, `"snow-bridge-36"`, `"vil3-bridge-36"`. Default: `"ropebridge-32"`.
- **entity links**: none
- **notes**: Art group and physics tuning both selected from `art-name`. Bridge length/width is baked into the variant. Physics are fully simulated (rope + planks).

### `orbit-plat` — see above

### `snow-bumper`
- **art group**: `snow-bumper` _(verify)_
- **lumps**:
  - `rotmin` `["float", base_ry, max_diff_ry]` — two floats. `rotmin[0]` = base shove rotation (default 0). `rotmin[1]` = max random variation added to shove (default 32768 = 180°). Raw angle units.
- **entity links**: `alt-actor 0` → optional blimp entity (for blimp-riding variant)
- **notes**: Bumps player upward with a rotation. alt-actor optional.

### `snow-ball`
- **art group**: `snow-ball` _(verify)_
- **lumps**: none
- **path**: reads `'path` **twice** with time offsets 1.0 and 2.0 — this is a curve-control that encodes **two path branches** in a single spline. Need at least 2 segments in the path curve.
- **entity links**: none
- **notes**: Rolls along the path, alternating between two branches. Path must be a multi-segment curve with enough verts for 2 branches.

### `mis-bone-bridge`
- **art group**: `mis-bone-bridge`
- **lumps**:
  - `animation-select` `["uint32", N]` — selects fall animation and particle group. Values: 1,2,3,7 (each maps to a different bone bridge visual). Default 0 (no particles).
- **entity links**: none
- **notes**: Breakable bridge. Collapses when hit with red eco or taken enough damage.

### `boatpaddle`
- **art group**: `boatpaddle`
- **lumps**: none
- **entity links**: none
- **notes**: Pure ambient animation. No interaction. Simple spawn.

### `accordian`
- **art group**: `accordian`
- **lumps**: none
- **entity links**: `alt-actor 0` → task gate entity (optional — controls whether accordian is open)
- **notes**: Animated obstacle. Checks entity perm task on spawn. alt-actor optional.

### `precurbridge`
- **art group**: `precurbridge` _(verify)_
- **lumps**: none (pending full verification — complex collision setup)
- **entity links**: none
- **notes**: Tier 2. Physics bridge. No explicit lump reads found.

### `breakaway-left` / `breakaway-mid` / `breakaway-right`
- **art group**: `breakaway-left`, `breakaway-mid`, `breakaway-right`
- **lumps**:
  - `height-info` `["float", h1, h2]` — two-float array controlling fall height offsets. Defaults unclear (no explicit default in source — use 0,0 for flat).
- **entity links**: none
- **notes**: Three separate etypes for the three bridge segment types. All use `init!` helper with `height-info`.

### `lavaballoon`
- **art group**: `lavaballoon`
- **lumps**:
  - `speed` `["meters", 3.0]` — movement speed along path. Default 12288 (3m/s).
- **path**: reads `'path` (path-control). Optional but if absent, balloon just idles in place.
- **entity links**: none

### `darkecobarrel`
- **art group**: `darkecobarrel`
- **lumps**:
  - `speed` `["meters", 15.0]` — movement speed along path. Default 61440 (15m/s).
  - `delay` `["float", t0, t1, ...]` — array of spawn delay times in seconds. Optional. If absent, uses 4 hardcoded delays. If present, replaces all delays.
- **path**: reads `'path` via `darkecobarrel-base-init`. **Required.**
- **entity links**: none
- **notes**: `delay` overrides the entire spawn table when present.

### `caveelevator`
- **art group**: `caveelevator`
- **lumps**:
  - `trans-offset` `["float", x, y, z]` — XYZ position offset applied after entity placement. Default 0,0,0.
  - `rotoffset` `["degrees", angle]` — Y-axis rotation offset. Default 0.
  - `mode` `["uint32", N]` — elevator mode variant. Default 0.
- **entity links**: none
- **notes**: `mode` likely selects a movement variant (not fully traced but read as uint).

### `caveflamepots`
- **art group**: `caveflamepots` _(verify stem)_
- **lumps**:
  - `shove` `["meters", 2.0]` — upward shove force when player touches flame. Default 8192 (2m).
  - `rotoffset` `["degrees", angle]` — Y-axis rotation for flame orientation. Default 0.
  - `cycle-speed` `["float", period, offset, pause]` — three-element float array:
    - `[0]` = cycle period in seconds (default 4.0)
    - `[1]` = phase offset as fraction of cycle (default 0.0)
    - `[2]` = pause duration between cycles in seconds (default 2.0)
- **path**: reads `'path`. **Required** — errors out with "no path" if absent.
- **entity links**: none
- **notes**: `cycle-speed` is one lump key with all three timing values packed in. Very useful for desynchronising multiple flame pots.

### `cavetrapdoor`
- **art group**: `cavetrapdoor`
- **lumps**: none
- **entity links**: none
- **notes**: Falls when player steps on it. No per-instance config.

### `cavespatula` / `cavespatulatwo`
- **art group**: `cavespatula` (switches to `cavespatula-darkcave` if current level is `'darkcave`)
- **lumps**: none
- **entity links**: none
- **notes**: Rotating platform. Level detection is hardcoded to level name — not a lump.

### `ogre-bridge`
- **art group**: `ogre-bridge` _(verify)_
- **lumps**: none
- **entity links**: `alt-actor 0` → `ogre-bridgeend` entity (**required** for bridge to function)
- **notes**: Drawbridge triggered by boss fight. Needs paired `ogre-bridgeend`.

### `ogre-bridgeend`
- **art group**: `ogre-bridgeend`
- **lumps**: none
- **entity links**: none

### `swampgate`
- **art group**: `swamp-spike-gate` _(verify — uses `init!` helper)_
- **lumps**: none
- **entity links**: none
- **notes**: Opens/closes based on entity perm status. No lumps.

### `ceilingflag`
- **art group**: `ceilingflag`
- **lumps**: none
- **entity links**: none
- **notes**: Hanging decoration. No interaction.

### `fishermans-boat`
- **art group**: `fishermans-boat`
- **lumps**: none
- **entity links**: none
- **notes**: State depends on `*game-info* current-continue level` (misty vs village1 dock variant). No per-instance config. Rigid body platform.

### `pontoon`
- **art group**: `pontoon` / `tra-pontoon`
- **lumps**:
  - `alt-task` `["uint32", 0]` — second task gate. If nonzero and that task is complete, pontoon dies (sinks). Default 0 (unused). Main task comes from entity perm.
- **entity links**: none
- **notes**: Floating rigid body. Uses `rigid-body-platform-method-30/31`. Two etypes: `pontoon` (village2) and `tra-pontoon` (training) — same logic, different art.

### `swamp-tetherrock`
- **art group**: `swamp-tetherrock`
- **lumps**: none
- **entity links**: `alt-actor 0` → master blimp entity (optional)
- **notes**: Breakable rock. State driven by task status. alt-actor optional.

### `windturbine`
- **art group**: `windturbine`
- **lumps**:
  - `particle-select` `["uint32", 0]` — if 1, enables particle effects. Default 0 (off).
- **entity links**: none
- **notes**: Ambient spinning prop with optional particles.

---

## Tier 2 Interactables / Doors

### `eco-door`
- **art group**: `eco-door` _(verify)_
- **lumps**:
  - `scale` `["float", 1.0]` — uniform scale. Default 1.0.
  - `flags` `["enum-uint32", "(eco-door-flags ...)"]` — bitfield. Common flags: `auto-close` (door closes after player passes), `one-way` (only opens from front). Default 0.
- **entity links**: `state-actor 0` → optional entity whose perm status controls door lock state
- **notes**: Auto-progression: if entity perm is complete and not auto-close, spawns in open state.

### `launcherdoor`
- **art group**: `launcherdoor` or `launcherdoor-maincave` (selected by current level name)
- **lumps**:
  - `continue-name` (string) — read in state code (not init), sets level continue point when door is passed through. Use bare string: `"continue-name": "village1-hut"`
- **entity links**: none
- **notes**: continue-name is read during the open transition state, not at init. Level selection of art is hardcoded.

### `helix-button`
- **art group**: `helix-button`
- **lumps**: none
- **entity links**: `alt-actor 0` → helix-water entity, `alt-actor 1` → helix-slide-door entity. Both **required**.
- **notes**: Press to raise water level. Needs both links.

### `helix-slide-door`
- **art group**: `helix-slide-door`
- **lumps**: none
- **entity links**: none
- **notes**: Purely reactive — opened by helix-button signal.

### `helix-water`
- **art group**: none (bare `trsqv`)
- **lumps**: none
- **entity links**: `alt-actor 0..N` → array of `helix-button` entities (**required** — controls water raise stages)
- **notes**: Each alt-actor is a button. Water rises one stage per button pressed. Spawns `helix-dark-eco` water-vol child.

### `sun-iris-door`
- **art group**: `sun-iris-door`
- **lumps**:
  - `timeout` `["float", 0.0]` — seconds door stays open before auto-closing. Default 0 (stays open).
  - `proximity` `["uint32", 0]` — if nonzero, door opens when player approaches. Default 0 (task-gated only).
  - `scale-factor` `["float", 1.0]` — uniform scale. Default 1.0.
  - `trans-offset` `["float", x, y, z]` — position offset. Default 0,0,0.
- **entity links**: none
- **notes**: Task gate comes from entity perm task. `proximity` overrides task gating with proximity trigger.

### `snow-button`
- **art group**: `snow-button`
- **lumps**:
  - `timeout` `["float", 10.0]` — how long the button stays pressed before resetting. Default 10.0s.
- **entity links**: `alt-actor 0` → previous button in chain (optional — for chained puzzle)
- **notes**: Timed reset button. alt-actor chain is optional.

### `snow-switch`
- **art group**: `snow-switch`
- **lumps**: none
- **entity links**: uses `actor-link-info` chain (standard actor-link, not alt-actor)
- **notes**: Toggle switch. Notifies all actor-linked entities. No per-instance config.

### `shover`
- **art group**: `shover`
- **lumps**:
  - `shove` `["meters", 3.0]` — upward launch force. Default 12288 (3m).
  - `collision-mesh-id` `["uint32", 0]` — collision mesh index. Default 0.
  - `trans-offset` `["float", x, y, z]` — position offset. Default 0,0,0.
  - `rotoffset` `["degrees", angle]` — Y-axis rotation. Default 0.
- **path**: reads `'path`. **Required** — errors with "no path" if absent.
- **entity links**: none
- **notes**: Moving shover platform that rides a path. `shove` is the upward impulse when the platform hits the player.

### `swingpole`
- **art group**: none (bare `process`, not `process-drawable`)
- **lumps**: **none**
- **entity links**: none
- **notes**: Invisible swing pole. Grabs Jak when he jumps through it. No mesh, no skeleton. Position and rotation from entity transform only. Y-axis of entity = pole axis direction. **Very easy to add.**

### `springbox` / `bouncer`
- **art group**: `bouncer`
- **lumps**:
  - `spring-height` `["meters", 11.0]` — launch height. Default 45056 (11m).
- **entity links**: none
- **notes**: etype is `springbox`, but art group is `bouncer`. Simple — one optional lump.

---

## Tier 2 Eco / Pickups

### `eco-pill`
- **art group**: `eco-pill` _(verify)_
- **lumps**: none — type and amount hardcoded to `eco-pill` / `health-small-inc`
- **entity links**: none

### `ecovent` / `ventblue`
- **art group**: vent geometry _(verify stem)_
- **lumps**: none — type hardcoded to `eco-blue`
- **entity links**: `alt-actor 0` → optional blocker entity (if present, vent is blocked until blocker's task completes)
- **notes**: Two etypes (`ecovent` and `ventblue`) are identical — both blue eco.

### `ventred`
- **art group**: same vent geometry
- **lumps**: none — type hardcoded to `eco-red`
- **entity links**: `alt-actor 0` → optional blocker

### `ventyellow`
- **art group**: same vent geometry  
- **lumps**: none — type hardcoded to `eco-yellow`
- **entity links**: `alt-actor 0` → optional blocker

### `ecoventrock`
- **art group**: `ecoventrock`
- **lumps**: none — standard vent logic but with rock mesh collision
- **entity links**: none

### `water-vol`
- **art group**: none (bare `trsqv` + vol-control)
- **lumps**:
  - `attack-event` — symbol lump. Default `'drown`. Controls what event fires when player is submerged. Bare string: `"attack-event": "'drown"` or `"'swim-hit"` etc.
  - `water-height` `["water-height", water_m, wade_m, swim_m]` — 3-5 element array:
    - `[0]` = water surface Y (meters)
    - `[1]` = wade height — Y above which player wades
    - `[2]` = swim height — Y above which player swims
    - `[3]` = water-flags bitmask (optional, int)
    - `[4]` = bottom height (optional, default 32768 = 8m below surface)
- **entity links**: none
- **notes**: Uses `vol-control` for volume bounds (reads from entity position/size). `water-height` is **required** — defaults to 0 for all fields. Use the `"water-height"` JSONC type for proper meter scaling. `attack-event 'drown` kills the player; other symbols like `'swim-hit` do damage.

### `snow-spatula`
- **art group**: `snow-spatula`
- **lumps**: reads `sync` via `load-params!` — but `load-params!` uses entity perm data, not a JSONC lump. No explicit JSONC lumps needed.
- **entity links**: none

### `snow-eggtop`
- **art group**: `snow-eggtop`
- **lumps**: none
- **entity links**: none
- **notes**: Standard pickup. Task-gated via entity perm task.

### `cavespatula`
- Same as `cavespatulatwo` — both have no lumps, level-name selects art group.

---

## Tier 2 NPCs

### `oracle`
- **art group**: `oracle`
- **lumps**:
  - `alt-task` `["uint32", 0]` — second orb task ID (game-task enum value). Default 0. First task comes from entity perm task.
- **entity links**: none
- **notes**: Oracle with 1 orb only needs entity perm task. Oracle with 2 orbs needs `alt-task` set to the second task's enum value. Both fuel-cells appear as eyes.

### `bird-lady`
- **art group**: `bird-lady`
- **lumps**: none — task hardcoded to `beach-flutflut`
- **entity links**: none
- **notes**: process-taskable NPC. Task is baked in, not configurable.

### `bird-lady-beach`
- **art group**: `bird-lady-beach`
- **lumps**: none — same as bird-lady, different model/position

### `minershort`
- **art group**: `minershort`
- **lumps**: none — task hardcoded to `village3-miner-money1`
- **entity links**: `alt-actor 0` → `minertall` partner (**required** — they reference each other)
- **notes**: Must be placed paired with a `minertall`. They cross-reference each other via alt-actor.

### `minertall`
- **art group**: `minertall`
- **lumps**: none — task hardcoded to `village3-miner-money1`
- **entity links**: none (minershort holds the link, not minertall)

---

## Tier 3 — Complex Systems (research only, no immediate implementation)

### `battlecontroller`
- **lumps**:
  - `patha` through `pathh` — up to 8 named paths (`'patha`, `'pathb`, ... `'pathh`). Each is a path-control.
  - `pathspawn` — optional spawn-point path.
  - `delay` `["float", 0.1]` — wave delay in seconds. Default 0.1s.
  - `num-lurkers` `["int32", n0, n1, ...]` — lurker count per creature type.
  - `lurker-type` — array of lurker type indices.
  - `percent` — array of spawn probability weights per type.
  - `final-pickup` `["enum-uint32", "(pickup-type fuel-cell)"]` — pickup spawned when battle won. Default: pickup-type 7 (fuel-cell).
  - `pickup-type`, `max-pickup-count`, `pickup-percent` — pickup table arrays.
  - `mode` `["uint32", 0]` — if 1, prespawns all lurkers at start.
- **notes**: Highly complex. Minimum viable setup needs at least 1 path + lurker-type.

### `mistycannon`
- **lumps**:
  - `rotmin` `["degrees", 90.0]` — minimum rotation angle. Default 16384 (~90°).
  - `rotmax` `["degrees", 180.0]` — maximum rotation angle. Default 32768 (~180°).
  - `rotspeed` `["degrees", 20.0]` — rotation speed. Default 3640.889.
  - `tiltmin` `["degrees", -10.0]` — minimum tilt. Default -1820.4445.
  - `tiltmax` `["degrees", 70.0]` — maximum tilt. Default 12743.111.
  - `tiltspeed` `["degrees", 20.0]` — tilt speed. Default 3640.889.
  - `center-radius` `["meters", N]` — radius of the aim constraint sphere.
  - `center-point` `["float", x, y, z]` — aim constraint center position.
- **entity links**: `alt-actor 0` → avoid-entity (entity the cannon avoids hitting)

### `racer`
- **lumps**:
  - `rotoffset` `["degrees", 0.0]` — initial yaw angle. Default 0.
  - `index` `["int32", 0]` — race condition/index selects which racer this is (0..N).
- **notes**: Part of rolling race system.

### `race-ring`
- **lumps**:
  - `timeout` `["float", 0.0]` — ring timeout in seconds. Default 0.
- **entity links**: `alt-actor 0` → optional. `next-actor` chain for ring sequence.
- **notes**: Uses actor-link-info for ordering.

### `keg-conveyor`
- **lumps**: none
- **path**: `'path` (curve-control). **Required.**
- **notes**: Spawns `keg` children along path.

### `periscope`
- **lumps**:
  - `height-info` `["meters", h]` — beam emission height above entity position.
  - `text-id` `["uint32", 0]` — task hint text ID to display.
  - `rotoffset` `["float", turn, tilt]` — two floats: yaw offset and tilt offset in raw angle units.
- **notes**: Part of jungle mirror puzzle system.

### `reflector-middle`
- **lumps**:
  - `height-info` `["meters", h]` — beam height above entity position. Also read from neighboring reflector entities in the chain.
- **entity links**: uses `actor-link-info` chain

### `reflector-mirror`
- **lumps**:
  - `height-info` `["meters", h]` — beam reflection height.
  - `alt-vector` `["vector3m", x, y, z]` — explicit beam endpoint if no next mirror in chain.
- **entity links**: `alt-actor 0` → blocker entity (breaks mirror when complete), `alt-actor 1..N` → chain of mirrors to notify

### `happy-plant`
- **lumps**:
  - `max-frame` `["float", N]` — max animation frame. Default = total frames.
  - `min-frame` `["float", 0.0]` — min animation frame. Default 0.
- **entity links**: `alt-actor 0` → task gate entity

---

## Art Group Verification Status

All stems below follow the pattern `<stem>-ag.go` for the art group file.

| etype | art group stem | verified? |
|---|---|---|
| balloonlurker | balloonlurker | ✓ |
| darkvine | darkvine | ✓ |
| junglefish | junglefish | ✓ |
| quicksandlurker | quicksandlurker | ✓ |
| spider-egg | spider-egg | ✓ |
| peeper | lightning-mole | ✓ |
| swamp-rat-nest | swamp-rat-nest | ✓ |
| sunkenfisha | (no art, bare proc) | ✓ |
| sharkey | sharkey | ✓ |
| orbit-plat | orbit-plat | ✓ |
| square-platform | square-platform | ✓ |
| ropebridge | variant-selected | ✓ |
| lavaballoon | lavaballoon | ✓ |
| darkecobarrel | darkecobarrel | ✓ |
| caveelevator | caveelevator | ✓ |
| caveflamepots | caveflamepots | needs verify |
| cavetrapdoor | cavetrapdoor | ✓ |
| cavespatula | cavespatula / cavespatula-darkcave | ✓ |
| cavespatulatwo | cavespatulatwo | ✓ |
| ogre-bridge | ogre-bridge | needs verify |
| ogre-bridgeend | ogre-bridgeend | ✓ |
| pontoon | pontoon | ✓ |
| tra-pontoon | tra-pontoon | needs verify |
| swamp-tetherrock | swamp-tetherrock | ✓ |
| windturbine | windturbine | ✓ |
| ceilingflag | ceilingflag | ✓ |
| fishermans-boat | fishermans-boat | ✓ |
| eco-door | eco-door | needs verify |
| helix-button | helix-button | ✓ |
| helix-slide-door | helix-slide-door | ✓ |
| sun-iris-door | sun-iris-door | ✓ |
| snow-button | snow-button | ✓ |
| snow-switch | snow-switch | ✓ |
| shover | shover | ✓ |
| springbox | bouncer | ✓ |
| ecoventrock | ecoventrock | ✓ |
| oracle | oracle | ✓ |
| bird-lady | bird-lady | ✓ |
| bird-lady-beach | bird-lady-beach | ✓ |
| minershort | minershort | ✓ |
| minertall | minertall | ✓ |
| snow-spatula | snow-spatula | ✓ |
| snow-eggtop | snow-eggtop | ✓ |
| breakaway-left/mid/right | breakaway-left/mid/right | ✓ |
| mis-bone-bridge | mis-bone-bridge | ✓ |
| boatpaddle | boatpaddle | ✓ |
| accordian | accordian | ✓ |
| snow-bumper | snow-bumper | needs verify |
| race-ring | race-ring | ✓ |
| keg-conveyor | keg-conveyor | ✓ |
| racer | racer | ✓ |
| periscope | periscope | ✓ |
| reflector-middle | reflector-middle | ✓ |
| reflector-mirror | reflector-mirror | ✓ |
| happy-plant | happy-plant | ✓ |
| lavafall | lavafall | ✓ |
| lavafallsewera | lavafallsewera | ✓ |
| lavafallsewerb | lavafallsewerb | ✓ |
| lavabase | lavabase | ✓ |
| lavayellowtarp | lavayellowtarp | ✓ |
| chainmine | chainmine | ✓ |
| lavaballoon | lavaballoon | ✓ |
| balloon | balloon | ✓ |
| crate-darkeco-cluster | crate-darkeco-cluster | ✓ |
| battlecontroller | (no art) | ✓ |
| mistycannon | mistycannon | needs verify |
| swingpole | (no art) | ✓ |
| water-vol | (no art) | ✓ |

---

## Known Gaps / Still Needs Research

- `babak-with-cannon` — standard enemy + cannon target lump not yet researched
- `lavashortcut` — confirm art group stem and lumps
- `lavaballoon` — verify that path is truly optional
- Several "needs verify" art group stems above
- `tra-pontoon` vs `pontoon` — confirm they share logic exactly
- `citb-base-plat` / `citb-drop-plat` — full citadel system would need additional actors not listed

---

_Researched from goal_src/jak1/ — all defmethod init-from-entity! + helper function lump reads_
