# Level Flow — Session Notes

**Branch:** `feature/level-flow`
**Status:** Research complete — level trigger approaches mapped out. No implementation yet.
**Last updated:** 2026-04-10

---

## Goal
Research and implement addon tools for everything related to level flow: spawning, continue points, checkpoints, loading zones, and level-to-level transitions. Users should be able to set all of this up from Blender without touching game code manually.

## Current Understanding — "Next Level" Triggers

### Three approaches exist (confirmed from source + community)

#### 1. `load-boundary` (static polygonal trigger, most powerful)
- Defined globally in `load-boundary-data.gc` — NOT per-level
- Polygon of XZ points + Y top/bot extents
- Fires on player or camera crossing
- Commands: `checkpt`, `load`, `display`, `vis`, `force-vis`
- **Con:** Must edit `load-boundary-data.gc` globally — not per-level JSONC
- **Community use:** LuminarLight's mod base shows working example of custom `static-load-boundary`
- **Best for:** Seamless streaming between adjacent levels (the "walk through an arch" transition)

#### 2. `VOL_` trigger volume (actor-based, already in our addon)
- A `VOL_` empty in Blender = trigger volume actor in JSONC
- Custom GOAL code on a trigger volume can call `set-continue!` and `want-levels`
- **Pro:** Works per-level, no global file edits
- **Con:** Requires writing a custom GOAL actor that responds to player overlap
- **Best for:** "Enter this zone → load next level" without black screen

#### 3. `launcherdoor` / custom actor with `continue-name` lump
- Actor reads `continue-name` lump string → calls `set-continue!` + `load-commands-set!`
- This is the vanilla pattern for cave entrances (jungle/sunken/maincave)
- **Pro:** Per-level, works via JSONC lump
- **Con:** `launcherdoor` is a vertical elevator door — need a custom actor for generic use
- **Best for:** Explicit "door you walk through" transitions with visual feedback

### The simplest working approach for "next level" trigger today
Place a `VOL_` volume at the level exit, write a small custom GOAL actor that:
```lisp
(when (player-in-volume? self)
  (set-continue! *game-info* "next-level-start")
  (initialize! *game-info* 'play #f "next-level-start"))
```
This gives a full screen transition (blackout + load) when the player enters the zone.

### What `load-boundary` adds
- Seamless streaming (no blackout, levels fade in/out as you walk)
- Checkpoint auto-assignment as player moves through the world
- Community has done this (LuminarLight's mod base has a working example)

---

## Open questions (remaining)
- Can `load-boundary-data.gc` be split into a per-mod file, or must it always be global?
- Is there a way to attach load boundaries to a level JSONC without editing the global file?
- What mods have shipped with working level-to-level transitions? ("Forgotten Lands" is a candidate)

## Community resources found
- LuminarLight mod base: https://github.com/LuminarLight/LL-OpenGOAL-ModBase — has `static-load-boundary` example
- Official custom levels guide: https://opengoal.dev/docs/developing/custom_levels/your_first_level/
- "The Forgotten Lands" mod: multiple custom levels, may have transitions — worth studying

## Known so far
- See `knowledge-base/opengoal/player-loading-and-continues.md` — solid existing research
- See `knowledge-base/opengoal/level-flow.md` — very complete reference
- Addon currently hardcodes a single continue point from `SPAWN_` empties (modding-addon.md)
- Multiple continue points written correctly but switching via `set-continue!` untested
- Level index hardcoded to 27 — would conflict with multiple simultaneous custom levels

## Session log
- 2026-04-08: Branch created. Good existing knowledge base on continue points. Loading zones and level linking are the main unknowns.
- 2026-04-10: Community research done. Three trigger approaches mapped. load-boundary confirmed as the "seamless" path; VOL_ actor approach confirmed as the practical "next level" path for addon users. LuminarLight mod base has a working load-boundary example.
