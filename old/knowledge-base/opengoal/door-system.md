# OpenGOAL Door System — Complete Reference

> Researched from jak-project source. Covers: all door types, how each opens, lump properties, button types, wiring patterns, and addon integration.

---

## Overview

Jak 1 has several distinct door families. They share no common base type — each is a separate `process-drawable` with its own state machine. The most useful for custom levels are `eco-door` (blue-eco sliding door) and `sun-iris-door` (event-triggered iris door).

| Type | Source file | Opens via | Good for custom levels? |
|---|---|---|---|
| `eco-door` | `engine/common-obs/baseplat.gc` | Proximity + blue eco OR perm-complete OR one-way exit | ✅ With Starts Open or button link |
| `sun-iris-door` | `levels/sunken/sun-iris-door.gc` | `'trigger` event OR proximity lump | ✅ Best choice |
| `launcherdoor` | `levels/common/launcherdoor.gc` | Jak on launch-jump surface below thresh-y | ⚠️ Needs launcher pad nearby |
| `basebutton` | `engine/common-obs/basebutton.gc` | Flop attack → sends `'trigger` to alt-actor | ✅ Pairs with sun-iris-door |
| `plat-button` | `engine/common-obs/plat-button.gc` | Jak stands on it → sets perm-complete | ⚠️ Path-driven, more complex |
| `maindoor` | `levels/jungle/jungle-obs.gc` | Proximity + blue eco (same as eco-door) | ❌ Jungle-specific art |
| `jng-iris-door` | `levels/jungleb/jungleb-obs.gc` | eco-door subclass | ❌ Jungle-specific art |
| `tra-iris-door` | `levels/training/training-obs.gc` | eco-door subclass | ❌ Training-specific art |
| `citb-iris-door` | `levels/citadel/citadel-obs.gc` | eco-door subclass | ❌ Citadel-specific art |
| `rounddoor` | `levels/misty/misty-warehouse.gc` | eco-door subclass, auto-close+one-way hardcoded | ❌ Misty-specific art |
| `sidedoor` | `levels/jungle/jungle-obs.gc` | eco-door subclass | ❌ Jungle-specific art |
| `helix-slide-door` | `levels/sunken/helix-water.gc` | Event from helix-button | ❌ Sunken puzzle system |
| `fin-door` / `final-door` | `levels/finalboss/final-door.gc` | Scripted cinematic | ❌ Final boss only |

---

## 1. `eco-door`

### Behavior

State machine: `door-closed → door-opening → door-open → door-closing → door-closed`

**`door-closed` opens when ALL of:**
- Jak is within `open-distance` (default 32768 units ≈ 8m)
- Door is not locked (`locked = #f`)
- Any ONE of:
  - The entity's own `perm-status-complete` bit is set (door was opened before)
  - Jak is holding blue eco (`send-event *target* 'query 'powerup eco-blue`)
  - `one-way` flag AND `vector4-dot(out-dir, target-pos) < -8192` (Jak on exit side)

**`door-open` auto-closes when `auto-close` is set AND:**
- Jak is beyond `close-distance` (default 49152 ≈ 12m)
- Camera and Jak are on the same side of the door

The `out-dir` vector is derived from the door's Z-axis quaternion at init time. It points "outward" — the direction Jak should be coming FROM to open it. One-way doors only open from the inward side.

### Lock system

The `state-actor` lump optionally links to another entity. If that entity has `perm-status-complete`:
- `ecdf01` flag set → door **unlocks** (task complete = door open)
- `ecdf00` flag set → door **locks** (task complete = door locked — unusual)

Most use cases: leave `ecdf00`/`ecdf01` unset, link a `basebutton` as `state-actor`. When the button is pressed it sets its own `perm-complete`, which the door polls every frame via `eco-door-method-26`.

### Lump properties

| Lump key | Type | Default | Notes |
|---|---|---|---|
| `scale` | float | 1.0 | Uniform scale |
| `flags` | uint32 | 0 | `eco-door-flags` bitfield (see below) |
| `state-actor` | entity link | none | Entity whose perm-complete status controls lock |

### `eco-door-flags` bitfield

The enum uses `:bitfield #t` so each name is a power-of-two bit position:

| Flag name | Bit | Value | Meaning |
|---|---|---|---|
| `ecdf00` | 0 | 1 | Lock the door when `state-actor` task is NOT complete |
| `ecdf01` | 1 | 2 | Lock the door when `state-actor` task IS complete |
| `auto-close` | 2 | 4 | Door closes automatically after Jak passes through |
| `one-way` | 3 | 8 | Door can only be opened from one side (the inward face) |

> **Bug fixed in addon v1.5:** Original export code set bits 0/1 for auto-close/one-way instead of 2/3. This accidentally set the lock-by-task bits. Fixed to `auto-close=4, one-way=8`.

### "Starts Open" — pre-opening without blue eco

`eco-door`'s `init-from-entity!` checks `(logtest? entity extra perm status complete)`. If that bit is set the door spawns already open (goes directly to `door-open`). The addon sets this via a `perm-status` lump with value `4` (bit 2 = complete).

This is the recommended approach for custom levels where blue eco is not available.

### `eco-door` subclasses

All subclasses inherit all behavior above. They only override:
- `eco-door-method-24` — collide shape setup
- `eco-door-method-25` — skeleton init + distance defaults

| Subclass | Art group | open-distance | close-distance | Special |
|---|---|---|---|---|
| `sidedoor` | `sidedoor-sg` | 22528 (~5.5m) | 61440 (~15m) | Jungle sidedoors |
| `jng-iris-door` | `jng-iris-door-sg` | 32768 (~8m) | 49152 (~12m) | Jungle B iris |
| `tra-iris-door` | `tra-iris-door-sg` | 32768 (~8m) | 49152 (~12m) | Training iris (same art as jng) |
| `citb-iris-door` | eco-door base | — | — | Citadel iris |
| `rounddoor` | `rounddoor-sg` | 69632 (~17m) | 81920 (~20m) | Misty arena; hardcodes auto-close+one-way |

---

## 2. `sun-iris-door`

### Behavior

State machine: `sun-iris-door-closed → sun-iris-door-opening → sun-iris-door-open → sun-iris-door-closing → sun-iris-door-closed`

**Opens when:**
- Receives `'trigger` event from any process, OR
- `proximity` lump is nonzero AND `should-open?` returns true (Jak within `open-dist`)

**Closes when:**
- Receives `'untrigger` event, OR
- `proximity` AND `should-close?` returns true (Jak beyond `close-dist`), OR
- `timeout` lump > 0 AND time elapsed since open > timeout seconds

**`door-open` state:**
- Door mesh is hidden (`draw-status hidden`)
- Collision is cleared (`clear-collide-with-as`)
- Restores both on transition to closing

### Directional proximity (`directional-proximity?`)

Only `sun-iris-door-6` (hardcoded by name) uses this. It checks whether Jak and the camera are on opposite sides of the door plane, meaning Jak has actually passed through. Not relevant for custom levels.

### Lump properties

| Lump key | Type | Default | Notes |
|---|---|---|---|
| `proximity` | uint128 | 0 | Nonzero = also open by proximity |
| `timeout` | float | 0.0 | Seconds before auto-close; 0 = no timeout |
| `scale-factor` | float | 1.0 | Uniform scale multiplier |
| `trans-offset` | float[3] | 0,0,0 | Position offset after placement |

### Events handled

| Event | State it works in | Effect |
|---|---|---|
| `'trigger` | `closed`, `closing` | Opens the door |
| `'untrigger` | `opening`, `open` | Closes the door |
| `'trigger` | `open` | Resets state timer (keeps door open longer) |
| `'move-to` | Any | Teleports door to a new position/rotation |

> **Trigger volume integration:** Trigger volumes in the addon send `'notify` by default (from the aggro-trigger GOAL pattern). `sun-iris-door` listens for `'trigger`. If wiring a trigger volume → sun-iris-door, the volume's emitted GOAL code must send `'trigger` not `'notify`. Alternatively, use a `basebutton` which always sends `'trigger`.

---

## 3. `launcherdoor`

### Behavior

Opens when Jak is on a `launch-jump` surface (set by a launcher pad) AND Jak's Y position is below `thresh-y` (which defaults to `door.root.trans.y - 81920` ≈ 20m below the door).

Stays open while Jak has the launch-jump surface state. Closes once Jak leaves or rises above the threshold.

### Special behavior

- When closing (after door has opened), checks for a `continue-name` lump. If set, activates that checkpoint as the current continue point.
- In jungle levels: sends `no-load-wait` to prevent level unloading during the launcher sequence.
- Has separate art for maincave (`launcherdoor-maincave-sg`), auto-selected based on the current level name.

### Lump properties

| Lump key | Type | Default | Notes |
|---|---|---|---|
| `continue-name` | string | none | Checkpoint name to activate when door closes after opening |

---

## 4. `basebutton`

### Behavior

State machine: `basebutton-up-idle → basebutton-going-down → basebutton-down-idle → basebutton-going-up → basebutton-up-idle`

**Triggered by:**
- `'attack` event with param `'flop` (flop / ground pound attack)
- `'trigger` event from any process

**On press (`basebutton-going-down` enter):**
- Calls `arm-trigger-event!` which sets `event-going-down = 'trigger`
- When animation finishes → `basebutton-method-29` fires the event

**`basebutton-method-29` dispatch:**
1. If `notify-actor` is set: send the event directly to that entity's process
2. Else if `link` (actor-link chain) exists: broadcast to all chained actors

**`notify-actor`** is set by the `alt-actor` entity link at lump index 0.

**On release (`basebutton-going-up`):**
- Fires `event-up` (which is `#f` by default — nothing happens on release)

**Timeout:**
- If `timeout > 0`: button stays in `down-idle` for that many seconds, then fires `event-going-up` and resets
- If `timeout = 0`: stays pressed permanently until `'untrigger` event

**Permanent press:**
- When pressed (not spawned-by-other): sets own `perm-status-complete`. Persists across level reloads.

### Lump properties

| Lump key | Type | Default | Notes |
|---|---|---|---|
| `timeout` | float | 0.0 | Seconds before button resets; 0 = permanent |
| `extra-id` | uint128 | -1 | Optional button ID for multi-button puzzles |
| `alt-actor` (link) | entity | none | Receives `'trigger` when button is pressed |

### Common wiring: button → sun-iris-door

```
ACTOR_basebutton_mybutton
  └─ alt-actor[0] → ACTOR_sun-iris-door_mydoor

Result: ground-pound button → door opens
```

The button sends `'trigger` to the door. If timeout=0, door stays open permanently.
If timeout=N, button resets after N seconds, door receives `'untrigger` after N seconds and closes.

---

## 5. `plat-button`

### Behavior

A floor pressure plate that physically moves downward when Jak stands on it. Path-driven — it requires a `path` curve to define its travel direction and distance.

**Opens when:** Jak is touching the collision mesh (`'touch` event + `prims-touching?` check)

**On press:** Sets own `perm-status-complete`. Does NOT directly send events to other entities — relies on other processes polling its perm-status.

**Resetting:** `bidirectional` lump allows the button to travel both ways on its path (teleports to opposite end). Otherwise one-way.

### Lump properties

| Lump key | Type | Notes |
|---|---|---|
| `path` | curve | Required — defines movement direction and distance |
| `bidirectional` | uint128 | Nonzero = can move both directions |
| `trans-offset` | vector | Position offset from path point |

> **Note:** `plat-button` does not send `'trigger`. It's designed for the sunken ruins puzzle system where the helix-water controller polls button perm-status. For custom levels, prefer `basebutton`.

---

## 6. Wiring Patterns

### Pattern A — Proximity iris door (simplest)

Place `ACTOR_sun-iris-door`. Enable "Open by Proximity" in the panel.

Door opens when Jak walks within ~10m. Closes when Jak walks ~12m away.
No scripting required.

### Pattern B — Always-open eco-door

Place `ACTOR_eco-door`. Enable "Starts Open" in the panel.

Door spawns already open. Cannot be closed. Good for passages where the door is just decorative.

### Pattern C — Button → iris door

```
ACTOR_basebutton  →(alt-actor)→  ACTOR_sun-iris-door
```

Ground-pound the button → door opens. Set button timeout if you want it to reset.

### Pattern D — Trigger volume → iris door

Place a VOL_ trigger volume. In its link settings, target the sun-iris-door.

**Important:** The volume GOAL code must send `'trigger` to the door process, not `'notify`. Check the emitted `send-event` call in the generated GOAL. The door's event handler in `sun-iris-door-closed` only matches `('trigger)`.

### Pattern E — Task-gated eco-door

```
ACTOR_basebutton  →(state-actor)→  ACTOR_eco-door
```

The eco-door polls the button's `perm-status-complete` each frame via `eco-door-method-26`. When the button is pressed (perm-complete set), `ecdf01` flag → `locked = #f` → door opens on next proximity check (still needs blue eco unless `starts_open` or `one-way` is also set).

For a fully button-controlled eco-door with no blue eco requirement, also set `one-way` on the door (so it opens from the approach side without eco).

### Pattern F — Vanilla blue-eco door

Place `ACTOR_eco-door` with no special settings. Door opens when Jak approaches with blue eco. Most useful near blue eco vents.

---

## 7. DGO / .o File Requirements

These processes live in compiled object files. The DGO system needs them loaded for the actors to spawn.

> **Important:** `eco-door` is an **abstract base type** with no `defskelgroup` and no art group file (`.go`). It is never placed directly — all spawnable doors are concrete subclasses. Verified from `.gd` source files.

| Entity | Art `.go` file | Object `.o` file | DGO |
|---|---|---|---|
| `jng-iris-door` | `jng-iris-door-ag.go` | `jungleb-obs.o` | `JUB.DGO`, `TRA.DGO` |
| `sidedoor` | `sidedoor-ag.go` | `jungle-obs.o` | `JUN.DGO` |
| `rounddoor` | `rounddoor-ag.go` | `misty-warehouse.o` | `MIS.DGO` |
| `citb-iris-door` | `citb-iris-door-ag.go` | `citadel-obs.o` | `CTB.DGO` |
| `sun-iris-door` | `sun-iris-door-ag.go` | `sun-iris-door.o` | `SUN.DGO` |
| `launcherdoor` | `launcherdoor-ag.go` | `launcherdoor.o` | `JUN.DGO`, `MAI.DGO`, `SUN.DGO` |
| `basebutton` | `generic-button-ag.go` | `basebutton.o` | `GAME.CGO` (always loaded) |
| `eco-door` (base) | *(none — abstract)* | `baseplat.o` | `GAME.CGO` (always loaded) |

> `basebutton` and the `eco-door` base class code are in `GAME.CGO`, always resident — no injection needed. For custom levels, the recommended pairing is `sun-iris-door` (inject `sun-iris-door.o` + `sun-iris-door-ag.go` from `SUN.DGO`) with `basebutton` (free).

---

## 8. Bug History & Lessons Learned

### Actor link name mismatch (global fix — affects all entity links)
**Bug:** `_build_actor_link_lumps` wrote the Blender object name (`ACTOR_basebutton_0`) into the lump string. `entity-actor-lookup` calls `entity-by-name()` which looks up by the entity's **lump `name` field** (`basebutton-0`). The link resolved to `#f` every time, silently breaking all actor-to-actor references.

**Fix:** Strip `ACTOR_` prefix and replace the first `_` with `-`: `ACTOR_{etype}_{uid}` → `{etype}-{uid}`. Matches `collect_actors` lump name format `f"{etype}-{uid}"`.

**Scope:** Every entity using actor links — orbit-plat, helix chain, minershort/minertall, eco-door state-actor, all vents, etc. All were broken before this fix.

### eco-door state-actor: ecdf00 must be set explicitly
**Bug:** Without `ecdf00=1`, `locked` defaults to `False` regardless of the button state. `eco-door-method-26` only changes `locked` when a flag bit is set — it does nothing if both `ecdf00` and `ecdf01` are 0.

**Fix:** Auto-set `ecdf00=1` at export when a `state-actor` link is present. Door spawns locked; button sets perm-complete; door polls and unlocks each frame.

### eco-door flags wrong bit positions
**Bug:** `auto-close=1, one-way=2` were wrong. Those are `ecdf00` and `ecdf01` (lock-by-task bits). Correct values: `auto-close=4` (bit 2), `one-way=8` (bit 3).

### eco-door is abstract — crashes on spawn
**Bug:** `eco-door` base class `eco-door-method-25` is a no-op. No skeleton initialized. `ja-post` dereferences null in `door-closed` → crash.

**Fix:** Remap `etype "eco-door"` → `"jng-iris-door"` at export time.

### entity-perm-status bit values (process-drawable-h.gc)
| Flag | Bit index | Value |
|---|---|---|
| `bit-0` | 0 | 1 |
| `bit-1` | 1 | 2 |
| `dead` | 2 | 4 |
| `bit-3` | 3 | 8 |
| `bit-4` | 4 | 16 |
| `user-set-from-cstage` | 5 | 32 |
| `complete` | **6** | **64** |
| `bit-7` | 7 | 128 |
| `real-complete` | 8 | 256 |

`complete` (64) is what eco-door checks. `dead` (4) would corrupt the entity — earlier `starts_open` accidentally used 4.

## 9. Engine Source References

| File | What's in it |
|---|---|
| `goal_src/jak1/engine/common-obs/baseplat.gc` | `eco-door` type, `eco-door-flags` enum, `door-closed/opening/open/closing` states |
| `goal_src/jak1/engine/common-obs/basebutton.gc` | `basebutton` type, all states, `press!`, `arm-trigger-event!`, `basebutton-method-29` dispatch |
| `goal_src/jak1/engine/common-obs/plat-button.gc` | `plat-button` type, path-driven floor button |
| `goal_src/jak1/levels/sunken/sun-iris-door.gc` | `sun-iris-door` type, `should-open?`/`should-close?`, all states |
| `goal_src/jak1/levels/common/launcherdoor.gc` | `launcherdoor` type, launch-jump detection, continue-name logic |
| `goal_src/jak1/levels/jungle/jungle-obs.gc` | `maindoor`, `sidedoor` |
| `goal_src/jak1/levels/jungleb/jungleb-obs.gc` | `jng-iris-door` |
| `goal_src/jak1/levels/training/training-obs.gc` | `tra-iris-door` |
| `goal_src/jak1/levels/misty/misty-warehouse.gc` | `rounddoor` |
| `goal_src/jak1/levels/citadel/citadel-obs.gc` | `citb-iris-door`, `citb-button` |

---

## 10. Addon Integration (v1.5+)

### Entities available in the spawn picker

| Entity | Category | Art group | Notes |
|---|---|---|---|
| `jng-iris-door` | Objects | `jng-iris-door-ag.go` | Jungle/Training iris door |
| `sidedoor` | Objects | `sidedoor-ag.go` | Jungle sliding side door |
| `rounddoor` | Objects | `rounddoor-ag.go` | Misty round arena door |
| `sun-iris-door` | Objects | `sun-iris-door-ag.go` | Best choice for custom levels |
| `launcherdoor` | Objects | `launcherdoor-ag.go` | Needs launcher pad nearby |
| `basebutton` | Objects | `generic-button-ag.go` | Always available (GAME.CGO) |

> `eco-door` itself is not spawnable — the picker uses concrete subclasses. The Door Settings panel covers `eco-door`, `jng-iris-door`, `sidedoor`, and `rounddoor` (all share the same flag/lump schema).

### Panels (selected-object sidebar)

**Eco Door Settings** (`ACTOR_eco-door` selected):
- Open-condition hint (explains blue eco requirement)
- Auto Close toggle (flag bit 2, value 4)
- One Way toggle (flag bit 3, value 8)
- Starts Open toggle (emits `perm-status` lump, door spawns pre-opened)
- Actor Links → state-actor slot (optional lock controller)

**Iris Door Settings** (`ACTOR_sun-iris-door` selected):
- Open method hint
- Open by Proximity toggle (emits `proximity = 1` lump)
- Auto-Close Timeout nudger (emits `timeout` float lump in seconds)

**Button Settings** (`ACTOR_basebutton` selected):
- Usage hint (flop-attack to press)
- Reset Timeout nudger (emits `timeout` float lump)
- Actor Links → alt-actor[0] slot (target receives `'trigger` on press)

**Launcher Door Settings** (`ACTOR_launcherdoor` selected):
- Continue Point picker (lists scene checkpoints/spawns)

### Known issues / open questions (as of v1.7.0)

**Confirmed working (live tested):**
- [x] `jng-iris-door` spawns correctly
- [x] `basebutton` spawns and responds to flop/ground-pound
- [x] Button → state-actor → door wiring works end-to-end
- [x] `eco-door` flags corrected: `auto-close=4`, `one-way=8` (was wrong 1/2)
- [x] Actor link name resolution fixed globally (was Blender name, now entity lump name)
- [x] `sun-iris-door.o` confirmed in `SUN.DGO`; `basebutton.o` in `GAME.CGO`

**Unverified / needs live test:**
- [ ] **`starts_open`**: Emits `perm-status` lump (value 64 = `complete` bit 6). No engine code found that reads a `perm-status` res-lump — perm status is loaded from save data, not lumps. This feature may do nothing.
- [ ] **Trigger volume → sun-iris-door**: Volumes emit `'notify`; `sun-iris-door` only handles `'trigger`. Use `basebutton` instead for now.
- [ ] **`rounddoor`, `sidedoor`** — entity defs added, not live tested.
- [ ] **`sun-iris-door` proximity** — lump emitted correctly, not live tested.
