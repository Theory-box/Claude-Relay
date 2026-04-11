# OpenGOAL — Player Loading, Continue Points, Save Points & Respawn

**Source files analyzed from `open-goal/jak-project`:**
- `goal_src/jak1/engine/game/game-info-h.gc` — type definitions
- `goal_src/jak1/engine/game/game-info.gc` — `set-continue!`, `initialize!`, `get-or-create-continue!`
- `goal_src/jak1/engine/game/game-save.gc` — save/load serialization
- `goal_src/jak1/engine/game/main.gc` — game loop, mode entry
- `goal_src/jak1/engine/level/level-info.gc` — all continue-point static data per level
- `goal_src/jak1/engine/level/level.gc` — level loading, auto checkpoint on level entry
- `goal_src/jak1/engine/target/logic-target.gc` — `init-target`, `start`, `stop`
- `goal_src/jak1/engine/target/target-death.gc` — `target-continue` state (the spawn animation/sequence)

---

## 1. The `continue-point` Type

Defined in `game-info-h.gc`:

```lisp
(deftype continue-point (basic)
  ((name          string)       ;; unique string key, e.g. "training-start"
   (level         symbol)       ;; level symbol, e.g. 'training
   (flags         continue-flags)
   (trans         vector :inline)       ;; player spawn position
   (quat          quaternion :inline)   ;; player spawn rotation
   (camera-trans  vector :inline)       ;; camera initial position
   (camera-rot    float 9)              ;; camera rotation matrix (3x3 flat)
   (load-commands pair)                 ;; extra load commands (special textures etc.)
   (vis-nick      symbol)               ;; vis nickname for the level
   (lev0          symbol)               ;; primary level to load
   (disp0         symbol)               ;; 'display or 'special for lev0
   (lev1          symbol)               ;; secondary level to load (or #f)
   (disp1         symbol)))             ;; display mode for lev1
```

### continue-flags enum

```lisp
(defenum continue-flags :type uint32 :bitfield #t
  (contf00)
  (contf01)
  (warp)          ;; this is a warp gate point (triggers warp-in animation)
  (demo)
  (intro)         ;; triggers intro sequence
  (sage-intro)
  (sage-demo-convo)
  (title)         ;; goes to target-title state
  (contf08)
  (contf09)
  (game-start)    ;; used for the very first game start
  (sage-ecorocks))
```

For a **plain custom level continue point**, use **no flags** (flags = 0 / omit).

---

## 2. Where Continue Points Are Defined

All continue points for all vanilla levels are defined as **static inline data** inside `level-info.gc`, attached to their `level-load-info` struct under the `:continues` field.

### Example (training level, first continue point):

```lisp
(define training
  (new 'static 'level-load-info
       :index 1
       :name 'training
       ...
       :continues
       '((new 'static 'continue-point
             :name "training-start"
             :level 'training
             :trans (new 'static 'vector :x -5393626.5 :y 28072.346 :z 4332472.5 :w 1.0)
             :quat  (new 'static 'quaternion :y 0.9995 :w 0.0297)
             :camera-trans (new 'static 'vector ...)
             :camera-rot   (new 'static 'array float 9 ...)
             :load-commands '(...)
             :vis-nick 'tra
             :lev0 'training
             :disp0 'display
             :lev1 'village1
             :disp1 'special)
         ...)))
```

**For a custom level**, you define the same structure inside your level's `level-load-info` `:continues` list.

---

## 3. The Call Chain: How the Player Gets Loaded

```
start('play, continue-point)
  → process-spawn target :init init-target arg0
      → init-target(continue-point)
          → set-continue! *game-info* arg0
          → move-to-point! (sets player position from continue-point :trans)
          → go target-continue arg0    ← the big state machine
              → waits for level to be 'active
              → applies load-commands
              → sets camera
              → spawns actors (*spawn-actors* = #t, *teleport* = #t)
              → go target-stance       ← normal gameplay begins
```

### `start` function (`logic-target.gc:1293`)

```lisp
(defun start ((arg0 symbol) (arg1 continue-point))
  (set! (-> *level* border?) #f)
  (set! (-> *setting-control* default border-mode) #f)
  (stop arg0)
  (let ((v1-3 (process-spawn target :init init-target arg1
                :from *target-dead-pool*
                :to *target-pool*
                :stack *kernel-dram-stack*)))
    (if v1-3 (set! *target* (the-as target (-> v1-3 0 self))) (set! *target* #f)))
  *target*)
```

- **`arg0`** = `'play` or `'debug` (the game mode)
- **`arg1`** = the `continue-point` struct

### `init-target` (`logic-target.gc:1177`)

Key actions inside `init-target`:
1. `set-continue! *game-info* arg0` — registers the active continue point
2. `move-to-point! (-> self control) (-> arg0 trans)` — teleports player to spawn position
3. Sets up collide shape, skeleton, fact-info, water, sidekick
4. `go target-continue arg0` — hands off to the spawn sequence state

---

## 4. The `target-continue` State

Defined in `target-death.gc`. This is the **spawn/load-in sequence** after a continue or death:

### What it does step by step:
1. Reads `arg0` (the `continue-point`)
2. Applies settings: mutes SFX, ambient; sets BG alpha to 1 (black screen)
3. Moves player: `move-to-point!` (again, from the continue-point's `:trans`)
4. Applies player rotation from `:quat`
5. **Sets `*load-state*`** — this is the actual level loading:
   ```lisp
   (set! (-> *load-state* want 0 name) (-> arg0 lev0))
   (set! (-> *load-state* want 0 display?) (-> arg0 disp0))
   (set! (-> *load-state* want 1 name) (-> arg0 lev1))
   (set! (-> *load-state* want 1 display?) (-> arg0 disp1))
   ```
6. **Waits** until both required levels reach `'active` status (the loading loop)
7. Executes `load-commands` from the continue-point
8. Sets camera position from `:camera-trans` and `:camera-rot`
9. Checks `continue-flags`:
   - `title` → go to `target-title`
   - `intro` → run `start-sequence-a`
   - `sage-intro` → trigger sage cutscene
   - `warp` → run warp-gate animation (`go target-warp-in`)
   - **(no flags)** → `(suspend-for (seconds 0.05))` — just a tiny pause, then falls through
10. Final `(set-continue! *game-info* arg0)` — locks in the continue point
11. `(go target-stance)` — gameplay begins

**Key insight:** For a custom level with no special flags, the `else` branch is hit, which is just a brief delay before normal gameplay. This is what you want.

---

## 5. `set-continue!` — Registering a Continue Point

Defined in `game-info.gc:104`:

```lisp
(defmethod set-continue! ((this game-info) (arg0 basic))
  ;; arg0 can be:
  ;;   '() or #f  → no-op
  ;;   string     → looks up continue-point by name via get-continue-by-name
  ;;   continue-point → sets directly
  ;; Falls back to *default-continue* if lookup fails
  ...)
```

- `(set-continue! *game-info* "my-level-start")` — set by name
- `(set-continue! *game-info* my-continue-point)` — set by struct
- When the continue changes, `continue-deaths` and `continue-time` reset

---

## 6. How Death / Respawn Works

### On player death (`game-info.gc:initialize!`):

```
initialize! called with cause = 'dead
  → increments death counters
  → case 'play mode:
      → if lives > 0: cause becomes 'life (respawn at current continue)
      → else: cause becomes 'try (same behavior, no lives system really used)
  → spawns a temporary process that:
      (stop arg0)                     ;; kills current target
      (reset-actors arg1)             ;; resets all entities
      (set-continue! *game-info* arg2) ;; re-applies current continue (no change)
      (start arg0 arg2)               ;; respawns player at same continue point
```

**The player always respawns at `*game-info* current-continue`.** You do not need to do anything special — as long as `current-continue` points to your custom level's continue-point, the player will respawn there.

### Hardcoded death fallbacks (`target-death.gc:205-275`):

If the player dies in certain levels with certain task states, the game forces a different continue:
```lisp
(set-continue! *game-info* "village1-hut")    ;; village 1 intro
(set-continue! *game-info* "training-start")  ;; training
(set-continue! *game-info* "village2-start")  ;; etc.
```
For custom levels these won't trigger unless you match those exact level names — so you're safe.

---

## 7. Auto-Checkpoint on Level Entry

In `level.gc:1210`, when the player physically enters a new level, the engine auto-assigns a continue point:

```lisp
;; checkpoint assignment
;; if the new level has continues, set the first one as current
(if (-> gp-1 info continues)
    (set-continue! *game-info* (the-as continue-point (car (-> gp-1 info continues)))))
```

This means **the first entry in your level's `:continues` list is auto-set as the active checkpoint when the player loads in**. This is the "save point" equivalent in Jak 1 — there are no explicit save point objects, the continue point is set automatically.

---

## 8. The `*default-continue*` Fallback

```lisp
;; global fallback, defined in game-info-h.gc
(define *default-continue* (new 'static 'continue-point :name "default" ...))
```

When `set-continue!` is called with an unrecognized name or `#f`, it falls back to `*default-continue*`, which positions the player in front of the current camera. The `target-continue` state detects the `"default"` name and uses a fixed camera mode instead of the normal camera setup.

---

## 9. Recipe for a Custom Level Continue Point

### In your level's `level-load-info`:

```lisp
(define my-level
  (new 'static 'level-load-info
       :index 99              ;; unique index, must not collide with vanilla
       :name 'my-level
       :visname 'my-level-vis
       :nickname 'myl
       :packages '(my-level)
       :sound-banks '()
       :music-bank 'village1   ;; or whatever music
       :mood '*village1-mood*
       :mood-func 'update-mood-village1
       :sky #t
       :sun-fade 1.0
       :continues
       '((new 'static 'continue-point
             :name "my-level-start"    ;; unique string
             :level 'my-level          ;; must match :name above
             :flags 0                  ;; no special flags for plain spawn
             :trans (new 'static 'vector :x YOUR_X :y YOUR_Y :z YOUR_Z :w 1.0)
             :quat  (new 'static 'quaternion :y 1.0 :w 0.0)  ;; facing direction
             :camera-trans (new 'static 'vector :x CX :y CY :z CZ :w 1.0)
             :camera-rot (new 'static 'array float 9
                              1.0 0.0 0.0
                              0.0 1.0 0.0
                              0.0 0.0 1.0)
             :load-commands '()
             :vis-nick 'myl
             :lev0 'my-level
             :disp0 'display
             :lev1 #f         ;; no secondary level
             :disp1 #f))
       ...))
```

### To start the player there:

```lisp
;; In REPL or startup code:
(set-continue! *game-info* "my-level-start")
(start 'play (get-or-create-continue! *game-info*))
```

Or via `initialize!`:
```lisp
(initialize! *game-info* 'game #f "my-level-start")
```

### To get coordinates for :trans from an in-game position:
The debug function `trsq->continue-point` (`game-info.gc:614`) prints a `static-continue-point` expression to stdout with the current player position/rotation. Use this in a debug REPL to get real coordinates.

---

## 10. Lives / Tries / Continues

Jak 1 tracks:
- `(-> *game-info* life)` — float, default 4.0, decrements on death (essentially unused in gameplay terms)
- `(-> *game-info* continue-deaths)` — deaths since last continue change
- `(-> *game-info* total-deaths)` — all-time deaths

There is **no traditional "save point" object** in Jak 1. Continue points are purely static data in `level-load-info`. The game saves via the memory card system (`game-save.gc`) which serializes `*game-info*` including `current-continue` by name.

---

## 11. Key File Summary

| File | What it has |
|---|---|
| `engine/game/game-info-h.gc` | `continue-point` type, `continue-flags` enum, `game-info` type |
| `engine/game/game-info.gc` | `set-continue!`, `get-continue-by-name`, `initialize!`, `get-or-create-continue!` |
| `engine/game/game-save.gc` | Serializes `current-continue` to save file by name |
| `engine/game/main.gc` | Game loop, debug mode toggle (`start 'play`) |
| `engine/level/level-info.gc` | All vanilla static continue-point data |
| `engine/level/level.gc` | Auto-checkpoint on level entry, level load state |
| `engine/target/logic-target.gc` | `init-target`, `start`, `stop` |
| `engine/target/target-death.gc` | `target-continue` state (full spawn sequence), `next-level`, `*auto-continue*` |
