# Trigger & Event System — Jak 1 OpenGOAL Custom Levels

A complete reference for how actors communicate, how triggers fire, and how game state (orbs, cells, scout flies) can gate doors, platforms, and spawns in custom levels.

---

## 1. Core Concepts

### How Actors Communicate

The engine uses a **message-passing** system. Any process can send an event to any other process using `send-event`. The receiving process handles it in its current state's `:event` handler.

```lisp
(send-event target-process 'message-symbol)
; or with params:
(send-event target-process 'message param0 param1)
```

Actors in a JSONC don't call each other directly — they reference each other by **name** (string lookup) or **AID** (actor ID, binary search). The addon exports these as the `alt-actor`, `state-actor`, `water-actor`, `next-actor`, `prev-actor` lump fields.

### Entity Perm — Persistent State

Each actor has an `entity-perm` — a persistent status block that survives actor death/respawn:

| Bit flag | Meaning |
|---|---|
| `dead` | Actor is permanently dead, won't respawn |
| `complete` | Actor has been "completed" (button pressed, task done) |
| `real-complete` | Task fully closed (used for power cells / game-task system) |

The `complete` bit is the key flag for door/trigger wiring. When `basebutton` is pressed, it sets `complete` on itself. Doors that poll `state-actor` read this bit each frame.

---

## 2. Lump Fields Used for Linking

These are the res-lump keys used to wire actors together. The addon exposes these via the Entity Links panel.

| Lump key | Type | Purpose |
|---|---|---|
| `alt-actor` | `string` (array) | General-purpose target reference. Used by battlecontroller (enemy waves), launcherdoor (notify on open), orbit-plat (partner). |
| `state-actor` | `string` | Door watches this actor's `complete` perm bit each frame to decide locked/unlocked. Used by eco-door family. |
| `water-actor` | `string` | Water volume reference. |
| `next-actor` | `string` | Forward link in an actor chain (used by actor-link-info linked list). |
| `prev-actor` | `string` | Backward link in the chain. |
| `trigger-actor` | `string` (array) | battlecontroller sends `'trigger` to all trigger-actors when the wave is cleared. |
| `notify-actor` | `string` | basebutton sends its event to this specific actor (alternative to link-chain). |

---

## 3. The Event Vocabulary

These are the standardised event symbols the engine actors understand. Sending the wrong one does nothing; sending the right one causes the state transition.

### Universal / Common

| Event | Who handles it | What it does |
|---|---|---|
| `'trigger` | sun-iris-door, shover, battlecontroller, most platforms | Opens/activates the actor |
| `'untrigger` | sun-iris-door | Closes/deactivates |
| `'notify` | launcherdoor (alt-actors) | Launcherdoor sends this to all alt-actors when it opens |
| `'attack` | basebutton (up-idle state) | Jak ground-pounds the button → goes down |
| `'move-to` | basebutton | Teleports button to a new position/rotation |

### Camera Events

| Event | Target | What it does |
|---|---|---|
| `'change-state` | `*camera*` | Switch to a named camera state |
| `'change-to-entity-by-name` | `*camera*` | Snap camera to a named entity |
| `'clear-entity` | `*camera*` | Release entity camera lock |
| `'blend-from-as-fixed` | `*camera*` | Blend from current position as fixed |
| `'teleport` | `*camera*` | Instant cut with no blend |

### battlecontroller-specific

| Event | Direction | Meaning |
|---|---|---|
| `'trigger` | battlecontroller → trigger-actors | Sent to all `trigger-actor` refs when wave is cleared |
| `'trigger` | → battlecontroller | Kills the battlecontroller (go to die state) |
| `'cue-chase` | → enemy | Tell a linked enemy to start chasing |
| `'cue-jump-to-point` | → enemy | Tell enemy to jump to a position |

---

## 4. Wiring Patterns (What Works Today)

### Pattern A — Button → Door

The most reliable wiring in the engine. `basebutton` sets its own `complete` perm when pressed. The door (eco-door / jng-iris-door) polls its `state-actor` ref's `complete` bit each frame.

**In the addon:**
1. Place `ACTOR_basebutton_<uid>` empty
2. Place `ACTOR_jng-iris-door_<uid2>` empty
3. Select the door → Entity Links → set `state-actor` → pick the button

**What the engine does internally:**
- `basebutton` on press: `(process-entity-status! self (entity-perm-status complete) #t)`
- `jng-iris-door` each frame: checks `(logtest? (-> state-actor extra perm status) (entity-perm-status complete))` → if true, opens

**Lump flags auto-set by addon:**
- `ecdf00` bit 0 on door (locked until `state-actor` is complete)

---

### Pattern B — Enemy Wave → Door / Platform

`battlecontroller` manages a wave of enemies linked via `next-actor`/`prev-actor` chain. When all enemies in the chain are dead, it sends `'trigger` to all its `trigger-actor` refs.

**In the addon:**
1. Place a `ACTOR_battlecontroller_<uid>` empty
2. Place your enemies — link them in a chain via `next-actor`/`prev-actor` Entity Links
3. Link the battlecontroller's `trigger-actor` to whatever should open (door, platform, etc.)

**Engine flow:**
```
all next/prev-chain actors dead
  → battlecontroller enters die state
    → sends 'trigger to each trigger-actor ref
      → door/platform receives 'trigger → opens
```

**Note:** `battlecontroller` also fires an intro camera (`alt-actor` ref) when the wave starts. Set `alt-actor` to a `CAMERA_` empty if you want a cutscene-style pan when the wave triggers.

---

### Pattern C — Launcherdoor → Notify Chain

`launcherdoor` (used with launcher pads) sends `'notify` to all its `alt-actor` refs when it opens. You can use this to trigger particle effects, activate platforms, etc.

**In the addon:**
1. Place `ACTOR_launcherdoor_<uid>`
2. Set `og_continue_name` property to a `CHECKPOINT_` empty name
3. Add `alt-actor` links to anything you want notified on open

---

### Pattern D — sun-iris-door (Proximity / Trigger)

`sun-iris-door` responds to `'trigger` and `'untrigger` events directly. It has no built-in proximity check — something else must send `'trigger` to it.

**Options for triggering it:**
- Send `'trigger` from a `basebutton` via `notify-actor` lump (button sends its event to the door directly, bypassing the `state-actor` perm-poll)
- Send `'trigger` from a `battlecontroller` via `trigger-actor`
- *(Future)* Send `'trigger` from a custom volume trigger

---

## 5. actor-link-info — The Linked List

When actors have `next-actor`/`prev-actor` lump entries, the engine builds a doubly-linked list. `actor-link-info` provides helper methods:

| Method | What it does |
|---|---|
| `send-to-next` | Send event to the next actor's process |
| `send-to-prev` | Send event to previous actor |
| `send-to-all` | Send to every actor in the whole chain (both directions) |
| `send-to-all-after` | Send only to actors after this one |
| `actor-count` | Count all actors in the chain |
| `get-matching-actor-type-mask` | Returns bitmask of which positions match a given type |
| `actor-count-before` | How many actors precede this one (used for button-id) |

`actor-link-subtask-complete-hook` and `actor-link-dead-hook` are iterator callbacks used to check if all actors in a chain are complete/dead respectively.

`alt-actor-list-subtask-incomplete-count` — counts how many `alt-actor` refs on a process-drawable do **not** have the `complete` bit set. Useful for "collect N of these to unlock" patterns.

---

## 6. Game State Gating (Orbs / Cells / Flies)

### What's available in `*game-info*`

| Field | Type | What it holds |
|---|---|---|
| `(-> *game-info* money)` | `float` | Current dark eco orb count |
| `(-> *game-info* fuel)` | `float` | Current power cell count |
| `(-> *game-info* buzzer-total)` | `float` | Total scout flies collected (all tasks) |
| `(-> *game-info* task-perm-list data <task-id> status)` | `entity-perm-status` | Completion bits for a specific `game-task` |

### Checking task completion in GOAL

```lisp
; Is a specific game-task complete?
(task-complete? *game-info* (game-task village1-yakow))  ; → #t / #f

; Does player have at least N orbs?
(>= (-> *game-info* money) 50.0)

; Does player have at least N power cells?
(>= (-> *game-info* fuel) 3.0)

; Scout flies for a specific task (returns count 0-7)
(buzzer-count *game-info* (game-task beach-buzzer))
```

### game-task enum — Custom Level Strategy

`game-task` is a `uint8` with max value 116. The last assigned vanilla slot is 115 (`assistant-village3`). `max` = 116.

**For custom levels:** There is no safe way to permanently add new `game-task` values without patching `game-task-h.gc` and the task control tables. The uint8 type gives headroom up to 255, but the perm arrays and task-control tables are statically sized to 116.

**Practical options:**
1. **Reuse existing unused tasks** — some task IDs exist in the enum but are unimplemented (e.g. `village3-extra1` #74 appears unused in vanilla). Check `task-control.gc` before reusing.
2. **Use global counters only** — check `(-> *game-info* money)` / `(-> *game-info* fuel)` thresholds. Coarse but requires no patching.
3. **Use entity perm bits directly** — give a specific in-level actor a `game-task` assignment via its JSONC `game_task` field. When that actor is "completed" (e.g. a power cell collected), its `real-complete` bit is set and can be polled via `task-complete?`.

The JSONC `game_task` field on an actor tells the engine which `game-task` slot to mark `real-complete` when the actor fires its completion event (cell pickup, buzzer collection, etc.).

---

## 7. Game-Task Slots — Full Analysis

### The hard limit is 116 — but it's patchable

`task-perm-list` is allocated as exactly 116 entries at startup (`game-info.gc` line 673). The `get-task-control` function hard-gates on `>= 116` and returns `*null-task-control*` for anything out of range. The save file serializer also hardcodes 116 loops.

**To add new task IDs beyond 116 you would need to:**
1. Add entries to `game-task-h.gc` (uint8 allows up to 255)
2. Extend `*task-controls*` array in `task-control.gc`
3. Change the `116` literal in `game-info.gc` allocation
4. Change the `116` literal in `get-task-control` bounds check
5. Change the `116` literal in `game-save.gc` serialization

This is doable in an OpenGOAL fork but is risky for save compatibility across multiple custom level projects. Not recommended unless you control the full build.

### The two genuinely safe cut-content slots

A full cross-reference of every `game-task` enum value against all non-infrastructure source files (`levels/`, `engine/common-obs/`, `engine/ui/`) reveals exactly two that are plumbed into all the engine infrastructure (task-control, progress screen, debug menu, autosplit) but have **zero references in any actual level or entity code**:

| Slot | ID | Progress screen label | Safe to repurpose? |
|---|---|---|---|
| `village3-extra1` | 74 | "hidden-power-cell" (Village 3 section) | ✅ Yes — fully cut, no entity uses it |
| `ogre-secret` | 110 | "hidden-power-cell" (Ogre section) | ✅ Yes — fully cut, no entity uses it |

Both have complete `task-control` entries (hint/intro/reminder/resolution stages with `#t` conditions), progress screen entries, debug menu entries, and autosplit tracking. The content was fully scaffolded then cut. The task ID, its perm slot, its progress screen position, and its save file bit are all reserved and working — just no entity ever sets them.

**`red-eggtop` (106) looks unused but is NOT safe** — it gates red eco vents in `collectables.gc`. Repurposing it would break eco vent blocking logic in Ogre/Volcano areas.

### So yes — only two task slots, but they're enough for most designs

Each slot can gate one completion event. But a single task slot can be checked by **multiple doors/triggers simultaneously** — all of them poll the same bit. So one power cell unlocks as many things as you want. For more complex multi-step progression, use the `perm-list` system (entity AIDs, 4096 slots) instead of `task-perm-list`.

### Using entity AIDs as unlimited gating slots

The `perm-list` in `*game-info*` is allocated at **4096 entries** and is keyed by AID (actor ID), not by `game-task`. Every actor in your level already has an AID. When an actor's `complete` perm bit is set, it persists across sessions via `copy-perms-from-level!` / `copy-perms-to-level!`.

This means: **any actor can be a gate.** If a power cell (AID 5) is collected, its `complete` bit is set in `perm-list`. A custom trigger that reads `(lookup-entity-perm-by-aid *game-info* 5)` and checks its `complete` bit can fire without touching `task-perm-list` at all. This is effectively unlimited — you get 4096 persistent per-actor state bits per playthrough.

The tradeoff is that AID-based gating requires knowing AIDs at write time (they're assigned at export), and requires GOAL code that explicitly walks `perm-list`. The two `game-task` slots are simpler to use from JSONC alone.

---

## 8. State Trigger — Planned Feature

**Not yet implemented.** Tracked for future addon development.

### Proposed design

Place a `STATE_TRIGGER_<uid>` empty with these custom properties:

| Property | Type | Meaning |
|---|---|---|
| `og_require_cells` | int | Minimum power cells player must have |
| `og_require_orbs` | int | Minimum dark eco orbs |
| `og_require_flies` | int | Minimum total scout flies |
| `og_require_task` | string | `game-task` enum name that must be complete |

The `STATE_TRIGGER_` actor would be a custom GOAL entity (templated `.gc` file generated by the addon per level, similar to how the obs stub works). Each frame it checks the relevant `*game-info*` fields; when all conditions are met it sends `'trigger` to its `alt-actor` link targets.

**Why Path A (global counters) and not Path B (task bits):**
- Path B requires patching `game-task-h.gc` and resizing perm arrays — invasive and likely to conflict across custom levels
- Path A (thresholds on `money`/`fuel`) requires only a simple GOAL process, no engine changes
- Limitation: thresholds are global, not per-level. "Collect 50 orbs in this level" isn't natively expressible — only "player has 50 orbs total"

**Workaround for per-level gating:** Assign specific in-level actors (a power cell, a scout fly group) a `game_task` value and link the trigger to `task-complete?` on that task. This is exactly how vanilla locks work.

---

## 9. Actor Spawning Lifecycle

Understanding when actors are born/killed matters for trigger design.

```
Level loads
  → entity system iterates entity array
    → for each entity: check birth?()
      → birth? = not dead, within birth-dist (~80m of camera)
        → if yes: spawn the process (call init-from-entity!)

Actor process runs until:
  a) process-entity-status! sets the 'dead bit → never respawns
  b) actor walks out of birth-dist → killed, respawns on re-entry
  c) explicit (deactivate self) call
```

**Key implication for triggers:** If a door is triggered open and the player walks away (killing the door process), will it remember to stay open on respawn? Yes — as long as the door's `init-from-entity!` checks the `complete` perm bit at startup. The eco-door family does this correctly. Custom entities need to explicitly read perm state at init time.

---

## 10. What the Addon Exports for Each Actor

For reference, the JSONC fields relevant to triggering:

```json
{
  "trans": [gx, gy, gz],
  "etype": "jng-iris-door",
  "game_task": "(game-task none)",
  "quat": [qx, qy, qz, qw],
  "vis_id": 0,
  "bsphere": [gx, gy, gz, radius],
  "lump": {
    "name": "jng-iris-door-1",
    "state-actor": ["string", "basebutton-1"],
    "flags": ["uint32", 1]
  }
}
```

The `game_task` field at the top level tells the engine which task slot to mark complete when this entity fires. Set to `(game-task none)` for entities that don't award a task. Set to e.g. `(game-task village1-yakow)` to mark that task complete when this entity completes.

---

## 11. Confirmed Working Combinations (April 2026)

| Source | Target | Link used | Status |
|---|---|---|---|
| `basebutton` pressed | `jng-iris-door` opens | `state-actor` | ✅ Confirmed working |
| `basebutton` pressed | `eco-door` opens | `state-actor` | ✅ Confirmed working |
| `battlecontroller` wave cleared | `'trigger` to next actor | `trigger-actor` | ✅ Source-confirmed |
| `launcherdoor` opens | notifies `alt-actor` refs | `alt-actor` | ✅ Source-confirmed |
| `sun-iris-door` | receives `'trigger` from any source | direct send-event | ✅ Source-confirmed |
| State trigger (orb/cell count) | any actor | `alt-actor` | ⚠ Not yet implemented |
| `game-task` completion → perm | door/trigger poll | `game_task` JSONC field | ⚠ Untested in custom levels |

---

## 12. Open Questions

**⚠ Checkpoint-gated spawns** — can we set an actor's perm `dead` bit before level load to prevent it spawning until a condition is met? Needs testing via nREPL.

**⚠ One-shot vs persistent triggers** — after a battlecontroller fires `'trigger`, can the target re-close? The `complete` perm persists across sessions, so perm-based doors stay open permanently after trigger. Need to verify if `untrigger` clears the perm or just closes visually.

**⚠ State trigger GOAL codegen** — the templated `.gc` approach needs a prototype. Key question: does `(mi)` correctly pick up a new entity type defined in a level-specific file, or does it need to be in a specific DGO?

**⚠ Reusable game-task slots** — need to audit `task-control.gc` and `game-task-h.gc` to confirm which IDs (74+) have empty task-control entries and are safe to repurpose for custom levels.
