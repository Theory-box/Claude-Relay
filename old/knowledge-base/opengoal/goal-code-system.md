# GOAL Code System — Custom Logic in Custom Levels

> Covers the full goal-code feature: how custom GOAL types are defined, spawned, wired to trigger volumes, and exported into obs.gc.
> **Status: Merged to main, confirmed working in-game (April 2026)**

---

## Overview

The GOAL Code system lets you define arbitrary GOAL logic directly in Blender and have it compiled into your level automatically on export. No manual file editing required.

Three components work together:

| Component | What it does |
|---|---|
| **Custom Type Spawner** | Places a correctly-named `ACTOR_` empty for any deftype you write |
| **GOAL Code Panel** | Attaches a Blender text block to an actor; exported verbatim into `*-obs.gc` |
| **VOL_ → custom actor wiring** | Links a trigger volume to a custom actor; auto-emits a `vol-trigger` GOAL entity |

---

## 1. Custom Type Spawner

**Location:** Spawn panel → **⚙ Custom Types**

Type any deftype name (lowercase, hyphens allowed, e.g. `die-relay`) and hit **Spawn**. Places an `ACTOR_die-relay_0` empty at the 3D cursor, coloured yellow-green to distinguish it from built-in actors.

The name must:
- Be lowercase letters, digits, hyphens only
- Not already be a built-in entity type (the spawner rejects conflicts)
- Match the `deftype` name in your GOAL code exactly

---

## 2. GOAL Code Panel

**Location:** N-panel → OpenGOAL tab → Selected Object → **GOAL Code** (sub-panel)

Only appears when a non-built-in `ACTOR_` empty is selected.

### Workflow

1. Select your custom `ACTOR_` empty
2. **Create boilerplate block** — creates a Blender text block pre-filled with a minimal skeleton
3. Open the text editor (Shift+F11) → **Open in Editor** button to jump to the block
4. Replace the boilerplate with your actual GOAL code
5. Export — the block is appended verbatim to `goal_src/levels/<n>/<n>-obs.gc`

### Rules
- One text block per actor, but multiple actors can share the same block — it's emitted only once
- The **enabled** toggle controls whether the block exports
- The panel shows a line count and "will inject / disabled" status
- Compile errors appear in the goalc build log, not in Blender

---

## 3. VOL_ → Custom Actor Wiring

Place a `VOL_` mesh trigger volume. In its **Volume Links** panel, Shift-select the VOL_ and your custom actor, then hit **Link →**.

On export the exporter:
1. Detects the custom target via `_classify_target` → `"custom"`
2. Calls `collect_custom_triggers` → emits a `vol-trigger` JSONC actor with AABB bounds + `target-name` lump
3. Emits the `vol-trigger` GOAL deftype in obs.gc via `write_gc(has_custom_triggers=True)`

The `vol-trigger` entity sends:
- `'trigger` to the target when Jak **enters** the volume
- `'untrigger` to the target when Jak **exits** the volume

**No manual lump work needed** — bounds are derived from the VOL_ mesh automatically.

---

## 4. Complete Working Example: Trigger Volume Kills a Platform

Confirmed working in-game. Jak walks into a zone → platform disappears permanently.

### Setup

1. Spawn a platform (e.g. `plat-eco`). Its entity lump name will be `plat-eco-0`
2. Spawn Panel → ⚙ Custom Types → type `die-relay` → Spawn
3. Select `ACTOR_die-relay_0` → Custom Lumps → add:
   - Key: `target-name` | Type: `string` | Value: `plat-eco-0`
4. Select `ACTOR_die-relay_0` → GOAL Code → Create boilerplate → replace with the code below
5. Add a cube mesh, rename to `VOL_die_trigger`, size over the trigger zone
6. Shift-select `VOL_die_trigger` + `ACTOR_die-relay_0` → Volume Links → Link →
7. Export + Build

### die-relay GOAL code (confirmed working)

```lisp
;;-*-Lisp-*-
(in-package goal)

(deftype die-relay (process-drawable)
  ((target-name string))
  (:states die-relay-idle))

(defstate die-relay-idle (die-relay)
  :event
    (behavior ((proc process) (argc int) (message symbol) (block event-message-block))
      (case message
        (('trigger)
         (let ((tgt (process-by-ename (-> self target-name))))
           (when tgt
             (process-entity-status! tgt (entity-perm-status dead) #t)
             (deactivate tgt)))
         (deactivate self))))
  :code
    (behavior ()
      (loop (suspend))))

(defmethod init-from-entity! ((this die-relay) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (set! (-> this target-name)
        (res-lump-struct arg0 'target-name string))
  (go die-relay-idle)
  (none))
```

### Key notes
- `(process-entity-status! tgt (entity-perm-status dead) #t)` — marks target as dead so it won't respawn within the session
- `(deactivate tgt)` — immediately kills the process. Use this, NOT `(send-event tgt 'die)` — plat-eco ignores `'die`
- `:event` handler parameters **must be typed**: `(proc process) (argc int) (message symbol) (block event-message-block)` — GOAL is strictly typed, untyped params cause a typecheck compile error
- No `radius` lump needed — the VOL_ mesh defines the trigger zone

### Entity lump name convention
`process-by-ename` looks up the `'name` lump string — not the Blender object name:

| Blender object name | Entity lump name |
|---|---|
| `ACTOR_plat-eco_0` | `plat-eco-0` |
| `ACTOR_die-relay_0` | `die-relay-0` |
| `ACTOR_jng-iris-door_2` | `jng-iris-door-2` |

---

## 5. Proximity Trigger (no VOL_ needed)

For a simpler test or when a VOL_ box doesn't fit, the entity can self-detect proximity:

```lisp
(deftype proximity-relay (process-drawable)
  ((target-name string)
   (radius      float))
  (:states proximity-relay-idle))

(defstate proximity-relay-idle (proximity-relay)
  :code
    (behavior ()
      (loop
        (when (and *target*
                   (< (vector-vector-distance
                        (-> self root trans)
                        (-> *target* control trans))
                      (-> self radius)))
          (let ((tgt (process-by-ename (-> self target-name))))
            (when tgt
              (process-entity-status! tgt (entity-perm-status dead) #t)
              (deactivate tgt)))
          (deactivate self))
        (suspend))))

(defmethod init-from-entity! ((this proximity-relay) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (set! (-> this target-name)
        (res-lump-struct arg0 'target-name string))
  (set! (-> this radius)
        (res-lump-float arg0 'radius :default (meters 10.0)))
  (go proximity-relay-idle)
  (none))
```

Custom Lumps needed:
- `target-name` — string — `plat-eco-0`
- `radius` — **meters** — `10.0` ← must use `meters` type, not `float`

**Important:** `res-lump-float` returns the raw stored value. A `meters` lump stores `value × 4096`. `vector-vector-distance` also returns raw units. Using `float` type with value `10.0` = ~2.4mm and will never trigger.

---

## 6. What Gets Written to obs.gc

On export, obs.gc contains (in order):

1. `camera-marker` type (always)
2. `camera-trigger` type (if camera volumes exist)
3. `checkpoint-trigger` type (if checkpoints exist)
4. `aggro-trigger` type (if enemy aggro volumes exist)
5. **`vol-trigger` type** (if VOL_ → custom actor links exist)
6. **Custom GOAL code blocks** (from text blocks attached to ACTOR_ empties)

The `vol-trigger` type is always emitted as a built-in — you don't write it. Your custom entity just handles `'trigger` in its `:event` handler.

---

## 7. GOAL Code Rules (confirmed from source research)

### Event handler parameters must be typed
```lisp
;; CORRECT
:event
  (behavior ((proc process) (argc int) (message symbol) (block event-message-block))
    ...)

;; WRONG — compiler typechecks fail
:event
  (behavior (proc argc message block)
    ...)
```

### Boolean fields use symbol type
```lisp
(deftype my-entity (process-drawable)
  ((was-triggered symbol)   ;; correct — engine standard
   (is-active     symbol))) ;; correct
```

### offset-assert not required in level code
Level `.gc` files don't use `:offset-assert`, `:heap-base`, or `:size-assert`. The compiler infers layout. Only engine header files use them.

### Killing processes
```lisp
;; Kill immediately (correct)
(deactivate proc)

;; Mark dead so engine won't re-birth (use with deactivate)
(process-entity-status! proc (entity-perm-status dead) #t)

;; DO NOT use send-event 'die on platforms — plat-eco ignores it
```

### Units
```lisp
;; Distance comparison — must be consistent:
;; lump type "meters" stores value × 4096
;; vector-vector-distance returns raw units
;; (meters 10.0) = 40960.0 raw units

(set! (-> this radius) (res-lump-float arg0 'radius :default (meters 10.0)))
(< (vector-vector-distance ...) (-> self radius))  ;; both raw units ✓
```

---

## 8. Bug Fix History

| Commit | Bug | Fix |
|---|---|---|
| `8fc7e79` | `OG_PT_SpawnCustomTypes` registered twice — Blender silently killed all classes after it | Removed duplicate |
| `f509e96` | Both new panels in import tuple but not `register()` — never actually registered | Added to classes tuple |
| `091502d` | `_is_custom_type` used in panels/export but not imported | Added to module-level imports |
| `9c7ea26` | `_is_linkable` didn't accept custom actors — VOL_ link UI never appeared | Added `_is_custom_type` check |
| `dfa7fab` | `CreateGoalCodeBlock.poll` missing `_wpb_` guard | Added `_wpb_` exclusion |
| `9eaee82` | vol-trigger GOAL: wrong player pos, missing null guard, missing cull-radius field, paren imbalance | Full rewrite mirroring aggro-trigger pattern |
| `6786af1` | `_is_custom_type` missing from `utils.py` import — `_is_linkable` would NameError | Added to import |
