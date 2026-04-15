# GOAL Code — Tested Working Examples

These examples have been verified in-game. Each includes Blender setup, custom lumps needed, and exact GOAL code.

For language reference see `goal-scripting.md`. For the addon workflow see `goal-code-system.md`.

---

## Example 1 — Level Exit (Confirmed Working ✅)

Teleports Jak to a named continue point when he walks within range. Use this to connect custom levels to each other or to vanilla levels.

### Blender setup
- Spawn panel → ⚙ Custom Types → type `level-exit` → Spawn
- Place the empty at the exit point
- Custom Lumps:
  - `continue-name` — **string** — e.g. `village1-hut`
  - `radius` — **meters** — e.g. `3.0`

### Valid village1 continue names
| Name | Where Jak spawns |
|---|---|
| `village1-hut` | Samos's hut (standard spawn) |
| `village1-intro` | Intro cutscene position |
| `village1-warp` | Near the warp gate |

For custom levels the pattern is `<level-name>-<spawn-uid>`, e.g. `my-level-start`.

### GOAL code
```lisp
;;-*-Lisp-*-
(in-package goal)

(deftype level-exit (process-drawable)
  ((continue-name string)
   (radius        float))
  (:states level-exit-idle))

(defstate level-exit-idle (level-exit)
  :code
  (behavior ()
    (loop
      (when (and *target*
                 (< (vector-vector-distance
                      (-> self root trans)
                      (-> *target* control trans))
                    (-> self radius)))
        (let ((cp (get-continue-by-name *game-info* (-> self continue-name))))
          (when cp
            (set-blackout-frames (seconds 0.05))
            (start 'play cp))))
      (suspend))))

(defmethod init-from-entity! ((this level-exit) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (set! (-> this radius)
        (res-lump-float arg0 'radius :default (meters 3.0)))
  (set! (-> this continue-name)
        (res-lump-struct arg0 'continue-name string))
  (format 0 "[level-exit] armed -> ~A radius ~M~%"
          (-> this continue-name) (-> this radius))
  (go level-exit-idle)
  (none))
```

### Notes
- `start 'play` is a full level transition — kills current Jak process, loads destination, spawns at continue point
- `set-blackout-frames` gives a clean black frame before the cut
- `get-continue-by-name` returns `#f` if the name doesn't match — check the armed log to confirm the name is correct
- Type redefinition error on recompile = goalc cached old type — restart goalc, recompile
- Art group error in log (`level-exit-ag.go not found`) is non-fatal, can be ignored

---

## Key Patterns (Engine-Confirmed)

### Getting Jak's position
```lisp
(-> *target* control trans)        ; Jak's feet position (use this for proximity)
(target-pos 0)                     ; same, but null-safe (returns camera-pos if no target)
```

### Proximity check (throttled — 15Hz)
```lisp
(when (and *target* (zero? (mod (-> *display* base-frame-counter) 4)))
  (let ((dist (vector-vector-distance (-> self root trans) (-> *target* control trans))))
    (when (< dist (meters 5.0))
      ;; in range
      )))
```

### Reading lumps in init
```lisp
(res-lump-float  arg0 'my-float   :default 1.0)          ; float, raw units
(res-lump-float  arg0 'my-meters  :default (meters 5.0)) ; use meters lump type in Blender
(res-lump-struct arg0 'my-string  string)                ; string
(res-lump-value  arg0 'my-int     uint128)               ; integer (cast with the int)
```

### Level transition
```lisp
(start 'play (get-continue-by-name *game-info* "village1-hut"))
```

### Send event to another entity
```lisp
(let ((proc (process-by-ename "target-entity-0")))
  (when proc (send-event proc 'trigger)))
```

### Deactivate another entity
```lisp
(let ((proc (process-by-ename "plat-eco-0")))
  (when proc (deactivate proc)))
```

### Game settings
```lisp
(set-setting! 'music 'village1 0.0 0)        ; change music
(set-setting! 'letterbox #t 0.0 0)           ; enable letterbox
(set-setting! 'allow-pause #f 0.0 0)         ; disable pause menu
(remove-setting! 'letterbox)                  ; restore default
```
