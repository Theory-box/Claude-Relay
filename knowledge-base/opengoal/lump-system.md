# Jak 1 Lump System — Complete Reference

Researched from OpenGOAL source: `goalc/build_level/`, `goal_src/jak1/`.
Last updated: April 2026.

---

## What Is a Lump?

Every entity (actor or ambient) in Jak 1 carries a `res-lump` — a compact, sorted key-value store baked into the level file at compile time. The engine reads it at runtime using typed lookup functions. Think of it as per-entity configuration data: position offsets, behaviour flags, spawn tables, path parameters, anything an actor needs to know about itself beyond its base position and type.

Lumps are read-only after level load. They cannot be changed at runtime.

---

## How Lumps Work Internally

The C++ level builder (`goalc/build_level/common/ResLump.cpp`) builds a `res-lump` struct:
- A sorted tag array (sorted by first 8 bytes of key name for fast binary search)
- A data block packed immediately after the tags
- 10 extra tag slots pre-allocated for runtime additions

Each tag contains: the key name (as a symbol), a keyframe float (always `DEFAULT_RES_TIME = -1e9` for static lumps), the element type, element count, and an offset into the data block.

The GOAL-side read functions are in `engine/entity/res.gc`:
- `res-lump-value` — reads a single scalar value, returns a typed default if not found
- `res-lump-data` — returns a raw pointer into the data block
- `res-lump-struct` — returns a typed pointer for struct/vector lookups
- `res-lump-float` — convenience wrapper for single float values
- `lookup-tag-idx` — low-level tag index lookup, used with `'exact` or `'interp` mode

**Important:** Tags are written at `DEFAULT_RES_TIME = -1000000000.0`. The `'exact` lookup mode matches only tags at time `0.0` — this is the crash source we found with one-shot ambient sounds (see audio session notes). Use `'interp` mode (or `res-lump-struct`/`res-lump-data` which use `-1e9`) for static lumps.

---

## JSONC Lump Type Reference

These are the ONLY valid array type strings. Anything else throws a runtime error in the builder.

| JSONC type string | Res type | GOAL type | Notes |
|---|---|---|---|
| `"int32"` | ResInt32 | int32 | `["int32", 5, -3]` — array of signed 32-bit ints |
| `"uint32"` | ResUint32 | uint32 | `["uint32", 100]` — array of unsigned 32-bit ints |
| `"enum-int32"` | ResInt32 | int32 | `["enum-int32", ["(game-task none)"]]` — resolves GOAL enum |
| `"enum-uint32"` | ResUint32 | uint32 | `["enum-uint32", "(text-id fuel-cell)"]` — resolves GOAL enum |
| `"eco-info"` | ResInt32 | int32[2] | `["eco-info", "(pickup-type money)", 1]` — pickup type + amount |
| `"cell-info"` | ResInt32 | int32[2] | `["cell-info", "(game-task none)"]` — fuel cell, encodes task |
| `"buzzer-info"` | ResInt32 | int32[2] | `["buzzer-info", "(game-task none)", 1]` — scout fly + index |
| `"water-height"` | ResFloat | float[4-5] | `["water-height", water_m, wade_m, swim_m, "(water-flags ...)", bottom_m]` |
| `"symbol"` | ResSymbol | symbol | `["symbol", "thunder"]` — GOAL symbol reference |
| `"type"` | ResType | type | `["type", "process-drawable"]` — GOAL type reference |
| `"string"` | ResString | string | `["string", "some-string"]` |
| `"vector"` | ResVector | vector | `["vector", [x, y, z, w]]` — raw floats, NO unit scaling |
| `"vector4m"` | ResVector | vector | `["vector4m", [x, y, z, w]]` — each component × 4096 (meters) |
| `"vector3m"` | ResVector | vector | `["vector3m", [x, y, z]]` — 3 components × 4096, w=1 |
| `"movie-pos"` | ResVector | vector | `["movie-pos", [x, y, z, rot_deg]]` — xyz × 4096, w × degrees constant |
| `"vector-vol"` | ResVector | vector | `["vector-vol", [x, y, z, radius_m]]` — xyz raw, w × 4096 |
| `"float"` | ResFloat | float | `["float", 1.5, 2.0]` — raw float array, multiple values allowed |
| `"meters"` | ResFloat | float | `["meters", 4.0]` — value × 4096 |
| `"degrees"` | ResFloat | float | `["degrees", 90.0]` — value × degrees constant (182.044) |

**Bare string values** (not arrays):
- Starts with `'` → ResSymbol (the quote is stripped): `"type": "'sound"`
- Otherwise → ResString: `"name": "my-actor-01"`

**Integer shorthand:** The level builder also accepts a raw JSON integer for `game_task` (not `0` doesn't need to be `"(game-task none)"`). Both work.

---

## Lump Sorting

The level builder sorts all lump tags by the first 8 bytes of the key name before writing. This is a binary search optimisation. The sort is `stable_sort` by raw byte value of the name prefix — not alphabetical in the human sense, but by ASCII byte order. Implication: key names with similar prefixes cluster together. This doesn't affect JSONC authoring — the builder handles sorting.

---

## Universal Lumps (All Actors)

These lumps are read by base engine code and apply to every entity.

### `name` — ResString
**Used by:** `engine/entity/entity.gc`, debug display, `entity-by-name` lookup  
**JSONC:** `"name": "my-actor-01"` (bare string)  
**Notes:** Required. Used to identify the actor at runtime. Must be unique per level. The engine looks up entities by name for things like camera triggers, path links, etc.

### `vis-dist` — ResFloat (meters)
**Used by:** `engine/entity/entity.gc` vis culling  
**JSONC:** `["meters", 200.0]`  
**Default:** 409600.0 (100m) if not set  
**Notes:** Controls the distance at which the entity is considered "visible" by the visibility system. Enemies need large values (100–200m) to stay active. Pickups and static props can use small values. The addon hardcodes 200m for all enemies.

### `visvol` — ResVector (two vector4m entries)
**Used by:** `engine/entity/entity.gc` vis volume computation  
**JSONC:** `["vector4m", [x1,y1,z1,1.0], [x2,y2,z2,1.0]]` (two vectors defining a bounding box)  
**Notes:** Defines a visibility bounding box (min corner, max corner) for the entity. Used by the BSP visibility system. Custom levels without a BSP vis system can omit this — the engine falls back to bsphere.

### `eco-info` — ResInt32 (special)
**Used by:** `engine/common-obs/collectables.gc`, `engine/game/fact-h.gc`  
**JSONC:** `["eco-info", "(pickup-type money)", 1]` / `["cell-info", "(game-task none)"]` / `["buzzer-info", "(game-task none)", 1]`  
**Notes:** Encodes pickup type and amount. The `cell-info` and `buzzer-info` shortcuts pack the data differently. Used on fuel-cell, money, buzzer, crate, and eco actors.

### `options` — ResUint64 (fact-options bitfield)
**Used by:** `engine/common-obs/process-drawable.gc`, `engine/common-obs/collectables.gc`  
**JSONC:** `["enum-uint32", "(fact-options has-power-cell)"]`  
**Known flags:**
- `has-power-cell` — spawn power cell on death
- `instant-collect` — set on balloon-lurker, puffer
- `skip-jump-anim` — skips fuel cell jump animation
- `fade` — entity fades in/out

### `shadow-mask` — ResUint32
**Used by:** `engine/common-obs/process-drawable.gc`  
**JSONC:** `["uint32", 255]`  
**Notes:** Controls which shadow layers are rendered for this entity.

### `light-index` — ResUint32
**Used by:** `engine/common-obs/process-drawable.gc`  
**JSONC:** `["uint32", 0]`  
**Notes:** Index into the level's light array. Controls which light group illuminates this entity.

### `lod-dist` — ResFloat
**Used by:** `engine/common-obs/process-drawable.gc` LOD system  
**JSONC:** `["meters", 40.0]`  
**Notes:** Distance thresholds for LOD (level-of-detail) switching. Array of floats for each LOD transition.

### `texture-bucket` — ResInt32
**Used by:** `engine/common-obs/process-drawable.gc`  
**JSONC:** `["int32", 1]`  
**Default:** 1  
**Notes:** Controls which texture bucket the entity's draw calls go into.

### `joint-channel` — ResInt32
**Used by:** `engine/common-obs/process-drawable.gc`  
**JSONC:** `["int32", 6]`  
**Default:** 6  
**Notes:** Controls joint animation channel assignment.

---

## Navigation Lumps

### `nav-mesh-sphere` — ResVector (vector4m)
**Used by:** `engine/nav/navigate.gc`  
**JSONC:** `["vector4m", [x, y, z, radius_m]]`  
**Notes:** Provides a fallback sphere for nav-mesh initialization when no real navmesh is assigned. Prevents null dereference in `nav-mesh-connect`. The addon injects this automatically for nav-unsafe enemies (Category A enemies without a linked navmesh).

### `nav-mesh-actor` — ResSymbol or actor-ref
**Used by:** `engine/nav/navigate.gc`  
**JSONC:** `["symbol", "other-actor-name"]`  
**Notes:** Links to another actor that provides the navmesh. Advanced use.

### `nav-max-users` — ResInt32
**Used by:** `engine/nav/navigate.gc`  
**JSONC:** `["int32", 32]`  
**Default:** 32  
**Notes:** Maximum number of nav-control users that can share the navmesh.

---

## Path Lumps

### `path` — ResVector (vector4m, multi-point)
**Used by:** Most path-following enemies and many objects  
**JSONC:** `["vector4m", [x1,y1,z1,1.0], [x2,y2,z2,1.0], ...]`  
**Notes:** Each point is a nested array. The `w` component should always be `1.0`. Minimum point counts vary by actor. The addon generates this from waypoint empties named `ACTOR_<type>_<uid>_wp_00`.

### `pathb` — ResVector (vector4m, multi-point)
**Used by:** `swamp-bat` only  
**JSONC:** Same format as `path`  
**Notes:** Second patrol path for swamp-bat slave spawning. Must have at least 2 points. The addon generates from `_wpb_` waypoints.

### `pathspawn` — ResVector (vector4m, multi-point)
**Used by:** `battlecontroller`  
**JSONC:** Same format as `path`  
**Notes:** Separate spawn-point path for battlecontroller enemy spawning logic.

---

## Enemy Behaviour Lumps

### `num-lurkers` — ResInt32
**Used by:** `swamp-bat`, `yeti`, `swamp-rat-nest`, `battlecontroller`, `villa-starfish`  
**JSONC:** `["int32", 6]`  
**Defaults:** swamp-bat: 6 (clamped 2–8), yeti: path vertex count, villa-starfish: 3  
**Notes:** Controls how many child enemies are spawned/managed.

### `notice-dist` (also `distance`) — ResFloat (meters)
**Used by:** `yeti` (as `notice-dist`), `puffer` (as `distance`), `sunken-fish` (as `distance`)  
**JSONC:** `["meters", 50.0]`  
**Defaults:** yeti: 204800.0 (50m), puffer: min/max as two-float array  
**Notes:** Distance at which AI notice/activate behaviour triggers. For `puffer`, `distance` is a two-float array: `["float", min_dist, max_dist]` where both are in internal units (multiply by 4096 for meters).

### `mode` — ResUint32 or ResInt32 (actor-specific)
**Used by:** many actors — meaning varies completely per type  
**JSONC:** `["int32", 0]` or `["uint32", 1]`  
**Notes:** Completely context-dependent. Examples:
- `snow-piston`: `[mode_type, open_mode]` — two int32 values
- `dark-crystal`: `1` = underwater variant
- `battlecontroller`: `1` = prespawn mode
- `launcher`: camera mode selector
- `snow-bunny`: variant selector
- `citb-drop-plat`: drop behaviour mode
- `snow-ram`, `snow-flutflut-obs`: state variant

### `flags` — ResInt32 (eco-door-flags bitfield)
**Used by:** `eco-door` and subclasses (doors, gates)  
**JSONC:** `["enum-int32", ["(eco-door-flags auto-close)"]]`  
**Known flags:** `auto-close`, `one-way`  
**Notes:** Controls door behaviour. Bitfield, so multiple flags can be combined.

### `delay` — ResFloat
**Used by:** `plat-flip`, `lavatube-obs`, `battlecontroller`, `sharkey`  
**JSONC:** `["float", 2.0]` or two-float: `["float", before_down, before_up]`  
**Notes:** For plat-flip: two values — delay before flipping down, delay before flipping up (in seconds, multiplied by 300 for frames). For battlecontroller: spawn period in seconds. For sharkey: reaction time in seconds.

### `sync` — ResFloat (2–4 values)
**Used by:** any actor that calls `load-params!` on a sync-info (platforms, moving objects)  
**JSONC:** `["float", period_sec, phase]` or `["float", period_sec, phase, in_frac, out_frac]`  
**Notes:** Controls oscillation/sync timing for moving platforms. `period_sec` is in seconds (multiplied by 300 for frames). `phase` is 0.0–1.0. `in_frac`/`out_frac` are easing fractions (default 0.15).

### `sync-percent` — ResFloat
**Used by:** `plat-flip`  
**JSONC:** `["float", 0.0]`  
**Notes:** Phase offset for sync.

### `alt-task` — ResInt32 (via enum)
**Used by:** `rolling-race-ring`, `village2-obs`, `oracle`  
**JSONC:** `["enum-int32", ["(game-task ...)"]]`  
**Notes:** Secondary task reference. Context-dependent.

### `extra-id` — ResInt32
**Used by:** `basebutton` (button ID), `dark-crystal` (crystal number), `snow-ram`, `snow-flutflut-obs`  
**JSONC:** `["int32", 0]`  
**Notes:** Varies by actor. For buttons: explicitly overrides the auto-assigned button ID.

### `prev-actor` / `next-actor` (actor reference)
**Used by:** `basebutton` chain linking  
**JSONC:** referenced via `entity-actor-lookup` — set by actor reference system, not direct lump  
**Notes:** Links buttons in a sequence.

### `camera-name` — ResString or ResSymbol
**Used by:** `battlecontroller`, `plat-button`  
**JSONC:** `"camera-name": "some-camera-entity-name"` (bare string)  
**Notes:** Name of a camera entity to activate during this actor's event. For battlecontroller: activates when wave starts.

### `continue-name` — ResString
**Used by:** `launcherdoor`, `jungle-elevator`  
**JSONC:** `"continue-name": "beach-start"` (bare string)  
**Notes:** Name of a continue-point to activate when Jak passes through this trigger. Used for level transitions.

### `lurker-type` — ResType (array)
**Used by:** `battlecontroller`  
**JSONC:** `["type", "babak", "hopper"]` (one or more type names)  
**Notes:** Enemy types that battlecontroller will spawn. Parallel array with `percent`.

### `percent` — ResFloat (array)
**Used by:** `battlecontroller`, `steam-cap`  
**JSONC:** `["float", 0.5, 0.3, 0.2]` (one value per lurker-type)  
**Notes:** Spawn probability weights per lurker type. For steam-cap: completion percentage threshold.

### `final-pickup` — ResUint32 (pickup-type enum)
**Used by:** `battlecontroller`  
**JSONC:** `["enum-uint32", "(pickup-type fuel-cell)"]`  
**Default:** 7 (fuel-cell)  
**Notes:** What to spawn after all waves are defeated.

### `pickup-type` / `max-pickup-count` / `pickup-percent` — ResInt32 arrays
**Used by:** `battlecontroller`  
**JSONC:** `["int32", ...]` arrays, parallel to `lurker-type`  
**Notes:** Per-creature-type pickup override arrays.

---

## Spatial / Transform Lumps

### `trans-offset` — ResFloat (3 values)
**Used by:** `water-anim`, `gnawer`, `maincave-obs`, `sunken/shover`, `sunken/sun-iris-door`  
**JSONC:** `["float", dx, dy, dz]` (raw floats in internal units) or `["meters", ...]`  
**Notes:** Adds a positional offset to the actor's trans. Applied after the base position. Values are in internal units unless the actor reads them as meters.

### `rotoffset` — ResFloat (degrees or radians)
**Used by:** `jungle-mirrors`, `water-anim`  
**JSONC:** `["float", angle_radians]` — raw radian value  
**Notes:** Rotates the actor around Y axis by this amount after placement. In radians (NOT degrees) for most uses. Check actor source for exact interpretation.

### `rotmin` — ResFloat
**Used by:** `snow-bumper`  
**JSONC:** `["float", angle]`  
**Notes:** Minimum rotation angle constraint.

### `rot-offset` — ResVector (camera-specific)
**Used by:** `engine/camera/cam-layout.gc`  
**JSONC:** `["vector4m", [x, y, z, w]]`  
**Notes:** Camera rotation offset. Camera-entity only.

### `scale` — ResVector
**Used by:** `citb-plat`  
**JSONC:** `["vector4m", [sx, sy, sz, 1.0]]`  
**Notes:** Non-uniform scale applied to the actor's draw transform and collision.

### `translation` — ResVector (camera-specific)
**Used by:** `engine/camera/cam-layout.gc`  
**JSONC:** `["vector3m", [x, y, z]]`  
**Notes:** Camera translation override. Camera-entity only.

### `height-info` — ResFloat (2 values)
**Used by:** `jungle-obs` (reflector-middle)  
**JSONC:** `["float", y_base_offset, height]`  
**Notes:** Y-axis base offset and height for reflector beam attachment. Both in internal units.

### `movie-pos` — ResVector (multi, movie-pos format)
**Used by:** `collectables.gc` (fuel-cell jump landing positions)  
**JSONC:** `["movie-pos", [x, y, z, rot_deg]]` (one or more)  
**Notes:** Array of positions for fuel cell pop-out animation. If present, the cell jumps to these positions in sequence during the collection cutscene.

### `alt-vector` — ResVector
**Used by:** `launcher`, `jungle-mirrors`, `yakow`  
**JSONC:** `["vector4m", [x, y, z, t]]` where `w` is used as a time value for launchers  
**Notes:** For launchers: destination position and flight time (w × 300 = frames). For jungle-mirrors: reflection target. For yakow: movement destination.

### `interesting` — ResVector (vector3m)
**Used by:** `engine/camera/cam-layout.gc`  
**JSONC:** `["vector3m", [x, y, z]]`  
**Notes:** Camera "look-at" point override. If present, the camera points at this world position regardless of entity quaternion. The addon uses this for camera entities with a linked look-at target.

### `pivot` — ResVector
**Used by:** `engine/camera/cam-layout.gc`  
**JSONC:** `["vector4m", [x, y, z, 1.0]]`  
**Notes:** Pivot point for camera orbit mode.

### `align` — ResVector (camera-specific)
**Used by:** `engine/camera/cam-layout.gc`  
**JSONC:** `["vector3m", [x, y, z]]`  
**Notes:** Camera alignment vector.

---

## Ambient Lumps

Ambients have a different entity type (`entity-ambient`) but use the same lump system.

### `type` — ResSymbol (bare string with `'`)
**Used by:** `engine/entity/ambient.gc`  
**JSONC:** `"type": "'sound"` (bare string starting with quote)  
**Valid values:**
- `'sound` — looping sound emitter (via `ambient-type-sound-loop`, cycle-speed < 0) ✅ working
- `'sound` — one-shot sound (cycle-speed >= 0) ⚠️ crashes (known engine bug)
- `'hint` — voice hint trigger
- `'poi` — point of interest marker
- `'music` — music zone trigger
- `'light` — lighting zone
- `'dark` — dark eco zone
- `'weather-off` — disables weather
- `'ocean-off` — disables ocean
- `'ocean-near-off` — disables near ocean

### `effect-name` — ResSymbol
**Used by:** `engine/entity/ambient.gc` (all ambient types)  
**JSONC:** `["symbol", "thunder"]`  
**Notes:** For `'sound`: the sound effect name. For `'hint`/`'poi`: effect/entity name. For `'music`/`'light`/`'dark`/weather types: float value used differently. Must be `["symbol", name]` array format — NOT a bare string.

### `cycle-speed` — ResFloat (2 values)
**Used by:** `engine/entity/ambient.gc`  
**JSONC:** `["float", base_seconds, random_seconds]`  
**Notes:** Controls ambient timing. CRITICAL: `base_seconds < 0` = looping (`ambient-type-sound-loop`). `base_seconds >= 0` = one-shot interval (`ambient-type-sound`) which crashes due to engine bug (exact vs interp lookup mismatch). Always use negative base for sounds.

### `text-id` — ResUint32 (text-id enum)
**Used by:** `engine/entity/ambient.gc` (`'hint` type)  
**JSONC:** `["enum-uint32", "(text-id fuel-cell)"]`  
**Notes:** Which hint text to display. Only used for `type='hint` ambients.

### `play-mode` — ResSymbol (bare string)
**Used by:** `engine/entity/ambient.gc` (`'hint` type)  
**JSONC:** `"play-mode": "'notice"` (bare string)  
**Valid values:** `'notice`, others  
**Notes:** How the hint plays.

### `loc-name-id` — ResUint32
**Used by:** `engine/entity/ambient.gc` (`'poi` type)  
**JSONC:** `["uint32", id]`  
**Notes:** POI location name ID.

### `music` — ResFloat
**Used by:** `engine/entity/ambient.gc` (`'music` type)  
**JSONC:** `["float", value]`  
**Notes:** Music variant index (alongside `flava`).

### `flava` — ResFloat
**Used by:** `engine/entity/ambient.gc` (`'music` type)  
**JSONC:** `["float", value]`  
**Notes:** Music flava/variant selector.

### `effect-param` — ResFloat array
**Used by:** `engine/entity/ambient.gc`, `engine/sound/gsound.gc`  
**JSONC:** `["float", ...]`  
**Notes:** Extended sound parameters passed to `effect-param->sound-spec`. Controls volume, pitch, etc. per sound instance. Advanced use.

---

## Camera Entity Lumps

Camera actors (entity-actor with type `camera-marker`) use these lumps. These are read by `engine/camera/cam-layout.gc`.

### `campoints` — ResFloat pointer
**Used by:** `engine/camera/cam-layout.gc`, `cam-debug.gc`  
**JSONC:** `["float", ...]`  
**Notes:** Spline control points for camera path. Complex — used for scripted camera sequences.

### `campoints-offset` — ResVector
**Used by:** `engine/camera/cam-layout.gc`  
**JSONC:** `["vector3m", [x, y, z]]`  
**Notes:** Position offset for campoints.

### `campoints-flags` — ResUint32
**Used by:** `engine/camera/cam-layout.gc`  
**JSONC:** `["uint32", flags]`  
**Notes:** Bitfield controlling camera spline behaviour.

### `focalpull` / `focalpull-flags` — ResFloat / ResUint32
**Used by:** `engine/camera/cam-layout.gc`  
**JSONC:** `["float", near, far]` / `["uint32", flags]`  
**Notes:** Focal pull (depth of field) near/far distances and control flags.

### `spline-offset` — ResVector
**Used by:** `engine/camera/cam-layout.gc`, `cam-states.gc`  
**JSONC:** `["vector3m", [x, y, z]]`  
**Notes:** Spline path offset for camera movement.

### `interpTime` — ResFloat
**Used by:** addon-generated camera-trigger entities  
**JSONC:** `["float", 1.0]`  
**Notes:** Blend/transition time in seconds when this camera activates.

### `fov` — ResFloat (degrees)
**Used by:** addon-generated camera-trigger entities  
**JSONC:** `["degrees", 75.0]`  
**Notes:** Field of view override for this camera.

---

## Water Lumps

### `water-height` — ResFloat (simple) or multi-field
**Used by:** `sharkey`, `junglefish`, `rolling-robber`, `mistycannon` (single float); `water-vol` (multi-field via `water-height` lump type)  
**JSONC (simple):** `["meters", 5.0]` — Y coordinate of water surface  
**JSONC (water-vol full):** `["water-height", water_m, wade_m, swim_m, "(water-flags ...)", bottom_m]`  
- `water_m`: surface Y height in meters
- `wade_m`: height at which Jak transitions to wading
- `swim_m`: height at which Jak transitions to swimming  
- water-flags: bitfield (all flags are unnamed `wt00`–`wt31` in source, not yet documented)
- `bottom_m`: optional, bottom height

### `water-anim-fade-dist` — ResFloat
**Used by:** `levels/misty/mud.gc`  
**JSONC:** `["meters", 50.0]`  
**Notes:** Distance at which water animation fades.

---

## Object-Specific Lumps

### `speed` — ResFloat (context-dependent units)
**Used by:** `whirlpool` (two values: base_speed, random_range), `sunken-fish`, `sharkey`  
**JSONC:** `["float", base, range]` for whirlpool / `["meters", val]` for fish  
**Notes:** For whirlpool: both values are internal units (not meters). Two-float array.

### `distance` — ResFloat (two values for puffer)
**Used by:** `puffer` (min/max notice distance), `sunken/square-platform`, `sunken-fish`, `sharkey`  
**JSONC:** `["float", min_dist, max_dist]` for puffer — INTERNAL UNITS (not meters!)  
**Default puffer:** 57344.0 (~14m) for notice, auto for chase  
**Notes:** Puffer reads two floats — min and max distance. Both in raw internal units.

### `count` — ResUint32
**Used by:** `sunken-fish` (spawn count), `citb-drop-plat`  
**JSONC:** `["uint32", 3]`  
**Default:** 1 for sunken-fish  
**Notes:** For sunken-fish: spawns this many additional fish at the same entity position.

### `path-max-offset` — ResFloat (2 values)
**Used by:** `sunken-fish`  
**JSONC:** `["float", x_offset, y_offset]`  
**Notes:** Maximum deviation from path in X and Y axes.

### `path-trans-offset` — ResFloat (3 values)
**Used by:** `sunken-fish`  
**JSONC:** `["float", dx, dy, dz]`  
**Notes:** Translation offset applied to each path point.

### `orb-cache-count` — ResInt32
**Used by:** `orb-cache` (platform that spawns orbs)  
**JSONC:** `["int32", 20]`  
**Default:** 20  
**Notes:** Number of precursor orbs to spawn when this platform activates.

### `art-name` — ResSymbol or ResString
**Used by:** `engine/common-obs/generic-obs.gc` (launcher, springbox), `ropebridge`  
**JSONC:** `["symbol", "art-group-name"]`  
**Notes:** Overrides the art group used for this actor's skeleton/mesh.

### `spring-height` — ResFloat (meters)
**Used by:** `launcher`, `springbox`  
**JSONC:** `["meters", 40.0]`  
**Default:** 163840.0 (~40m)  
**Notes:** How high Jak is launched vertically when hitting this launcher/spring.

### `look` — ResInt32
**Used by:** `water-anim`  
**JSONC:** `["int32", 0]`  
**Default:** -1  
**Notes:** Index into `*water-anim-look*` table. Selects water animation variant (ripple style, colour, etc.).

### `collision-mesh-id` — ResInt32
**Used by:** `sunken/shover`  
**JSONC:** `["int32", 0]`  
**Notes:** ID of collision mesh group to use.

### `proximity` — ResFloat (meters)
**Used by:** `sunken/sun-iris-door`  
**JSONC:** `["meters", 5.0]`  
**Notes:** Proximity trigger distance for the iris door.

### `extra-radius` — ResFloat
**Used by:** `dark-crystal`  
**Default:** 28672.0  
**JSONC:** `["float", val]`  
**Notes:** Explosion danger radius for dark crystal.

### `crystal-light` — (actor-reference)
**Used by:** `maincave/cavecrystal-light`  
**Notes:** Links the crystal to a light source entity.

### `extra-count` — ResInt32 (2 values)
**Used by:** `gnawer`  
**JSONC:** `["int32", 5, total_money]`  
**Notes:** First value = mode (5 = money mode). Second = total money count.

### `gnawer` — ResInt32 array
**Used by:** `gnawer`  
**JSONC:** `["int32", 0, 1, 2, 3]` (indices into money spawn positions)  
**Notes:** Bit-mask encoded money spawn table for gnawer worm.

### `collide-mesh-group` — ResUint32
**Used by:** `engine/collide/collide-shape.gc`, `test-zone-obs`  
**JSONC:** `["uint32", group_id]`  
**Notes:** Which collision mesh group this entity uses.

### `shadow-mask` — ResUint8 (not the same as the process-drawable one)
**Used by:** debug display  
**Notes:** Different from process-drawable `shadow-mask`. Context-dependent.

### `bidirectional` — ResSymbol or flag
**Used by:** `plat-button`  
**Notes:** Makes the platform button bidirectional.

### `index` — ResUint32
**Used by:** `generic-obs` (level portal), `flutflut`, `racer`, `training-obs`, `villagep-obs`, `minecart`  
**JSONC:** `["uint32", 0]`  
**Notes:** General-purpose index. Meaning varies by actor type — usually an index into a table or array.

### `level` — ResSymbol
**Used by:** `engine/common-obs/generic-obs.gc` (portal)  
**JSONC:** `["symbol", "beach"]`  
**Notes:** Target level name for a level portal entity.

### `plat-type` — ResInt32
**Used by:** `citb-drop-plat`  
**JSONC:** `["int32", 0]`  
**Notes:** Drop platform type variant.

### `animation-select` — (Misty specific)
**Used by:** `misty-obs`  
**Notes:** Selects which animation set to use for misty level props.

### `particle-select` — (Misty specific)
**Used by:** `misty-obs`  
**Notes:** Selects particle effect variant.

### `center-point` — ResVector
**Used by:** `misty/mistycannon`  
**JSONC:** `["vector3m", [x, y, z]]`  
**Notes:** Cannon aim centre point.

### `mother-spider` — (maincave specific)
**Used by:** `maincave/mother-spider`  
**Notes:** Links to the mother spider entity for baby spider spawning.

### `rot-offset` — see Spatial section above

---

## Spline / Curve Lumps (keg-conveyor style)

For actors that use `curve-control` instead of `path-control`:

### `path-k` — ResFloat (N+8 values)
**Used by:** any actor using `curve-control` (e.g. `keg-conveyor`, possibly others)  
**JSONC:** `["float", 0.0, 0.0, 0.0, 0.0, 1.0, 2.0, ..., N-1, N-1, N-1, N-1]`  
**Format:** Cubic B-spline knot vector. For N path points:
- 4 lead values = 0.0
- N middle values = 0.0, 1.0, 2.0, ..., N-1
- 4 trailing values = N-1 (repeat last)
- Total entries: N + 8

**Auto-generation formula:**
```python
def make_path_k(n_points):
    lead = [0.0] * 4
    middle = [float(i) for i in range(n_points)]
    trail = [float(n_points - 1)] * 4
    return ["float"] + lead + middle + trail
```

---

## Actor-Lump Quick Reference Table

| Actor | Key Lumps | Notes |
|---|---|---|
| **fuel-cell** | `eco-info` (cell-info), `movie-pos`, `options` | `movie-pos` = jump destination; `options` skip-jump-anim |
| **buzzer** | `eco-info` (buzzer-info) | task + index encoded |
| **money** | `eco-info` (eco-info) | pickup-type money |
| **crate** | `eco-info` (eco-info), `crate-type` | crate-type = 'steel/'iron/'dark |
| **eco** (blue/green/red/yellow) | `eco-info` | pickup-type + amount |
| **launcher** | `spring-height`, `mode`, `alt-vector`, `art-name` | alt-vector xyz = dest, w = fly time (sec×300) |
| **springbox** | `spring-height`, `mode` | mode controls camera |
| **babak** | `nav-mesh-sphere` (addon), `vis-dist` | standard nav-enemy |
| **hopper** | `nav-mesh-sphere` (addon), `vis-dist` | notice-nav-radius = 1m; Jak must be on mesh |
| **swamp-bat** | `path`, `pathb`, `num-lurkers` | BOTH paths required; num-lurkers 2–8 |
| **yeti** | `path`, `num-lurkers`, `notice-dist` | spawns yeti-slave at path points |
| **snow-bunny** | `path`, `nav-mesh-sphere` | path REQUIRED, errors without |
| **puffer** | `path`, `distance` | distance = [min, max] in INTERNAL units |
| **flying-lurker** | `path` | standard path follower |
| **driller-lurker** | `path` (min 2 pts) | errors "bad path" if <2 points |
| **gnawer** | `path`, `extra-count`, `gnawer` | spline worm, complex lump setup |
| **swamp-rat-nest** | `num-lurkers` | spawns swamp-rats |
| **villa-starfish** | `path`, `num-lurkers` | spawns starfish children |
| **balloonlurker** | `path` | rigid-body platform |
| **whirlpool** | `speed` | two-float [base, range] internal units |
| **sunken-fish** | `count`, `speed`, `distance`, `path-max-offset`, `path-trans-offset` | complex fish school setup |
| **water-vol** | `water-height` (multi-field) | 4–5 field water volume |
| **water-anim** | `look`, `trans-offset`, `rotoffset` | animation variant selector |
| **orb-cache** | `orb-cache-count` | spawn count for precursor orbs |
| **citb-plat** | `scale` | non-uniform scale |
| **citb-drop-plat** | `count`, `plat-type` | drop timing |
| **plat-flip** | `delay`, `sync-percent`, `sync` | flip timing control |
| **eco-door** | `flags` | auto-close, one-way bitfield |
| **plat-button** | `bidirectional`, `camera-name` | button linking |
| **basebutton** | `extra-id`, `prev-actor` | button chain |
| **battlecontroller** | `num-lurkers`, `lurker-type`, `percent`, `mode`, `camera-name`, `final-pickup`, `pickup-type`, `max-pickup-count`, `pickup-percent`, `pathspawn`, `delay` | full combat arena setup |
| **launcherdoor** | `continue-name` | level transition trigger |
| **jungle-elevator** | `continue-name` | level transition |
| **dark-crystal** | `mode`, `extra-id` | underwater variant, crystal index |
| **gnawer** | `path`, `trans-offset`, `extra-count`, `gnawer` | |
| **sharkey** | `water-height`, `delay`, `distance`, `speed` | big fish enemy |
| **jungle-mirrors** | `alt-vector`, `rotoffset`, `text-id` | mirror target + rotation |
| **ambient (sound)** | `type`, `effect-name`, `cycle-speed` | cycle-speed MUST be negative for loop |
| **ambient (hint)** | `type`, `effect-name`, `text-id`, `play-mode` | |
| **ambient (poi)** | `type`, `effect-name`, `loc-name-id` | |
| **ambient (music)** | `type`, `effect-name`, `music`, `flava` | |
| **camera-marker** | `name`, `interesting`, `interpTime`, `fov`, `pivot`, `align`, `rot-offset`, `campoints`, `focalpull` | |
| **camera-trigger** | `name`, `interpTime`, `fov`, `interesting` | AABB trigger, addon-generated |

---

## Shared Lumps (Cross-Actor)

These lumps are read by base engine code and work on any actor:

| Lump | Applies to |
|---|---|
| `name` | ALL actors and ambients |
| `vis-dist` | All actors with visibility culling |
| `visvol` | All actors in BSP vis system |
| `eco-info` | All pickup actors |
| `options` (fact-options) | All process-drawable subclasses |
| `shadow-mask` | All process-drawable subclasses |
| `light-index` | All process-drawable subclasses |
| `lod-dist` | All actors with LOD meshes |
| `nav-mesh-sphere` | All nav-control users |
| `path` | All curve-control / path-control users |
| `sync` | All actors using sync-info timing |
| `mode` | Many actors — meaning varies per type |
| `delay` | Various timed actors |
| `speed` | Various moving actors |
| `distance` | Various range-based actors |
| `trans-offset` | Various positionally-offset actors |
| `water-height` | Water surface actors |
| `continue-name` | Level transition triggers |
| `num-lurkers` | Any spawner actor |
| `camera-name` | Any actor that can change camera |

---

## Addon Automation Status

| Lump | Currently Automated? | How |
|---|---|---|
| `name` | ✅ | auto from object name |
| `vis-dist` | ✅ | hardcoded 200m for enemies |
| `eco-info` / `cell-info` / `buzzer-info` | ✅ | pickup UI |
| `crate-type` | ✅ | dropdown |
| `nav-mesh-sphere` | ✅ | auto for nav-unsafe enemies |
| `path` / `pathb` | ✅ | waypoint empties |
| `effect-name`, `cycle-speed` | ✅ | audio panel |
| `interpTime`, `fov`, `interesting` | ✅ | camera panel |
| `num-lurkers` | ❌ | per-entity slider needed |
| `notice-dist` / `distance` | ❌ | per-entity float needed |
| `mode` | ❌ | complex — actor-dependent |
| `sync` | ❌ | platform timing panel needed |
| `delay` | ❌ | per-entity float |
| `spring-height` | ❌ | launcher panel |
| `alt-vector` | ❌ | launcher destination picker |
| `water-height` (multi) | ❌ | water vol panel needed |
| `flags` (eco-door) | ❌ | door flags checkboxes |
| `options` (fact-options) | ❌ | options checkboxes |
| `scale` | ❌ | scale inputs |
| `rot-offset` / `rotoffset` | ❌ | rotation offset |
| `continue-name` | ❌ | checkpoint picker |
| `path-k` | ❌ | auto-generate from waypoint count |
| `battlecontroller.*` | ❌ | complex — needs dedicated panel |
| *any custom lump* | ❌ | needs `og_lump_*` passthrough |

