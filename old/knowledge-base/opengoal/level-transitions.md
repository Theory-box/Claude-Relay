# OpenGOAL — Level Transition Triggers

**Research date:** April 2026
**Branch context:** feature/level-flow
**Status:** Research complete. Implementation not started.
**Sources:** Source crawl of `load-boundary*.gc`, `launcherdoor.gc`, `jungle-elevator.gc`, `game-info.gc`, LuminarLight mod base, official OpenGOAL custom levels guide.

---

## Overview

"Next level" triggers in OpenGOAL are the mechanism by which the player physically moves between levels — walking through a door, entering a cave, crossing a boundary. Three approaches exist, each with different tradeoffs for custom level work.

---

## Approach 1 — `load-boundary` (Seamless Streaming)

### What it is
The vanilla mechanism for all level transitions in the game. A polygonal XZ shape with Y top/bot extents. Fires commands when the player or camera crosses the boundary. 170 boundaries exist in vanilla across all levels.

### How it works
```lisp
(static-load-boundary
  :flags (player)          ; trigger on player pos, not camera
  :top 322236.65           ; Y ceiling
  :bot -524288.0           ; Y floor
  :points (x0 z0 x1 z1 x2 z2)  ; XZ polygon vertices, game units
  :fwd (load level-a level-b)   ; command on forward crossing
  :bwd (load level-b level-a))  ; command on backward crossing
```

### Available commands
| Command | Effect |
|---|---|
| `(checkpt "name" #f)` | Set named continue as current checkpoint (no transition) |
| `(load lev0 lev1)` | Load both level slots |
| `(display lev0 mode)` | Set display mode on a level |
| `(vis nick)` | Switch vis nickname |
| `(force-vis lev onoff)` | Force vis for a level |

### The big constraint
**Load boundaries live in `load-boundary-data.gc` — a single global file, not per-level.** Any custom level that uses them must edit this file directly in GOAL. There is no per-level JSONC equivalent.

### Community usage
LuminarLight's mod base contains a working custom `static-load-boundary` entry. This is the most technically documented community example. The pattern is: copy the macro, supply your level's XZ polygon coordinates (in game units), and wire up the `fwd`/`bwd` commands.

### Best for
- Seamless streaming: player walks through an arch and the next level appears without any loading screen
- Checkpoint auto-assignment as the player moves through a multi-area world
- Exact replication of vanilla-style level flow

### Addon work required
High. To drive this from Blender we'd need to either:
- Auto-generate GOAL code from a `VOL_` empty flagged as a load-boundary, OR
- Auto-patch `load-boundary-data.gc` on build with the boundary coordinates
Neither exists yet. For now this requires manual GOAL authoring.

---

## Approach 2 — `VOL_` Trigger + Custom GOAL Actor (Practical Path)

### What it is
Use an existing `VOL_` empty (trigger volume) from Blender, but back it with a new custom GOAL actor type that executes a level transition when the player enters.

### How the transition fires
```lisp
; Inside the custom actor's overlap/collision handler:
(when (player-in-volume? self)
  (let ((cp-name (res-lump-struct (-> self entity) 'continue-name structure)))
    (when cp-name
      (initialize! *game-info* 'play #f (the-as string cp-name)))))
```

`initialize!` with `'play` cause does a full black-screen transition — same experience as dying and respawning at a new checkpoint.

### What the user does in Blender
1. Place a `VOL_` empty at the level exit
2. Set `etype` to the custom actor name (e.g. `level-transition-vol`)
3. Add a `continue-name` lump → string matching the destination continue-point name
4. That's it — no GOAL authoring required

### JSONC actor entry
```jsonc
{
  "trans": [x, y, z],
  "etype": "level-transition-vol",
  "game_task": 0,
  "quat": [0, 0, 0, 1],
  "bsphere": [x, y, z, 4.0],
  "lump": {
    "name": "exit-to-level2",
    "continue-name": "level2-start"
  }
}
```

### What needs to be built (GOAL side)
One new actor file, e.g. `levels/common/level-transition-vol.gc`:
- Extends `process-drawable` or a basic trigger base
- Has a collide shape matching the volume (or reads size from lumps)
- On player overlap: reads `continue-name` lump, calls `initialize!`
- Optional: support a `(blackout N)` lump for controlling fade frames

### Best for
- Explicit portal-style transitions with a loading screen
- Multi-level mods where each level is a discrete area
- Fits naturally into existing addon `VOL_` workflow

### Addon work required
Medium. One GOAL actor + one new UI field in the Triggers panel (a continue-name picker, possibly reusing existing lump infrastructure). The JSONC side is already supported by the lump system.

---

## Approach 3 — `launcherdoor` (Vanilla Actor, Works Today)

### What it is
A vanilla actor used for cave entrances (jungle → jungleb, maincave → darkcave/robocave, sunken → sunkenb). Reads a `continue-name` lump and triggers the level change when the player uses the launch surface.

### How to use it from Blender today
Place an `ACTOR_` empty with `etype = launcherdoor` and add a `continue-name` lump. No custom GOAL code needed — the actor already exists in the game.

```jsonc
{
  "etype": "launcherdoor",
  "lump": {
    "name": "my-door-1",
    "continue-name": "next-level-start"
  }
}
```

### Limitations
- The actor has a specific visual (a vertical sliding door) tied to cave aesthetics
- Collision shape is fixed — it's a launch surface, not a generic walk-through trigger
- Animation and sound are baked into the actor — looks out of place in non-cave contexts

### Best for
- Cave-style vertical entrances in custom levels
- Quick proof-of-concept to test level chaining before a custom actor exists

---

## Decision Matrix

| Need | Recommended approach |
|---|---|
| Seamless streaming, no load screen | `load-boundary` (manual GOAL for now) |
| Portal transition, loading screen | `VOL_` + custom actor (needs one new GOAL file) |
| Cave entrance right now | `launcherdoor` (works today via JSONC) |
| Checkpoint auto-update as player walks | `load-boundary` with `checkpt` command |
| User-friendly, no GOAL authoring | `VOL_` approach once the actor is written |

---

## Implementation Plan (when we tackle this)

### Phase 1 — Works today, no new code
- Document `launcherdoor` actor in the addon UI (actor picker, continue-name lump field)
- Users can wire up cave-style transitions from Blender

### Phase 2 — Custom transition actor
1. Write `level-transition-vol.gc` — the custom GOAL actor
2. Add it to the mod base `game.gp` build
3. Add `continue-name` lump picker to the Triggers panel in the addon
4. Test: level A → VOL_ exit → loads level B → player spawns at level B continue

### Phase 3 — Load boundary generation (longer term)
1. Add a new empty type: `LBND_` (load boundary)
2. User places a plane/polygon empty, assigns fwd/bwd level names
3. On export, addon generates the `static-load-boundary` GOAL entry
4. Build pipeline appends to or patches `load-boundary-data.gc`

---

## Key Source Files

| File | Role |
|---|---|
| `engine/level/load-boundary-h.gc` | `load-boundary` type, `load-boundary-cmd` enum, flags |
| `engine/level/load-boundary.gc` | `check-boundary`, `execute-command` — full command language |
| `engine/level/load-boundary-data.gc` | 170 vanilla static boundaries — the file to edit for custom ones |
| `engine/game/game-info.gc` | `set-continue!`, `initialize!` — the transition functions |
| `levels/common/launcherdoor.gc` | Vanilla cave entrance actor — uses `continue-name` lump |
| `levels/jungle/jungle-elevator.gc` | Bidirectional example — `continue-name` + `alt-load-commands` |

---

## Community References

- **LuminarLight mod base** — https://github.com/LuminarLight/LL-OpenGOAL-ModBase — contains working `static-load-boundary` GOAL example
- **The Forgotten Lands** — https://github.com/Kuitar5/the-forgotten-lands — multi-level mod, worth studying for transition approach used
- **Official custom levels guide** — https://opengoal.dev/docs/developing/custom_levels/your_first_level/ — covers continue points and references load boundaries
- **OpenGOAL modding Discord** — primary community support channel for custom level questions

---

## Related Knowledge Base Files

- `player-loading-and-continues.md` — full continue-point system reference
- `level-flow.md` — complete level flow system (load-state, target-continue, full respawn sequence)
- `modding-addon.md` — current addon VOL_ / trigger volume implementation
