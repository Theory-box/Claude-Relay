# OpenGOAL Water System — Complete Reference

> Researched from jak-project source. Covers: swimmable water, water shaders/animation, flowing water, and water enemies.

---

## Overview

The water system has three distinct layers:

| Layer | What it does | Key type |
|---|---|---|
| **Collision / gameplay** | Tells the engine Jak is wading or swimming; triggers drowning, damage, etc. | `water-vol` / `water-control` |
| **Visual** | Animated water surface mesh with ripple shader | `water-anim` |
| **Enemies** | Enemies that live in or attack from water | `sharkey` (nav-enemy) |

Each layer is independent. A water-vol defines the gameplay zone. A water-anim defines what the surface looks like. They are placed separately; the visual mesh does **not** have to match the collision box exactly.

---

## 1. Swimmable Water (`water-vol`)

### How it works

`water-vol` is a process spawned from an entity actor. It maintains a `vol-control` (an AABB) and each frame checks whether `*target*` (the player) is inside it. When they enter, it copies its height/behavior parameters onto the player's `water-control` struct and sends `'wade` or `'swim` events. When the player exits it clears those flags.

### Entity lump properties

```
'water-height  float[2..5]   required
    [0] water-height   — Y coordinate of the water surface (world space)
    [1] wade-height    — how far below surface before wade triggers
    [2] swim-height    — how far below surface before swim triggers
    [3] flags          — (optional) water-flags bitmask (see below)
    [4] bottom-height  — (optional) kill-plane depth

'attack-event  symbol         optional, default = 'drown
```

### `attack-event` values

| Value | Effect |
|---|---|
| `drown` | Default. Sends a shove attack below a depth threshold. |
| `drown-death` | Instant death. |
| `lava` | Instant death (lava damage type). |
| `dark-eco-pool` | Instant death (dark eco type). |
| `heat` | Applies heat over time (`'heat` event, 10 units/frame). |
| `#f` | No attack — purely cosmetic / wade-only water. |

### Water flags (bitmask for lump[3])

The engine sets some flags automatically from the other lump values; you can OR additional ones in manually.

| Flag | Bit | Meaning |
|---|---|---|
| `wt01` | 0 | Player is currently inside this volume (set at runtime) |
| `wt02` | 1 | Enable wading (auto-set if wade-height > 0) |
| `wt03` | 2 | Enable swimming (auto-set if swim-height > 0) |
| `wt04` | 3 | Entity uses bobbing on water surface |
| `wt05` | 4 | Spawn splash particles on entry/exit |
| `wt08` | 7 | Use ocean height (open-ocean wave offsets) |
| `wt17` | 16 | Bottom-kill: attack player if below threshold Y (used in Sunken) |
| `wt18` | 17 | Mud flag — player walks on top (no wade/swim), applies mud-specific logic |
| `wt19` | 18 | Water is currently deadly/electrified (used in Sunken electric water) |
| `wt20` | 19 | Use ripple height from attached water-anim for bobbing |
| `wt21` | 20 | Disable water while player is being grabbed |
| `wt22` | 21 | Emit wake/wave particles when moving on water surface |
| `wt23` | 22 | Water is active/visible (always set by init; clear to deactivate) |

### Minimal working example (level JSONC entity)

```jsonc
{
  "trans": [X, Y, Z],          // position of the vol
  "etype": "water-vol",
  "game_task": 0,
  "vis_id": 0,
  "aid": <unique_id>,
  "lump": {
    "water-height": [
      Y_SURFACE,   // water surface Y (same as trans Y usually)
      -0.5,        // wade starts 0.5m below surface
      -1.5         // swim starts 1.5m below surface
    ],
    "bsphere": [X, Y, Z, RADIUS],
    "attack-event": "drown"
  }
}
```

**Important:** The vol AABB is derived from the `bsphere` lump, not a separate box. Make it large enough to cover the visual water area. The engine expands the vol automatically.

### Lump-only water flags (set via flag index in water-height[3])

To make the water instantly kill with lava damage instead of drown:
```jsonc
"water-height": [Y, -0.5, -1.5, 0],  // flags = 0, let attack-event handle it
"attack-event": "lava"
```

To add bobbing + splash effects:
```jsonc
"water-height": [Y, -0.5, -1.5, 48]  // wt04 (8) | wt05 (16) | wt23 (auto) = 48
```
*(wt23 = 0x400000 = bit 22, but it's always auto-added; practical bits to set manually: wt04=8, wt05=16, wt08=128, wt17=131072, wt19=524288, wt22=4194304)*

---

## 2. Water Shaders and Visual Water (`water-anim`)

### Architecture

`water-anim` extends `water-vol`. It is both a gameplay water volume **and** a visible animated mesh. The mesh is a skeletal (MERC) actor with a looping animation, and a `ripple-control` that deforms its vertices each frame using additive sine waves. This is how all water in the base game gets its "rippling" look.

The visual quality depends on:
1. **The mesh** — authored in Blender, exported as a level art asset (merc geometry)
2. **The skeleton animation** — drives any scrolling/flowing motion
3. **The ripple-control waveform** — sine wave overlay on top of the mesh

### Placing water-anim in a level

Each water-anim instance picks its mesh and animation from the `water-look` enum via a `'look` lump. There are **48 built-in looks** you can reuse:

```
0  water-anim-sunken-big-room
1  water-anim-sunken-first-room-from-entrance
2  water-anim-sunken-qbert-room
...
14 water-anim-maincave-water-with-crystal
15 water-anim-maincave-center-pool
20 water-anim-robocave-main-pool
21-31 water-anim-misty-mud-* (mud variants)
33 water-anim-ogre-lava
34 water-anim-jungle-river        ← flowing water
35 water-anim-village3-lava
36 water-anim-training-lake
38 water-anim-rolling-water-back  ← rolling hills water
39 water-anim-rolling-water-front
42 water-anim-lavatube-energy-lava
43-46 water-anim-village1-rice-paddy-*
47 water-anim-village2-bucket
```

### Entity lump properties for water-anim

```
'look          int     required — index into water-look enum (0–47)
'water-height  float[2..5]     — same as water-vol (gameplay volumes)
'trans-offset  float[3]        — optional XYZ offset applied after placement
'rotoffset     float           — optional Y-axis rotation offset (radians)
'water-anim-fade-dist  float[2] — [close-fade, far-fade] for ripple rendering
'attack-event  symbol          — inherited from water-vol
```

### Minimal water-anim JSONC

```jsonc
{
  "trans": [X, Y, Z],
  "etype": "water-anim",
  "game_task": 0,
  "vis_id": 0,
  "aid": <unique_id>,
  "lump": {
    "look": 36,              // training-lake look
    "water-height": [Y, -0.5, -1.5],
    "bsphere": [X, Y, Z, RADIUS],
    "attack-event": "drown"
  }
}
```

### How the ripple works (shader detail)

The ripple system deforms merc mesh vertices on the VU1 (vector unit). A `ripple-wave-set` defines up to 4 sine wave passes, each with:

```lisp
(new 'static 'ripple-wave
  :scale  40.0   ; amplitude in engine units
  :xdiv   1      ; x-axis frequency divider (negative = reversed)
  :zdiv   0      ; z-axis frequency divider
  :speed  1.5)   ; animation speed multiplier
```

`normal-scale` on the wave-set controls overall ripple intensity (affects surface normals → lighting shimmer).

Example wave sets from the game:

```lisp
;; Normal water (sunken / training)
:count 3 :normal-scale 1.0
wave[0]: scale 40.0 xdiv  1       speed 1.5
wave[1]: scale 40.0 xdiv -1 zdiv 1 speed 1.5
wave[2]: scale 20.0 xdiv  5 zdiv 3 speed 0.75

;; Mud (slower, same structure)
:count 3 :normal-scale 1.0
wave[0]: scale 40.0 xdiv  1       speed 1.5
wave[1]: scale 40.0 xdiv -1 zdiv 1 speed 1.5
wave[2]: scale 20.0 xdiv  5 zdiv 3 speed 0.75

;; Dark eco pool (heavy distortion)
:count 3 :normal-scale 8.57
wave[0]: scale 14.0 xdiv  1       speed 1.0
wave[1]: scale  5.25 xdiv -1 zdiv 1 speed 4.0
wave[2]: scale  0.7  xdiv  5 zdiv 3 speed 2.0
```

**Custom `water-anim` subtype** — to use a custom ripple waveform you must subtype `water-anim`, override `water-vol-method-22`, create a `ripple-control`, assign your `ripple-wave-set`, and attach it to `(-> this draw ripple)`. See `sunken-water.gc` or `mud.gc` for the pattern.

### Ambient sound

`water-anim-look` entries include an optional `ambient-sound-spec`. Built-in looks that have sound:
- Looks 0–13 (sunken): `"water-loop"` with varying fo-min/fo-max
- Looks 10, 13–19, 20, 32, 41 (dark eco): `"darkeco-pool"`
- Look 40 (helix dark eco): `"helix-dark-eco"`

Most mud and lava looks have `#f` (no ambient sound).

### Visibility culling

`water-anim` hides itself when the camera Y drops more than 8192 units (2m) below the water surface — this is the underwater hide threshold. The `ripple-control` has its own `close-fade-dist` / `far-fade-dist` fade range for the deformation effect.

---

## 3. Flowing Water

### How "flowing" is achieved in the engine

There is **no shader-based UV scroll** for water in Jak 1. "Flowing" water is achieved in two ways:

**Method A: Animated mesh (skeleton animation)**
The water mesh is a skeletal actor. The "flow" is a looping joint animation that deforms/scrolls the mesh geometry. Examples:
- Jungle River (look 34): looping anim index 3
- Rolling Hills water (looks 38, 39): looping anim index 4
- Village3 lava (look 35): looping anim index 3

All you need to do is pick the right `'look` value for a pre-existing flowing water mesh. The flow direction and speed are baked into the animation.

**Method B: Moving process (helix-water)**
`helix-water` in Sunken is a `process-drawable` that physically moves its transform Y upward over time when triggered (a rising water mechanic). It has a `transv-y`, `start-y`, and `end-y`. The water visual moves in world space. This is for scripted "water rising" sequences, not decorative flow.

### Custom flowing water (practical approach)

To get flowing water in a custom level today:
1. Pick a `water-anim` look that already has a flowing animation (34, 35, 38, 39, 42).
2. The mesh bounds of those looks are fixed (they're level-specific skeletons). You can't resize them.
3. For truly custom flowing geometry, you would need to author a new `defskelgroup` and add it to `*water-anim-look*` — this requires engine changes (new GOAL code + new art asset pipeline). This is not yet supported in the addon.

**Recommendation for modders:** Use look 34 (jungle river) or 38/39 (rolling water) for natural-looking flowing water. Position and rotate the entity to align the flow direction. Use `'trans-offset` and `'rotoffset` lumps to fine-tune.

---

## 4. Enemies That Use Water

### The `sharkey` (water predator)

**Type:** `nav-enemy` — uses the standard nav-enemy chase/attack state machine.
**Tpage group:** `Beach`, `Training`, `Village2`, `Jungle`, `Misty`, `Swamp`, `Village1`
**Asset:** `sharkey-ag.go` (must be in the level's DGO)

**Behavior summary:**
- Hides below `y-min` (12m below water surface by default) in `nav-enemy-idle`
- Watches for `*target*` on the navmesh — only activates if player is near a nav point
- On notice: teleports to a spawn point behind the player, rises to `y-max` (2m below surface)
- Chases player in `nav-enemy-chase` using `nav-control` (navmesh navigation)
- Attacks by launching along a ballistic arc (`setup-from-to-duration!`) — does a chomping jump
- After attack, sinks back down and hides again

**How water interacts with sharkey:**
Sharkey creates its own `water-control` (internal to the process, not a separate `water-vol` entity). It reads `'water-height` from its own entity lump to know where the surface is. It creates splash particles (`create-splash`) as it breaches and re-enters.

**Entity lump properties for sharkey:**

```
'water-height  float   required — Y of the water surface (must match water-vol)
'scale         float   default 1.0 — scale factor (affects size and attack sphere)
'delay         float   default 1.0 — multiplier on reaction-time (300 frames base)
'distance      float   default 30m — spawn distance (how far behind player it appears)
'speed         float   default 12m/s — chase speed
```

**Required navmesh:** Sharkey needs a navmesh in the water area. It uses `nav-control` to move. Without a navmesh it won't chase. The navmesh faces just need to cover the water surface footprint.

**Minimal sharkey entity JSONC:**

```jsonc
{
  "trans": [X, Y_SURFACE_MINUS_12m, Z],  // spawn below surface
  "etype": "sharkey",
  "game_task": 0,
  "vis_id": 0,
  "aid": <unique_id>,
  "lump": {
    "water-height": Y_SURFACE,
    "bsphere": [X, Y, Z, 6.0],
    "scale": 1.0,
    "delay": 1.0,
    "distance": 30.0,
    "speed": 12.0
  }
}
```

**Attack mode:** `'sharkey` — this is a unique attack type. It uses `attack-invinc` (bypasses invincibility frames). After a hit, sharkey grabs the player briefly (`send-event *target* 'end-mode` to release).

**Notice condition:** Sharkey checks `sharkey-notice-player?` every frame in idle:
- Target's Y must be below `y-max` (i.e., player is at or near water surface)
- Player must not be in `'racer` mode
- Player's shadow position must be near the navmesh

### The `swamp-rat` (water-adjacent enemy)

`swamp-rat` creates a `water-control` on itself with flags `wt01` only — it can enter/wade through water but doesn't trigger swim or special behavior. It's a nav-enemy that navigates over shallow water. Not a "water enemy" in the same sense as sharkey.

### `dark-eco-pool` / `mud` (hazard volumes that aren't enemies)

These are `water-anim` subtypes that kill on contact:
- `dark-eco-pool`: sets `attack-event = 'dark-eco-pool` (instant death)
- `mud`: uses `wt18` flag — player walks on surface, doesn't wade
- `sunken-water`: `wt19` flag = electrically deadly; can sync to a `sync-info` timer (periodic on/off)

---

## 5. Water Type Decision Tree

```
Do you need gameplay (Jak swims/wades/drowns)?
  └─ YES → use water-vol or water-anim (water-anim gives you visual + gameplay in one)
           Set 'water-height with wade-height and swim-height values
           Set 'attack-event for damage type

Do you need a visible animated water surface?
  └─ YES → use water-anim, pick a 'look (0–47)
           For still water pools: looks 0–13 (sunken), 15–20 (cave), 36 (training)
           For flowing river: look 34 (jungle), 38/39 (rolling)
           For lava: look 33 (ogre), 35 (village3), 42 (lavatube)
           For mud: looks 21–31 (misty mud)
           For dark eco: looks 10, 13, 14–19, 20, 32, 40, 41

Do you need an enemy that lives in/attacks from water?
  └─ YES → use sharkey
           Requires: navmesh over water, 'water-height lump matching the water-vol

Do you need electrified/hazard water that toggles on/off?
  └─ YES → use sunken-water subtype (requires custom GOAL code — not directly spawnable
           from the addon yet). Or use 'attack-event 'lava / 'dark-eco-pool on a
           standard water-anim for always-deadly variants.
```

---

## 6. Known Limitations for Custom Levels

1. **water-anim meshes are level-specific** — the 48 looks use art assets baked into specific level DGOs (SUN, MIS, ROB, VI1, etc.). Using look 34 (jungle river) in a non-jungle level requires that level to load `JUN.DGO` or the equivalent art assets.

2. **No custom ripple waveforms from entity lumps** — ripple parameters are hardcoded in GOAL subtypes. To change ripple behavior you must write a new GOAL type.

3. **Swimmable water + water-anim must be coordinated manually** — if you use a separate `water-vol` for gameplay and a `water-anim` for visuals, their Y positions and bsphere bounds must match or the player will swim through invisible water / stand on visible water.

4. **Sharkey requires a navmesh** — place navmesh polys over the water surface. Without this sharkey won't chase.

5. **One water-vol active at a time** — the engine only stores one active water volume handle on the player (`(-> *target* water volume)`). If two water-vols overlap, the second one won't activate until the player exits the first.

---

## 7. Addon Support Status (as of v1.4.0)

| Feature | Addon support |
|---|---|
| Place `water-vol` entities | ✅ Via entity picker (Props & Objects) |
| Place `water-anim` entities | ✅ Via entity picker |
| Set `'look` lump | ❌ Not yet — must edit JSONC by hand |
| Set `'water-height` lumps | ❌ Not yet — must edit JSONC by hand |
| Place `sharkey` | ✅ Via Enemies sub-panel |
| Set sharkey lumps (scale, delay, speed) | ❌ Not yet — must edit JSONC by hand |
| Navmesh for water area | ✅ Via standard navmesh link |

**Recommended workflow today:**
1. Place the entity from the addon (gets you position/aid/bsphere)
2. Open the generated `entity.jsonc` and manually add water-specific lumps
3. Rebuild and test in-engine

---

## Custom Level Implementation (Blender Addon)

### Working approach (confirmed working as of feature/water merge)

Use `WATER_` prefixed mesh cubes. Place via **Spawn → Water Volumes → Add Water Volume**.

**Key facts learned from debugging:**

### 1. vol-h.gc engine patch required
Vanilla `vol-h.gc` uses `'exact 0.0` to look up the `'vol` lump tag. The custom level C++ builder stores ALL tags at `DEFAULT_RES_TIME = -1000000000.0`. These never match, so `pos-vol-count` stays 0 and `point-in-vol?` always returns `#f`.

**Fix:** Change two lines in `goal_src/jak1/engine/geometry/vol-h.gc`:
```lisp
; Line ~50 — change 'exact to 'base
(s4-0 (-> ((method-of-type res-lump lookup-tag-idx) (the-as entity-actor s5-1) 'vol 'base 0.0) lo))
; Line ~64 — same for cutoutvol
(s4-1 (-> ((method-of-type res-lump lookup-tag-idx) (the-as entity-actor s5-2) 'cutoutvol 'base 0.0) lo))
```
This fix is also present in LuminarLight's LL-OpenGOAL-ModBase ("Hat Kid water hack").

### 2. Vol plane normals must point OUTWARD
`point-in-vol?` returns `#f` (outside) when `dot(P,N) - w > 0`. Normals must face away from the box centre. Inside = negative side of all planes.

Correct plane format for an AABB (xmin/xmax in game metres):
```json
["vector-vol",
  [0,  1, 0,  surface],   // top:   P.y <= surface
  [0, -1, 0, -bottom],    // floor: P.y >= bottom
  [1,  0, 0,  xmax],      // +X:    P.x <= xmax
  [-1, 0, 0, -xmin],      // -X:    P.x >= xmin
  [0,  0, 1,  zmax],      // +Z:    P.z <= zmax
  [0,  0,-1, -zmin]       // -Z:    P.z >= zmin
]
```

### 3. water-height lump flags must be explicit
`logior! wt23` always runs unconditionally before the `(zero? flags)` auto-set check. So `wt02` (wade) and `wt03` (swim) must be set explicitly in the lump:
```json
["water-height", surface_m, wade_depth_m, swim_depth_m, "(water-flags wt02 wt03 wt05 wt22)"]
```

### 4. water.o is in GAME.CGO
Do NOT inject `water.o` into the custom DGO — it's already always loaded. Use `in_game_cgo: True` in ETYPE_CODE.

### 5. WATER_ mesh must be invisible
Set `set_invisible = True` on the mesh object so the level builder skips it for geometry/collision export.

### 6. wade/swim are depths, not absolute Y
The engine computes: `surface - wade_lump >= jak_foot_y`
So `wade_lump = 0.5` means "wade when 0.5m below surface". NOT an absolute world Y.

### Debugging via REPL
```lisp
; Check process exists
(process-by-name "water-vol-0" *active-pool*)

; Check vol loaded correctly  
(let ((w (the water-vol (process-by-name "water-vol-0" *active-pool*))))
  (format #t "flags:~d vol-count:~d~%" (-> w flags) (-> w vol pos-vol-count)))
; vol-count must be > 0. If 0 = vol-h.gc patch not applied.

; Check point-in-vol directly
(let ((w (the water-vol (process-by-name "water-vol-0" *active-pool*))))
  (format #t "in-vol:~A~%" (point-in-vol? (-> w vol) (-> *target* control trans))))

; Check if Jak has water volume assigned
(format #t "volume:~A~%" (-> *target* water volume))

; Get Jak's position
(format #t "pos: ~m ~m ~m~%" (-> *target* control trans x) (-> *target* control trans y) (-> *target* control trans z))

; List all lump tags on the entity
(let ((w (the water-vol (process-by-name "water-vol-0" *active-pool*))))
  (let ((e (-> w entity)))
    (dotimes (i (-> (the res-lump e) length))
      (format #t "tag~d: ~A key:~f~%" i (-> (the res-lump e) tag i name) (-> (the res-lump e) tag i key-frame)))))
```
