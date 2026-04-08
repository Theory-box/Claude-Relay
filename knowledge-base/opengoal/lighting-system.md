# Lighting System — OpenGOAL Jak 1
> Source: Direct read of jak-project source, April 2026.
> Confidence: High — sourced from actual .gc files, not community inference.

---

## Overview

Jak 1's lighting pipeline has three distinct but interconnected layers:

1. **Vertex color baking** — Static per-vertex lighting stored in geometry, one set per time-of-day slot. This affects TIE/TFRAG/shrub (level geometry).
2. **Mood system** — Per-level dynamic state that drives fog, sun, sky, and actor lighting. Interpolated every frame.
3. **Light groups** — Sets of directional + ambient lights applied to foreground objects (actors, enemies, Jak). Selected per-entity and interpolated spatially.

These three systems run simultaneously and are distinct pipelines.

---

## File Map

### Core Engine (Jak1)
| File | Role |
|---|---|
| `goal_src/jak1/engine/gfx/lights-h.gc` | Type definitions: `vu-lights`, `light`, `light-group` |
| `goal_src/jak1/engine/gfx/mood/mood-h.gc` | Type definitions: `mood-fog`, `mood-lights`, `mood-sun`, `mood-context` |
| `goal_src/jak1/engine/gfx/mood/time-of-day-h.gc` | `time-of-day-proc`, `time-of-day-context`, `time-of-day-palette`, `palette-fade-control` |
| `goal_src/jak1/engine/gfx/mood/time-of-day.gc` | ToD process tick, `start-time-of-day`, `set-time-of-day`, `update-time-of-day` |
| `goal_src/jak1/engine/gfx/mood/mood.gc` | All `update-mood-*` functions, per-level mood callbacks |
| `goal_src/jak1/engine/gfx/mood/mood-tables.gc` | Static data: all mood globals, fog/light/sun tables, palette interp tables, `make-light-kit` |
| `goal_src/jak1/engine/gfx/sky/sky-h.gc` | `sky-color-hour`, `sky-color-day`, `sky-parms`, `sky-tng-data`, `*sky-drawn*`, `*cloud-drawn*` |
| `goal_src/jak1/engine/gfx/sky/sky-tng.gc` | New sky renderer (TNG) implementation |
| `goal_src/jak1/engine/level/level-h.gc` | `level-load-info` (mood, mood-func, sky, sun-fade fields); `level` type |
| `goal_src/jak1/engine/level/level-info.gc` | Per-level static config: which mood global and func each level uses |
| `goal_src/jak1/engine/game/main-h.gc` | Global toggles: `*time-of-day-effects*`, `*time-of-day-fast*`, `*weather-off*` |
| `goal_src/jak1/pc/pckernel-impl.gc` | PC-only debug: `*mood-override-debug*`, `*mood-override-table*` |

### Level-Specific Lighting Callbacks
All in `mood.gc`. One function per level, e.g. `update-mood-village1`, `update-mood-sunken`, etc. See [Per-Level Mood Callbacks](#per-level-mood-callbacks) below.

### Special In-Level Lighting
| File | Role |
|---|---|
| `goal_src/jak1/levels/maincave/cavecrystal-light.gc` | Crystal glow system using `palette-fade-controls` |
| `goal_src/jak1/levels/finalboss/light-eco.gc` | Light eco visual effect |

---

## Type Reference

### `vu-lights` — VU-Ready Light Packet
```
(deftype vu-lights (structure)
  ((direction vector 3 :inline)   ; 3 directional light directions (transposed for VU)
   (color     vector 3 :inline)   ; matching colors
   (ambient   vector :inline)))   ; ambient contribution
```
This is the final format sent to the VU for rendering actors. Transposed layout for VU efficiency.

---

### `light-group` — 4-Light Set (Pre-VU)
```
(deftype light-group (structure)
  ((dir0  light :inline)    ; primary directional
   (dir1  light :inline)    ; secondary directional
   (dir2  light :inline)    ; tertiary directional (often used for special effects: lava glow, lightning)
   (ambi  light :inline)    ; ambient
   (lights light 4 :inline :overlay-at dir0)))
```
Each `light` has: `direction` (vec4), `color` (rgba), `levels` (vec4 — x=intensity, y=sort-level).

The `mood-context` holds 8 `light-group` slots (indices 0–7). Index 0 is the base/default for the level. Higher indices are for zone-specific lighting (indoors, near torches, etc.).

The player (`*target*`) has a `draw.light-index` field. `set-target-light-index` switches which slot applies to the player. `*time-of-day-context*.target-interp` controls blend between index 0 and the selected slot.

---

### `mood-context` — Per-Level Lighting State
This is the core per-level lighting object. Each level has one (e.g. `*village1-mood*`).

```
(deftype mood-context (basic)
  ((mood-fog-table       mood-fog-table)      ; fog data for 8 ToD slots
   (mood-lights-table    mood-lights-table)   ; light data for 8 ToD slots
   (mood-sun-table       mood-sun-table)      ; sun/sky data for 8 ToD slots
   (fog-interp           sky-color-day)       ; interpolation schedule for fog
   (palette-interp       sky-color-day)       ; interpolation schedule for vertex palette
   (sky-texture-interp   sky-color-day)       ; interpolation schedule for sky texture
   (current-fog          mood-fog :inline)    ; current blended fog state
   (current-sun          mood-sun :inline)    ; current blended sun state
   (current-prt-color    vector :inline)      ; current particle color
   (current-shadow       vector :inline)      ; current shadow direction
   (current-shadow-color vector :inline)      ; shadow color
   (light-group          light-group 8 :inline) ; 8 light zones, index 0 = base
   (times                vector 8 :inline)   ; blend weights for each of 8 ToD slots (w component used)
   (sky-times            float 8)            ; sky-specific blend weights
   (itimes               vector4w 4 :inline) ; integer-packed times (used by VU)
   (state                uint8 16)           ; per-level scratch state bytes
   (num-stars            float)
   (some-byte            uint8 :offset 1939)))
```

---

### `mood-lights` — One Time-of-Day Lighting Entry
```
(deftype mood-lights (structure)
  ((direction vector :inline)   ; sun/main light direction
   (lgt-color vector :inline)   ; main light color (RGB)
   (prt-color vector :inline)   ; particle color
   (amb-color vector :inline)   ; ambient color (applied to whole model)
   (shadow    vector :inline))) ; shadow cast direction (separate from direction for engine reasons)
```
8 of these form a `mood-lights-table`, one per ToD slot.

---

### `mood-fog` — One Time-of-Day Fog Entry
```
(deftype mood-fog (structure)
  ((fog-color   vector :inline)    ; RGB fog color
   (fog-dists   vector :inline)    ; x=fog-start, y=fog-end, z=fog-max, w=fog-min
   (fog-start   meters :overlay)
   (fog-end     meters :overlay)
   (fog-max     float :overlay)
   (fog-min     float :overlay)
   (erase-color vector :inline)))  ; background clear color (sky backdrop)
```

---

### `mood-sun` — One Time-of-Day Sun Entry
```
(deftype mood-sun (structure)
  ((sun-color vector :inline)   ; sun disc/halo color
   (env-color vector :inline))) ; environment/sky ambient color (halved at ~0.5 before use)
```
Note: `env-color` is multiplied by `~0.502` in `update-time-of-day` before being applied.

---

### `time-of-day-context` — Global ToD State
```
(deftype time-of-day-context (basic)
  ((active-count         uint32)          ; number of active skies
   (interp               float)           ; desired blend weight between level 0 and level 1
   (current-interp       float)           ; actual (smoothly ramped) blend weight
   (moods                mood-context 2)  ; the two active level moods
   (current-fog          mood-fog :inline)
   (current-sun          mood-sun :inline)
   (current-prt-color    vector :inline)
   (current-shadow       vector :inline)
   (current-shadow-color vector :inline)
   (light-group          light-group 9 :inline) ; 9 zones (8 level + 1 extra)
   (title-light-group    light-group :inline)
   (time                 float)           ; current hour (0.0–24.0)
   (target-interp        float)           ; blend for player-specific lighting
   (erase-color          rgba)
   (num-stars            float)
   (light-masks-0        uint8 2)
   (light-masks-1        uint8 2)
   (light-interp         float 2)
   (sky                  symbol)          ; #t if any loaded level has sky=true
   (sun-fade             float)
   (title-updated        symbol)))
```
Global instance: `*time-of-day-context*`

---

## The Time-of-Day Process

`time-of-day-proc` is a GOAL process (like an actor) that ticks forward a simulated clock. It owns:
- A full calendar: year/month/week/day/hour/minute/second/frame
- `time-of-day` (float, 0.0–24.0) — the primary value everything reads
- `time-ratio` — multiplier. Normal = `300.0` (real-time). Fast = `18000.0` (60x speed). Zero = frozen.
- Particle spawn controllers for stars, sun, green-sun, moon

**Clock math:** 300 internal frames = 1 real second. Ticks via `*display*.time-adjust-ratio` for framerate independence.

### Key API
```goal
(start-time-of-day)              ; spawn/restart the ToD process
(set-time-of-day 14.5)           ; set hour directly (14:30 = 2:30pm)
(time-of-day-setup #t)           ; toggle ToD on/off
```

### Sun/star visibility thresholds
- Stars appear: hour >= 19 OR hour <= 5 (night), AND `num-stars > 45`
- Sun appears: 6.25 <= hour < 18.75 AND `sun-fade != 0`
- Green sun appears: hour >= 21.75 OR hour <= 10.25 AND `sun-fade != 0`

---

## Global Toggles

Defined in `engine/game/main-h.gc` and `pc/pckernel-impl.gc`:

| Global | Default | Effect |
|---|---|---|
| `*time-of-day-effects*` | `#t` | Gates all dynamic lighting effects (flames, lightning, caustics, etc.) inside mood callbacks |
| `*time-of-day-fast*` | `#t` | If true, ToD starts at 60x speed (time-ratio = 18000); otherwise real-time |
| `*weather-off*` | `#f` | Reverses snow weather (in snow mood callback); when true, removes weather |
| `*mood-override-debug*` | `#f` | PC debug: `'copy` or `'mult` to manually set `times` blend weights |
| `*mood-override-table*` | `float[8]` | PC debug: the 8 weights to apply when override is active |

---

## How Vertex Color Baking Works (Blender → Game)

Level geometry (TIE/TFRAG/shrub) stores **8 sets of vertex colors**, one per time-of-day slot. These are baked as **vertex color attributes** in Blender.

### Attribute Names
| Attribute | Slot |
|---|---|
| `_SUNRISE` | 0 — Dawn |
| `_MORNING` | 1 — Morning |
| `_NOON` | 2 — Midday |
| `_AFTERNOON` | 3 — Afternoon |
| `_SUNSET` | 4 — Dusk |
| `_TWILIGHT` | 5 — Twilight |
| `_EVENING` | 6 — Night |
| `_GREENSUN` | 7 — Green sun (alternate sky) |

The game interpolates between adjacent slots at runtime using `time-of-day-interp-colors` (implemented as `def-mips2c` — it's a VU-coded function). The `mood-context.times[n].w` float weights control the blend.

**The `itimes` field** in `mood-context` is the integer-packed version of `times` (for VU use), recomputed every frame by `update-mood-itimes`. The packing applies `vftoi12` (fixed point 12) after squaring each weight — this is a non-linear response curve.

---

## The Mood System — Frame-by-Frame Flow

Each frame, `update-time-of-day` (in `time-of-day.gc`) does the following:

1. Iterates over `*level*` (up to 2 active levels).
2. For each active level, calls `level.mood-func(level.mood, time, level-index)`.
3. Computes an interpolation weight `current-interp` based on camera distance to each level (`level-distance`). Smooth ramp — `0.0033` per frame (NTSC) or `0.00396` (PAL). Teleport snaps it instantly.
4. Blends `moods[0]` and `moods[1]` together into the global `*time-of-day-context*` using `vector4-lerp!` across fog, sun, prt-color, shadow, and all 8 light-groups.
5. Writes final fog values into `*math-camera*` (`fog-start`, `fog-end`, `fog-max`, `fog-min`).
6. Updates player light index blending via `target-interp`.
7. Runs `make-sky-textures` for both levels.
8. Sets `sky-base-polygons` erase color (the solid background behind the sky geometry).

### Special Level Blend Hack
There is a hardcoded hack: when level0=`village2` and level1=`sunken` (or vice versa) AND camera is above y=0, the blend always uses village2's mood. This prevents the sunken underwater look from bleeding into village2.

---

## Per-Level Mood Callbacks

Each level has a `mood-func` registered in `level-info.gc`, pointing to a function in `mood.gc`.

### Standard callback structure
```goal
(defun update-mood-LEVELNAME ((ctx mood-context) (time float) (level-index int))
  (update-mood-fog ctx time)           ; interpolates fog from fog-table
  (update-mood-sky-texture ctx time)   ; interpolates sky-times weights
  (clear-mood-times ctx)               ; zeros all 8 times.w
  (update-mood-palette ctx time level-index) ; sets times.w and light-group[0] from lights-table
  (when *time-of-day-effects*
    ... ; dynamic effects: flames, lightning, caustics, lava, etc.
  )
  (update-mood-itimes ctx)             ; packs times into itimes for VU
  0
  (none))
```

### Cave/interior variant (no ToD, always same slot)
```goal
(defun update-mood-maincave (...)
  (clear-mood-times ctx)
  (set! (-> ctx times 0 w) 1.0)       ; always use slot 0 only
  (update-mood-quick ctx 0 0 0 level-index)  ; snap to single slot
  ...
)
```
`update-mood-quick` is a fast path that snapshots a single slot directly without interpolation.

### All registered level callbacks
| Level | mood-func | mood global |
|---|---|---|
| training | `update-mood-training` | `*training-mood*` |
| village1 | `update-mood-village1` | `*village1-mood*` |
| beach | `update-mood-village1` | `*beach-mood*` |
| jungle | `update-mood-jungle` | `*jungle-mood*` |
| jungleb | `update-mood-jungleb` | `*jungleb-mood*` |
| misty | `update-mood-misty` | `*misty-mood*` |
| firecanyon | `update-mood-firecanyon` | `*firecanyon-mood*` |
| village2 | `update-mood-village2` | `*village2-mood*` |
| swamp | `update-mood-swamp` | `*swamp-mood*` |
| sunken | `update-mood-sunken` | `*sunken-mood*` |
| rolling | `update-mood-rolling` | `*rolling-mood*` |
| ogre | `update-mood-ogre` | `*ogre-mood*` |
| village3 | `update-mood-village3` | `*village3-mood*` |
| snow | `update-mood-snow` | `*snow-mood*` |
| maincave | `update-mood-maincave` | `*maincave-mood*` |
| darkcave | `update-mood-darkcave` | `*darkcave-mood*` |
| robocave | `update-mood-robocave` | `*robocave-mood*` |
| lavatube | `update-mood-lavatube` | `*lavatube-mood*` |
| citadel | `update-mood-citadel` | `*citadel-mood*` |
| finalboss | `update-mood-finalboss` | `*finalboss-mood*` |
| default (fallback) | `update-mood-default` | `*default-mood*` |

`*default-mood*` uses village1's fog/light/sun tables and is used for any level without a valid mood.

---

## Dynamic Lighting Effects (inside `*time-of-day-effects*`)

These are all functions in `mood.gc` used inside level callbacks:

### `update-mood-flames`
Flickering fire light effect. Oscillates a specific `times[n].w` weight using random timers and sin. Parameters: start slot index, count, state-byte offset, base brightness, amplitude, speed.

### `update-mood-lightning`
Strobing lightning flash using preset flash curves (`*flash0*` through `*flash7*`). Controls sky brightness (`sky-times`) and optionally a light slot (`times[n].w`). Includes thunder sound playback with camera-distance-based volume. Lightning frames advance every 2 real frames.

### `update-mood-light`
Smooth fade-in/fade-out of a single light slot using a cosine curve. Uses time-of-day to determine if the light is "day" (off) or "night" (on). Driven by `state` bytes in `mood-context`.

### `update-mood-lava`
Animated lava glow using `dir2` light in the light group. Randomized scale with sin-based oscillation. Sets direction straight down `(0,-1,0)`, color orange `(1, 0.364, 0, 1)`.

### `update-mood-caustics`
Underwater caustic light ripple — cycles through 4 sequential `times` slots using a counter. Creates a moving highlight effect on geometry.

### `update-mood-interp`
Blends two `mood-context` objects into a third. Used when a level needs to transition between two distinct lighting states (e.g. ogre boss approaching the lava pit).

---

## Fog System

Fog is driven by `mood-fog` data interpolated from the fog table. Final values are written directly into `*math-camera*`:
- `fog-start` — distance fog begins
- `fog-end` — distance fog is full
- `fog-max` — maximum fog density (0.0–255.0 scale)
- `fog-min` — minimum fog density at far distances

The `erase-color` sets the sky background clear color (the solid fill behind all sky geometry).

`*fog-color*` global (RGBA) is also set from the current fog for use by renderers.

### Swamp fog override
`update-mood-swamp` contains a special case: it modifies the interpolated fog color and `fog-min` based on the camera's rotation vector z-component — this simulates looking "into" dense swamp fog when the camera pitches down.

---

## Sky System

### `sky-color-day` / `sky-color-hour` — Interpolation Schedule
This is the schedule that controls WHICH two ToD slots are active for any given hour. Each `sky-color-hour` entry has:
- `snapshot1` — first active slot index
- `snapshot2` — second active slot index (may equal snapshot1 = no blend)
- `morph-start` — blend weight at the start of this hour
- `morph-end` — blend weight at the end of this hour

Three separate schedules exist per level (as `sky-color-day` arrays):
- `fog-interp` — schedule for fog interpolation
- `palette-interp` — schedule for vertex color palette (geometry lighting)
- `sky-texture-interp` — schedule for sky texture selection

Different levels can share these tables — most share `*default-interp-table*` or `*village1-palette-interp-table*`.

### TNG Sky Renderer
`sky-tng.gc` implements the "TNG" (The Next Generation) sky renderer used in-game. It writes sky and cloud textures into VRAM each frame. `*sky-drawn*` and `*cloud-drawn*` are set when textures are ready. `update-sky-tng-data(time)` updates the sky renderer state for the current hour.

### `sky-parms`
Contains orbit data for sun/moon motion, light group presets for sun-lit and moon-lit environments, and default VU lights.

---

## Level Configuration (level-info.gc)

Each level entry in `level-info.gc` has:
```
:mood '*LEVELNAME-mood*     ; symbol pointing to the mood-context global
:mood-func 'update-mood-LEVELNAME  ; symbol pointing to the update function
:sky #t / #f               ; whether this level contributes a sky
:sun-fade 1.0 / 0.5 / etc  ; how visible the sun is (0.0 = no sun, 1.0 = full)
```

`sun-fade` controls sun disc visibility. Notable values:
- misty: `0.25` (overcast feel)
- snow: `0.5`
- most open levels: `1.0`
- caves/interior: field absent (defaults to 0)

---

## Zone-Based Lighting (Light Groups)

`mood-context.light-group` has 8 slots. Slot 0 is the base for the whole level. Slots 1–7 are used for sub-zones (interiors, near special objects, etc.).

Each `update-mood-*` function manually configures the additional slots. Examples:
- `village1`: slots 1–7 are 7 different interior/torch zones, each defined by proximity radius. When Jak enters a zone, `set-target-light-index(n)` is called and `target-interp` is ramped to 1.0.
- `village2`: custom slot 5 uses a downward-pointing orange light `(0.242, -0.970, 0)` for torch glow.
- `sunken`: slot 1 uses `update-light-kit` (copies ambi from slot 0) for depth-adjusted ambient; slot 2 has animated caustic colors.

### `update-light-kit`
Copies the ambient color from one light group to another, scaling by a factor:
```goal
(defun update-light-kit (target-group source-light scale)
  (set! (-> target-group ambi color) source-light.color)
  (set! (-> target-group ambi levels x) (* source-light.levels.x scale)))
```
Used extensively to derive interior lighting from the base ambient.

### `make-light-kit`
Creates a standard 2-directional-light setup on a group with a rotation offset (in angular units), adjustable intensities for dir0/dir1/dir2. Default colors are warm white `(0.8, 0.775, 0.7)`.

---

## `palette-fade-controls` — Actor-Driven Palette Modification

```
(deftype palette-fade-control (structure)
  ((trans      vector :inline)   ; world position of the controlling actor
   (fade       float)            ; 0.0–1.993 blend intensity
   (actor-dist float)))          ; distance to nearest valid actor
```

8 slots, global `*palette-fade-controls*`. Reset every frame in `update-time-of-day`. Actors write into slots using `set-fade!`. The `times[n].w` weights in the mood callback are then set from `(-> *palette-fade-controls* control n fade)`.

Used by: cave crystals, deadly water (lpc), lavatube glow, citadel shield, finalboss.

---

## Shadows

Shadows in Jak 1 are geometry-based blobs rendered by `shadow.gc` / `shadow-cpu.gc` / `shadow-vu1.gc`. The *direction* of shadow casting is driven by `mood-context.current-shadow` — a normalized vector set from the active `mood-lights` entry's `shadow` field, interpolated like all other mood data.

In `update-time-of-day`, a clamp is applied: if shadow direction y < 0.9063, the shadow direction is forced to a minimum y of -0.9063 (prevents nearly-horizontal shadows that would look wrong).

---

## Implementation Notes for Custom Levels

### Minimum viable setup
A custom level needs in `level-info.gc`:
```
:mood '*village1-mood*          ; safest default — uses village1 tables
:mood-func 'update-mood-village1
:sky #t                         ; or #f for interior
:sun-fade 1.0                   ; or lower for overcast
```

### Adding time-of-day lighting to a custom level
1. **Geometry**: bake vertex colors into the 8 `_SUNRISE` / `_MORNING` / etc. attributes in Blender (exporter handles mapping).
2. **Actors**: define a `mood-lights-table` and `mood-fog-table` with 8 entries each. Copy from an existing level as a base.
3. **Register**: add a `(define *mylevel-mood* ...)` in `mood-tables.gc`, assign the tables, and write a `(defun update-mood-mylevel ...)` in `mood.gc`.
4. **Connect**: set `:mood '*mylevel-mood*` and `:mood-func 'update-mood-mylevel` in `level-info.gc`.

### Adding interior light zones
1. Add `(update-light-kit (-> ctx light-group N) (-> ctx light-group 0 ambi) 1.0)` for each zone N in your mood function.
2. Override any directional lights on that zone with custom direction/color.
3. In gameplay code or a trigger entity, call `(set-target-light-index N)` and set `(-> *time-of-day-context* target-interp) 1.0` (or blend from 0→1 over a few frames).

### Adding dynamic effects
- **Torches/fire**: call `(update-mood-flames ctx slot-start slot-count state-byte-offset base-intensity amplitude speed)`.
- **Lightning**: call `(update-mood-lightning ctx sky-slot num-sky-slots state-byte light-slot intensity realtime?)`.
- **Lava glow**: call `(update-mood-lava ctx slot state-byte use-palette?)`.
- All require `(when *time-of-day-effects* ...)` wrapper.

---

## Open Questions / Research Gaps
- ⚠ How `time-of-day-interp-colors` (mips2c) packs/unpacks palette data internally — exact VU1 program not fully traced.
- ⚠ How `make-sky-textures` builds the sky texture from `sky-times` — sky-tng.gc is long and complex.
- ⚠ Relationship between `*sky-parms*` orbit data and actual sun/moon particle positions — partially implemented in old sky renderer code.
- ⚠ How `palette-interp` vs `fog-interp` schedules interact with `sky-texture-interp` — they can use different schedules for the same level, but exact visual effect of mismatching them is unclear.
- ⚠ `prt-color` field: confirmed it drives particle color, but exact which particle systems respect it is not fully traced.
- ⚠ Whether a custom level can safely define entirely new fog/light/sun table values without impacting other levels using the same pointers — tables should be independent per-level globals, but needs testing.
