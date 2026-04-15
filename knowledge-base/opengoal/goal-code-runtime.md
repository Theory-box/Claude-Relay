# GOAL Code Runtime — Research Notes
> Branch-local knowledge doc. Research sourced from jak-project goal_src/jak1/.
> Topics: process lifecycle, unit system, event routing, detection patterns.

---

## Unit System (confirmed from source)

`res-lump-float` returns the **raw stored value** — no conversion.

| JSONC lump type | What gets stored | What res-lump-float reads back |
|---|---|---|
| `["float", 10.0]` | `10.0` raw | `10.0` (game units — ~2.4mm) |
| `["meters", 10.0]` | `10.0 × 4096 = 40960.0` | `40960.0` |
| `["degrees", 90.0]` | `90.0 × 182.044 = 16384.0` | `16384.0` |

**Rule:** If you enter a distance in the Custom Lumps panel and want it to behave as meters in GOAL code, set the lump type to `meters` AND compare in GOAL using `(meters N)` or the raw stored value directly.

```lisp
;; Correct — lump type "meters", value 10.0 → stores 40960.0
(set! (-> this radius) (res-lump-float arg0 'radius :default (meters 10.0)))
;; Then compare:
(< (vector-vector-distance ...) (-> self radius))   ;; both in raw units ✓

;; WRONG — lump type "float", value 10.0 → stores 10.0 (= ~2.4mm)
;; (< (vector-vector-distance ...) (-> self radius)) will never fire at normal distances
```

`vector-vector-distance` returns distance in raw game units (1m = 4096 units).
Source: `engine/math/vector.gc:519`.

---

## Process Lifecycle

### Killing a process from another process

```lisp
;; Correct — matches how citadel-sages.gc kills platforms
(let ((proc (process-by-ename "plat-eco-0")))
  (when proc (deactivate proc)))

;; Also correct if you have a handle
(let ((proc (handle->process my-handle)))
  (when proc (deactivate proc)))
```

**DO NOT use `(send-event proc 'die)`** to kill platforms. `plat-eco` only handles:
- `'wake` → go path-active
- `'eco-blue` → go notice-blue
- `'ridden` / `'edge-grabbed` → go path-active (with blue eco)

`'die` is silently ignored. Source: `engine/common-obs/plat-eco.gc:35-75`.

`deactivate` is a method on `process` (the base type). It gracefully tears down the process, runs any `:exit` handlers, and returns the process to the dead pool. Safe to call on any live process pointer. Source: `kernel/gkernel.gc:1903`.

### `process-by-ename` behaviour

```lisp
(define-extern process-by-ename (function string process))
```

- Returns the `process` pointer for the entity with the matching `name` lump, or `#f` if not found / not yet spawned
- Searches actors, ambients, and cameras across all active levels
- Matches against `(res-lump-struct entity 'name basic)` — the `name` lump in JSONC
- The addon writes name lumps as `etype-uid`: `ACTOR_die-relay_0` → `"die-relay-0"`
- Always null-check before using: `(when proc ...)`
- Source: `engine/entity/entity.gc:165`

---

## Detection Pattern (proven working — matches aggro-trigger)

The canonical pattern for proximity/volume detection in a custom entity:

```lisp
(defstate my-trigger-active (my-trigger)
  :code
  (behavior ()
    (loop
      (when (and *target* (zero? (mod (-> *display* base-frame-counter) 4)))
        (let* ((pos (-> *target* control trans))
               ;; ... compute detection ...)
          (cond
            ((and triggered (not (-> self was-triggered)))
             (set! (-> self was-triggered) #t)
             ;; rising edge action
             )
            ((and (not triggered) (-> self was-triggered))
             (set! (-> self was-triggered) #f)
             ;; falling edge action
             ))))
      (suspend))))
```

Key elements:
- `(when (and *target* ...)` — null-guard Jak before any access
- `(zero? (mod (-> *display* base-frame-counter) 4))` — throttle to every 4th frame (15Hz at 60fps). Matches aggro-trigger and camera-trigger
- `(-> *target* control trans)` — Jak's world position (feet level). NOT `(target-pos 0)` for this pattern
- `(suspend)` — must be at the loop level, not inside the detection block
- Edge detection via a `symbol` field (`#f`/`#t`) — engine uses `symbol` for all boolean fields

---

## Boolean Fields in GOAL deftypes

`symbol` is the standard type for boolean fields in GOAL, not `bool` or `uint32`.

```lisp
(deftype my-entity (process-drawable)
  ((was-triggered symbol)   ;; ← correct
   (is-active     symbol))) ;; ← correct
```

Initialized to `#f`, set to `#t`. Comparisons work naturally:
```lisp
(not (-> self was-triggered))   ;; ← correct
(-> self was-triggered)         ;; truthy check ← correct
```

Evidence: `baseplat.bouncing`, `plat-button.go-back-if-lost-player?`, `plat-button.bidirectional?`, `eco-door.locked` are all `symbol`. Source: `engine/common-obs/baseplat.gc:48`, `engine/common-obs/plat-button.gc:11-16`.

---

## `deftype` Field Layout — Level Files

**`:offset-assert`, `:heap-base`, `:size-assert` are NOT required in level `.gc` files.**

The OpenGOAL compiler infers field layout automatically. These annotations are only present in engine header files for validation. Zero level files (`levels/` directory) use them. Examples without annotations that have custom fields:

- `drop-plat` (citb-drop-plat.gc) — `spin-axis vector`, `spin-angle float`, `spin-speed float`, `interp float`, `duration time-frame`, `delay time-frame`, `color int8`
- `citb-sagecage` (citadel-sages.gc) — `bar-array vector 12 :inline`, `angle-offset float`, `bars-on symbol`

Safe to omit in custom obs.gc code. The compiler assigns offsets sequentially starting at 176 (end of process-drawable base).

---

## Standard init-from-entity! Template

```lisp
(defmethod init-from-entity! ((this my-type) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))   ;; allocate trsqv root — standard for non-collision entities
  (process-drawable-from-entity! this arg0)       ;; read trans/quat/bsphere from entity lumps
  ;; read custom lumps here
  (go my-initial-state)
  (none))                                          ;; (none) return is REQUIRED — missing it is a compile error
```

`(new 'process 'trsqv)` — allocates position/rotation struct in process heap. This is the correct allocation for simple entities without collision. Used by camera-marker, camera-trigger, checkpoint-trigger, aggro-trigger, and all citadel obs. Source: confirmed across `levels/citadel/citadel-obs.gc`, `levels/village1/village-obs.gc`.

---

## Paren Balance in Complex Nested Structures

When a cond branch has `(let ((proc ...)) (when proc ...))` wrappers, the closing paren count is:

```
(when proc (send-event proc 'symbol))))))
```

Working outward from the innermost:
1. `)` close send-event
2. `)` close `(when proc ...)`
3. `)` close `(let ((proc ...)) ...)`
4. `)` close the cond branch progn
5. `)` close `(cond ...)`
6. `)` close outer `(let* (... (in-vol ...)) ...)`
7. `)` close outer `(when (and *target* ...) ...)`

Total: **7 closes** when BOTH cond branches have `let`+`when` wrappers.

If only the first branch has `let`+`when` and the second branch only has flat forms (like `format`), the second branch needs only **4 closes** (branch, cond, let*, outer-when).

The automated paren counter catches this: extract GOAL lines, sum `(` and `)`, result must be 0.

---

## Events Handled by plat-eco

| Event | Handler | Effect |
|---|---|---|
| `'wake` | `plat-idle` | → `plat-path-active` immediately |
| `'eco-blue` | `plat-idle` | → `notice-blue` state (glow animation) |
| `'ridden` / `'edge-grabbed` | `plat-idle` | → `plat-path-active` if player has blue eco |
| `'bonk` | `plat-event` (inherited) | Triggers smush/bounce animation |
| anything else | — | **silently ignored** |

To kill a `plat-eco` from custom code: call `(deactivate proc)` directly.
Source: `engine/common-obs/plat-eco.gc`, `engine/common-obs/baseplat.gc`.

---

## Entity Name Lump Convention

The addon writes name lumps as `etype-uid`:

| Blender object name | JSONC name lump | `process-by-ename` lookup string |
|---|---|---|
| `ACTOR_die-relay_0` | `die-relay-0` | `"die-relay-0"` |
| `ACTOR_plat-eco_0` | `plat-eco-0` | `"plat-eco-0"` |
| `ACTOR_babak_1` | `babak-1` | `"babak-1"` |

**Common mistake:** Using the Blender object name directly (`plat-eco_0` with underscore) instead of the lump name convention (`plat-eco-0` with hyphen).

Source: `export.py:1359` — `lump = {"name": f"{etype}-{uid}"}`.
Confirmed working: `entity-by-name` in `engine/entity/entity.gc:92` matches against `(res-lump-struct entity 'name basic)`.

