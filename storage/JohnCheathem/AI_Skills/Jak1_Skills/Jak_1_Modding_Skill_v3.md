# OpenGOAL Jak 1 — Level Design, Entity Spawning & Tech Art Skill

**Purpose:** Teaches AI assistants how to help humans create custom levels, spawn entities,
script events, manage animations, handle sound/music, collision, lighting, and build Blender
tooling for the OpenGOAL Jak 1 decompilation project.

**Source repo:** https://github.com/open-goal/jak-project
**All file paths are relative to the repo root unless otherwise stated.**
**This is a living document — update it as new patterns are discovered.**

---

## TABLE OF CONTENTS

1. Repo Structure Map
2. Complete Level Creation Pipeline
3. Level Config (.jsonc) — All Fields
4. Actor / Entity System
5. Spawnable Entity Reference (483 types)
6. Concrete Spawn Examples
7. Death Planes & Kill Zones
8. Checkpoints & Respawn Points
9. Invisible Walls
10. Moving Platforms
11. Doors & Conditional Triggers
12. Actor Linking & Event Chaining
13. Scripted Sequences & State Machines
14. Path System (Actor Movement)
15. Water Volumes
16. Collision System
17. Lighting Bake (Vertex Colors)
18. Sound & Music System
19. Particle Effects
20. Animation System
21. Camera System
22. Hint Text & Dialog
23. Pickup & Eco System
24. Debug REPL Commands
25. Blender Workflow & Tech Art
26. Units & Coordinate System
27. Key Files for Further Exploration
28. Planned Blender Addon

---

## 1. REPO STRUCTURE MAP

```
jak-project/
├── custom_assets/jak1/                ← YOUR WORK GOES HERE
│   ├── levels/
│   │   └── test-zone/                 ← Template — copy this for new levels
│   │       ├── test-zone.jsonc        ← Level definition (actors, ambients, mesh, settings)
│   │       ├── test-zone2.glb         ← Blender-exported level mesh
│   │       └── testzone.gd            ← DGO package definition (art groups, tpages)
│   ├── models/custom_levels/          ← Custom actor .glb files go here
│   └── blender_plugins/
│       ├── opengoal.py                ← Collision plugin (targets 2.83, needs 4.x update)
│       └── gltf2_blender_extract.py   ← Patched GLTF exporter for vertex color export
│
├── goal_src/jak1/
│   ├── engine/
│   │   ├── level/
│   │   │   ├── level-info.gc          ← *** REGISTER EVERY CUSTOM LEVEL HERE ***
│   │   │   ├── level-h.gc             ← level-load-info struct (bottom-height, mood, etc.)
│   │   │   ├── level.gc               ← Level loading, bg function
│   │   │   └── bsp.gc                 ← BSP visibility culling
│   │   ├── entity/
│   │   │   ├── entity-h.gc            ← entity, entity-actor, entity-ambient types
│   │   │   ├── entity.gc              ← Entity loading logic
│   │   │   ├── actor-link-h.gc        ← Actor linked list (next-actor/prev-actor chains)
│   │   │   ├── res-h.gc               ← res-lump property storage type
│   │   │   ├── res.gc                 ← res-lump lookup functions
│   │   │   └── ambient.gc             ← Ambient triggers, level-hint-spawn
│   │   ├── common-obs/
│   │   │   ├── process-drawable.gc    ← Base for all visible entities
│   │   │   ├── process-taskable.gc    ← Base for NPCs, scripted interactables
│   │   │   ├── nav-enemy.gc           ← Base for all AI enemies
│   │   │   ├── nav-enemy-h.gc         ← nav-enemy-info struct, AI flags
│   │   │   ├── baseplat.gc            ← Base for platforms, moving objects
│   │   │   ├── basebutton.gc          ← Button/switch base class
│   │   │   ├── collectables.gc        ← Orbs, cells, buzzers, eco
│   │   │   ├── crates.gc              ← Crate variants
│   │   │   ├── plat.gc                ← Moving platform (uses path + sync)
│   │   │   ├── water.gc               ← Water volume logic
│   │   │   └── water-h.gc             ← water-flags enum, water-vol type
│   │   ├── collide/
│   │   │   ├── pat-h.gc               ← PAT surface (material/mode/event per triangle)
│   │   │   ├── collide-shape-h.gc     ← collide-kind, collide-action, collide-offense enums
│   │   │   └── surface-h.gc           ← surface-flags (Jak movement on surfaces)
│   │   ├── anim/
│   │   │   ├── joint-h.gc             ← Joint control channel types
│   │   │   └── joint.gc               ← Joint update logic
│   │   ├── geometry/
│   │   │   ├── path-h.gc              ← path-control (spline paths for movement)
│   │   │   └── path.gc                ← Path eval, random point, length
│   │   ├── nav/
│   │   │   ├── navigate-h.gc          ← Navigation mesh types
│   │   │   └── navigate.gc            ← Pathfinding
│   │   ├── sound/
│   │   │   ├── gsound-h.gc            ← sound-id, music-flava enum, sound commands
│   │   │   └── gsound.gc              ← sound-play, ambient-sound, flava functions
│   │   ├── camera/
│   │   │   ├── camera-h.gc            ← Camera state list
│   │   │   ├── cam-states.gc          ← All camera state implementations
│   │   │   └── cam-start.gc           ← Camera spawn/reset
│   │   ├── gfx/mood/
│   │   │   ├── mood-h.gc              ← mood-fog, mood-lights, mood-context
│   │   │   └── mood.gc                ← Mood blending (atmosphere/fog/lighting)
│   │   ├── gfx/sprite/sparticle/
│   │   │   ├── sparticle-launcher-h.gc ← defpartgroup, defpart macros
│   │   │   └── sparticle-launcher.gc  ← Particle launch logic
│   │   ├── game/
│   │   │   ├── game-info-h.gc         ← continue-point struct, game-info
│   │   │   └── game-info.gc           ← set-continue!, get-continue-by-name
│   │   └── game/task/
│   │       ├── game-task-h.gc         ← game-task enum (all task IDs)
│   │       └── hint-control.gc        ← level-hint-spawn, hint timer
│   │
│   ├── levels/
│   │   ├── test-zone/
│   │   │   └── test-zone-obs.gc       ← *** TEMPLATE for custom actor .gc ***
│   │   ├── village1/                  ← Best reference level (complete, simple)
│   │   │   ├── sequence-a-village1.gc ← Scripted cutscene state machine example
│   │   │   ├── assistant.gc           ← NPC with dialog + task
│   │   │   ├── yakow.gc               ← Simple ambient animal AI
│   │   │   └── village-obs.gc         ← Platforms, doors, obstacles
│   │   └── common/
│   │       └── blocking-plane.gc      ← Invisible wall (path-based, racer/flut only)
│   │
│   └── game.gp                        ← *** BUILD SYSTEM — ADD LEVEL TARGETS HERE ***
│
├── goalc/
│   ├── build_level/                   ← C++ level compiler (.jsonc → .go binary)
│   │   ├── common/
│   │   │   ├── Entity.h/cpp           ← EntityActor + EntityAmbient data layout
│   │   │   ├── ResLump.h/cpp          ← res-lump serializer
│   │   │   └── gltf_mesh_extract.h/cpp ← GLTF → tfrag/collision conversion
│   │   └── jak1/
│   │       ├── Entity.h/cpp           ← Jak1-specific actor layout
│   │       ├── LevelFile.h/cpp        ← Level binary serializer
│   │       ├── ambient.h/cpp          ← Ambient zone serializer
│   │       └── build_level.h/cpp      ← Entry point
│   └── build_actor/                   ← C++ actor compiler (.glb → -ag.go)
│       ├── common/
│       │   ├── build_actor.h/cpp      ← Main actor build logic
│       │   ├── animation_processing.h/cpp ← GLTF animation → compressed game format
│       │   └── MercExtract.h/cpp      ← Mesh → merc renderer
│       └── jak1/
│           └── build_actor.h/cpp      ← Jak1-specific joint format quirks
```

---

## 2. COMPLETE LEVEL CREATION PIPELINE

### Step 1 — Copy Template
```
custom_assets/jak1/levels/my-level/
├── my-level.jsonc
├── my-level.glb         ← exported from Blender
└── mylevel.gd
```

**Naming rules (all must match):**
- Folder name = `my-level`
- `.jsonc` filename = `my-level.jsonc`
- `long_name` in jsonc = `"my-level"` (lowercase dashes, max 10 chars)
- `iso_name` = `"MYLEVEL"` (uppercase, max 8 chars)
- `nickname` = `"myl"` (exactly 3 lowercase chars)

### Step 2 — Register in level-info.gc
`goal_src/jak1/engine/level/level-info.gc` — add at the bottom:
```lisp
(define my-level
  (new 'static 'level-load-info
       :index 27                     ;; increment from last custom level
       :name 'my-level
       :visname 'my-level-vis
       :nickname 'myl
       :packages '()
       :sound-banks '(village1)
       :music-bank 'village1
       :ambient-sounds '()
       :mood '*village1-mood*
       :mood-func 'update-mood-village1
       :ocean '*ocean-map-village1*
       :sky #t
       :sun-fade 1.0
       :bottom-height (meters -100)  ;; Y below this = death
       :continues
       '((new 'static 'continue-point
              :name "my-level-start"
              :level 'my-level
              :trans (new 'static 'vector :x 0.0 :y (meters 5) :z 0.0 :w 1.0)
              :quat (new 'static 'quaternion :w 1.0)
              :camera-trans (new 'static 'vector :x 0.0 :y (meters 8) :z (meters -5) :w 1.0)
              :camera-rot (new 'static 'array float 9 1.0 0.0 0.0 0.0 1.0 0.0 0.0 0.0 1.0)
              :load-commands '()
              :vis-nick 'none
              :lev0 'my-level :disp0 'display :lev1 #f :disp1 #f))
       :tasks '()
       :priority 100
       :load-commands '()
       :alt-load-commands '()
       :bsp-mask #xffffffffffffffff
       :bsphere (new 'static 'sphere :w (meters 300))))
```

### Step 3 — Add to game.gp
`goal_src/jak1/game.gp` near line 1657:
```lisp
(build-custom-level "my-level")
(custom-level-cgo "MYLEVEL.DGO" "my-level/mylevel.gd")
```

### Step 4 — Write the .gd Package File
`custom_assets/jak1/levels/my-level/mylevel.gd`:
```lisp
("MYL.DGO"
 ("my-level-obs.o"
  "tpage-401.go"         ;; village1 sky tpage (match your :sky setting)
  "plat-ag.go"
  "yakow-ag.go"
  "my-actor-ag.go"
  "my-level.go"
  )
 )
```

### Step 5 — Write Game Logic .gc
`goal_src/jak1/levels/my-level/my-level-obs.gc` — copy test-zone-obs.gc as template.

### Step 6 — Export from Blender
- Format: GLTF 2.0 Binary (`.glb`) via the patched exporter
- Must have vertex colors baked (see Section 17)
- Save to: `custom_assets/jak1/levels/my-level/my-level.glb`

### Step 7 — Build and Test
```lisp
(mi)                           ;; rebuild all changed files
(lt)                           ;; connect GOALC to running gk
(bg-custom 'my-level-vis)      ;; load and go to your level
```

---

## 3. LEVEL CONFIG (.jsonc) — ALL VALID FIELDS

Full reference for `custom_assets/jak1/levels/MY-LEVEL/my-level.jsonc`.
Source: `goalc/build_level/jak1/Entity.cpp` and `LevelFile.cpp`

```jsonc
{
  "long_name": "my-level",    // max 10 chars, lowercase dashes — MUST match folder name
  "iso_name":  "MYLEVEL",     // max 8 chars, uppercase
  "nickname":  "myl",         // exactly 3 lowercase chars

  "gltf_file": "custom_assets/jak1/levels/my-level/my-level.glb",

  "automatic_wall_detection": true,   // auto ground vs wall by slope angle
  "automatic_wall_angle":     45.0,   // threshold degrees
  "double_sided_collide":     false,  // 2× slower — only use if mesh has inverted normals

  "base_id": 100,             // actor ID base — must be unique across all custom levels

  "art_groups":    ["plat-ag", "yakow-ag"],    // vanilla art groups (also add to .gd)
  "custom_models": ["my-actor"],               // from custom_assets/jak1/models/custom_levels/

  "textures": [["village1-vis-alpha"]],        // tpages to include [tpage-name, optional tex names...]
  "tex_remap": "village1",                     // vanilla level whose texture remap to copy
  "sky":       "village1",                     // sky source level (determines alpha tpage in .gd)
  "tpages":    [],                             // explicit tpage list — leave [] to auto-fill

  "actors":  [ ... ],    // see Section 6 for examples
  "ambients": [ ... ]    // see Section 22 for hint/sound ambient examples
}
```

### Lump Tag Types

| JSON type string | Stores | Example |
|---|---|---|
| `"int32"` / `"uint32"` | Integer | `["int32", 5]` |
| `"float"` | Float | `["float", 2.5]` |
| `"meters"` | Float × 4096 | `["meters", 3.0]` |
| `"degrees"` | Float × 182.044 | `["degrees", -45.0]` |
| `"vector"` | 4 raw floats | `["vector", [x,y,z,w]]` |
| `"vector4m"` | 4 floats in meters | `["vector4m", [x,y,z,w]]` |
| `"vector3m"` | 3 floats meters, w=1 | |
| `"symbol"` | GOAL symbol | `["symbol", "steel"]` |
| `"string"` | String | `["string", "my-thing"]` |
| `"eco-info"` | Pickup type + amount | `["eco-info", "(pickup-type money)", 10]` |
| `"cell-info"` | Power cell task | `["cell-info", "(game-task none)"]` |
| `"buzzer-info"` | Scout fly + index | `["buzzer-info", "(game-task none)", 3]` |
| `"water-height"` | Water surface data | `["water-height", 25.0, 0.5, 2.0, "(water-flags wt08 wt03 wt01)"]` |
| `"movie-pos"` | Cutscene camera | `["movie-pos", [x, y, z, yaw-degrees]]` |
| `"enum-int32"` / `"enum-uint32"` | Enum as int | `["enum-int32", "(fact-options wrap-phase)"]` |

### Common Lump Property Names

| Property | Description |
|---|---|
| `name` | Actor identity name — always required |
| `spring-height` | Jump pad launch height (meters) |
| `eco-info` | Pickup configuration |
| `crate-type` | `'steel` `'wood` `'barrel` `'darkeco` |
| `rotoffset` | Initial rotation offset (degrees) |
| `notice-dist` | AI alert range (meters) |
| `next-actor` | Name of next actor in event chain |
| `prev-actor` | Name of previous actor in event chain |
| `alt-actor` | Actor to notify on trigger |
| `path` | Waypoints for path movement (vector4m array) |
| `timeout` | Auto-reset timer in seconds |
| `speed` | Movement speed |
| `scale` | Visual scale multiplier |
| `sync` | Platform timing: [period-frames, phase-0to1, ease-out, ease-in] |
| `text-id` | Hint text ID (enum-uint32) |
| `water-height` | Water surface descriptor |
| `extra-id` | Button ID for multi-button puzzles |

---

## 4. ACTOR / ENTITY SYSTEM

Every actor is an `entity-actor` in the level binary. At load time the engine spawns
the matching GOAL process for each `etype`. Per-instance data lives in a `res-lump`.

Source: `engine/entity/entity-h.gc`, `engine/entity/res.gc`

### Actor Activation
Actors activate when Jak enters their `bsphere` radius. Larger = activates earlier.
Rule of thumb: bsphere radius ≈ 2–3× the actor's visual size.

### Which Actors Need Extra .gc Files
**Always available (in ENGINE.CGO / GAME.CGO) — just add art group to .gd:**
`plat`, `plat-eco`, `plat-button`, `balance-plat`, `crate`, `fuel-cell`,
`eco-yellow`, `eco-blue`, `eco-green`, `eco-red`, `money`, `buzzer`,
`warpgate`, `warp-gate-switch`, `springbox`, `water-vol-deadly`, `dark-eco-pool`

**Level-specific — also require their .gc in your level file:**
```lisp
;; At top of goal_src/jak1/levels/my-level/my-level-obs.gc:
(require "levels/village1/yakow.gc")
(require "levels/village1/assistant.gc")
```

---

## 5. SPAWNABLE ENTITY REFERENCE

**483 types** from `goal_src/jak1/levels/` `.gc` files (grep `^(deftype`).
**367 art groups** from `.gd` files (grep `"-ag.go"`).

### By Category

**Collectables:** `fuel-cell`, `eco-yellow`, `eco-red`, `eco-blue`, `eco-green`, `money`, `buzzer`, `orb-cache-top`, `powercellalt`, `dark-crystal`, `cavegem`, `crate`, `springbox`

**Platforms & Moving:** `plat`, `plat-eco`, `plat-flip`, `plat-button`, `balance-plat`, `orbit-plat`, `side-to-side-plat`, `wedge-plat`, `tar-plat`, `bone-platform`, `teetertotter`, `square-platform`, `drop-plat`, `wall-plat`

**Doors & Gates:** `warpgate`, `warp-gate-switch`, `jng-iris-door`, `tra-iris-door`, `citb-iris-door`, `sun-iris-door`, `rounddoor`, `sidedoor`, `silodoor`, `eco-door`, `maindoor`

**NPCs / Characters:** `yakow`, `billy`, `assistant`, `sage`, `oracle`, `mayor`, `farmer`, `fisher`, `explorer`, `sculptor`, `gambler`, `geologist`, `warrior`, `robber`, `muse`, `bird-lady`, `evilbro`, `evilsis`

**Enemies:** `kermit`, `hopper`, `puffer`, `bully`, `bonelurker`, `gnawer`, `lurkercrab`, `lurkerworm`, `yeti`, `snow-bunny`, `ram`, `baby-spider`, `mother-spider`, `flying-lurker`, `double-lurker`, `driller-lurker`, `plunger-lurker`, `quicksandlurker`, `swamp-bat`, `swamp-rat`, `lightning-mole`

**Hazards:** `water-vol-deadly`, `dark-eco-pool`, `spike`, `chainmine`, `tntbarrel`, `swamp-tetherrock`, `swamp-spike`, `cave-trap`, `evilplant`, `dark-plant`, `darkvine`

**Decor / Ambient:** `windmill-one`, `windmill-sail`, `gondola`, `seagull`, `pelican`, `villa-fisha`, `junglefish`, `starfish`, `happy-plant`, `ceilingflag`, `logtrap`

**Custom:** `test-actor` — template model in `custom_assets/jak1/models/custom_levels/test-actor.glb`

---

## 6. CONCRETE SPAWN EXAMPLES

### Power Cell (no task)
```jsonc
{
  "trans": [5.0, 3.0, 10.0], "etype": "fuel-cell",
  "game_task": "(game-task none)", "quat": [0,0,0,1],
  "bsphere": [5.0, 3.0, 10.0, 8.0],
  "lump": { "name": "my-cell-1", "eco-info": ["cell-info", "(game-task none)"] }
}
```
**.gd needs:** `"fuel-cell-ag.go"`

### Scout Fly (buzzer)
```jsonc
{
  "trans": [0.0, 2.0, 0.0], "etype": "buzzer",
  "game_task": "(game-task none)", "quat": [0,0,0,1],
  "bsphere": [0.0, 2.0, 0.0, 5.0],
  "lump": { "name": "my-fly-1", "eco-info": ["buzzer-info", "(game-task none)", 0] }
}
```
**.gd needs:** `"buzzer-ag.go"`

### Precursor Orb (money)
```jsonc
{
  "trans": [3.0, 1.5, 3.0], "etype": "money",
  "game_task": "(game-task none)", "quat": [0,0,0,1],
  "bsphere": [3.0, 1.5, 3.0, 3.0],
  "lump": { "name": "my-orb-1" }
}
```
**.gd needs:** `"money-ag.go"`

### Steel Crate with Orbs
```jsonc
{
  "trans": [0.0, 1.0, 5.0], "etype": "crate",
  "game_task": "(game-task none)", "quat": [0,0,0,1],
  "bsphere": [0.0, 1.0, 5.0, 5.0],
  "lump": {
    "name": "my-crate-1",
    "crate-type": ["symbol", "steel"],
    "eco-info": ["eco-info", "(pickup-type money)", 5]
  }
}
```
**Crate types:** `'steel` `'wood` `'barrel` `'darkeco`
**.gd needs:** `"crate-ag.go"`

### Yellow Eco Vent
```jsonc
{
  "trans": [3.0, 1.0, 3.0], "etype": "eco-yellow",
  "game_task": "(game-task none)", "quat": [0,0,0,1],
  "bsphere": [3.0, 1.0, 3.0, 5.0],
  "lump": { "name": "my-eco-1" }
}
```

### Jump Pad
```jsonc
{
  "trans": [0.0, 0.0, 0.0], "etype": "springbox",
  "game_task": "(game-task none)", "quat": [0,0,0,1],
  "bsphere": [0.0, 0.0, 0.0, 5.0],
  "lump": { "name": "my-pad-1", "spring-height": ["meters", 15.0] }
}
```

### Warp Gate
```jsonc
{
  "trans": [20.0, 0.0, 20.0], "etype": "warpgate",
  "game_task": "(game-task none)", "quat": [0,0,0,1],
  "bsphere": [20.0, 0.0, 20.0, 10.0],
  "lump": { "name": "my-gate-1" }
}
```
**.gd needs:** `"warpgate-ag.go"`

### Yakow (ambient animal)
```jsonc
{
  "trans": [12.0, 0.0, 8.0], "etype": "yakow",
  "game_task": "(game-task none)", "quat": [0,0,0,1],
  "bsphere": [12.0, 0.0, 8.0, 10.0],
  "lump": { "name": "my-yakow-1" }
}
```
**.gd needs:** `"yakow-ag.go"`
**.gc needs:** `(require "levels/village1/yakow.gc")`

---

## 7. DEATH PLANES & KILL ZONES

### Method A — Y-Height Kill Floor (simplest, no actors)
In `level-info.gc`, set `bottom-height` on your level entry:
```lisp
:bottom-height (meters -100)   ;; Jak dies if he falls below Y = -100 meters
```
Checked every frame in `engine/target/logic-target.gc`. Result: `'endlessfall` death.

### Method B — PAT Event on Mesh Faces (Blender)
In Blender via the opengoal.py plugin, set per-material/object:
- **Event: `deadly`** → instant kill on contact
- **Event: `endlessfall`** → falling-off-world death
- **Event: `burn`** → fire damage
- **Event: `melt`** → dark eco melt death

Source: `engine/collide/pat-h.gc` — `pat-event` enum
Handled in: `engine/collide/collide-shape.gc` ~line 691

### Method C — water-vol-deadly Actor
```jsonc
{
  "trans": [0.0, -5.0, 0.0], "etype": "water-vol-deadly",
  "game_task": "(game-task none)", "quat": [0,0,0,1],
  "bsphere": [0.0, -5.0, 0.0, 50.0],
  "lump": {
    "name": "death-water",
    "water-height": ["water-height", -2.0, 0.5, 1.0, "(water-flags wt08 wt03 wt01)"]
  }
}
```

---

## 8. CHECKPOINTS & RESPAWN POINTS

### Multiple Checkpoints in One Level
Add multiple `continue-point` entries to `:continues` in `level-info.gc`:
```lisp
:continues
'((new 'static 'continue-point
       :name "my-level-start"
       :level 'my-level
       :trans (new 'static 'vector :x 0.0 :y (meters 5) :z 0.0 :w 1.0)
       :quat (new 'static 'quaternion :w 1.0)
       :camera-trans (new 'static 'vector :x 0.0 :y (meters 8) :z (meters -5) :w 1.0)
       :camera-rot (new 'static 'array float 9 1.0 0.0 0.0 0.0 1.0 0.0 0.0 0.0 1.0)
       :vis-nick 'none :lev0 'my-level :disp0 'display :lev1 #f :disp1 #f)
  (new 'static 'continue-point
       :name "my-level-midpoint"
       :level 'my-level
       :trans (new 'static 'vector :x (meters 50) :y (meters 5) :z (meters 50) :w 1.0)
       :quat (new 'static 'quaternion :w 1.0)
       :camera-trans (new 'static 'vector :x (meters 50) :y (meters 8) :z (meters 45) :w 1.0)
       :camera-rot (new 'static 'array float 9 1.0 0.0 0.0 0.0 1.0 0.0 0.0 0.0 1.0)
       :vis-nick 'none :lev0 'my-level :disp0 'display :lev1 #f :disp1 #f))
```

### Switching Checkpoints at Runtime
```lisp
;; From .gc code, when Jak reaches a trigger zone:
(set-continue! *game-info* "my-level-midpoint")

;; From GOALC REPL directly:
(set-continue! *game-info* "my-level-midpoint")
```
Source: `engine/game/game-info.gc` — `set-continue!`

### continue-point Fields
| Field | Description |
|---|---|
| `name` | Unique string — used for lookup |
| `level` | Symbol of the level this belongs to |
| `trans` | Jak spawn position (w=1) |
| `quat` | Jak spawn rotation |
| `camera-trans` | Camera spawn position |
| `camera-rot` | Camera rotation matrix (row-major float[9]) |
| `lev0` / `disp0` | Primary level name / `'display` |
| `lev1` / `disp1` | Streaming secondary level / `'display` or `#f` |
| `vis-nick` | Vis data nickname, or `'none` |

---

## 9. INVISIBLE WALLS

### Recommended: Invisible Collision Mesh in Blender
Create a separate wall mesh, set its collision properties, mark it invisible:
1. Model a plane/box where the wall should be
2. In Properties → Object (opengoal.py plugin):
   - Check **Apply Collision Properties**
   - **Mode:** `wall`
   - **Material:** `stone` (or any)
   - Check **Invisible** — renders nothing, still collides
3. Export normally — the level builder processes all collision geometry

This requires no code, no art groups, works anywhere.

### Advanced: blocking-plane (Code-Spawned, Racer/Flut Only)
Source: `levels/common/blocking-plane.gc`

`blocking-plane` is **not** an etype — it cannot be placed in the jsonc directly.
It must be spawned from a parent actor's `.gc` code via `(blocking-plane-spawn path)`.
It creates flat invisible wall panels between consecutive path waypoints.
Needs `"ef-plane-ag.go"` and `"blocking-plane.o"` in the `.gd`.
Only useful for dynamically spawned/despawned walls in code-driven scenarios.

---

## 10. MOVING PLATFORMS

### How the System Works
`plat` reads from its entity: **path** (waypoints), **sync** (timing), **options** (loop mode).
Speed = path_length_meters ÷ (period_frames ÷ 60). Not set directly.

### Complete Moving Platform JSON
```jsonc
{
  "trans": [0.0, 5.0, 0.0],
  "etype": "plat",
  "game_task": "(game-task none)",
  "quat": [0, 0, 0, 1],
  "bsphere": [5.0, 5.0, 10.0, 15.0],
  "lump": {
    "name": "my-plat-1",
    "path": ["vector4m",
      [0.0,  5.0,  0.0,  1.0],   // waypoint A (start)
      [0.0,  5.0,  20.0, 1.0]    // waypoint B (end)
    ],
    // [period-frames, phase-0to1, ease-out, ease-in]
    // 600 frames ≈ 10 seconds. ease values: 0.15 = gentle, 0.0 = instant
    "sync": ["uint32", 600, "float", 0.0, "float", 0.15, "float", 0.15],
    // wrap-phase = loop continuously. Without it = ping-pong
    "options": ["enum-int32", "(fact-options wrap-phase)"]
  }
}
```
**.gd needs:** `"plat-ag.go"`

### Speed Formula
```
speed (m/s) = path_length_meters / (period_frames / 60)

20m path, 600 frames → 20 / 10 = 2.0 m/s
20m path, 240 frames → 20 / 4  = 5.0 m/s
```

### Staggered Platforms (phase offset)
```jsonc
// Plat 1: starts at path beginning
"sync": ["uint32", 600, "float", 0.0,  "float", 0.15, "float", 0.15]
// Plat 2: starts halfway through cycle
"sync": ["uint32", 600, "float", 0.5,  "float", 0.15, "float", 0.15]
// Plat 3: starts at 25%
"sync": ["uint32", 600, "float", 0.25, "float", 0.15, "float", 0.15]
```

### Platform Variants

| etype | Art group | Behavior |
|---|---|---|
| `plat` | `plat-ag.go` | Standard precursor, path-following |
| `plat-eco` | `plat-eco-ag.go` | Glowing eco, path-following |
| `plat-flip` | `plat-flip-ag.go` | Flips when stood on |
| `balance-plat` | `balance-plat-ag.go` | Tilts toward Jak's weight |
| `orbit-plat` | `orbit-plat-ag.go` | Orbits a fixed center |
| `side-to-side-plat` | `side-to-side-plat-ag.go` | Single-axis oscillation |
| `wall-plat` | `wall-plat-ag.go` | Emerges from wall |
| `wedge-plat` | `wedge-plat-ag.go` | Wedge-shaped tilting |
| `tar-plat` | `tar-plat-ag.go` | Floats on tar, sinks with weight |
| `teetertotter` | `teetertotter-ag.go` | See-saw balance |

---

## 11. DOORS & CONDITIONAL TRIGGERS

### basebutton — Switch That Triggers an Actor
Source: `engine/common-obs/basebutton.gc`

Sends `'trigger` to the actor named in `alt-actor` when pressed.
The target receives the event and can act on it.

```jsonc
// Button/switch:
{
  "trans": [0.0, 0.0, 0.0], "etype": "plat-button",
  "game_task": "(game-task none)", "quat": [0,0,0,1],
  "bsphere": [0.0, 0.0, 0.0, 8.0],
  "lump": {
    "name": "my-button",
    "alt-actor": ["string", "my-door"],  // notifies this actor on press
    "timeout": ["float", 3.0]            // seconds until auto-reset (0 = stays down)
  }
},
// Door/target (receives 'trigger):
{
  "trans": [20.0, 0.0, 0.0], "etype": "rounddoor",
  "game_task": "(game-task none)", "quat": [0,0,0,1],
  "bsphere": [20.0, 0.0, 0.0, 10.0],
  "lump": { "name": "my-door" }
}
```
**.gd needs:** `"plat-button-ag.go"`, `"rounddoor-ag.go"`

### basebutton State Flow
```
basebutton-up-idle
  → receives 'trigger → basebutton-going-down → basebutton-down-idle
  → receives 'untrigger (or timeout) → basebutton-going-up → basebutton-up-idle
```

### Receiving Events in Custom Actor .gc
```lisp
(defstate idle (my-actor)
  :virtual #t
  :event (behavior ((proc process) (argc int) (msg symbol) (block event-message-block))
    (case msg
      (('trigger)   (go-virtual activated))
      (('untrigger) (go-virtual idle))
      (('touch)     (go-virtual touched-by-jak))))
  :code (behavior () (loop (suspend))))
```

---

## 12. ACTOR LINKING & EVENT CHAINING

Source: `engine/entity/actor-link-h.gc`

Actors form linked lists via `next-actor`/`prev-actor` lump properties.
Events propagate through these chains without needing hardcoded names.

### Chain Setup in JSON
```jsonc
{ "etype": "plat-button", "lump": { "name": "btn-a", "next-actor": ["string", "plat-b"] } },
{ "etype": "plat",        "lump": { "name": "plat-b", "prev-actor": ["string", "btn-a"] } }
```

### Chain Event Methods (in .gc code)
```lisp
(let ((link (new 'process 'actor-link-info self)))
  (send-to-next link 'trigger)          ;; send to next actor only
  (send-to-prev link 'trigger)          ;; send to prev actor only
  (send-to-all-after link 'trigger)     ;; broadcast forward through whole chain
  (send-to-all-before link 'trigger)    ;; broadcast backward
  (send-to-next-and-prev link 'msg))    ;; both directions one hop
```

### Common Event Messages
| Message | Meaning |
|---|---|
| `'trigger` / `'untrigger` | Activate / deactivate |
| `'touch` | Jak made contact |
| `'attack` | Deal damage |
| `'notice` | Something noticed Jak |
| `'jump` | Jump action triggered |
| `'pause` / `'resume` | Pause/resume animation |
| `'play-anim` | Play a scripted animation |
| `'anim-mode` | Set animation playback mode |

---

## 13. SCRIPTED SEQUENCES & STATE MACHINES

Source: `levels/village1/sequence-a-village1.gc`
Base class: `engine/common-obs/process-taskable.gc`

### Full Pattern: Player Walks In → Sequence Plays → Checkpoint Updates
```lisp
(deftype my-sequence (process-taskable)
  ((phase int32))
  (:state-methods idle triggered playing done))

(defstate idle (my-sequence)
  :virtual #t
  :event (behavior ((proc process) (argc int) (msg symbol) (block event-message-block))
    (case msg
      (('touch) (go-virtual triggered))   ;; player entered trigger zone
      (('trigger) (go-virtual triggered))));; or triggered by button
  :code (behavior () (loop (suspend))))

(defstate triggered (my-sequence)
  :virtual #t
  :code (behavior ()
    ;; Brief delay then begin
    (dotimes (i 30) (suspend))
    (go-virtual playing)))

(defstate playing (my-sequence)
  :virtual #t
  :code (behavior ()
    ;; Lock camera
    (send-event *camera* 'change-state cam-fixed 0)
    ;; Wait 3 seconds
    (let ((end (+ (current-time) (seconds 3.0))))
      (until (>= (current-time) end) (suspend)))
    ;; Notify linked actor
    (send-to-next (new 'process 'actor-link-info self) 'trigger)
    ;; Update respawn point
    (set-continue! *game-info* "my-level-midpoint")
    ;; Restore camera
    (send-event *camera* 'change-state cam-string 0)
    ;; Complete task
    (task-complete! self (-> self game-task))
    (go-virtual done)))

(defstate done (my-sequence)
  :virtual #t
  :code (behavior () (loop (suspend))))

(defmethod init-from-entity! ((this my-sequence) (arg0 entity-actor))
  (process-taskable-method-40 this arg0 *my-sequence-sg* 3 31
    (new 'static 'vector :w 4096.0) 5)
  (go (method-of-object this idle)))
```

### Timer Patterns
```lisp
;; Wait exactly N seconds:
(let ((end (+ (current-time) (seconds 3.0))))
  (until (>= (current-time) end) (suspend)))

;; Wait N frames:
(dotimes (i 120) (suspend))

;; Wait for Jak to get within N meters of this actor:
(until (< (vector-vector-distance (-> self root trans) (target-pos 0)) (meters 5.0))
  (suspend))

;; Has N seconds elapsed since stored time?
(time-elapsed? stored-time (seconds 5.0))
```

### Task Completion
```lisp
(task-complete! self (game-task my-task-name))
(close-specific-task! (game-task none) (task-status need-resolution))
```

---

## 14. PATH SYSTEM (Actor Movement)

Source: `engine/geometry/path-h.gc`, `path.gc`

### Path in JSON (inline on actor)
```jsonc
{
  "etype": "my-patrol",
  "lump": {
    "name": "patrol-1",
    "path": ["vector4m",
      [0.0,  5.0,  0.0,  1.0],
      [10.0, 5.0,  0.0,  1.0],
      [10.0, 5.0,  20.0, 1.0],
      [0.0,  5.0,  20.0, 1.0]
    ]
  }
}
```

### Using a Path in .gc
```lisp
;; In actor type:
(deftype my-patrol (process-drawable)
  ((path  path-control)
   (t-pos float))   ;; 0.0 = start, 1.0 = end
  ...)

;; In init-from-entity!:
(set! (-> this path) (new 'process 'path-control this 'path 0.0))
(set! (-> this t-pos) 0.0)

;; In movement behavior — eval position at t, then advance t:
(let ((pos (new 'stack 'vector)))
  (eval-path-curve! (-> self path) pos (-> self t-pos) 'interp)
  (vector-copy! (-> self root trans) pos))
(+! (-> self t-pos) (* 0.5 (seconds-per-frame)))  ;; speed = 0.5 units/sec
(when (>= (-> self t-pos) 1.0) (set! (-> self t-pos) 0.0))  ;; loop

;; Random point on path:
(get-random-point (-> self path) pos)

;; Path total length in meters:
(* 0.00024414062 (path-distance (-> self path)))
```

---

## 15. WATER VOLUMES

Source: `engine/common-obs/water.gc`, `water-h.gc`

### water-height JSON Tag — Full Format
```jsonc
"water-height": ["water-height",
  25.0,                            // surface height Y in meters
  0.5,                             // wade-height: depth where Jak starts wading
  2.0,                             // swim-height: depth where Jak starts swimming
  "(water-flags wt08 wt03 wt01)", // behavior flags
  -10.0                            // optional: bottom height in meters
]
```

### Water Flags Decoded
From usage in `water.gc`:

| Flag combination | Result |
|---|---|
| `wt08 wt03 wt01` | Standard swimmable water |
| `wt02 wt01` | Shallow wading only, no swimming |
| `wt07 wt01` | Dark eco (damages Jak on contact) |
| `wt04 wt03 wt01` | Underwater / full submersion |
| `wt05 wt03 wt01` | Ocean/large body water mode |

Individual flags: `wt01` = water active, `wt02` = wade, `wt03` = swim,
`wt04` = underwater, `wt05` = ocean mode, `wt06` = surface ripple,
`wt07` = dark eco damage, `wt08` = standard swim setup, `wt17` = shallow mode

---

## 16. COLLISION SYSTEM

Source: `engine/collide/pat-h.gc`, `collide-shape-h.gc`

### PAT Surface Attributes (Per Triangle — Set in Blender Plugin)

**Materials (surface feel/sound):**
`stone`, `ice`, `quicksand`, `waterbottom`, `tar`, `sand`, `wood`, `grass`,
`pcmetal`, `snow`, `deepsnow`, `hotcoals`, `lava`, `crwood`, `gravel`, `dirt`,
`metal`, `straw`, `tube`, `swamp`, `stopproj`, `rotate`, `neutral`

**Modes:**
- `ground` — walkable floor
- `wall` — blocks movement, no grip
- `obstacle` — partial block

**Events (triggered on contact):**
- `none`, `deadly`, `endlessfall`, `burn`, `deadlyup`, `burnup`, `melt`

**Flags:** `set_invisible`, `noedge`, `noentity`, `nolineofsight`, `nocamera`

### Collision Kinds, Actions, Offense
```
KINDS (what an object IS):
  background, target, enemy, wall-object, ground-object,
  projectile, water, powerup, crate

ACTIONS (what it DOES on contact):
  solid, rider-plat-sticky, rider-target, edgegrab-active, attackable

OFFENSE (how hard to break):
  no-offense, touch, normal-attack, strong-attack, indestructible
```

### Custom Actor Collision (.gc)
```lisp
(defmethod init-collision! ((this my-actor))
  (let ((cshape (new 'process 'collide-shape-moving this (collide-list-enum hit-by-player))))
    (set! (-> cshape dynam) (copy *standard-dynamics* 'process))
    (set! (-> cshape reaction) default-collision-reaction)
    (set! (-> cshape no-reaction)
      (the (function collide-shape-moving collide-shape-intersect vector vector none) nothing))
    (let ((cgroup (new 'process 'collide-shape-prim-group cshape (the uint 1) 0)))
      (set! (-> cgroup prim-core collide-as) (collide-kind ground-object))
      (set! (-> cgroup collide-with) (collide-kind target))
      (set! (-> cgroup prim-core action) (collide-action solid rider-plat-sticky))
      (let ((mesh (new 'process 'collide-shape-prim-mesh cshape (the uint 0) (the uint 0))))
        (set! (-> mesh prim-core collide-as) (collide-kind ground-object))
        (set! (-> mesh collide-with) (collide-kind target))
        (set! (-> mesh prim-core action) (collide-action solid))
        (set! (-> mesh prim-core offense) (collide-offense indestructible))
        (set! (-> mesh transform-index) 0)
        (set-vector! (-> mesh local-sphere) 0.0 0.0 0.0 (meters 5))
        (append-prim cgroup mesh)))
    (set! (-> cshape nav-radius) (* 0.75 (-> cshape root-prim local-sphere w)))
    (backup-collide-with-as cshape)
    (set! (-> this root) cshape)))
```

### Trigger Zone (invisible sphere → fires event)
```lisp
(let ((sphere (new 'process 'collide-shape-prim-sphere cshape (the uint 0))))
  (set! (-> sphere prim-core collide-as) (collide-kind wall-object))
  (set! (-> sphere collide-with) (collide-kind target))
  (set! (-> sphere prim-core action) (collide-action solid))
  (set! (-> sphere prim-core offense) (collide-offense no-offense))
  (set-vector! (-> sphere local-sphere) 0.0 0.0 0.0 (meters 5.0)))
;; In :event handler: (case msg (('touch) (go-virtual triggered)))
```

---

## 17. LIGHTING BAKE (VERTEX COLORS)

The game uses **vertex colors** for baked lighting — not lightmaps or texture baking.
The build pipeline reads `COLOR_0` from the GLTF and quantizes it with a KD-tree palette.

**Required exporter:** `custom_assets/blender_plugins/gltf2_blender_extract.py`
This patches the GLTF exporter to correctly export `color_attributes` as `COLOR_0`.

**Plugin warning:** "Make sure that no meshes have face corner colors.
All colors must be vertex colors (float)."

### Step-by-Step Bake in Blender 4.x
1. Set renderer to **Cycles**
2. Place lights (sun lamp recommended for outdoors)
3. Select all level mesh objects
4. **Properties → Object Data → Color Attributes:**
   - Ensure exactly **one** attribute exists
   - Domain: **Vertex** (NOT Face Corner)
   - Data Type: **Color** (float RGBA)
5. **Render Properties → Bake:**
   - Bake Type: **Diffuse**
   - Contributions: uncheck **Color**, keep **Direct** + **Indirect**
   - Output → Target: **Active Color Attribute**
6. Click **Bake**
7. Export using the patched exporter with **Vertex Colors** enabled

### Lighting Bake Tips
- Only `COLOR_0` (first attribute) is used — delete any extra attributes before export
- Colors are quantized to a palette — fine detail can be lost in high-variety scenes
- Aim for 20–80% brightness — very dark or very bright bakes lose detail
- Faces sharing vertices across hard edges need split vertices (use Edge Split modifier)
- Each mesh object bakes independently — merge objects for consistent light transitions

### Sky / Tpage Reference

| Sky level | Tpage for .gd alpha slot |
|---|---|
| training | `tpage-1308.go` |
| village1 | `tpage-401.go` |
| beach | `tpage-215.go` |
| jungle | `tpage-388.go` |
| misty | `tpage-520.go` |
| firecanyon | `tpage-1123.go` |
| village2 | `tpage-921.go` |
| rolling | `tpage-925.go` |
| sunken | `tpage-162.go` |
| swamp | `tpage-630.go` |
| ogre | `tpage-1117.go` |
| snow | `tpage-712.go` |
| finalboss | `tpage-1418.go` |

---

## 18. SOUND & MUSIC SYSTEM

Source: `engine/sound/gsound.gc`, `gsound-h.gc`

### Level Music Setup (level-info.gc)
```lisp
:sound-banks '(village1)    ;; SFX bank — controls ambient sounds and effects
:music-bank 'village1       ;; Background music track
:ambient-sounds '()         ;; Per-level ambient loop list (usually empty)
```

**Available music banks:** `village1`, `village2`, `village3`, `beach`, `jungle`,
`jungleb`, `misty`, `swamp`, `rolling`, `snow`, `firecanyon`, `lavatube`, `ogre`,
`sunken`, `maincave`, `darkcave`, `robocave`, `citadel`, `finalboss`, `#f` (silence)

Sound banks use the same names. Can load multiple: `'(village1 jungle)`

### Music Flava (Sub-Track Variation)
Changes the instrument layer in the current music bank.
Used to add tension, character themes, or area ambience.

```lisp
;; Set a flava (e.g. when Jak approaches an NPC):
(set-setting! 'sound-flava #f 30.0 (music-flava sage))

;; Revert to default:
(remove-setting! 'sound-flava)
```

**All music-flava values:**
`racer`, `flutflut`, `to-maincave`, `to-snow`, `sage`, `assistant`, `birdlady`,
`mayor`, `sculptor`, `explorer`, `sage-yellow`, `sage-red`, `sage-blue`, `miners`,
`warrior`, `geologist`, `gambler`, `sage-hut`, `dock`, `farmer`, `jungleb-eggtop`,
`misty-boat`, `misty-battle`, `beach-sentinel`, `beach-cannon`, `beach-grotto`,
`citadel-center`, `robocave`, `robocave-top`, `maincave`, `darkcave`, `snow-battle`,
`snow-cave`, `snow-fort`, `snow-balls`, `levitator`, `swamp-launcher`, `swamp-battle`,
`jungle-temple-exit`, `jungle-lurkerm`, `jungle-temple-top`, `rolling-gorge`,
`ogre-middle`, `ogre-end`, `lavatube-middle`, `lavatube-end`, `finalboss-middle`,
`finalboss-end`, `default`

### Playing SFX in .gc Code
```lisp
;; One-shot at entity position:
(sound-play "launch")

;; With volume (0–100) and pitch (-1000 to 1000):
(sound-play "miss" :vol 80.0 :pitch 500)

;; Store ID to stop later:
(let ((sid (new-sound-id)))
  (sound-play "dark-eco-loop" :id sid)
  ;; ... later ...
  (sound-stop sid))

;; Positional 3D sound:
(sound-play "plat-land" :id (new-sound-id) :position #t)
```

### Ambient Sound Zone (jsonc)
```jsonc
{
  "trans": [0.0, 5.0, 0.0, 20.0],
  "bsphere": [0.0, 5.0, 0.0, 25.0],
  "lump": {
    "name": "waterfall-loop",
    "type": "'ambient-sound",
    "effect-name": ["string", "waterfall"]
  }
}
```

### Mood Functions (atmosphere/fog/sky)
```
update-mood-village1/2/3
update-mood-jungle / update-mood-jungleb
update-mood-misty / update-mood-swamp / update-mood-snow
update-mood-ogre / update-mood-firecanyon / update-mood-lavatube
update-mood-sunken / update-mood-rolling / update-mood-citadel
update-mood-darkcave / update-mood-maincave / update-mood-robocave
update-mood-training / update-mood-finalboss / update-mood-default
```

---

## 19. PARTICLE EFFECTS

Source: `engine/gfx/sprite/sparticle/sparticle-launcher-h.gc`
Reference: `levels/village1/village1-part.gc`

### Defining Particles in .gc
```lisp
;; A particle group = collection of emitters
(defpartgroup group-my-sparks
  :id 700                        ;; unique — don't clash with vanilla IDs (0-699 used)
  :duration (seconds 0.5)
  :linger-duration (seconds 1.0)
  :flags (use-local-clock)
  :bounds (static-bspherem 0 0 0 8)
  :parts ((sp-item 2900 :period (seconds 1) :length (seconds 0.017))))

;; An individual emitter
(defpart 2900
  :init-specs
  ((:texture (hotdot effects))        ;; texture (see list below)
   (:num 10.0)                        ;; particles per burst
   (:x (meters -1) (meters 2))       ;; spawn X offset: min + random range
   (:y (meters 0) (meters 1))
   (:z (meters -1) (meters 2))
   (:scale-x (meters 0.1) (meters 0.2))
   (:scale-y :copy scale-x)
   (:r 255.0) (:g 128.0) (:b 0.0)   ;; color 0–255
   (:a 128.0 64.0)                   ;; alpha + random
   (:vel-y (meters 0.03) (meters 0.05))
   (:accel-y (meters -0.001))        ;; gravity
   (:timer (seconds 1.5))            ;; particle lifetime
   (:flags (bit2 bit3))
   (:fade-a -0.5)))                  ;; alpha fade per frame
```

### Attaching Particles to an Actor
```lisp
;; In deftype:
(deftype my-actor (process-drawable)
  ((part sparticle-launch-control)) ...)

;; In init-from-entity!:
(set! (-> this part) (create-launch-control group-my-sparks this))

;; In idle :post or update loop:
(spawn (-> self part) (-> self root trans))
```

### Available Particle Textures
**From `effects` tpage:**
`hotdot`, `middot`, `harddot`, `bigpuff`, `bigpuff-half`, `bigpuff2`,
`lakedrop`, `rockbit`, `starflash`, `starflash2`, `flare`,
`lightning`, `lightning2`, `lightning3`,
`falls-particle`, `falls-particle-02`,
`water-splash`, `water-ring`, `water-wave`, `surfacebubble`,
`footprntr`, `butterfly-wing`, `buzzerwing`, `dragonfly`,
`hummingbird-body`, `hummingbird-wing`, `hummingbird-wing2`,
`lava-part-01`, `citadel-shield`, `e-white`, `p-white`,
`crate-metalbolt-splinter`, `crate-wood-01-splinter`

**From `common` tpage:**
`checkpoint`, `powercell-icon`, `egg-icon`, `buzzerfly-icon`

---

## 20. ANIMATION SYSTEM

Source: `engine/anim/joint-h.gc`, `joint.gc`
Pipeline: `goalc/build_actor/common/animation_processing.h`

### GLTF Requirements for Animated Custom Actors
- Must have a **Skin** (armature in Blender)
- Joints must be **parent-before-child** order (lower index = parent)
- Animations: named Action strips in the NLA editor → multiple in-game animations
- Framerate: 60fps recommended (game interpolates keyframes)
- Apply all transforms before export (Ctrl+A → All Transforms in Blender)

### Jak1 Animation Quirk
Jak1 uses a legacy `JointAnimCompressed` per joint per animation, but only joint 0's
data is read for length. Jak2 cleaned this up. Source: `goalc/build_actor/jak1/build_actor.h`

### Initializing a Skeleton in .gc
```lisp
;; Declare from art group:
(declare-type my-actor process-drawable)
(define-extern *my-actor-sg* skeleton-group)

;; In init-from-entity!:
(initialize-skeleton this *my-actor-sg* '())
```

### Playing Animations
```lisp
;; Push animation channel (with blend):
(ja-channel-push! 1 (seconds 0.1))

;; Set animation by art group data index:
(ja :group! (-> self draw art-group data ANIM_INDEX) :num! (identity 0.0))

;; Loop:
(ja :num! (loop!))

;; Play to end:
(ja :num! (seek!))

;; Wait for animation finish:
(ja-no-eval :num! (seek!) :frame-num 0.0)
(until (ja-done? 0) (suspend))
```

### State Post Functions
```lisp
:post transform-post    ;; update transforms, no animation advance
:post ja-post           ;; advance joint animation channels each frame
```

---

## 21. CAMERA SYSTEM

Source: `engine/camera/camera-h.gc`, `cam-states.gc`

### Available Camera States
| State | Behavior |
|---|---|
| `cam-string` | Default follow camera (rubber-band) |
| `cam-fixed` | Locked to fixed position/angle |
| `cam-free-floating` | Fully free (debug) |
| `cam-lookat` | Always looking at a target point |
| `cam-orbit` | Orbits a center point |
| `cam-spline` | Follows a spline path |
| `cam-pov` | First person |
| `cam-endlessfall` | Void/fall death camera |

### Changing Camera in .gc Code
```lisp
(send-event *camera* 'change-state cam-fixed 0)      ;; lock camera
(send-event *camera* 'change-state cam-string 0)     ;; restore follow
(send-event *camera* 'change-state cam-free-floating 0) ;; free cam
(send-event *camera* 'no-intro)                      ;; skip intro blend
(send-event *camera* 'clear-entity)                  ;; clear camera entity ref
(send-event *camera* 'force-blend 0)                 ;; force blend transition
```

### Saving Camera Position (Debug)
From the in-game Debug Menu → Camera → Save Pos (prints a restore function).
Then run `(cam-restore)` in GOALC to jump back.

---

## 22. HINT TEXT & DIALOG

Source: `engine/entity/ambient.gc`, `engine/ui/text-h.gc`, `engine/game/task/hint-control.gc`

### Showing a Hint from .gc Code
```lisp
;; (level-hint-spawn text-id voice-string entity pool game-task)

;; Show "POWER CELL" text with voice line:
(level-hint-spawn (text-id fuel-cell) "sksp0001" (the-as entity #f) *entity-pool* (game-task none))

;; Show hint with no voice:
(level-hint-spawn (text-id press-to-talk) "" (the-as entity #f) *entity-pool* (game-task none))
```

### Hint Via Ambient Zone (no code needed)
```jsonc
{
  "trans": [-21.0, 20.0, 17.0, 15.0],
  "bsphere": [-21.0, 20.0, 17.0, 20.0],
  "lump": {
    "name": "my-hint-zone",
    "type": "'hint",
    "text-id": ["enum-uint32", "(text-id fuel-cell)"],
    "play-mode": "'notice"     // notice | remind | resolution
  }
}
```

### Useful text-id Values
| text-id | Text shown |
|---|---|
| `fuel-cell` | "POWER CELL" |
| `press-to-talk` | "Press to Talk" |
| `press-to-use` | "Press to Use" |
| `press-to-warp` | "Press to Warp" |
| `hidden-power-cell` | "Hidden Power Cell" |
| `press-to-trade-money` | "Press to Trade Orbs" |
| `village1-level-name` | "Sandover Village" |

Full list: `engine/ui/text-h.gc` — `defenum text-id`

---

## 23. PICKUP & ECO SYSTEM

Source: `engine/common-obs/collectables.gc`, `engine/common-obs/generic-obs-h.gc`

### pickup-type Enum
```
none              — no pickup
eco-yellow        — yellow eco (ranged attack power)
eco-red           — red eco (melee boost)
eco-blue          — blue eco (speed boost)
eco-green         — green eco (health restore)
money             — precursor orb (currency)
fuel-cell         — power cell (level objective)
eco-pill          — dark eco (damage to Jak)
buzzer            — scout fly
eco-pill-random   — random eco type
```

### eco-info Lump Examples
```jsonc
"eco-info": ["eco-info", "(pickup-type eco-green)", 2]    // 2 green eco
"eco-info": ["eco-info", "(pickup-type money)", 10]       // 10 orbs
"eco-info": ["cell-info", "(game-task jungle-eggtop)"]    // power cell + task
"eco-info": ["buzzer-info", "(game-task none)", 3]        // scout fly index 3
```

### Crate Types
| Symbol | Visual | Default contents |
|---|---|---|
| `'steel` | Metal crate | set via `eco-info` lump |
| `'wood` | Wood crate | orbs by default |
| `'barrel` | Barrel | eco by default |
| `'darkeco` | Dark eco crate | dark eco pill |

### fact-options Flags
```
wrap-phase      — platform path loops (vs ping-pong)
has-power-cell  — spawn power cell on death
instant-collect — auto-collect on proximity
```

---

## 24. DEBUG REPL COMMANDS

All commands typed into the GOALC compiler window while `gk` is running.

### Connection & Build
| Command | Effect |
|---|---|
| `(lt)` | **Listen to target** — connect GOALC to running gk |
| `(mi)` | **Make ISO** — rebuild all changed files |
| `(mi-report)` | Rebuild with verbose output |
| `(r)` | Reset/reconnect |

### Level Loading
| Command | Effect |
|---|---|
| `(bg-custom 'my-level-vis)` | Load and go to a custom level |
| `(bg 'village1)` | Load vanilla level by name or vis-name |
| `(start 'play cont)` | Spawn Jak at a continue-point |
| `(stop 'play)` | Kill Jak |

### Position & Camera
```lisp
;; Print Jak's position in meters:
(let ((pos (target-pos 0)))
  (format #t "pos: ~m ~m ~m~%" (-> pos x) (-> pos y) (-> pos z)))

;; Print camera position:
(let ((pos (camera-pos)))
  (format #t "cam: ~m ~m ~m~%" (-> pos x) (-> pos y) (-> pos z)))

;; Teleport Jak (in game units — multiply meters by 4096):
(set! (-> *target* control trans x) (* 10.0 4096.0))
(set! (-> *target* control trans y) (*  5.0 4096.0))
(set! (-> *target* control trans z) (* 20.0 4096.0))

;; Switch checkpoint:
(set-continue! *game-info* "my-level-midpoint")
```

### Debug Visualization Toggles
```lisp
(set! *display-actor-marks* #t)    ;; actor bspheres and labels
(set! *display-path-marks* #t)     ;; path waypoints and lines
(set! *display-nav-marks* #t)      ;; navigation mesh
(set! *display-entity-marks* #t)   ;; entity activation spheres
(set! *display-bug-report* #t)     ;; overlay: position, camera, music, level info
```

### Game State Queries
```lisp
(-> *level* level 0 name)          ;; current level name
(-> *target* state name)           ;; Jak's current state
(-> *game-info* current-continue name) ;; active checkpoint name
```

---

## 25. BLENDER WORKFLOW & TECH ART

### Level Mesh Requirements
- **Format:** GLTF 2.0 Binary (`.glb`) via patched exporter
- **Vertex colors:** Required, Cycles-baked (see Section 17)
- **Scale:** 1 Blender unit = 1 meter in-game
- **Up axis:** Blender Z-up → GLTF Y-up (exporter handles this)
- **Materials:** Can reference textures (PNG) by material name
- **Triangulation:** Auto-triangulate on export is fine

### Custom Actor (.glb) Requirements
- Skinned mesh with armature for animated actors
- Parent joints must have lower indices than children
- Named Action strips in NLA editor → multiple in-game animations
- Apply all transforms before export (Ctrl+A → All Transforms)
- For bounds: `def-actor` in `.gc` or `build-actor` args in `game.gp`

### Existing Blender Plugin — opengoal.py
`custom_assets/blender_plugins/opengoal.py` — for Blender 2.83, needs 4.x update.

Adds to **Properties → Material** and **Properties → Object:**
- **Invisible** — no render, still collides
- **Apply Collision Properties:**
  - **Mode:** ground / wall / obstacle
  - **Material:** stone / ice / lava / sand / etc.
  - **Event:** none / deadly / endlessfall / burn / etc.
  - **Flags:** noedge / noentity / nolineofsight / nocamera

### Recommended Blender Scene Layout
```
Scene Collection
├── LEVEL_GEO          ← visual geometry (bake vertex colors here)
│   ├── floor_mesh
│   ├── walls_mesh
│   └── props_mesh
├── COLLISION_ONLY     ← invisible geometry (set_invisible checked)
│   ├── kill_floor     ← PAT event: endlessfall
│   └── invis_wall     ← PAT mode: wall, Invisible checked
├── ACTORS             ← empties for actor placement (future addon)
│   ├── ACTOR_fuel-cell_1
│   ├── ACTOR_plat_1
│   ├── PATH_plat_1_0
│   └── PATH_plat_1_1
└── LIGHTS             ← for baking only, not exported
```

---

## 26. UNITS & COORDINATE SYSTEM

| Concept | Value |
|---|---|
| 1 meter | 4096.0 game units |
| 1 degree | 182.044 game units (65536 = 360°) |
| 1 second | ~300 frames (NTSC ~60fps) |
| `(meters N)` | Multiplies N × 4096.0 |
| `(degrees N)` | Multiplies N × 182.044 |
| `(seconds N)` | Converts to frame count |
| `(seconds-per-frame)` | Frame delta for per-frame movement |
| Blender X/Y/Z | → Game X/Z/Y (exporter converts) |
| Actor `trans` in jsonc | In meters |
| Actor `trans` in .gc code | In raw game units |
| `bsphere` radius in jsonc | In meters |

### Common Reference Distances
| Use | Typical range |
|---|---|
| Actor activation bsphere | 10–30 meters |
| AI notice distance | 15–40 meters |
| Jump pad height | 5–20 meters |
| Platform speed | 2–5 m/s |
| Hint trigger radius | 10–25 meters |

---

## 27. KEY FILES FOR FURTHER EXPLORATION

| Goal | Files |
|---|---|
| Add a new game task | `engine/game/task/game-task-h.gc` |
| AI pathfinding / nav mesh | `engine/nav/navigate.gc`, `engine/common-obs/nav-enemy.gc` |
| Full particle init-spec params | `engine/gfx/sprite/sparticle/sparticle-launcher-h.gc` |
| Camera volumes and zones | `engine/camera/cam-layout.gc` |
| Water volume details | `engine/common-obs/water.gc`, `water-h.gc` |
| Sound bank structure | `engine/sound/gsound.gc`, `gsound-h.gc` |
| Debug draw in .gc code | `engine/debug/debug.gc` |
| Full NPC with dialog | `levels/village1/assistant.gc` |
| Simple patrol animal | `levels/village1/yakow.gc` |
| Complex boss fight | `levels/ogre/ogreboss.gc` |
| Scripted intro cutscene | `levels/village1/sequence-a-village1.gc` |
| Button + platform trigger | `engine/common-obs/plat-button.gc`, `basebutton.gc` |
| Rigid body physics objects | `engine/common-obs/rigid-body.gc` |
| Actor build pipeline internals | `goalc/build_actor/common/build_actor.cpp` |
| Level binary format | `goalc/build_level/jak1/LevelFile.cpp` |
| All valid jsonc fields | `goalc/build_level/jak1/Entity.cpp` (grep `json["`) |
| Level streaming / load zones | `engine/level/load-boundary.gc`, `load-boundary-h.gc` |
| Surface behavior (ice, etc.) | `engine/collide/surface-h.gc` |
| Swing poles / climbing | `engine/common-obs/generic-obs.gc`, `levels/beach/beach-obs.gc` |

---

## 28. PLANNED BLENDER ADDON

Target: Blender 4.4. All features derived from codebase patterns above.

### Panel 1 — Level Settings
- Long name, ISO name, nickname fields
- Mood / sky preset dropdown (all 20 options)
- `bottom-height` death plane Y input
- Music bank, sound bank dropdowns
- One-click vertex color bake button

### Panel 2 — Actor Placement
- Place empties → export as actors
- Naming: `ACTOR_<etype>_<uid>`, path empties: `PATH_<etype>_<uid>_<index>`
- Dropdown of all 483 entity types
- Per-actor: bsphere radius (wire sphere overlay), game_task, lump properties UI
- Ambient zones: `AMBIENT_<type>_<uid>`

### Panel 3 — Collision Properties
Updated opengoal.py for Blender 4.x — per-material and per-object:
mode, material, event, flags, invisible toggle

### Panel 4 — Export & Build
- Export mesh as `.glb`
- Generate `.jsonc` from empties + scene settings
- Auto-detect required art groups → write `.gd`
- Trigger GOALC rebuild via TCP socket:
```python
import socket
def goalc_rebuild():
    with socket.create_connection(("localhost", 8181), timeout=5) as s:
        s.sendall(b'(mi)\n')
        return s.recv(4096).decode()
```
- Status display in Blender UI panel

### Empty → Actor JSON Mapping
```
ACTOR_yakow_1     → { "etype": "yakow", "trans": [empty.location], ... }
ACTOR_plat_1      → { "etype": "plat", "lump": { "path": [PATH_plat_1_0, PATH_plat_1_1, ...] } }
PATH_plat_1_0     → waypoint 0 for plat_1
PATH_plat_1_1     → waypoint 1 for plat_1
AMBIENT_hint_1    → { "trans": [..., radius], "lump": { ... } }
```
