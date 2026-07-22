# OpenGOAL Level Flow System — Complete Research Reference

**Research date:** April 2026  
**Branch:** feature/level-flow  
**Status:** Research complete. Implementation shipped to main (commit 6be87e3).  
**Sources:** Full source crawl of `goal_src/jak1/engine/level/`, `engine/game/game-info*.gc`, `engine/target/target-death.gc`, `engine/target/logic-target.gc`, `engine/common-obs/basebutton.gc`, `levels/common/launcherdoor.gc`, `levels/jungle/jungle-elevator.gc`

---

## Overview

Level flow in OpenGOAL is the combination of five interlocking systems:

1. **`continue-point`** — static spawn data (position, camera, which levels to load)
2. **`load-state`** — the two-slot runtime "what do I want loaded right now" machine
3. **`load-boundary`** — invisible polygonal triggers in the world that fire load-state commands and checkpoint assignments
4. **`level-load-info`** — per-level metadata including continue point lists, alt-load-commands, packages, bsphere
5. **Actor lumps** — `continue-name` and `load-name` on entities like `launcherdoor` and `jungle-elevator`

---

## 1. `continue-point` — The Spawn Record

**Defined in:** `engine/game/game-info-h.gc`

```
(deftype continue-point (basic)
  ((name          string)
   (level         symbol)          ; which level this point belongs to
   (flags         continue-flags)
   (trans         vector :inline)  ; spawn position
   (quat          quaternion :inline) ; spawn facing
   (camera-trans  vector :inline)  ; camera position on spawn
   (camera-rot    float 9)         ; camera 3x3 rotation matrix (row-major)
   (load-commands pair)            ; commands to execute on spawn (see §3)
   (vis-nick      symbol)          ; vis nickname e.g. 'vi1
   (lev0          symbol)          ; primary level to load
   (disp0         symbol)          ; display mode for lev0
   (lev1          symbol)          ; secondary level to load (or #f)
   (disp1         symbol)))        ; display mode for lev1 (or #f)
```

### `continue-flags` enum (bitfield)
| Flag | Value | Meaning |
|---|---|---|
| `warp` | bit 2 | This is a warp gate destination. Triggers cutscene/teleport in `target-continue`. |
| `demo` | bit 3 | Demo mode spawn |
| `intro` | bit 4 | Triggers intro cutscene sequence |
| `sage-intro` | bit 5 | Triggers sage intro cutscene |
| `sage-demo-convo` | bit 6 | Sage demo conversation |
| `title` | bit 7 | Title screen spawn |
| `game-start` | bit 10 | First-ever game start (completes intro task) |
| `sage-ecorocks` | bit 11 | Sage ecorocks cutscene |

Flags 0, 1, 8, 9 are reserved/unused.

**Zero-flag continue-points** are the "normal" checkpoints — no cutscene, no warp, just respawn.  
During the automatic checkpoint assignment loop, only **zero-flag** continues are eligible for auto-assignment (see §5).

### `disp0` / `disp1` — Display Mode Values
| Value | Meaning |
|---|---|
| `'display` | Normal: load and show. If `wait-for-load` is `#t` on the level, block until loaded. |
| `'special` | Load but mark as "special" — used for adjacent levels that should be loaded but may not immediately need full display. Seen on village levels when loading sub-areas. |
| `'special-vis` | Like special but also implies a vis relationship. Used in swamp dock continues. |
| `'display-no-wait` | Display but don't wait for load even if `wait-for-load` is set. |
| `'display-self` | Forces vis system into single-level mode (vis only uses self). Used in title screen. |
| `#f` | Don't display this slot. Level may still be held in memory. |

### Where continue-points live
All continue-points are **statically allocated** inside their level's `level-load-info` under the `:continues` list.  
They are looked up at runtime by `get-continue-by-name` which walks `*level-load-list*`.

**Special case: `*default-continue*`**  
A fallback static continue-point with `#f` for everything. Used in debug mode. `get-or-create-continue!` falls back to this if no continue is set, placing the player in front of the camera.

---

## 2. `load-state` — The Two-Slot Load Machine

**Defined in:** `engine/game/game-info-h.gc`

```
(deftype load-state (basic)
  ((want          level-buffer-state 2 :inline)  ; 2 level slots
   (vis-nick      symbol)                         ; current vis nickname
   (command-list  pair)                            ; pending timed commands
   (object-name   symbol 256)                     ; alive/dead object name table
   (object-status basic 256)))                    ; saved perm status for alive/dead
```

```
(deftype level-buffer-state (structure)
  ((name          symbol)   ; level name symbol
   (display?      symbol)   ; display mode (see §1)
   (force-vis?    symbol)
   (force-inside? symbol)))
```

The game can hold **at most 2 levels active** at any time (slots 0 and 1).

### Key functions
| Function | What it does |
|---|---|
| `(load-state-want-levels lev0 lev1)` | Set both level slots simultaneously |
| `(load-state-want-display-level level mode)` | Set display mode for a level that's already in a slot |
| `(load-state-want-vis nick)` | Set which level's vis to use |
| `(load-state-want-force-vis level onoff)` | Force vis for a level |
| `(want-levels this lev0 lev1)` | Method version of above |
| `(backup-load-state-and-set-cmds this cmds)` | Save current state, inject commands (used during respawn) |
| `(restore-load-state this)` | Restore from backup |
| `(execute-commands-up-to this time)` | Run command-list up to a given time |

### The `update!` loop
Called every frame in `activate-levels!`. Compares `*load-state* want` against current level statuses and:
- Starts loading a level if it's wanted but not loaded
- Activates/displays a level if it's loaded and `display?` is set
- Deactivates a level if `display?` is cleared

---

## 3. Continue Point `load-commands` — The Spawn Command Language

When a continue-point is used (death respawn or warp), `target-continue` executes all entries in its `:load-commands` list via `execute-command`. These run **after** the level is loaded.

### All supported command types in `execute-command`:

| Command | Syntax | Effect |
|---|---|---|
| `set!` | `(set! symbol value)` | Set a global variable |
| `eval` | `(eval func)` | Call a zero-arg function |
| `want-vis` | `(want-vis nick)` | Set vis nick |
| `want-levels` | `(want-levels lev0 lev1)` | Load both level slots |
| `display-level` | `(display-level level mode)` | Set display mode |
| `want-force-vis` | `(want-force-vis level onoff)` | Force vis |
| `want-force-inside` | `(want-force-inside level onoff)` | Force inside |
| `alive` | `(alive "entity-name")` | Birth a specific entity (saves/restores its perm status) |
| `dead` | `(dead "entity-name")` | Kill and mark a specific entity dead |
| `kill` | `(kill "entity-name")` | Kill an entity (sets dead perm) |
| `special` | `(special "entity-name" #t/#f)` | Set/clear bit-7 perm flag on an entity |
| `active` | `(active level-name)` | Suspend until the level is active |
| `part-tracker` | `(part-tracker group entity)` | Spawn a particle tracker on an entity |
| `auto-save` | `(auto-save ...)` | Trigger auto-save |
| `shadow` | `(shadow process onoff)` | Toggle shadows |
| `time-of-day` | `(time-of-day hour)` | Set time of day (-1 = resume) |
| `save` | `(save)` | Backup the current load-state |
| `setting-reset` | `(setting-reset sym value)` | Set a settings value |
| `setting-unset` | `(setting-unset sym)` | Clear a settings override |
| `blackout` | `(blackout frames)` | Black screen for N frames |
| `teleport` | `(teleport)` | Set *teleport* flag |
| `joint` | `(joint ...)` | Send joint event to movie process |
| `ambient` | `(ambient type entity)` | Spawn ambient hint |
| `send-event` | `(send-event process event ...)` | Send event to a process |

**Important:** `(teleport)` is **always injected automatically** during a continue — you don't add it manually.

### Commonly seen in practice:
```lisp
; Make a specific entity alive (e.g. exit chamber doors):
(alive "exit-chamber-1")

; Set an entity's special flag (med-res geometry objects):
(special "med-res-level-1" #t)
(special "fishermans-boat-2" #t)

; Set an entity's special flag to false:
(special "swamp-blimp-3" #t)
(special "citb-exit-plat-4" #t)
```

The `special` command with `#t`/`#f` maps to `entity-perm-status bit-7`. Many geometry swaps and optional objects use this flag.

---

## 4. `level-load-info` — Per-Level Metadata

**Defined in:** `engine/level/level-h.gc`  
**Data in:** `engine/level/level-info.gc`

```
(deftype level-load-info (basic)
  ((name              symbol)          ; e.g. 'village1
   (visname           symbol)          ; e.g. 'village1-vis
   (nickname          symbol)          ; e.g. 'vi1 (3-letter)
   (index             int32)           ; level number (1-indexed)
   (packages          pair)            ; DGO packages to load e.g. '(village1)
   (sound-banks       pair)
   (music-bank        symbol)
   (ambient-sounds    pair)
   (mood              symbol)
   (mood-func         symbol)
   (ocean             symbol)
   (sky               symbol)
   (sun-fade          float)
   (continues         pair)            ; list of continue-points for this level
   (tasks             pair)            ; game-task indices that belong here
   (priority          int32)           ; load priority (0xc8 = 200 for hubs, 100 for others)
   (load-commands     pair)            ; ??? (all empty in vanilla)
   (alt-load-commands pair)            ; indexed list of load-state command lists
   (bsp-mask          uint64)          ; BSP visibility mask
   (bsphere           sphere)          ; bounding sphere (x,z,w = centre xz + radius)
   (buzzer            int32)           ; scout fly task index
   (bottom-height     meters)          ; death plane Y
   (run-packages      pair)            ; packages needed before level can run
   (wait-for-load     symbol)))        ; #t = block until fully loaded on display
```

### `alt-load-commands` — Indexed Level Load Recipes

Used by `load-command-get-index` to switch level load states in response to gameplay events.

```lisp
; village1's alt-load-commands:
'(((display village1) (load misty))          ; index 0
  ((special village1) (display misty))       ; index 1
  ((display village1) (load beach)))         ; index 2
```

The `jungle-elevator` uses this: going down calls index 0, going up calls index 1.  
Command format mirrors `execute-command` syntax.

### Notable `level-load-info` fields per level:

| Level | `wait-for-load` | `priority` | `run-packages` | Notes |
|---|---|---|---|---|
| village1 | `#t` | 200 | `'("common")` | Hub level |
| village2 | `#t` | 200 | `'("common")` | Hub level |
| village3 | `#f` | 200 | `'("common")` | Hub level |
| training | `#f` | 100 | `'("common" "villagep")` | Needs villagep for warp gate code |
| jungleb | `#f` | 100 | `'("common" "jungle")` | Sub-level |
| sunkenb | `#f` | 100 | `'("common" "sunken")` | Sub-level |
| darkcave | `#t` | 100 | `'("common" "maincave")` | Sub-level |
| robocave | `#t` | 100 | `'("common" "maincave")` | Sub-level |
| finalboss | `#f` | 100 | `'("common")` | |
| intro/demo/title | `#f` | 100 | `'("common")` | Special levels |

### `*level-load-list*` — The Master List
A global pair-list of all level name symbols, in order. `get-continue-by-name` and `lookup-level-info` walk this list. Custom levels are added with `(cons! *level-load-list* 'my-level)`. The existing `test-zone` level is an example.

---

## 5. `load-boundary` — Spatial Level Flow Triggers

**Defined in:** `engine/level/load-boundary-h.gc`  
**Data in:** `engine/level/load-boundary-data.gc`  
**Count in vanilla:** 170 boundaries total

Load boundaries are **polygonal planes** (a list of 2D XZ vertices + Y top/bot extents). They activate when either the **camera** or the **player** (controlled by the `player` flag) crosses them.

### `load-boundary` structure
```
(deftype load-boundary (basic)
  ((num-points  uint16)
   (flags       load-boundary-flags)   ; open or closed, player vs camera
   (top-plane   float)                 ; max Y
   (bot-plane   float)                 ; min Y
   (tri-cnt     int32)
   (next        load-boundary)         ; linked list
   (cmd-fwd     load-boundary-crossing-command)  ; command on forward crossing
   (cmd-bwd     load-boundary-crossing-command)  ; command on backward crossing
   (rejector    vector)                ; fast rejection bounding circle
   (data        lbvtx ...)))          ; XZ vertex array (after struct in memory)
```

### `load-boundary-flags`
| Flag | Meaning |
|---|---|
| `closed` | Shape is a closed polygon (player inside/outside), not an open line |
| `player` | Trigger on player position; default is camera position |

### Boundary Command Types (`load-boundary-cmd`)
| Cmd | What fires |
|---|---|
| `checkpt` | `(set-continue! *game-info* name)` — assigns a named checkpoint |
| `load` | `(load-state-want-levels lev0 lev1)` — loads two levels |
| `display` | `(load-state-want-display-level lev0 mode)` — sets display mode |
| `vis` | `(load-state-want-vis nick)` — switches vis nickname |
| `force-vis` | `(load-state-want-force-vis lev onoff)` |

### Breakdown of vanilla boundaries
| Type | Count |
|---|---|
| `checkpt` | 71 |
| `display` | 97 |
| `load` | 28 |
| `vis` | 40 |

**Key insight:** `checkpt` boundaries are the primary mechanism for **automatic checkpoint assignment** as the player moves around a level. They don't respawn the player — they just update `*game-info* current-continue` silently.

### GOAL macro for defining a boundary
```lisp
(static-load-boundary
  :flags (player)             ; or () for camera
  :top 100000.0               ; max Y in game units
  :bot -100000.0              ; min Y
  :points (x0 z0 x1 z1 ...)  ; XZ pairs, game units
  :fwd (checkpt "my-checkpoint" #f)   ; forward crossing cmd
  :bwd (load village1 #f))           ; backward crossing cmd
```

---

## 6. Actor-Based Level Transitions

### `launcherdoor` — The Vertical Launch Door

Used in jungle, maincave, sunken transitions. An actor with a collide mesh.

**How it works:**
- When player enters `launch-jump` surface and drops below `thresh-y`, door opens
- When player rises above `thresh-y` going up, it reads the `continue-name` lump:

```lisp
(let ((a1-3 (res-lump-struct (-> self entity) 'continue-name structure)))
  (when a1-3
    (let ((v1-36 (set-continue! *game-info* (the-as basic a1-3))))
      (load-commands-set! *level* (-> v1-36 load-commands)))))
```

The `continue-name` lump value is a **string** — the name of a continue-point. The door sets this as the current continue and also applies that continue's `load-commands` to the level group.

**Lump:** `continue-name` → string (continue-point name)

### `jungle-elevator` — The Bidirectional Elevator

Subclass of `plat-button`. Uses **both** `continue-name` lump AND `alt-load-commands`:

- On downward travel: calls `(load-command-get-index *level* 'jungle 0)` at 20% travel
- On upward travel: calls `(load-command-get-index *level* 'jungle 1)` at 80% travel
- On arrival at bottom: reads `continue-name` lump and sets continue

**Lump:** `continue-name` → string (continue-point name)

### `warp-gate` — The Eco Warp Gates

Defined in `engine/common-obs/basebutton.gc`.

- Level index → `*warp-info*` array lookup: `["training-warp" "village1-warp" "village2-warp" "village3-warp" "citadel-warp"]`
- Calls `(get-continue-by-name *game-info* warp-name)` then `(start 'play ...)` to warp
- The `continue-flags warp` flag on those continues triggers special warp-in animations and cutscenes in `target-continue`
- Also uses the `load-name` field on the destination level to wait for it to load

---

## 7. The Full Respawn Flow (`target-continue`)

This state runs when the player spawns (game start, death, warp):

1. **Set audio/blackout** — mute music/sfx, full black
2. **Move player to `(-> arg0 trans)`** — teleport
3. **Set rotation** from `(-> arg0 quat)`
4. **Set `*load-state*`** — copy lev0/lev1/vis-nick/disp values from continue-point
5. **Wait for levels** — suspends until both wanted+displayed levels are `'active`
6. **`backup-load-state-and-set-cmds`** — saves current load state
7. **Inject `(teleport)` command** always
8. **Execute `load-commands`** from continue-point — `alive`, `dead`, `special`, etc.
9. **`restore-load-state`** — restores backup
10. **Set camera** — copies `camera-trans` and `camera-rot` from continue-point
11. **Check flags** — if `warp`, `intro`, `sage-intro`, etc., go to special state
12. **`(set-continue! *game-info* arg0)`** — record this continue as the current one
13. **`go target-stance`** — done, player is alive

### `set-continue!` — Accepts Three Forms
```lisp
; String lookup:
(set-continue! *game-info* "village1-hut")

; Direct continue-point object:
(set-continue! *game-info* my-continue-point)

; Fallback (nil/false/invalid):
(set-continue! *game-info* #f)  ; → uses *default-continue*
```

---

## 8. Automatic Checkpoint Assignment (In-Level)

Every frame, `activate-levels!` runs this loop:

```
For each active level:
  - If the level's vis-nick matches *load-state* vis-nick
  - AND the player's current-level is NOT this level (already handled)
  - AND border? is true (not in cutscene)
  Then: find the closest continue-point in this level's :continues list
        that has ZERO flags (normal checkpoint only)
        and set it as current-continue
```

This is the passive checkpoint update — the player just walks around and checkpoints are automatically updated to the nearest one. No actor, no trigger needed. The warp-flag continues are excluded from this auto-assignment.

---

## 9. Game State: `game-info`

`*game-info*` (type `game-info`) holds:
- `current-continue` — active continue-point (what you respawn at)
- `task-perm-list` — completion status of all 116 game tasks
- `perm-list` — entity perm status (collected items etc.)
- `money`, `fuel`, `life`, `buzzer-total` — player resources
- Death counters per level, timing data

`initialize!` with `'dead` cause increments death counters and calls `(start 'play current-continue)` through a spawned process.

`initialize!` with `'game` cause is a full reset — sets continue to `"village1-hut"` (debug) or `"title-start"` (play).

---

## 10. Level "Inside" Detection

Every frame per active level:
- `inside-boxes?` = `(point-in-boxes? level camera-pos)` — camera inside collision boxes of BSP
- `inside-sphere?` = level bsphere contains camera
- `meta-inside?` = latches true when `inside-boxes?`, stays true until you're in the other level

The vis system uses `inside-boxes?` to pick which vis info to render. `level-get-target-inside` returns the closest active level the player is inside (by bsphere distance tie-breaking).

**`bsphere` field in level-load-info:**  
`(new 'static 'sphere :x cx :y cy :z cz :w radius)` — all in game units (4096 = 1 metre).  
This is the coarse "am I near this level" test, not exact. Exact determination is from BSP boxes.

---

## 11. Key Findings for Addon Development

### What a custom level needs for basic flow:
1. A `level-load-info` entry in `level-info.gc` (or a custom levels file) with:
   - At least one continue-point in `:continues`
   - Correct `:bsphere` so the engine knows where the level is
   - Correct `:lev0 / :disp0` on the continue-point
   - `:wait-for-load #t` if it's a standalone level
2. The level added to `*level-load-list*`

### What continues need for correct respawn:
- `trans` — spawn position in game units
- `quat` — spawn facing quaternion
- `camera-trans` + `camera-rot` (9 floats, 3x3 row-major inv-camera matrix)
- `lev0` = level symbol, `disp0` = `'display`
- `lev1` + `disp1` = second level (or `#f`)
- `vis-nick` = 3-letter nickname symbol

### The `continue-name` lump pattern:
Any actor can read a `continue-name` lump string and call:
```lisp
(let ((cp-name (res-lump-struct (-> self entity) 'continue-name structure)))
  (when cp-name
    (let ((cp (set-continue! *game-info* (the-as basic cp-name))))
      (load-commands-set! *level* (-> cp load-commands)))))
```
This is the standard "trigger a level transition" pattern. Both `launcherdoor` and `jungle-elevator` use it.

### Load boundaries in custom levels:
Load boundaries are **globally compiled** into `load-boundary-data.gc` — they are NOT per-level. Any custom level needs to either:
- Add new entries to `load-boundary-data.gc`, OR
- Handle level loading purely through actors (launcherdoor/warp-gate pattern)

The `checkpt` boundary type is the cleanest way to auto-assign checkpoints as the player moves.

### `display?` mode cheat sheet for continues:
- Standalone level you're spawning into → `'display` for lev0
- Adjacent/connected level that should be visible → `'display` for lev1
- Adjacent level that should be loaded but not immediately rendered → `'special` for lev1
- Second level not relevant at this point → `#f` for lev1

---

## 12. Files Reference

| File | Role |
|---|---|
| `engine/game/game-info-h.gc` | `continue-point`, `continue-flags`, `load-state`, `game-info` type defs |
| `engine/game/game-info.gc` | `set-continue!`, `get-continue-by-name`, `initialize!`, `set-continue!` implementation |
| `engine/level/level-info.gc` | All `level-load-info` static definitions, `*level-load-list*`, `test-zone` example |
| `engine/level/level-h.gc` | `level-load-info`, `level`, `level-group` type defs |
| `engine/level/level.gc` | `activate-levels!`, `load-commands-set!`, `bg`, `play`, level status machine, inside detection |
| `engine/level/load-boundary-h.gc` | `load-boundary`, `load-boundary-crossing-command`, `load-boundary-cmd` enum |
| `engine/level/load-boundary.gc` | `check-boundary`, `execute-command` (full command language), `want-levels`, `want-display-level` |
| `engine/level/load-boundary-data.gc` | 170 static load boundaries for all vanilla levels |
| `engine/target/target-death.gc` | `target-continue` state — the full respawn sequence |
| `engine/target/logic-target.gc` | `start`, `stop`, `init-target`, `level-setup` |
| `engine/target/target-handler.gc` | `'continue` event handler → `go target-continue` |
| `engine/common-obs/basebutton.gc` | `warp-gate` actor, `*warp-info*` string array |
| `levels/common/launcherdoor.gc` | `launcherdoor` — uses `continue-name` lump |
| `levels/jungle/jungle-elevator.gc` | `jungle-elevator` — uses `continue-name` lump + `alt-load-commands` |

---

## 13. Save/Load System — Custom Level Safety

**Key finding: saves are 100% safe for custom levels.**

### What gets serialized
`save-game!` writes only the **continue-point name string** to disk (tag type `game-save-elt continue`). It does NOT serialize:
- The continue-point struct itself
- `lev0`/`lev1`/`vis-nick`/`trans`/`quat`
- The load-commands list

### What happens on load
```lisp
(((game-save-elt continue))
 (format (clear *temp-string*) "~G" (&+ (the-as pointer data) 16))
 (set-continue! this *temp-string*))
```
`load-game!` calls `set-continue!` with the saved name string. `set-continue!` calls `get-continue-by-name` which walks `*level-load-list*`. **If the name is not found, `set-continue!` falls back to `*default-continue*` (debug camera position) with no crash or corruption.**

### Implication
- Custom continue-point names work fine in saves
- If a custom level is later removed, old saves degrade gracefully to the debug default
- The `level-index` field in the save header (used for progress menu display) is `(lookup-level-info level-name).index` — if slightly wrong it only affects the menu icon, not gameplay

### Title-start special case
```lisp
(when (string= (-> this current-continue name) "title-start")
  (set! (-> arg0 new-game) 1)
  (set! (-> arg0 level-index) (-> (lookup-level-info 'training) index))
  ...)
```
If saving on the title screen, the save records index for training instead and sets `new-game = 1`. On load, this triggers `(set-continue! this "game-start")`. Custom levels should avoid naming continues `"title-start"`.

---

## 14. Complete JSONC Actor Format Reference

### Actor entry structure
```jsonc
{
  "trans": [x, y, z],           // metres, converted to game units (×4096)
  "etype": "launcherdoor",       // GOAL type name string
  "game_task": "(game-task none)", // enum string OR integer
  "quat": [x, y, z, w],         // quaternion, raw floats
  "bsphere": [x, y, z, radius],  // metres for all 4 values
  "aid": 105,                    // optional: explicit actor ID (default: base_id + index)
  "vis_id": 0,                   // optional: visibility ID
  "lump": {
    "name": "my-actor-1",        // required for entity-by-name lookups
    // ... lump keys
  }
}
```

### `trans` and `bsphere` — coordinate system
- JSONC uses **metres** (same as Blender metres)
- Compiler multiplies by `METER_LENGTH = 4096.0` automatically via `vectorm3_from_json` / `vectorm4_from_json`
- `bsphere` radius is also in metres, converted to game units

### `game_task` field
- Accepts enum string: `"(game-task none)"` or `"(game-task training-gimmie)"`
- Accepts raw integer: `0`
- `(game-task none) = 0` — use for actors with no associated power cell task

### Lump value format rules
```jsonc
"lump": {
  // Bare string → ResString (continue-name reads this back with res-lump-struct)
  "continue-name": "my-level-start",

  // Bare string starting with ' → ResSymbol (symbol lump)
  "crate-type": "'steel",

  // Array with type tag → typed lump
  "spring-height": ["meters", 2.5],
  "rotoffset": ["degrees", -45.0],
  "options": ["enum-int32", "(fact-options large)"],
  "eco-info": ["eco-info", "(pickup-type money)", 10],
  "eco-info": ["cell-info", "(game-task training-gimmie)"],
  "eco-info": ["buzzer-info", "(game-task training-buzzer)", 3],
  "water-height": ["water-height", 25.0, 0.5, 2.0, "(water-flags wt08 wt03)"],
  "nav-mesh-sphere": ["vector3m", [x, y, z]]  // xyz in metres, w=1.0
}
```

### Complete lump type string reference

| Type string | Output type | Format | Notes |
|---|---|---|---|
| `"int32"` | ResInt32 | `["int32", n, ...]` | Raw signed ints |
| `"uint32"` | ResUint32 | `["uint32", n, ...]` | Raw unsigned ints |
| `"enum-int32"` | ResInt32 | `["enum-int32", "(enum-type value)"]` | Enum → int32 |
| `"enum-uint32"` | ResUint32 | `["enum-uint32", "(enum-type value)"]` | Enum → uint32 |
| `"float"` | ResFloat | `["float", f, ...]` | Raw floats |
| `"meters"` | ResFloat | `["meters", m, ...]` | Float × 4096.0 |
| `"degrees"` | ResFloat | `["degrees", d, ...]` | Float × 182.044 |
| `"vector"` | ResVector | `["vector", [x,y,z,w]]` | Raw 4 floats |
| `"vector4m"` | ResVector | `["vector4m", [x,y,z,w]]` | All 4 × 4096 |
| `"vector3m"` | ResVector | `["vector3m", [x,y,z]]` | xyz × 4096, w=1.0 |
| `"vector-vol"` | ResVector | `["vector-vol", [x,y,z,w]]` | xyz raw, w × 4096 |
| `"movie-pos"` | ResVector | `["movie-pos", [x,y,z,deg]]` | xyz × 4096, w = degrees×182 |
| `"symbol"` | ResSymbol | `["symbol", "name1", ...]` | GOAL symbols |
| `"type"` | ResType | `["type", "typename"]` | Type tag |
| `"string"` | ResString | `["string", "str1", ...]` | GOAL strings |
| `"eco-info"` | ResInt32 | `["eco-info", "(pickup-type X)", amount]` | Pickup lump |
| `"cell-info"` | ResInt32 | `["cell-info", "(game-task X)"]` | Power cell lump |
| `"buzzer-info"` | ResInt32 | `["buzzer-info", "(game-task X)", index]` | Scout fly lump |
| `"water-height"` | ResFloat | `["water-height", h, wade, swim, "(water-flags ...)", [bottom]]` | Water lump |

**Constants:** `METER_LENGTH = 4096.0`, `DEGREES_LENGTH = 65536/360 ≈ 182.044`, `DEFAULT_RES_TIME = -1000000000.0`

### The `continue-name` lump — exact format
```jsonc
{
  "trans": [x, y, z],
  "etype": "launcherdoor",
  "game_task": 0,
  "quat": [0, 0, 0, 1],
  "bsphere": [x, y, z, 4.0],
  "lump": {
    "name": "my-door-1",
    "continue-name": "my-level-start"   // plain string → ResString
  }
}
```
Runtime code reads it with `(res-lump-struct entity 'continue-name structure)` which returns a pointer to the string data. The bare string (no `'` prefix) is correct here — it becomes a ResString, not a ResSymbol.

---

## 15. Build System — Registering a Custom Level

Three things required in `game.gp`:

```lisp
;; 1. Compile the JSONC → .go geometry/entity file
(build-custom-level "my-level")

;; 2. Package the DGO
(custom-level-cgo "MYL.DGO" "my-level/myl.gd")

;; 3. Register the GOAL source file for the level's actors/code
(goal-src "levels/my-level/my-level-obs.gc" "process-drawable")
```

The `.gd` file format (e.g. `myl.gd`):
```lisp
("MYL.DGO"
 ("my-level-obs.o"      ; compiled GOAL actor code
  "tpage-401.go"        ; sky texture (village1 sky example)
  "my-level.go"         ; compiled level geometry/entities from JSONC
  ))
```

The `level-info.gc` entry needs `:run-packages '("common")` at minimum. If sharing art groups with a vanilla level, add that package too (e.g. `'("common" "village1")`).

---

## 16. Task System — What Custom Levels Need to Know

### `game-task` enum (key values)
- `(game-task none) = 0` — no task, safe for decorative actors
- `(game-task complete) = 1` — always marked complete at game start
- Tasks 2–115 are vanilla game tasks
- `(game-task max) = 116` — total slot count

**Custom levels should use `(game-task none)` for most actors.** The task system is 116 fixed slots — there are no "custom task" slots available without modifying `game-task-h.gc`.

### `task-status` enum (progression)
```
invalid(0) → unknown(1) → need-hint(2) → need-introduction(3)
→ need-reminder-a(4) → need-reminder(5) → need-reward-speech(6)
→ need-resolution(7)
```
Higher value = further along. `task-complete?` checks for the `real-complete` flag separately (set when power cell is physically collected).

### Key task functions
```lisp
(task-complete? *game-info* (game-task jungle-tower))   ; bool: power cell collected?
(get-task-status (game-task jungle-tower))               ; → task-status enum value
(task-closed? task status)                               ; bool: at or past given status?
(close-specific-task! task status)                       ; advance task to status
(open-specific-task! task status)                        ; roll back task to status
(get-task-control task)                                  ; → task-control object
```

### `process-taskable` — the NPC/interactive object base
Used for sages, oracle pedestals, warp gates, and similar objects that have task-gated behaviour. The key method `should-display?` defaults to `#t` — override to hide the actor when the task is complete. The `give-cell` state handles handing out the power cell via `cell-for-task`.

For simple custom level objects that don't need task gating, extend `process-drawable` directly (as `test-actor` does) rather than `process-taskable`.

---

## 17. Death Plane (`bottom-height`)

`bottom-height` in `level-load-info` is the Y coordinate below which the player gets an `endlessfall` death.

**How it works:**
```lisp
; In logic-target, runs every frame:
(if (and (time-elapsed? ... (seconds 2))     ; 2-second grace period after spawn
         v1-146                               ; current-level exists
         (< (-> self control trans y)         ; player Y <
            (-> v1-146 info bottom-height)))  ; level's bottom-height
  (send-event self 'attack-invinc #f
    (static-attack-info ((mode 'endlessfall)))))
```

- The 2-second grace period prevents instant death on level transitions
- `endlessfall` mode plays the endless fall death animation and triggers `target-death`
- This uses `current-level` (the level the player is considered inside), so the active level's `bottom-height` applies
- Default in vanilla levels: `(meters -20)` for most outdoor areas, lower for pits/caves

**For custom levels:** Set `:bottom-height (meters -X)` where X is how far below the level floor the kill plane should sit. `(meters -20)` is the standard. For indoor/cave levels with deep drops, use `(meters -60)` or lower.

The `endlessfall` collision pat type is separate — it's a collision surface property assigned in the BSP that also triggers the same death, used for invisible kill volumes in the geometry itself.
