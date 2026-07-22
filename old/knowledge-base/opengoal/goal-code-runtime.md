# GOAL Code Runtime — Research Notes

> Sourced from jak-project `goal_src/jak1/` source research and confirmed in-game testing (April 2026).
> Topics: process lifecycle, unit system, event routing, detection patterns.

---

## Unit System

`res-lump-float` returns the **raw stored value** — no conversion.

| JSONC lump type | What gets stored | What res-lump-float reads back |
|---|---|---|
| `["float", 10.0]` | `10.0` raw | `10.0` (~2.4mm — almost never what you want for distance) |
| `["meters", 10.0]` | `10.0 × 4096 = 40960.0` | `40960.0` |
| `["degrees", 90.0]` | `90.0 × 182.044 = 16384.0` | `16384.0` |

**Rule:** For distance values, use lump type `meters` in the Custom Lumps panel and compare with `(meters N)` in GOAL code — or compare raw values directly. Never mix `float` lump type with `(meters N)` comparison or vice versa.

`vector-vector-distance` returns raw game units (1m = 4096 units). Source: `engine/math/vector.gc:519`.

---

## Process Lifecycle

### Killing a process from outside

```lisp
;; Correct — used by citadel-sages.gc
(let ((proc (process-by-ename "plat-eco-0")))
  (when proc
    (process-entity-status! proc (entity-perm-status dead) #t)  ;; prevent respawn
    (deactivate proc)))                                           ;; kill now
```

**DO NOT use `(send-event proc 'die)`** on platforms — `plat-eco` only handles `'wake`, `'eco-blue`, `'ridden`. `'die` is silently ignored. Source: `engine/common-obs/plat-eco.gc:35-75`.

`deactivate` is a method on `process` — safe to call on any live process pointer. Gracefully runs `:exit` handlers and returns the process to the dead pool. Source: `kernel/gkernel.gc:1903`.

`process-entity-status! (entity-perm-status dead) #t` marks the entity so the engine won't re-birth it when you re-enter the area. Without this the platform respawns on level re-entry.

### `process-by-ename`

```lisp
(define-extern process-by-ename (function string process))
```

- Returns the `process` pointer or `#f` if not found / not yet spawned
- Matches against the entity's `'name` lump — not the Blender object name
- Addon writes name lumps as `etype-uid`: `ACTOR_plat-eco_0` → `"plat-eco-0"`
- Always null-check before using
- Source: `engine/entity/entity.gc:165`

---

## Detection Patterns

### Proximity detection (self-contained)

```lisp
(when (and *target*
           (< (vector-vector-distance
                (-> self root trans)
                (-> *target* control trans))
              (-> self radius)))
  ;; ... act
  )
```

### AABB volume detection (mirrors aggro-trigger / vol-trigger pattern)

```lisp
(when (and *target* (zero? (mod (-> *display* base-frame-counter) 4)))
  (let* ((pos (-> *target* control trans))
         (dx  (- (-> pos x) (-> self root trans x)))
         (dy  (- (-> pos y) (-> self root trans y)))
         (dz  (- (-> pos z) (-> self root trans z)))
         (cr  (-> self cull-radius))
         (in-vol (and
           (< (+ (* dx dx) (* dy dy) (* dz dz)) (* cr cr))
           (< (-> self xmin) (-> pos x)) (< (-> pos x) (-> self xmax))
           (< (-> self ymin) (-> pos y)) (< (-> pos y) (-> self ymax))
           (< (-> self zmin) (-> pos z)) (< (-> pos z) (-> self zmax)))))
    (cond
      ((and in-vol (not (-> self inside)))
       (set! (-> self inside) #t)
       ;; rising edge
       )
      ((and (not in-vol) (-> self inside))
       (set! (-> self inside) #f)
       ;; falling edge
       ))))
```

Key elements:
- `(when (and *target* ...)` — always null-guard before accessing Jak
- `(zero? (mod (-> *display* base-frame-counter) 4))` — throttle to every 4th frame (~15Hz). Matches aggro-trigger, camera-trigger, checkpoint-trigger
- `(-> *target* control trans)` — Jak's world position (feet). NOT `(target-pos 0)` for this pattern
- `(suspend)` must be at the loop level, outside the detection block

---

## Event Handlers — Parameter Types Required

GOAL is strictly typed. Event handler parameters must declare types or the compiler throws a typecheck error:

```lisp
;; CORRECT
:event
  (behavior ((proc process) (argc int) (message symbol) (block event-message-block))
    (case message
      (('trigger) ...)))

;; WRONG — compile error: "got function object object object object when expecting..."
:event
  (behavior (proc argc message block)
    ...)
```

---

## Boolean Fields

`symbol` is the standard type for boolean fields — not `bool` or `uint32`:

```lisp
(deftype my-entity (process-drawable)
  ((was-triggered symbol)
   (is-open       symbol)))

;; Init to #f, set to #t, compare naturally:
(set! (-> this was-triggered) #f)
(not (-> self was-triggered))
```

Evidence: `baseplat.bouncing`, `plat-button.go-back-if-lost-player?`, `eco-door.locked` all use `symbol`. Source: `engine/common-obs/baseplat.gc:48`, `engine/common-obs/plat-button.gc:11-16`.

---

## deftype Field Layout

`:offset-assert`, `:heap-base`, and `:size-assert` are **not required** in level `.gc` files. The compiler infers layout. Zero level files in `goal_src/jak1/levels/` use them — including types with many custom fields like `drop-plat` and `citb-sagecage`.

Safe to omit. Fields start at offset 176 (end of process-drawable base), 4 bytes each for float/int32/symbol/string/pointer.

---

## Standard init-from-entity! Template

```lisp
(defmethod init-from-entity! ((this my-type) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))  ;; standard for non-collision entities
  (process-drawable-from-entity! this arg0)      ;; reads trans/quat/bsphere from entity
  ;; read custom lumps here
  (go my-initial-state)
  (none))  ;; (none) return is REQUIRED — missing it is a compile error
```

`(new 'process 'trsqv)` is confirmed correct for non-collision entities. Used by camera-marker, camera-trigger, checkpoint-trigger, aggro-trigger, vol-trigger, and all citadel obs. Source: `levels/citadel/citadel-obs.gc`, `levels/village1/village-obs.gc`.

---

## plat-eco Event Reference

| Event | State that handles it | Effect |
|---|---|---|
| `'wake` | `plat-idle` | → `plat-path-active` immediately |
| `'eco-blue` | `plat-idle` | → `notice-blue` state |
| `'ridden` / `'edge-grabbed` | `plat-idle` | → `plat-path-active` (with blue eco) |
| `'bonk` | `plat-event` (inherited) | Bounce animation |
| `'die` | — | **Silently ignored** |
| anything else | — | **Silently ignored** |

Source: `engine/common-obs/plat-eco.gc`, `engine/common-obs/baseplat.gc`.
