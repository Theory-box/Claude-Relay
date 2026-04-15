# feature/goal-code — Session Notes

## Branch Status
- **Branch:** `feature/goal-code`
- **Latest commit:** `9eaee82`
- **State:** Rebased on main, all known bugs fixed, ready for testing

---

## Active Work Summary

### What this branch does
- Adds a **Custom Types** spawn panel (Spawn → ⚙ Custom Types)
- Adds a **GOAL Code** sub-panel on any selected ACTOR_ empty
- Injects enabled text blocks verbatim into `*-obs.gc` at export time
- Adds `vol-trigger` GOAL deftype: AABB volume that sends `'trigger`/`'untrigger` to a custom actor when Jak enters/exits

### Files changed from main
- `data.py` — `_is_custom_type(etype)` helper
- `properties.py` — `OGGoalCodeRef` PropertyGroup, `custom_type_name` StringProperty
- `operators.py` — 4 new operators: Create/Clear/Open goal code block, SpawnCustomType
- `export.py` — `collect_custom_triggers()`, `_classify_target` custom path, `write_gc` vol-trigger + injection
- `build.py` — all 3 call sites updated
- `panels.py` — `OG_PT_SpawnCustomTypes`, `OG_PT_ActorGoalCode`
- `__init__.py` — registration wiring

---

## Bugs Fixed This Session

### Rebase session (2026-04-14/15)
- `CreateGoalCodeBlock.poll` was missing `_wpb_` guard — path-B waypoints would show Create button
- Vol-trigger GOAL code had 4 critical bugs (see below)

### Vol-trigger bugs (all fixed in `9eaee82`)
1. **Player position** — `(-> self root trans)` read entity spawn point (never changes). Fixed to `(-> *target* control trans)`
2. **Missing null guard + throttle** — Added `(when (and *target* (zero? (mod (-> *display* base-frame-counter) 4)))` wrapper, matching aggro-trigger exactly
3. **Missing `cull-radius` field** — Deftype declared no `cull-radius` but `init-from-entity!` wrote to it. Added at `:offset-assert 180` with correct `:heap-base #x70 :size-assert #xd4`
4. **Paren imbalance** — Double-nested `let`/`when` in second cond branch needed 7 closes, had 6. Verified balanced (depth=0) with automated counter

---

## First Test Plan — die-relay

### What to test
A custom `die-relay` entity that kills a platform when Jak approaches.

### Setup
1. Spawn `ACTOR_plat-eco_0` (or any platform) in your level
2. Spawn panel → ⚙ Custom Types → type `die-relay` → Spawn
3. Select `ACTOR_die-relay_0` → GOAL Code → Create boilerplate block
4. Open in Text Editor (Shift+F11) → paste the code below
5. Custom Lumps on `ACTOR_die-relay_0`:
   - `target-name` — **string** — `plat-eco-0`  ← note: hyphen, not underscore
   - `radius` — **meters** — `10.0`  ← MUST use `meters` type, not `float`
6. Export + Build

### die-relay GOAL code
```lisp
;;-*-Lisp-*-
(in-package goal)

(deftype die-relay (process-drawable)
  ((target-name string)
   (radius      float))
  (:states die-relay-idle))

(defstate die-relay-idle (die-relay)
  :code
    (behavior ()
      (loop
        (when (and *target*
                   (< (vector-vector-distance
                        (-> self root trans)
                        (-> *target* control trans))
                      (-> self radius)))
          (let ((tgt (process-by-ename (-> self target-name))))
            (when tgt (deactivate tgt)))
          (deactivate self))
        (suspend))))

(defmethod init-from-entity! ((this die-relay) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (set! (-> this target-name)
        (res-lump-struct arg0 'target-name string))
  (set! (-> this radius)
        (res-lump-float arg0 'radius :default (meters 10.0)))
  (go die-relay-idle)
  (none))
```

### Key notes on the code
- Uses `(deactivate tgt)` NOT `(send-event tgt 'die)` — plat-eco ignores `'die`, only handles `'wake`/`'eco-blue`/`'ridden`. `deactivate` is the correct engine-level kill (used by citadel-sages.gc)
- Uses `(meters 10.0)` as default — `res-lump-float` returns raw game units. A `meters` lump type stores value × 4096. `(meters 10.0)` = 40960 units. Both must be consistent.
- `process-by-ename` returns `process` type — `deactivate` is a method on `process`, so no cast needed
- `target-name` lump format: `ACTOR_plat-eco_0` → lump name = `plat-eco-0` (hyphen between etype and uid, NOT underscore)

### Expected build log
```
[write_gc] injected 1 custom GOAL code block(s): die-relay-goal-code
```

### Expected in-game
Walk within 10m of `ACTOR_die-relay_0`'s position. The platform should disappear and the die-relay deactivates itself.

---

## Open Questions
- [ ] Does `deactivate` on a `plat-eco` process cause any crash? (It has no custom deactivate method so falls through to base `process` deactivate — should be safe)
- [ ] Does the vol-trigger test need to run separately or can we skip straight to a more complex test once die-relay works?
- [ ] Units doc — should custom lump panel show a hint when type is `float` suggesting `meters` for distance values?

---

## VOL_ → Custom Actor Wiring (for later test)
Once die-relay works standalone, the vol-trigger system can be tested:

1. Place `VOL_` mesh, size it as trigger zone
2. Shift-select VOL_, then shift-select `ACTOR_die-relay_0` → Volume Links → Link →
3. Build log should show:
   ```
   [vol-trigger] VOL_x → ACTOR_die-relay_0 (lump: die-relay-0)
   [write_gc] vol-trigger type embedded
   ```
4. In-game: walk into the VOL_ zone → die-relay receives `'trigger` → platform dies

