# OpenGOAL Jak 1 — Level Design, Entity Spawning & Tech Art Skill

**Purpose:** This document teaches AI assistants how to help humans create custom levels,
spawn entities, script events, manage animations, and build Blender tooling for the
OpenGOAL Jak 1 decompilation project.

**Source repo:** https://github.com/open-goal/jak-project
**All file paths below are relative to the repo root.**

---

## 1. REPO STRUCTURE MAP (Level-Design Relevant)

```
jak-project/
├── custom_assets/jak1/          ← YOUR WORK GOES HERE
│   ├── levels/
│   │   └── test-zone/           ← Reference/template level
│   │       ├── test-zone.jsonc  ← Level definition (actors, ambients, settings)
│   │       ├── test-zone2.glb   ← Blender-exported mesh
│   │       └── testzone.gd      ← DGO package definition
│   ├── models/custom_levels/    ← Custom actor .glb files
│   └── blender_plugins/
│       ├── opengoal.py          ← Existing Blender collision plugin (targets 2.83 — needs 4.x update)
│       └── gltf2_blender_extract.py
│
├── goal_src/jak1/
│   ├── engine/
│   │   ├── level/               ← Level loading, BSP, level-info registry
│   │   │   ├── level-info.gc    ← *** REGISTER EVERY CUSTOM LEVEL HERE ***
│   │   │   ├── level-h.gc       ← Level data structures
│   │   │   ├── level.gc         ← Level loading logic
│   │   │   └── bsp.gc           ← BSP visibility system
│   │   ├── entity/              ← Core entity/actor system
│   │   │   ├── entity-h.gc      ← entity, entity-actor, entity-ambient types
│   │   │   ├── entity.gc        ← Entity loading logic
│   │   │   ├── actor-link-h.gc  ← Actor chaining (next-actor/prev-actor linked lists)
│   │   │   ├── res-h.gc         ← res-lump type (per-actor property storage)
│   │   │   ├── res.gc           ← res-lump lookups
│   │   │   └── ambient.gc       ← Ambient triggers (sound, hint, music zones)
│   │   ├── common-obs/          ← Base classes for all game objects
│   │   │   ├── process-drawable.gc   ← Base for all visible entities
│   │   │   ├── process-drawable-h.gc
│   │   │   ├── process-taskable.gc   ← Base for NPCs/interactive scripted objects
│   │   │   ├── nav-enemy.gc          ← Base for all AI enemies
│   │   │   ├── nav-enemy-h.gc        ← AI state flags, nav-enemy-info struct
│   │   │   ├── baseplat.gc           ← Base for platforms, moving objects
│   │   │   ├── collectables.gc       ← Orbs, cells, buzzers
│   │   │   ├── crates.gc             ← Crate types
│   │   │   ├── plat.gc               ← Moving platforms
│   │   │   ├── water.gc              ← Water volumes
│   │   │   └── generic-obs.gc        ← Miscellaneous game objects
│   │   ├── collide/             ← Collision system
│   │   │   ├── pat-h.gc         ← PAT surface attributes (material/mode/event per triangle)
│   │   │   ├── collide-shape.gc ← Collision shapes (sphere, mesh, group)
│   │   │   └── collide-h.gc     ← Collision type enums
│   │   ├── anim/                ← Animation system
│   │   │   ├── joint-h.gc       ← Joint control channel, joint-control
│   │   │   ├── joint.gc         ← Joint update logic
│   │   │   └── aligner.gc       ← Root motion / ground alignment
│   │   ├── geometry/            ← Math helpers
│   │   │   ├── path-h.gc        ← path-control (spline paths for actor movement)
│   │   │   └── path.gc          ← Path eval, random point, length
│   │   ├── nav/
│   │   │   ├── navigate-h.gc    ← Navigation mesh types
│   │   │   └── navigate.gc      ← Pathfinding
│   │   └── gfx/mood/            ← Atmosphere / lighting
│   │       ├── mood-h.gc        ← mood-fog, mood-lights, mood-sun, mood-context
│   │       ├── mood.gc          ← Mood blending logic
│   │       └── mood-tables.gc   ← Per-level mood data
│   │
│   ├── levels/                  ← Per-level game logic (GOAL source)
│   │   ├── test-zone/           ← *** CUSTOM LEVEL .gc FILE GOES HERE ***
│   │   │   └── test-zone-obs.gc ← Template: custom actor with collision + idle state
│   │   ├── village1/            ← Best reference level (complete, simple)
│   │   │   ├── sequence-a-village1.gc  ← Scripted intro sequence (state machine example)
│   │   │   ├── assistant.gc            ← NPC with dialog/task
│   │   │   ├── yakow.gc                ← Simple ambient animal AI
│   │   │   └── village-obs.gc          ← Platforms, doors, obstacles
│   │   └── common/              ← Shared logic across levels
│   │
│   └── game.gp                  ← *** BUILD SYSTEM — ADD LEVEL TARGETS HERE ***
│
├── goalc/
│   ├── build_level/             ← C++ level compiler (reads .jsonc → .go binary)
│   │   ├── common/
│   │   │   ├── Entity.h/cpp     ← EntityActor and EntityAmbient data structures
│   │   │   ├── ResLump.h/cpp    ← res-lump builder
│   │   │   ├── gltf_mesh_extract.h/cpp  ← GLTF → tfrag/collision conversion
│   │   │   └── build_level.h/cpp
│   │   └── jak1/
│   │       ├── Entity.h/cpp     ← Jak1-specific actor layout
│   │       ├── LevelFile.h/cpp  ← Full level binary serializer
│   │       ├── ambient.h/cpp    ← Ambient zone serializer
│   │       └── build_level.h/cpp
│   └── build_actor/             ← C++ actor compiler (reads .glb → -ag.go art group)
│       ├── common/
│       │   ├── build_actor.h/cpp          ← Main actor build logic
│       │   ├── animation_processing.h/cpp ← GLTF animation → compressed game format
│       │   └── MercExtract.h/cpp          ← Mesh → merc renderer format
│       └── jak1/
│           └── build_actor.h/cpp          ← Jak1-specific joint format quirks
```

---

## 2. THE COMPLETE LEVEL CREATION PIPELINE

### Step 1 — File Setup
Copy `custom_assets/jak1/levels/test-zone/` to your new level folder:
```
custom_assets/jak1/levels/my-level/
├── my-level.jsonc     ← Main config (actors, mesh reference, settings)
├── my-level.glb       ← Blender-exported level mesh
└── mylevel.gd         ← DGO package list
```

**Naming rules:**
- `long_name`: lowercase with dashes, max 10 chars (e.g. `"my-level"`)
- `iso_name`: uppercase, max 8 chars (e.g. `"MYLEVEL"`)
- `nickname`: exactly 3 lowercase chars (e.g. `"myl"`)
- Folder name, `.jsonc` filename, and `long_name` must all match exactly.

### Step 2 — Register in level-info.gc
File: `goal_src/jak1/engine/level/level-info.gc`

Copy the `test-zone` block at the bottom and modify:
```lisp
(define my-level
  (new 'static 'level-load-info
       :index 27                    ;; increment from last level
       :name 'my-level
       :visname 'my-level-vis
       :nickname 'myl
       :mood '*village1-mood*       ;; see mood options below
       :mood-func 'update-mood-village1
       :sky #t
       :continues
       '((new 'static 'continue-point
              :name "my-level-start"
              :level 'my-level
              :trans (new 'static 'vector :x 0.0 :y (meters 10.) :z (meters 10.) :w 1.0)
              :quat (new 'static 'quaternion :w 1.0)
              :lev0 'my-level
              :disp0 'display
              :lev1 #f
              :disp1 #f))
       :tasks '()
       :priority 100
       :bsp-mask #xffffffffffffffff))
```

**Available mood-func options** (controls fog, lighting, sky color):
- `update-mood-village1` / `update-mood-village2` / `update-mood-village3`
- `update-mood-jungle` / `update-mood-jungleb`
- `update-mood-misty` / `update-mood-swamp` / `update-mood-snow`
- `update-mood-ogre` / `update-mood-firecanyon` / `update-mood-lavatube`
- `update-mood-sunken` / `update-mood-rolling` / `update-mood-citadel`
- `update-mood-darkcave` / `update-mood-maincave` / `update-mood-robocave`
- `update-mood-training` / `update-mood-finalboss` / `update-mood-default`

### Step 3 — Register in game.gp
File: `goal_src/jak1/game.gp`

Add near the test-zone entries (around line 1657):
```lisp
(build-custom-level "my-level")
(custom-level-cgo "MYLEVEL.DGO" "my-level/mylevel.gd")
```

### Step 4 — Write the .gd DGO Package File
File: `custom_assets/jak1/levels/my-level/mylevel.gd`
```lisp
("MYL.DGO"
 ("my-level-obs.o"      ;; your compiled .gc game logic
  "tpage-401.go"        ;; village1 sky tpage (match your sky setting)
  "plat-ag.go"          ;; art groups for any vanilla actors you use
  "yakow-ag.go"
  "my-actor-ag.go"      ;; your custom actor art groups
  "my-level.go"         ;; compiled level binary
  )
 )
```

### Step 5 — Create Game Logic .gc File
File: `goal_src/jak1/levels/my-level/my-level-obs.gc`

Use `test-zone-obs.gc` as the template. Key patterns:
```lisp
;; Define your actor type
(deftype my-actor (process-drawable)
  ((root collide-shape-moving :override))
  (:state-methods idle))

;; Register with art group
(def-actor my-actor :bounds (0 0 0 5))

;; Required: initialize from entity (called when loaded from level)
(defmethod init-from-entity! ((this my-actor) (e entity-actor))
  (init-collision! this)
  (process-drawable-from-entity! this e)
  (initialize-skeleton this *my-actor-sg* '())
  (go-virtual idle))

;; State machine
(defstate idle (my-actor)
  :virtual #t
  :code (behavior ()
    (loop (suspend)))
  :post transform-post)
```

### Step 6 — Export from Blender
- Export as GLTF 2.0 Binary (`.glb`)
- **Required:** Mesh must have vertex colors baked (Cycles → Bake → Diffuse, uncheck Color, bake to vertex colors)
- Only first vertex color group is used
- Place at: `custom_assets/jak1/levels/my-level/my-level.glb`

### Step 7 — Build and Test
```lisp
;; In the GOALC compiler window:
(mi)                            ;; rebuild everything
(lt)                            ;; connect to running game (gk)
(bg-custom 'my-level-vis)      ;; load and go to your level
```

---

## 3. ACTOR/ENTITY SYSTEM

### Actor JSON Schema (in .jsonc `actors` array)
```jsonc
{
  "trans": [x, y, z],          // position in meters
  "etype": "yakow",            // entity type name (see list below)
  "game_task": "(game-task none)",  // or specific task ID
  "quat": [x, y, z, w],       // rotation quaternion (identity = [0,0,0,1])
  "bsphere": [x, y, z, radius], // bounding sphere (used for culling/activation)
  "lump": {
    "name": "unique-actor-name",
    // ... type-specific lump properties
  }
}
```

### Valid Lump Properties
These are the lump tag types supported in `.jsonc`:
| JSON type string | Description | Example |
|---|---|---|
| `"int32"` / `"uint32"` | Integer value | `"count": ["int32", 5]` |
| `"float"` | Float value | `"speed": ["float", 2.5]` |
| `"meters"` | Float in meters (×4096) | `"spring-height": ["meters", 3.0]` |
| `"degrees"` | Float in degrees (65536=360°) | `"rotoffset": ["degrees", -45.0]` |
| `"vector"` | 4-float vector | `"center-point": ["vector", [x,y,z,w]]` |
| `"vector4m"` | Vector in meters | `"movie-pos": ["vector4m", [x,y,z,w]]` |
| `"vector3m"` | Vector in meters, w=1 | |
| `"symbol"` | GOAL symbol | `"type": ["symbol", "plat-eco"]` |
| `"string"` | String | `"name": ["string", "my-thing"]` |
| `"eco-info"` | Pickup type + amount | `"eco-info": ["eco-info", "(pickup-type health)", 2]` |
| `"cell-info"` | Power cell task | `"eco-info": ["cell-info", "(game-task none)"]` |
| `"buzzer-info"` | Scout fly task | `"eco-info": ["buzzer-info", "(game-task training-buzzer)", 5]` |
| `"water-height"` | Water surface level | `"water-height": ["water-height", 25.0, 0.5, 2.0, "(water-flags wt08 wt03 wt01)"]` |
| `"enum-int32"` | Enum as int | `"options": ["enum-int32", "(fact-options large)"]` |

### Common Actor Lump Properties (from engine source)
Properties actors read from their res-lump at runtime:
- `name` — actor's identity name (required)
- `spring-height` — jump pad height in meters
- `eco-info` — pickup configuration
- `crate-type` — for crates: `'steel`, `'wood`, `'barrel`, `'darkeco`
- `rotoffset` — initial rotation offset (degrees)
- `movie-pos` — cinematic camera position
- `notice-dist` — AI notice distance in meters
- `alt-actor` — reference to another actor (for chained events)
- `next-actor` / `prev-actor` — actor linked list pointers (for event chains)
- `path-actor` — reference to a path entity for movement
- `timeout` — timer in seconds
- `speed` — movement speed
- `scale` — visual scale
- `vis-dist` — visibility distance override
- `lod-dist` — LOD switch distance
- `pickup-type` — pickup type enum
- `text-id` — hint text ID (for ambient hints)
- `cam-notice-dist` — camera notice distance
- `sync` / `sync-percent` — synchronization for oscillating platforms
- `mode` — behavioral mode flag

### Ambient Zone JSON Schema (in .jsonc `ambients` array)
Ambients are invisible trigger volumes for music, sound, hints, etc.
```jsonc
{
  "trans": [x, y, z, radius],    // position + trigger radius
  "bsphere": [x, y, z, radius],  // bounding sphere
  "lump": {
    "name": "my-ambient",
    "type": "'hint",              // hint | music | sound | movie
    "text-id": ["enum-uint32", "(text-id fuel-cell)"],
    "play-mode": "'notice"        // notice | remind | resolution
  }
}
```

---

## 4. SPAWNABLE ENTITY TYPE REFERENCE

All 483 types come from `goal_src/jak1/levels/` `.gc` files (grep: `^(deftype`).
Art groups are in `.gd` files (grep: `"-ag.go"`).

### To spawn any entity you need:
1. The `etype` name in the actor JSON
2. Its `-ag.go` art group file added to your `.gd`
3. If from a level-specific DGO, that .gc compiled into your level's .o

### Key Spawnable Types by Category

**Collectables / Interactables:**
`fuel-cell`, `eco-yellow`, `eco-blue`, `eco-green`, `eco-red`, `money`, `buzzer`,
`crate`, `orb-cache-top`, `powercellalt`, `dark-crystal`, `cavegem`

**Platforms & Moving Objects:**
`plat`, `plat-eco`, `plat-flip`, `plat-button`, `balance-plat`, `orbit-plat`,
`side-to-side-plat`, `wedge-plat`, `tar-plat`, `bone-platform`, `teetertotter`,
`springbox`, `square-platform`, `drop-plat`, `wall-plat`

**Doors & Gates:**
`warpgate`, `warp-gate-switch`, `jng-iris-door`, `tra-iris-door`, `citb-iris-door`,
`sun-iris-door`, `rounddoor`, `sidedoor`, `silodoor`, `eco-door`, `maindoor`

**NPCs / Characters:**
`yakow`, `billy`, `assistant`, `sage`, `oracle`, `mayor`, `farmer`, `fisherman`,
`explorer`, `sculptor`, `gambler`, `geologist`, `warrior`, `robber`, `muse`,
`bird-lady`, `evilbro`, `evilsis`, `redsage`, `bluesage`, `yellowsage`

**Enemies:**
`kermit`, `hopper`, `puffer`, `bully`, `bonelurker`, `gnawer`, `lurkercrab`,
`lurkerworm`, `yeti`, `snow-bunny`, `ram`, `baby-spider`, `mother-spider`,
`flying-lurker`, `double-lurker`, `driller-lurker`, `plunger-lurker`,
`quicksandlurker`, `swamp-bat`, `swamp-rat`, `lightning-mole`

**Water / Hazards:**
`water-vol-deadly`, `cave-water`, `dark-eco-pool`, `lava`, `mud`,
`swamp-spike`, `spike`, `chainmine`, `tntbarrel`, `swamp-tetherrock`

**Effects / Decor:**
`windmill-one`, `windmill-sail`, `gondola`, `ropebridge`, `ceilingflag`,
`seaweed`, `villa-fisha`, `junglefish`, `starfish`, `pelican`, `seagull`,
`happy-plant`, `dark-plant`, `evilplant`, `darkvine`

**Test/Custom:**
`test-actor` — the custom actor template in `custom_assets/jak1/models/custom_levels/test-actor.glb`

---

## 5. ACTOR LINKING & EVENT CHAINING SYSTEM

Source: `goal_src/jak1/engine/entity/actor-link-h.gc`

Actors can form **linked lists** using `next-actor` and `prev-actor` lump properties.
The `actor-link-info` system provides methods to send events through these chains.

### Setting Up Actor Chains in JSON
```jsonc
// Actor A (fires first)
{
  "trans": [0, 5, 0], "etype": "basebutton",
  "lump": {
    "name": "switch-a",
    "next-actor": ["string", "platform-b"]   // points to actor B by name
  }
},
// Actor B (receives events from A)
{
  "trans": [10, 5, 0], "etype": "plat",
  "lump": {
    "name": "platform-b",
    "prev-actor": ["string", "switch-a"]
  }
}
```

### Event Messages (send via `send-event` in .gc code)
Common messages actors understand:
- `'attack` — deal damage
- `'touch` — contact event
- `'trigger` — activate
- `'notice` — alert
- `'jump` — jump action
- `'pause` / `'resume`
- `'anim-mode` — set animation mode
- `'clone-anim` — copy animation from another process

### Actor Chain Methods (from actor-link-info)
```lisp
(send-to-next link 'trigger)        ;; send to next actor in list
(send-to-prev link 'trigger)        ;; send to prev
(send-to-all-after link 'trigger)   ;; broadcast forward
(send-to-all-before link 'trigger)  ;; broadcast backward
(send-to-next-and-prev link 'msg)   ;; both directions
(apply-function-forward link fn arg) ;; apply a function to each actor forward
```

### Referencing Actors by Name vs AID
- By name (string): `(entity-actor-lookup lump 'next-actor 0)` — slow but readable
- By AID (uint): faster, set `base_id` in .jsonc, each actor gets `base_id + index`

---

## 6. SCRIPTED SEQUENCES / STATE MACHINES

Source: `goal_src/jak1/levels/village1/sequence-a-village1.gc`
Base class: `goal_src/jak1/engine/common-obs/process-taskable.gc`

### Pattern: Scripted Sequence Actor
```lisp
(deftype my-sequence (process-taskable)
  ((boat handle)        ;; handles to other processes
   (door handle))
  (:state-methods idle wait-for-trigger play-sequence done))

(defstate idle (my-sequence)
  :virtual #t
  :event (behavior ((proc process) (argc int) (msg symbol) (block event-message-block))
    (case msg
      (('trigger) (go-virtual wait-for-trigger))))
  :code (behavior ()
    (loop (suspend))))

(defstate play-sequence (my-sequence)
  :virtual #t
  :code (behavior ()
    ;; camera control
    (send-event *camera* 'change-state cam-fixed 0)
    ;; control other actors
    (send-event (handle->process (-> self boat)) 'anim-mode 'clone-anim)
    ;; wait for animation frames
    (ja-no-frames 0)          ;; wait N frames
    (suspend)
    ;; task completion
    (task-complete! self (-> self game-task))
    (go-virtual done)))
```

### Timer-Based Sequence Commands (from sequence-a-village1.gc pattern)
```lisp
;; Inside a :code behavior, use frame counters:
(let ((start-time (current-time)))
  (until (>= (- (current-time) start-time) (seconds 3.0))
    (suspend)))
```

### Task Completion
```lisp
;; Mark a game-task complete:
(task-complete! self (game-task my-task-name))
;; or:
(close-specific-task! (game-task my-task) (task-status need-resolution))
```

---

## 7. PATH SYSTEM (Actor Movement Along Splines)

Source: `goal_src/jak1/engine/geometry/path-h.gc`

### Adding a Path to an Actor in JSON
```jsonc
{
  "trans": [0, 5, 0],
  "etype": "my-patrolling-actor",
  "lump": {
    "name": "patrol-actor",
    "path": ["vector4m",
      [0.0, 5.0, 0.0, 1.0],    // point 0
      [10.0, 5.0, 0.0, 1.0],   // point 1
      [10.0, 5.0, 20.0, 1.0],  // point 2
      [0.0, 5.0, 20.0, 1.0]    // point 3
    ]
  }
}
```

### Using a Path in .gc Code
```lisp
(deftype my-patrol (process-drawable)
  ((path path-control))  ;; path component
  ...)

;; In init-from-entity!:
(set! (-> this path) (new 'process 'path-control this 'path 0.0))

;; In behavior:
(let ((pos (new 'stack 'vector))
      (t 0.0))
  (eval-path-curve! (-> self path) pos t 'interp)  ;; t = 0.0 to 1.0
  (vector-copy! (-> self root trans) pos))
```

---

## 8. COLLISION SYSTEM

Source: `goal_src/jak1/engine/collide/pat-h.gc`
Blender plugin: `custom_assets/blender_plugins/opengoal.py`

### PAT Surface Attributes (per mesh triangle)
**Materials:** `stone`, `ice`, `quicksand`, `waterbottom`, `tar`, `sand`, `wood`,
`grass`, `pcmetal`, `snow`, `deepsnow`, `hotcoals`, `lava`, `crwood`, `gravel`,
`dirt`, `metal`, `straw`, `tube`, `swamp`, `stopproj`, `rotate`, `neutral`

**Modes:** `ground`, `wall`, `obstacle`

**Events:** `none`, `deadly`, `endlessfall`, `burn`, `deadlyup`, `burnup`, `melt`

**Flags:** `set_invisible`, `noedge`, `noentity`, `nolineofsight`, `nocamera`

### Level-Wide Collision Settings (in .jsonc)
```jsonc
"automatic_wall_detection": true,   // auto-classify ground vs wall by angle
"automatic_wall_angle": 45.0,       // angle threshold in degrees
"double_sided_collide": false        // 2x slower, only if mesh has bad normals
```

### Custom Actor Collision Setup (from test-zone-obs.gc)
```lisp
;; In init-collision!:
(let ((cshape (new 'process 'collide-shape-moving this (collide-list-enum hit-by-player))))
  (set! (-> cshape dynam) (copy *standard-dynamics* 'process))
  (set! (-> cshape reaction) default-collision-reaction)
  (let ((cgroup (new 'process 'collide-shape-prim-group cshape (the uint 1) 0)))
    (set! (-> cgroup prim-core collide-as) (collide-kind ground-object))
    (set! (-> cgroup collide-with) (collide-kind target))
    (set! (-> cgroup prim-core action) (collide-action solid rider-plat-sticky))
    (let ((mesh (new 'process 'collide-shape-prim-mesh cshape (the uint 0) (the uint 0))))
      (set! (-> mesh prim-core collide-as) (collide-kind ground-object))
      (set! (-> mesh collide-with) (collide-kind target))
      (set! (-> mesh prim-core action) (collide-action solid))
      (append-prim cgroup mesh))
    (set! (-> cshape nav-radius) (* 0.75 (-> cshape root-prim local-sphere w)))
    (backup-collide-with-as cshape)
    (set! (-> this root) cshape)))
```

---

## 9. ANIMATION SYSTEM

Source:
- `goal_src/jak1/engine/anim/joint-h.gc` — joint control channel types
- `goal_src/jak1/engine/anim/joint.gc` — joint update logic
- `goalc/build_actor/common/animation_processing.h` — GLTF animation → game format

### GLTF Requirements for Animated Actors
- Must have a **Skin** (armature/skeleton)
- Skeleton root must be defined in the GLTF skin's `skeleton` field
- Joints must be in **child-index > parent-index** order (topological sort)
- Animations use **keyframes** (not baked) — game interpolates between them
- Framerate: 60fps recommended (game will resample)

### Initializing Animations in .gc
```lisp
;; Initialize with a skeleton group:
(initialize-skeleton this *my-actor-sg* '())

;; Play an animation by index:
(ja-channel-push! 1 (seconds 0.1))   ;; push channel with 0.1s blend
(let ((chan (-> self draw jbuf janim channel 0)))
  (set! (-> chan frame-group) (-> self draw art-group data ANIM_INDEX))
  (set! (-> chan num) (ja-anim-length (-> chan frame-group)))
  (set! (-> chan frame-num) 0.0))

;; Looping animation:
(ja-no-frames 0)    ;; advance 0 frames
(ja :num! (loop!)) ;; loop current anim

;; Common state post functions:
:post transform-post        ;; standard transform update
:post ja-post               ;; joint animation post
```

### Animation Channel Modes
- `'none` — no animation, static pose
- `'clone-anim` — copy animation from another process
- `'interp` — interpolate between keyframes
- `'spool` — stream animation from disc

---

## 10. BLENDER WORKFLOW & TECH ART

### Level Mesh Requirements
1. **Geometry:** Any mesh — all faces are walkable unless collision properties set otherwise
2. **Vertex Colors:** Required for lighting. Use Cycles bake:
   - Renderer: Cycles
   - Bake Type: Diffuse
   - Uncheck "Color" contribution
   - Bake to vertex color attribute (only first group used)
3. **Materials:** Can have textures (PNG); referenced by material name
4. **Scale:** Blender 1 unit = 1 meter in OpenGOAL units

### Custom Actor (.glb) Requirements
1. **Mesh + Armature:** Skinned mesh with skeleton for animated actors
2. **Joint naming:** Joints can have any names; order must be parent-before-child
3. **Animations:** Named clips in Blender → multiple in-game animations
4. **Bounds:** Set in game.gp `build-actor` call or `def-actor` in .gc

### Existing Blender Plugin (needs 4.x update)
`custom_assets/blender_plugins/opengoal.py` — currently targets Blender 2.83
Adds per-material and per-object collision properties to the Properties panel:
- Material type (stone/ice/lava/etc.)
- Collision mode (ground/wall/obstacle)
- Event (deadly/burn/endlessfall/etc.)
- Flags (invisible, no-edge, no-entity, no-LOS, no-camera)

### Sky/Tpage Reference
To use a vanilla sky, add the corresponding tpage to your `.gd` in the alpha slot:

| Sky level | Tpage file |
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

## 11. GAME TASK SYSTEM

Source: `goal_src/jak1/engine/game/task/game-task-h.gc`

### Using game-task with Actors
```jsonc
// Power cell tied to a task:
{
  "etype": "fuel-cell",
  "game_task": "(game-task jungle-eggtop)",
  "lump": {
    "eco-info": ["cell-info", "(game-task jungle-eggtop)"]
  }
}
```

Custom levels should use `"(game-task none)"` unless you define new tasks.

### Task Status States
- `need-introduction` → `need-hint` → `need-reminder` → `need-reward-speech` → `need-resolution` → `complete`

---

## 12. UNITS & COORDINATE SYSTEM

| What | Value |
|---|---|
| 1 meter | 4096.0 game units |
| 1 degree | 182.044 game units (65536 = 360°) |
| 1 second | ~300 frames (NTSC) |
| Blender Z-up | Game Y-up — GLTF exporter handles this |
| `(meters N)` macro | Converts N meters to game float units |
| `(degrees N)` macro | Converts N degrees to game float units |
| `(seconds N)` macro | Converts N seconds to frame count |

---

## 13. KEY FILES FOR FURTHER EXPLORATION

When you need to go deeper, start here:

| Goal | Look at |
|---|---|
| Add new game task | `engine/game/task/game-task-h.gc` |
| Understand nav mesh / AI pathfinding | `engine/nav/navigate.gc`, `engine/common-obs/nav-enemy.gc` |
| Add particle effects | `engine/gfx/sprite/sparticle/sparticle-launcher.gc` |
| Understand camera system | `engine/camera/` directory |
| Water volumes | `engine/common-obs/water.gc`, `water-h.gc` |
| Sound / music triggers | `engine/sound/`, ambients in `entity/ambient.gc` |
| Debug drawing tools | `engine/debug/` directory |
| Full example NPC with dialog | `levels/village1/assistant.gc` |
| Simple patrol enemy | `levels/village1/yakow.gc` |
| Complex boss fight | `levels/ogre/ogreboss.gc` |
| Scripted intro cutscene | `levels/village1/sequence-a-village1.gc` |
| Platform with button trigger | `engine/common-obs/plat-button.gc`, `basebutton.gc` |
| Rigid body physics objects | `engine/common-obs/rigid-body.gc` |
| Build actor pipeline internals | `goalc/build_actor/common/build_actor.cpp` |
| Level binary format | `goalc/build_level/jak1/LevelFile.cpp` |

---

## 14. BLENDER ADDON GOALS (Planned Tooling)

The following Blender 4.x addon features are planned/in-progress based on this codebase:

1. **Level Export Panel**
   - Set `long_name`, `iso_name`, `nickname`
   - Select mood/sky preset
   - One-click export to correct path as `.glb` with vertex color baking
   - Auto-generate `.jsonc` skeleton

2. **Actor Placement**
   - Place empties in Blender viewport representing actors
   - Dropdown of all 483 entity types
   - Set `bsphere` radius visually
   - Export actors array to `.jsonc`

3. **Art Group Auto-detect**
   - Scan placed actors → determine required `-ag.go` files → write `.gd`

4. **Collision Properties Panel** (update of existing `opengoal.py` for Blender 4.x)
   - Per-material: surface type, mode, event, flags
   - Per-object override

5. **Path Painter**
   - Draw Bezier/polyline paths in Blender
   - Export as `path` vector4m array in actor lump

6. **Event Sequence Timeline**
   - Visual node graph for `next-actor` / `prev-actor` chains
   - Set trigger conditions, messages, timing
   - Export linked actor definitions

7. **One-Click Build Trigger**
   - Run GOALC `(mi)` via subprocess after export
   - Status feedback in Blender UI


---

## 15. CONCRETE SPAWN EXAMPLES (Q: "How do I spawn this exact character?")

### Rule: Every vanilla actor needs 3 things
1. `etype` in the actor JSON
2. Its `-ag.go` in your `.gd` file
3. Its `.gc` compiled into your DGO (usually already in ENGINE.CGO or GAME.CGO — check below)

### Which actors are already compiled into ENGINE/GAME.CGO (no extra .o needed)?
These are always available — just add the art group:
- `plat`, `plat-eco`, `plat-button`, `balance-plat` → `plat-ag.go`, `plat-eco-ag.go`
- `crate` → `crate-ag.go`
- `fuel-cell` → `fuel-cell-ag.go`
- `eco-yellow`, `eco-blue`, `eco-green` → `money-ag.go` / `light-eco-ag.go`
- `money` → `money-ag.go`
- `buzzer` → `buzzer-ag.go`
- `warpgate` → `warpgate-ag.go`
- `water-vol-deadly` → no art group needed
- `dark-eco-pool` → no art group needed

### Which actors need their level's .gc compiled in too?
Level-specific actors (NPCs, enemies) live in their level's DGO. To use them in a custom level,
you must add their `.gc` source file to your build and compile it:

Example — spawning `yakow`:
```lisp
;; In your goal_src/jak1/levels/my-level/my-level-obs.gc, add at top:
(require "levels/village1/yakow.gc")
```
Then add to your `.gd`:
```lisp
"yakow-ag.go"
```

### Concrete Examples

**Spawn a power cell (no task):**
```jsonc
{
  "trans": [5.0, 3.0, 10.0],
  "etype": "fuel-cell",
  "game_task": "(game-task none)",
  "quat": [0, 0, 0, 1],
  "bsphere": [5.0, 3.0, 10.0, 8.0],
  "lump": {
    "name": "my-cell-1",
    "eco-info": ["cell-info", "(game-task none)"]
  }
}
```

**Spawn a yakow (ambient animal, no task):**
```jsonc
{
  "trans": [12.0, 0.0, 8.0],
  "etype": "yakow",
  "game_task": "(game-task none)",
  "quat": [0, 0, 0, 1],
  "bsphere": [12.0, 0.0, 8.0, 10.0],
  "lump": { "name": "my-yakow-1" }
}
```
Required in `.gd`: `"yakow-ag.go"`
Required in `.gc`: `(require "levels/village1/yakow.gc")`

**Spawn a steel crate with orbs:**
```jsonc
{
  "trans": [0.0, 2.0, 5.0],
  "etype": "crate",
  "game_task": "(game-task none)",
  "quat": [0, 0, 0, 1],
  "bsphere": [0.0, 2.0, 5.0, 5.0],
  "lump": {
    "name": "my-crate-1",
    "crate-type": ["symbol", "steel"],
    "eco-info": ["eco-info", "(pickup-type money)", 5]
  }
}
```

**Spawn yellow eco:**
```jsonc
{
  "trans": [3.0, 1.0, 3.0],
  "etype": "eco-yellow",
  "game_task": "(game-task none)",
  "quat": [0, 0, 0, 1],
  "bsphere": [3.0, 1.0, 3.0, 5.0],
  "lump": { "name": "my-eco-1" }
}
```

**Spawn a jump pad (springbox):**
```jsonc
{
  "trans": [0.0, 0.0, 0.0],
  "etype": "springbox",
  "game_task": "(game-task none)",
  "quat": [0, 0, 0, 1],
  "bsphere": [0.0, 0.0, 0.0, 5.0],
  "lump": {
    "name": "my-jump-pad",
    "spring-height": ["meters", 15.0]
  }
}
```

**Spawn a warp gate:**
```jsonc
{
  "trans": [20.0, 0.0, 20.0],
  "etype": "warpgate",
  "game_task": "(game-task none)",
  "quat": [0, 0, 0, 1],
  "bsphere": [20.0, 0.0, 20.0, 10.0],
  "lump": { "name": "my-warpgate" }
}
```

---

## 16. LIGHTING BAKE — EXACT BLENDER STEPS (Q: "How do I bake lighting?")

The game uses **vertex colors** for baked lighting — not lightmaps or texture baking.
The build pipeline reads `COLOR_0` from the GLTF and quantizes it to a color palette.

### Required: Use the custom GLTF exporter plugin
`custom_assets/blender_plugins/gltf2_blender_extract.py` — this patches the GLTF exporter
to correctly export `color_attributes` (Blender 3.3+) as `COLOR_0` in the GLTF.

**Important:** Must use **vertex colors** (not face corner colors). The plugin comment states:
> "Make sure that no meshes have face corner colors. All colors must be vertex colors (float)."

### Step-by-step bake process in Blender
1. Set render engine to **Cycles** (not EEVEE)
2. Set up your lights in the scene (sun, area lights, etc.)
3. Select your level mesh
4. In **Properties → Object Data → Color Attributes**, ensure you have exactly **one** attribute
   - Name it anything (e.g. `Col`)
   - Domain: **Vertex** (not Face Corner)
   - Data Type: **Color** (float RGBA)
5. Go to **Render Properties → Bake**:
   - Bake Type: **Diffuse**
   - Contributions: uncheck **Color**, keep **Direct** and **Indirect** checked
   - Output → Target: **Active Color Attribute**
6. Click **Bake**
7. Export using the patched exporter with **Vertex Colors** enabled

### Known limitations
- Only the **first** color attribute (`COLOR_0`) is used by the game
- Color is quantized using a KD-tree color palette (max 256 colors by default)
- Very dark or very bright bakes may look washed out — aim for mid-range values
- No normal maps, specular, or PBR — vertex color only

---

## 17. SOUND & MUSIC SYSTEM (Q: "How do I change level sounds, music?")

### Setting Level Music in level-info.gc
```lisp
(define my-level
  (new 'static 'level-load-info
       ...
       :sound-banks '(village1)    ;; SFX bank to load
       :music-bank 'village1       ;; Music to play
       :ambient-sounds '()         ;; No ambient loops
       ...))
```

**Available music banks:** `village1`, `village2`, `village3`, `beach`, `jungle`, `jungleb`,
`misty`, `swamp`, `rolling`, `snow`, `firecanyon`, `lavatube`, `ogre`, `sunken`,
`maincave`, `darkcave`, `citadel`, `finalboss`, `#f` (silence)

**Sound banks** (SFX) use same names. You can mix: e.g. sound-banks `'(village1 jungle)`.

### Music Variations (Flava) — change mid-level
Music flava changes the instrument layer/variation of the current music bank.
Set it in `.gc` code when something happens (NPC approached, area entered, etc.):

```lisp
;; Set a music flava:
(set-setting! 'sound-flava #f 30.0 (music-flava sage))
;; Remove and revert to default:
(remove-setting! 'sound-flava)
```

**All available music-flava values:**
`racer`, `flutflut`, `to-maincave`, `to-snow`, `sage`, `assistant`, `birdlady`,
`mayor`, `sculptor`, `explorer`, `sage-yellow`, `sage-red`, `sage-blue`, `miners`,
`warrior`, `geologist`, `gambler`, `sage-hut`, `dock`, `farmer`, `jungleb-eggtop`,
`misty-boat`, `misty-battle`, `beach-sentinel`, `beach-cannon`, `beach-grotto`,
`citadel-center`, `robocave`, `robocave-top`, `maincave`, `darkcave`, `snow-battle`,
`snow-cave`, `snow-fort`, `snow-balls`, `levitator`, `swamp-launcher`, `swamp-battle`,
`jungle-temple-exit`, `jungle-lurkerm`, `jungle-temple-top`, `rolling-gorge`,
`ogre-middle`, `ogre-end`, `lavatube-middle`, `lavatube-end`, `finalboss-middle`,
`finalboss-end`, `default`

### Playing Sound Effects in .gc Code
```lisp
;; One-shot sound at entity position:
(sound-play "launch")                          ;; by name string
(sound-play "miss" :vol 80.0 :pitch 1000)     ;; with volume and pitch

;; Positional (3D) sound:
(sound-play "plat-land" :id (new-sound-id) :position #t)

;; Store a sound ID to stop it later:
(let ((sid (new-sound-id)))
  (sound-play "dark-eco" :id sid)
  ;; later:
  (sound-stop sid))
```

### Ambient Sound Zones (Looping Area Sound)
Use the `ambients` array in `.jsonc` to create audio trigger zones:
```jsonc
{
  "trans": [0.0, 5.0, 0.0, 20.0],   // x y z + trigger radius in meters
  "bsphere": [0.0, 5.0, 0.0, 25.0],
  "lump": {
    "name": "waterfall-ambient",
    "type": "'ambient-sound",
    "effect-name": ["string", "waterfall"]   // sound name from bank
  }
}
```

---

## 18. CUSTOM COLLISION MESHES (Q: "How do I make custom collision?")

### Two types of collision in custom levels

**Type A — Level background mesh collision (automatic)**
Any geometry in your `.glb` is automatically treated as walkable collision.
Use `automatic_wall_detection: true` and `automatic_wall_angle: 45.0` to auto-classify
steep faces as walls.

Per-face/material collision attributes are set in Blender using the `opengoal.py` plugin.
These get exported as GLTF material extras and read by the level builder.

**Type B — Actor collision (runtime, set in .gc code)**
Custom actors need their own collision shapes defined in their `init-collision!` method.

### Collision Shape Types
```lisp
;; Sphere — cheapest, best for enemies/NPCs:
(new 'process 'collide-shape-prim-sphere cshape (the uint 0))

;; Box — for crates, rectangular objects:
(new 'process 'collide-shape-prim-group cshape (the uint 1) 0)

;; Mesh — most accurate, uses art group mesh data:
(new 'process 'collide-shape-prim-mesh cshape (the uint 0) (the uint 0))
```

### Collision Kinds (what an object IS)
```
background    — static level geometry
target        — Jak himself
enemy         — enemies (also used for some NPCs)
wall-object   — doors, pushers, blockers
ground-object — platforms, dynamic floor objects
projectile    — thrown/shot objects
water         — water volumes
powerup       — collectables
crate         — breakable crates
```

### Collision Actions (what it DOES when touched)
```
solid              — blocks movement
rider-plat-sticky  — Jak sticks to it when riding (platforms)
rider-target       — Jak is riding something
edgegrab-active    — can grab its edge
attackable         — can be attacked
```

### Collision Offense (how hard to destroy)
```
no-offense      — can't interact
touch           — just needs to be touched
normal-attack   — any attack (spin, punch)
strong-attack   — ground pound, zoomer, flut attack only
indestructible  — cannot be destroyed
```

### Full Invisible Trigger Zone (no visual, triggers event)
```lisp
;; A collide-shape-prim-sphere with collide-action touch and no-offense touch:
(let ((sphere (new 'process 'collide-shape-prim-sphere cshape (the uint 0))))
  (set! (-> sphere prim-core collide-as) (collide-kind wall-object))
  (set! (-> sphere collide-with) (collide-kind target))
  (set! (-> sphere prim-core action) (collide-action solid))
  (set! (-> sphere prim-core offense) (collide-offense no-offense))
  (set-vector! (-> sphere local-sphere) 0.0 0.0 0.0 (meters 5.0)))

;; In the actor's :event handler, catch 'touch:
:event (behavior ((proc process) (argc int) (msg symbol) (block event-message-block))
  (case msg
    (('touch) (go-virtual triggered))))
```

---

## 19. MOVING PLATFORM — FULL SETUP (Q: "Spawn a moving platform with start/end/speed")

### How the plat system works
The vanilla `plat` actor reads three things from its entity data:
1. **`path`** — a series of waypoints (vector4m array) defining the route
2. **`sync`** — period (loop duration) and phase (start offset) — this controls speed
3. **`options`** — `fact-options` flags like `wrap-phase` (loop vs. ping-pong)

Speed is **not set directly** — it's derived from path length ÷ sync period.
To go faster: shorten the period. To go slower: lengthen it.

### Spawn a vanilla moving platform in .jsonc
```jsonc
{
  "trans": [0.0, 5.0, 0.0],
  "etype": "plat",
  "game_task": "(game-task none)",
  "quat": [0, 0, 0, 1],
  "bsphere": [0.0, 5.0, 0.0, 10.0],
  "lump": {
    "name": "my-moving-platform",
    // Path: array of waypoints in meters. Platform travels start→end→start
    "path": ["vector4m",
      [0.0, 5.0, 0.0, 1.0],    // start position
      [0.0, 5.0, 20.0, 1.0],   // end position
      // add more points for curved paths
    ],
    // sync: [period-in-frames, phase-0-to-1, ease-out, ease-in]
    // period 600 = 10 seconds for a full loop (NTSC: ~60fps)
    // phase 0.0 = starts at beginning of path
    // ease-out 0.15 = smooth deceleration at ends
    // ease-in 0.15 = smooth acceleration at ends
    "sync": ["uint32", 600, "float", 0.0, "float", 0.15, "float", 0.15],
    // wrap-phase = loops (0→1→0). Without it: ping-pong (0→1→0 reverse)
    "options": ["enum-int32", "(fact-options wrap-phase)"]
  }
}
```
Required in `.gd`: `"plat-ag.go"`

### Speed formula
```
speed (meters/sec) ≈ path_length_meters / (period_frames / 60)

Example: 20m path, period=600 frames → 20 / (600/60) = 2 m/s
For 5 m/s: period = (20 / 5) * 60 = 240 frames
```

### Platform variants available
| etype | Art group | Notes |
|---|---|---|
| `plat` | `plat-ag.go` | Standard precursor platform |
| `plat-eco` | `plat-eco-ag.go` | Eco-powered glowing platform |
| `plat-flip` | `plat-flip-ag.go` | Flips when stood on |
| `balance-plat` | `balance-plat-ag.go` | Tilts with weight |
| `orbit-plat` | `orbit-plat-ag.go` | Orbits a center point |
| `side-to-side-plat` | `side-to-side-plat-ag.go` | Slides on one axis |
| `wall-plat` | `wall-plat-ag.go` | Emerges from wall |
| `wedge-plat` | `wedge-plat-ag.go` | Wedge-shaped |
| `tar-plat` | `tar-plat-ag.go` | Floats on tar |

---

## 20. BLENDER ONE-BUTTON EXPORT WORKFLOW (Planned)

**Goal:** Place actors as Blender empties → click Export → all files update → relaunch game.

### Files that need updating per iteration
1. `custom_assets/jak1/levels/MY-LEVEL/my-level.jsonc` — actor/ambient list + settings
2. `custom_assets/jak1/levels/MY-LEVEL/my-level.glb` — level mesh
3. `custom_assets/jak1/levels/MY-LEVEL/mylevel.gd` — DGO art group list (if actors changed)
4. Trigger `(mi)` in GOALC to recompile → outputs to `out/jak1/iso/MYL.DGO`

### Blender Empty → Actor Mapping Convention (for addon)
Recommended naming convention for empties in Blender:
```
ACTOR_yakow_1        → etype=yakow, uid=1
ACTOR_fuel-cell_2    → etype=fuel-cell, uid=2
ACTOR_plat_1         → etype=plat, uid=1 (check for PATH_ child empties)
PATH_plat_1_0        → waypoint 0 for plat_1
PATH_plat_1_1        → waypoint 1 for plat_1
AMBIENT_music_1      → ambient zone, uid=1
```

### GOALC Subprocess Call (Python)
```python
import subprocess, socket

def trigger_goalc_rebuild():
    """Send (mi) to running GOALC via TCP (default port 8181)"""
    try:
        with socket.create_connection(("localhost", 8181), timeout=5) as s:
            s.sendall(b'(mi)\n')
            result = s.recv(4096).decode()
            return result
    except ConnectionRefusedError:
        return "GOALC not running — start gk and goalc first"
```

### Export Script Pseudocode
```python
def full_export(context, level_name, project_root):
    # 1. Export level mesh as GLB
    export_glb(f"{project_root}/custom_assets/jak1/levels/{level_name}/{level_name}.glb")

    # 2. Collect actor empties from scene
    actors = collect_actor_empties(context.scene)
    ambients = collect_ambient_empties(context.scene)

    # 3. Generate .jsonc
    jsonc = build_jsonc(level_name, actors, ambients, context.scene.opengoal_settings)
    write_jsonc(f"{project_root}/custom_assets/jak1/levels/{level_name}/{level_name}.jsonc", jsonc)

    # 4. Generate .gd (scan required art groups from actor types)
    art_groups = resolve_art_groups(actors)
    gd = build_gd(level_name, art_groups)
    write_gd(f"{project_root}/custom_assets/jak1/levels/{level_name}/{level_name[:3].upper()}.gd", gd)

    # 5. Trigger GOALC rebuild
    result = trigger_goalc_rebuild()
    return result
```
