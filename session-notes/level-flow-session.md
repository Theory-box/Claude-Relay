# Level Flow — Session Notes

**Branch:** `feature/level-flow`
**Status:** Research phase — no implementation yet
**Last updated:** 2026-04-08

---

## Goal
Research and implement addon tools for everything related to level flow: spawning, continue points, checkpoints, loading zones, and level-to-level transitions. Users should be able to set all of this up from Blender without touching game code manually.

## Scope (research targets)
- Continue points — full authoring pipeline for custom levels
- Checkpoint / respawn points mid-level
- Loading zones — how the game triggers loading a new level
- Level-to-level linking — can levels be chained? how does the game handle transitions?
- Loading screen / transition handling
- Multiple continue points per level (switching via `set-continue!`)
- vis-nick, lev0/lev1, disp0/disp1 — secondary level loading (what loads alongside)
- `load-commands` pair — what can go here for custom levels

## Known so far
- See `knowledge-base/opengoal/player-loading-and-continues.md` — solid existing research
- `continue-point` type defined in `game-info-h.gc` — name, level symbol, trans, quat, camera-trans, camera-rot, lev0/lev1, etc.
- Continue points defined as static data in `level-info.gc` under `:continues`
- Addon currently hardcodes a single continue point from `SPAWN_` empties (modding-addon.md)
- Multiple continue points written correctly but switching via `set-continue!` untested
- Level index hardcoded to 27 — would conflict with multiple simultaneous custom levels

## Open questions
- How do loading zones work — is there an existing entity type or is it custom?
- Can two custom levels be linked so walking into a zone loads the next level?
- What exactly does `disp1` / `lev1` enable — is that how sub-levels (like village1 + villager) work?
- How does `vis-nick` affect what geometry is visible?
- Is there a checkpoint entity type in vanilla, or do checkpoints just call `set-continue!`?
- What triggers the loading screen / transition fade?
- Level index conflict — how to solve for multi-level mods?

## Research approach
- Study vanilla level transitions (e.g. village1 → beach, training → village1)
- Find loading zone entity types in decompiled source
- Trace `set-continue!` call sites to understand what triggers it mid-game
- Look at how `lev1`/`disp1` is used for sub-levels in existing levels

## Session log
- 2026-04-08: Branch created. Good existing knowledge base on continue points. Loading zones and level linking are the main unknowns.
