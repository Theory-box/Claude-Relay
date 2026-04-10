

# SKILL.md — Jak 1 OpenGOAL Custom Level Modding

## Overview

This skill covers everything tested and confirmed working for creating custom Jak 1 levels using OpenGOAL and the Blender addon (`opengoal_tools.py`). Sections marked **⚠ OPEN QUESTION** are known unknowns — things that need solving but haven't been confirmed yet.

---

## Environment

- **Engine**: OpenGOAL `jak-project` (cloned from `github.com/open-goal/jak-project`)
- **Blender addon**: `opengoal_tools.py` — handles GLB export, JSONC/GD/GC file writing, game.gp patching, level-info.gc patching, GOALC launch, GK launch
- **ISO**: Jak and Daxter: The Precursor Legacy (USA) dumped from physical disc
- **Blender version**: 4.4+
- **OpenGOAL version**: v0.2.29+

The addon stores two paths in preferences:
- **EXE folder**: contains `gk.exe` and `goalc.exe`
- **Data folder**: contains `data/goal_src` (e.g. `active/jak1`)

---

## Workflow

### Correct button usage
- **Export & Build**: always run this after making any changes in Blender (geometry, actor placement, anything). Exports GLB, rewrites all source files, compiles with GOALC.
- **Play**: run after a successful Export & Build. Just kills GK, relaunches it, and loads the compiled level. Does **not** recompile. If you hit Play without a prior Export & Build your changes won't appear.

### What Export & Build does
1. Exports scene to `.glb`
2. Writes `<n>.jsonc` (actor/ambient placement)
3. Writes `<nick>.gd` (DGO file list — includes enemy `.o` files)
4. Writes `<n>-obs.gc` (stub GOAL source)
5. Patches `level-info.gc` (registers level with continue points)
6. Patches `game.gp` (adds build-custom-level, custom-level-cgo, goal-src lines)
7. Runs `(mi)` in GOALC via nREPL if available, otherwise launches fresh GOALC with startup.gc

### What Play does
1. Kills any running `gk.exe`
2. If GOALC nREPL is live: launches fresh GK, waits 6 seconds, runs `(lt)` then `(bg-custom '<n>-vis)`
3. If no nREPL: writes startup.gc with `(lt)` + `(bg-custom)`, launches GOALC, then GK

### Console management
Both buttons kill existing GOALC/GK instances before launching new ones — no stacking. If GOALC's nREPL is already connected, Export & Build reuses it (faster compile, no new window).

---

## File Structure

```
active/jak1/data/
  custom_assets/jak1/levels/<n>/
    <n>.glb              ← exported mesh
    <n>.jsonc            ← actor/ambient placement + art groups
    <nick>.gd            ← DGO definition (enemy .o + art groups)
  goal_src/jak1/
    levels/<n>/
      <n>-obs.gc         ← stub GOAL source (currently empty)
    engine/level/
      level-info.gc      ← patched to register level + continue points
    game.gp              ← patched with build/compile entries
    user/blender/
      startup.gc         ← auto-generated GOALC startup commands
      user.gc            ← extern declarations for REPL functions
```

---

## Actor Placement

### Naming convention

| Prefix | Purpose |
|---|---|
| `SPAWN_start` | Player spawn (first one) |
| `SPAWN_<id>` | Additional spawns |
| `ACTOR_<etype>_<uid>` | Any spawnable entity |
| `AMBIENT_<n>` | Ambient hint/sound trigger |

### Coordinate system
Blender Y-up → game Z-up. Addon converts: game `(x, y, z)` = Blender `(x, z, -y)`.

### Entity categories
The Spawn panel has separate sub-panels per category, each with its own filtered dropdown:

- **⚔ Enemies** — 33 types (Enemies + Bosses), grouped by tpage source level e.g. `[Beach] Babak [nav]`
- **🟦 Platforms** — 13 types, separate spawn controls with sync/path settings per actor
- **📦 Props & Objects** — 18 types (Props + Objects + Debug)
- **🧍 NPCs** — 14 types (Yakow, Flut Flut, Mayor, Farmer, Fisher, Explorer, Geologist, Warrior, Gambler, Sculptor, Billy, Muse, Pelican, Seagull)
- **⭐ Pickups** — 10 types (Power Cell, Orb, Scout Fly, Crate, Orb Cache, eco vents ×4, alt cell)
- **🔊 Sound Emitters** — not entity types; ambient sound placement with bank/sound picker

Each enemy dropdown entry shows `[TpageGroup] Label [nav]` to remind about navmesh/OOM requirements. Clicking **Add Entity** spawns the type selected in whichever sub-panel you used and syncs `entity_type` for export.

### Addon Panel Layout (v1.1.0)

The N-panel tab "OpenGOAL" has this hierarchy:

| Panel | Type | Purpose |
|---|---|---|
| ⚙ Level | parent, always open | Level name, base ID, death plane |
| └ 🗺 Level Flow | sub, collapsed | Spawns, checkpoints, bsphere |
| └ 🗂 Level Manager | sub, collapsed | Discovered levels list |
| └ 💡 Light Baking | sub, collapsed | Samples + bake button |
| └ 🎵 Music | sub, collapsed | Music bank, sound banks |
| ➕ Spawn Objects | parent, collapsed | (content in sub-panels) |
| └ ⚔ Enemies | sub, collapsed | Per-category dropdown, Add Entity |
| └ 🟦 Platforms | sub, collapsed | Platform type, Add Platform |
| └ 📦 Props & Objects | sub, collapsed | Per-category dropdown, Add Entity |
| └ 🧍 NPCs | sub, collapsed | Per-category dropdown, Add Entity |
| └ ⭐ Pickups | sub, collapsed | Per-category dropdown, Add Entity |
| └ 🔊 Sound Emitters | sub, collapsed | Pick sound, Add Emitter |
| 🔍 Selected Object | standalone, poll-gated | Context-aware settings for active object |
| 〰 Waypoints | standalone, poll-gated | Waypoint list + add/delete |
| 🔗 Triggers | standalone, always visible | Volume linking, volume list |
| 📷 Camera | standalone, collapsed | Camera list, mode/blend/FOV per camera |
| ▶ Build & Play | standalone, always visible | Export, Build, Play buttons |
| 🔧 Developer Tools | standalone, collapsed | Quick open, reload addon |
| Collision | standalone, poll-gated | Per-object collision/visibility flags |

**Selected Object panel** is the primary edit hub — select any OG-managed object
and it shows all relevant settings (navmesh link/unlink, platform sync, waypoints,
camera mode/blend/FOV/look-at, volume linking, collision, light baking, navmesh
tagging). Spawn sub-panels are for *placing* new objects; Selected Object is for
*editing* placed objects.

### Bsphere radius
- Enemies and Bosses: **120 meters** — required so `draw-status was-drawn` gets set, enabling AI logic
- Everything else: **10 meters**

Without a large bsphere on enemies, `run-logic?` returns false and enemies idle forever with no AI, collision, or attack — even if their type is correctly loaded.

---

## Enemy System

### The only enemy in GAME.CGO
**Babak** — the only enemy whose compiled code lives in `GAME.CGO` and is always loaded. All others need their `.o` added to the custom DGO.

### Code dependency injection
The addon handles this automatically via `needed_code()` and `ETYPE_CODE`. For every enemy placed in the scene it:
1. Adds `<enemy>.o` to the `.gd` file (bundled into the DGO)
2. Adds `(goal-src "levels/<path>/<enemy>.gc" "<dep>")` to `game.gp` (so GOALC compiles it)

Without this, the type is undefined at runtime — engine spawns a bare `process-drawable` that animates but has zero AI, collision, or attack.

### Confirmed enemy code locations

| Enemy | Source file | Home DGO |
|---|---|---|
| babak | engine/common-obs/babak.gc | GAME.CGO ✓ |
| bonelurker | levels/misty/bonelurker.gc | MIS.DGO |
| kermit | levels/swamp/kermit.gc | SWA.DGO |
| hopper | levels/jungle/hopper.gc | JUN.DGO |
| puffer | levels/sunken/puffer.gc | SUN.DGO |
| bully | levels/sunken/bully.gc | SUN.DGO |
| yeti | levels/snow/yeti.gc | SNO.DGO |
| snow-bunny | levels/snow/snow-bunny.gc | CIT.DGO |
| swamp-bat | levels/swamp/swamp-bat.gc | SWA.DGO |
| swamp-rat | levels/swamp/swamp-rat.gc | SWA.DGO |
| gnawer | levels/maincave/gnawer.gc | MAI.DGO |
| lurkercrab | levels/beach/lurkercrab.gc | BEA.DGO |
| lurkerworm | levels/beach/lurkerworm.gc | BEA.DGO |
| lurkerpuppy | levels/beach/lurkerpuppy.gc | BEA.DGO |
| flying-lurker | levels/ogre/flying-lurker.gc | OGR.DGO |
| double-lurker | levels/sunken/double-lurker.gc | SUN.DGO |
| driller-lurker | levels/maincave/driller-lurker.gc | MAI.DGO |
| quicksandlurker | levels/misty/quicksandlurker.gc | MIS.DGO |

### Nav-safe vs nav-unsafe

**Nav-safe** (spawn without navmesh): kermit, swamp-bat, flying-lurker, puffer, bully, quicksandlurker

**Nav-unsafe** (crash without workaround): babak, hopper, bonelurker, snow-bunny, swamp-rat, gnawer, lurkercrab, lurkerworm, lurkerpuppy, yeti, double-lurker, muse

**Workaround (automatic)**: injects `nav-mesh-sphere` res-lump tag — enemy falls back to `*default-nav-mesh*` stub, doesn't crash, idles and notices Jak, but can't pathfind without a real navmesh. Per-actor radius stored as `og_nav_radius` custom property (default 6m).

### Enemy AI gating
`run-logic?` only runs AI when both:
1. `draw-status was-drawn` is set (enemy passed renderer cull check last frame)
2. Enemy is within 50m of camera (`*ACTOR-bank* pause-dist`)

### Known in-game behaviors
- **Kermit**: animates, idles, does not chase (requires `nav-enemy-test-point-in-nav-mesh?` to pass)
- **Babak**: no longer crashes with workaround applied
- **Bonelurker**: ⚠ breaks level load — avoid until resolved
- **evilplant**: decorative only, no AI, no collision — do not use for combat testing

---

## Collision

Walk-through and attack events are gated by the same `run-logic?` / `was-drawn` check as AI. Collision shapes are correctly set up by each enemy's `initialize-collision` at spawn time — the issue is always the logic gating, not the shape registration.

---

## Level Registration

`level-info.gc` is patched with a `level-load-info` block at index 27, village1 mood/sky, and continue points from `SPAWN_` empties (default spawn at origin +10m Y if none placed).

`game.gp` gets three lines per level plus one `(goal-src ...)` per non-GAME.CGO enemy. Old entries are stripped before rewriting to prevent duplicates.

---

## Art Groups

Automatically managed by the addon via `ETYPE_AG`. Added to JSONC `art_groups` and `.gd` file. No manual management needed.

---

## Open Questions

**⚠ Bonelurker crash** — breaks level load when placed. Most likely cause: `goal-src` injection for `bonelurker.gc` conflicts with the existing MIS.DGO build step in `game.gp`, causing a type redefinition at link time. May also require `battlecontroller.o` as a dependency since bonelurker is never spawned directly via entity-actor in vanilla. Check GOALC console for type redefinition errors during build.

**⚠ Navmesh** — `Entity.cpp` writes null for nav-mesh field on every actor. No engine support for custom navmesh yet. Addon collects tagged geometry via `collect_nav_mesh_geometry()` ready for when engine support lands.

**⚠ Enemy attack/interaction not confirmed in-game** — next test candidates: hopper or swamp-bat.

**⚠ Enemy walk-through not confirmed fixed** — 120m bsphere should enable `was-drawn` → touch events, not yet verified.

**⚠ NPCs** — `process-taskable` types need proper `game-task` values for dialogue/missions. With `(game-task none)` they'll likely spawn but do nothing.

**⚠ Eco pickups** — no art group, may need specific lump fields. Untested.

**⚠ Crate contents** — `og_crate_type` → `crate-type` lump written correctly but not confirmed in-game.

**⚠ Scout flies** — `buzzer-info` lump with `(game-task none)` behavior unknown.

**⚠ Sky/mood** — hardcoded to village1. Other options documented in test-zone JSONC but untested.

**⚠ Multiple continue points** — written correctly, switching via `set-continue!` untested.

**⚠ Level index** — hardcoded to 27, would conflict if multiple custom levels loaded simultaneously.

---

## Debugging

**GOALC console** — watch during Export & Build for file-not-found or type redefinition errors.

**In-game REPL:**
```lisp
(lt)                     ; connect to game
(bg-custom '<n>-vis)     ; load custom level
(bg 'village1)           ; return to village1
```

**Entity not appearing** — check art group in `.gd`, check `.o` in `.gd`, check `goal-src` in `game.gp`, rebuild.

**Enemy idle with no AI** — bsphere too small, code not loaded, or nav-unsafe without workaround.

**Level crash on load** — remove actors one at a time to isolate. Known bad actor: bonelurker.

---

## April 2026 Update — feature/lumps session

### New actor coverage: 147 types (was 73)

Major additions across all categories. See `entity-spawning.md` section 11 for full list.

### Lump system (Custom Lumps panel)

Every `ACTOR_` empty now has:
- **Custom Lumps** sub-panel — assisted key/type/value entry for any res-lump key
- **Lump Reference** sub-panel — per-etype hints showing all known lump keys, types, and descriptions
- 147 etypes fully covered in `LUMP_REFERENCE`

Custom lump rows export as JSONC lump entries and take priority over addon-hardcoded values (with a warning in the export log).

### Entity link system (Entity Links panel)

23 actor types with entity reference slots now show an **Entity Links** sub-panel. Workflow:
1. Select the source actor (e.g. `orbit-plat`)
2. Shift-select the target actor (e.g. the empty it should orbit)
3. Click **Link → target-name** button that appears

Links export as `"alt-actor": ["string", "target-name"]` — resolved at runtime via `entity-by-name`.

Required slots are marked with `*` and emit `[WARNING]` in the export log if unset.

### Actor sub-panel refactor

Selected Object panel now uses targeted sub-panels:
- **Activation** — idle-distance for all enemies/bosses
- **Trigger Behaviour** — aggro event for nav-enemies only
- **NavMesh** — navmesh patch link for nav-enemies
- **Entity Links** — alt-actor/water-actor/state-actor for 23 etypes
- **Platform Settings** — sync/path/notice-dist for platform types
- **Waypoints** — path waypoint management for path-required types
- **Custom Lumps** — assisted lump entry for all actors
- **Lump Reference** — per-etype documentation

### Data structure overview

| Structure | Purpose | Count |
|---|---|---|
| `ENTITY_DEFS` | Picker metadata (label, cat, ag, color, shape) | 147 etypes |
| `ETYPE_CODE` | .o file injection into custom DGO | 138 entries + 16 in_game_cgo |
| `ETYPE_TPAGES` | Tpage group per etype for art loading | 124 entries |
| `LUMP_REFERENCE` | UI hint table (key, type, description) | 148 entries |
| `ACTOR_LINK_DEFS` | Entity link slot definitions | 23 etypes, 26 slots |
| `ENTITY_WIKI` | Wiki images and descriptions | 33 entries |

