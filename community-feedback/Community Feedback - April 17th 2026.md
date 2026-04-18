# Community Feedback — April 17th, 2026

---

## Table of Contents
- [Macros \& Level Info](#macros--level-info)
- [Platforms](#platforms)
- [Pickups / Collectables](#pickups--collectables)
- [Bugs \& Misc](#bugs--misc)

---

## Macros & Level Info

Hat Kid [GOAL] suggests adding macros for level-info to keep code shorter and easier to generate from the plugin — for example, continue point macros like those used in TFL. A `define-level` macro with sensible defaults where you only need to specify what differs would be ideal.

barg [GOAL] shared a commonly used macro for meters-based vectors:

```lisp
(defmacro static-vector-meters (x y z)
  `(new 'static 'vector :x (meters ,x) :y (meters ,y) :z (meters ,z) :w 1.0))
```

---

## Platforms

### General Platform Feedback
- Most platform crashes are caused by code not being included in the level. Much of that code lives in a specific level's `-obs.gc` file; some platforms have their own code file.
- For platforms with their own code file: add it to the level's `.gd`.
- For platforms with code in another level's `-obs.gc`: copy only the required code blocks rather than importing the whole file — cleaner, and allows custom res-lump additions.
- Consider renaming **Waypoints** to **Path** and adding a button to connect to an existing path using the `path-k` lump.
- Add a *select without centering view* button next to waypoints.
- Consider adding cameras as children of platforms, similar to checkpoints.

---

### Button Platform
- Disappears when button is pressed by default. Consider auto-adding two waypoints so it works out of the box.
- With two or more waypoints added, works correctly — moves from 1st to last waypoint through all intermediate points.
- No default length/speed; stuck at default duration unless code is edited.
  - Useful res-lump to expose: `bidirectional` (int, `0`/`1`) — allows the platform to return when it reaches the endpoint.

---

### Cave Flame Pots
- **Compiler crash:** `No rule to make out/jak1/obj/caveflamepots-ag.go` — no art group exists; visuals are all particles defined in code.
- Probably should not be in Platforms — it is an obstacle (damages the player, not something to stand on). Consider Enemies, Props/Objects, or a new Obstacles section.

---

### Cave Spatula Plat / 2
- **Compiler crash:** `No rule to make out/jak1/obj/cavespatula-ag.go` — the actual art group names are:
  - `cavespatula-darkcave-ag.go` (single)
  - `cavespatulatwo-ag.go` (double)

---

### Dark Eco Barrel
- **Crashes the game.**
- Same as flame pots — probably should not be in Platforms.

---

### Eco Platform
- Activates by default — consider making it inactive by default, since as-is it is functionally identical to a plain platform. Setting eco notice distance to `~2m` restores expected behaviour.
- A way to keep the platform active after death exists but needs investigation.

---

### Flip Platform
- Works fine out of the box.
- Useful res-lumps to expose:
  - `delay` (float) — seconds the platform stays upright
  - `sync-percent` (float, `0.0`–`1.0`) — phase offset to desync multiple flip platforms

---

### Floating Platform
- Works fine.

---

### Launcher
- Works fine out of the box.
- **Fly time** does not appear to be working — it should control how long the player is locked into the trajectory before being free to move.
- Pressing X on the destination does not delete the destination empty (may or may not be intended).
- Suggestion: display the destination empty as a single arrow scaled to the jump height for easy in-level visualisation.

---

### Lava Balloon
- Works fine (implemented by loading `lavatube-obs.gc` in the level's `.gd`).
- The warning may not be necessary since it works without it.
- Probably should not be in Platforms.

---

### Ogre Bridge
- Works fine (same approach as Lava Balloon).
- Not yet investigated for additional settings potential.

---

### Ogre Drawbridge
- **Blender error on export:** `cannot access local variable '_actor_get_link' where it is not associated with a value`

---

### Orbit Platform
- No obvious way to link the alt-actor for the center entity. If a specific actor type is required, it should be documented and a button added to spawn it directly.
- **Export error:** `cannot access local variable '_actor_get_link' where it is not associated with a value`

---

### Platforms Currently Crashing the Game
- Balance Platform
- Bone Bridge
- Breakaway Plat L / M / R
- Cave Elevator
- Dark Eco Barrel
- Cave Trap Door
- Tar Platform

---

### Platforms Not Yet Tested
- Pontoon Training / Village2
- Rope Bridge
- Side-to-Side Plat
- Square Platform
- Warp Gate
- Wedge Platform

---

### Pontoon Training / Village2
- **Compiler crash:** `No rule to make out/jak1/obj/tra-pontoon-ag.go` — correct art groups:
  - `pontoonfive-ag.go`
  - `pontoonten-ag.go`
  - `allpontoons-ag.go`
- Will also need to be linked to a water volume/actor.

---

### Rope Bridge
- Collision loads but visuals do not. There are 6 different bridge art groups depending on the bridge — best to read the `art-name` res-lump setting and include only the relevant AG.
- See `init-from-entity` in `ropebridge.gc` for the full `art-name` res-lump list.

---

### Rotating Platform
- Consider spawning the recycle actor instead — it is the zoomer visual mesh.

---

### Side-to-Side Plat
- Works fine when `sunken-obs` is loaded.

---

### Square Platform
- Linking mechanism unclear — water volume added but linking option not found.
- Loads fine in game otherwise.
- Can be linked to a button or other platforms to move up and down.

---

### Teeter Totter
- Works fine, has its own file.
- No exposed settings currently — at minimum a jump height parameter would be useful.

---

### Wall Platform
- Visual model loads.
- Missing sync parameters (same as floating platforms) for in/out of wall timing.
- No collision unless manually added.

---

### Warp Gate
- Probably should not be in Platforms.
- The original warp gate is not modular — a custom, more modular version is worth building (see Zed's *Jak the Chicken* for reference).
- Does nothing currently without a linked button.

---

### Wedge Platform
- Loads fine.
- Needs `wedge-plat-master` for the rotation center and a way to link it.
- Missing `wedge-plat-outer` for the outer ring.
- Res-lumps to expose:
  - `rotspeed` (float) — master
  - `rotoffset` (float) — both plats
  - `distance` (float) — both plats

---

## Pickups / Collectables

### General Pickups Feedback
- Almost every collectable supports the `eco-info` res-lump to control what is given/spawned on break — at minimum this should be in the lump documentation.
- `collectables.o` does not need to be in a level's `.gd` — it is loaded via `game.gd`.
- Vents could be unified like crates: one list entry, then a selector for eco type. The same approach could work for eco blobs.

---

### Blue Eco
- Listed as *Blue Eco Vent* — should be renamed.
- Works fine.
- Suggestion: quantity setting (grants more than 1 eco meter unit without spawning extra blobs).

---

### Blue Eco Vent
- **Compiler crash:** `No rule to make out/jak1/obj/vent-ag.go` — no art group; the vent is geometry and the particle blocker is in common.
- The blocker triggers when its object is destroyed, not through a task.
- Needs a parameter to activate only when a specific task is complete (see fire canyon vents for reference).

---

### Blue Eco Vent (alt)
- Purpose unclear — if this is just a pre-blocked variant, it should be a parameter on the normal Blue Eco Vent rather than a separate entry.

---

### Crate
- Works fine.
- Suggested defaults per crate type:

| Type | Default Content |
|------|----------------|
| Steel | 1 orb |
| Wood | Empty (gives random eco-pill amounts based on *you suck* value) |
| Iron | Scout Fly |
| Dark Eco | Empty |
| Barrel | Empty (same behaviour as Wood) |
| Bucket | Empty |

- Missing eco-pill content type (small health), which also accepts a numeric quantity.
- Orb count description of `1–5` is misleading — base game includes crates with 10 orbs (e.g. fire canyon).
- Suggestion: button to auto-align a crate to the ground beneath it.
- Scout Flies require special handling: the `amount` field identifies which of the 7 flies for a specific task it is. Multiple scout flies currently can't all be collected to spawn the cell. Required setup:
  - `game-task` res-lump
  - `movie-pos` to place the cell when the final fly is collected
- `crate-ag.go` does not need to be loaded in the level's `.gd`.

---

### Eco Pill (Health)
- **Compiler crash:** `No rule to make out/jak1/obj/eco-pill-ag.go` — no art group needed; purely particle-based.
- Suggestion: quantity setting (grants more than 1 eco-pill unit without spawning extras).

---

### Green Eco
- Listed as *Green Eco Vent* — should be renamed.
- Does not work — type is wrong, should be `health`.
- Suggestion: quantity setting.

---

### Orb (Precursor)
- Works fine.
- Suggestion: button to float selected orbs at a consistent height above the ground (`1`–`2` metres default), with multi-selection support so all orbs can be adjusted at once.
- Feature idea — distribute orbs along a curve:
  1. Spawn the desired orbs
  2. Create a curve
  3. Select orbs + curve and use a link option
  4. Orbs spread evenly along the curve and follow edits to it
  5. Optional height offset so the curve can be drawn on the ground

---

### Orb Cache
- Works fine.
- Default of 20 orbs may be high but is easy to change.
- `active-distance` and `inactive-distance` would be useful settings — currently hard-coded and require a code edit to expose.

---

### Power Cell
- Requires an associated `game-task` or the cell does nothing.
- *Skip jump animation* only prevents one specific animation, not the full collect animation.
- Consider a way to place the `mov-pos` (where the collect animation plays from), similar to scout flies.
- The fuel-cell art group does not need to be loaded — it is in `common/game`.

---

### Power Cell (alt)
- Appears to be specific to the final boss door visual (cells flying out of Jak to the door). Probably should not be in Collectables.

---

### Red Eco
- Listed as *Red Eco Vent* — should be renamed.
- Works fine.
- Suggestion: quantity setting.

---

### Red Eco Vent
- Same issues as Blue Eco Vent.

---

### Scout Fly
- Does not spawn.
- Requires all setup described in the [Crate](#crate) section (`game-task` lump, `movie-pos`, correct `amount` index, etc.).
- **Note from barg:** scout flies can also use a `movie-pos` res-lump for the cell destination / animation origin when it is the 7th fly. Without this, the cell spawns at the fly/crate location.

---

### Yellow Eco
- Listed as *Yellow Eco Vent* — should be renamed.
- Works fine.
- Suggestion: quantity setting.

---

### Yellow Eco Vent
- Same issues as Blue Eco Vent.

---

### Eco Vent (Rock)
- Works fine.
- Probably should not be in Collectables — it is a breakable rock, not a collectable.
- How the cell spawn from these works is unclear; may be tightly coupled to the Beach cell.

---

### Missing Collectables
- Green Eco Vent
- `pickup-spawner` — can spawn nearly anything and can be triggered by other actor code rather than spawning automatically. Very useful to add.

---

## Bugs & Misc

- **Collection visibility export bug:** Making the collection containing the level un-selectable causes it to disappear on export. Suspected cause: the addon performs a selection-only export pass and marking the collection un-selectable breaks it. Needs investigation.
