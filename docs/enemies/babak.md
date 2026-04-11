# Babak Enemy — Developer Documentation

## Overview

Babak is a standard navigating enemy in Jak and Daxter. It patrols, detects the player, chases, and can be configured to operate a cannon (babak-with-cannon variant). Babaks appear across 9 levels making them one of the most reused enemy types in the game.

---

## Type Hierarchy

```
process-drawable
  └── nav-enemy
        └── babak
              └── babak-with-cannon
```

Inheriting from `nav-enemy` gives Babak full navigation mesh support, collision, animation control, joint/skeleton system, and the standard enemy state machine for free. You configure behaviour via `nav-enemy-info` fields rather than reimplementing it.

---

## States

### Base babak states

| State | Trigger |
|---|---|
| `nav-enemy-idle` | Default on spawn, or when player moves out of `idle-distance` |
| `nav-enemy-patrol` | After idle timeout elapses and player is within range |
| `nav-enemy-chase` | Player noticed during patrol |
| `nav-enemy-stare` | Chase transition — briefly stares before committing |
| `nav-enemy-give-up` | Player escapes detection range during chase |
| `nav-enemy-jump-land` | After completing a jump |

### babak-with-cannon additional states

| State | Trigger |
|---|---|
| `babak-run-to-cannon` | Player moves beyond `distance` threshold OR drops 40960 units below babak |
| `babak-with-cannon-jump-onto-cannon` | Babak reaches cannon spawn point |
| `babak-with-cannon-shooting` | After jumping onto cannon — loops until exit condition |
| `babak-with-cannon-jump-off-cannon` | Player returns within `distance` and is not too far below |

---

## Spawning a Babak in a Level

Babak is registered in the entity table as `"babak"` with 76 methods. Spawning is handled through the level editor entity system.

**Step by step:**

1. In your level's entity list, add an actor with type `"babak"`
2. Place it at the desired spawn position on the nav mesh
3. The engine calls `init-from-entity!` automatically, which:
   - Runs `initialize-collision`
   - Calls `process-drawable-from-entity!` to link art assets
   - Calls `nav-enemy-method-48` to initialize nav behaviour
   - Transitions to `nav-enemy-idle`

**No manual process-spawn call is needed** — the entity system handles it when the level loads.

---

## Setting Up babak-with-cannon

This variant requires linking a `mistycannon` entity via the level editor.

1. Place a `babak-with-cannon` actor in the level
2. Place a `mistycannon` actor nearby
3. In the babak-with-cannon actor's properties, set `alt-actor 0` to point to the mistycannon entity
4. Optionally set the `distance` lump float — default is `163840.0` units. This controls how far the player must be before babak retreats to the cannon.

The cannon linkage is resolved at runtime:
```
(set! (-> this cannon-ent) (entity-actor-lookup (-> this entity) 'alt-actor 0))
```

**Cannon exit conditions:**
- Player comes within `distance` units AND is not more than 40960 units below babak → babak jumps off cannon
- babak-with-cannon-shooting loops indefinitely until this condition is met

---

## Available Animations

All animations are in the `babak-ag` art group:

| Index | Name | Used in state |
|---|---|---|
| 5 | `babak-idle-ja` | nav-enemy-idle |
| 6 | `babak-walk-ja` | nav-enemy-patrol |
| 7 | `babak-spot-ja` | nav-enemy-stare |
| 8 | `babak-charge-ja` | nav-enemy-chase, run-to-cannon |
| 9 | `babak-give-up-ja` | nav-enemy-give-up |
| 10 | `babak-give-up-hop-ja` | nav-enemy-give-up variant |
| 11 | `babak-win-ja` | victory |
| 12 | `babak-death-ja` | nav-enemy-die |
| 13 | `babak-jump-ja` | jump states |
| 14 | `babak-jump-land-ja` | nav-enemy-jump-land |
| 15 | `babak-taunt-ja` | taunt |
| 16 | `babak-turn-ja` | turning |
| 17 | `babak-look-ja` | babak-with-cannon-jump-onto/off-cannon |
| 18 | `babak-stop-look-ja` | stop looking |

---

## Nav Configuration (nav-enemy-info)

These fields control Babak's movement and detection behaviour:

| Field | Type | Description |
|---|---|---|
| `idle-distance` | meters | Detection range — player within this triggers patrol |
| `run-travel-speed` | meters | Chase movement speed |
| `run-rotate-speed` | degrees | How fast babak rotates while running |
| `run-acceleration` | meters | Acceleration during chase |
| `run-turn-time` | seconds | Time to complete a turn while running |
| `walk-travel-speed` | meters | Patrol movement speed |
| `walk-rotate-speed` | degrees | Rotation speed while patrolling |
| `walk-acceleration` | meters | Acceleration during patrol |
| `walk-turn-time` | seconds | Time to complete a turn while walking |
| `neck-joint` | int32 | Joint index used for player look-at tracking |
| `player-look-at-joint` | int32 | Joint index for player awareness head tracking |

---

## Levels Using Babak (Reference Examples)

These levels already have working Babak placements to reference:

- `beach` (bea.gd)
- `citadel` (cit.gd)
- `fire-canyon` (fic.gd)
- `jungle` (jun.gd)
- `misty` (mis.gd) — includes babak-with-cannon
- `rolling-hills` (rol.gd)
- `snowy-mountain` (sno.gd)
- `sunken` (sub.gd)
- `swamp` (swa.gd)

The misty level is the primary reference for babak-with-cannon setup as it contains the only cannon configuration in Jak 1.

---

## Related Files

| File | Purpose |
|---|---|
| `goal_src/jak1/engine/common-obs/babak.gc` | Core babak type and states |
| `goal_src/jak1/levels/misty/babak-with-cannon.gc` | Cannon variant |
| `goal_src/jak1/engine/common-obs/nav-enemy-h.gc` | nav-enemy-info config structure |
| `goal_src/jak1/engine/entity/entity-table.gc` | Entity registration |
| `goal_src/jak1/engine/data/art-elts.gc` | Animation asset definitions |
