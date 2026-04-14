

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
4. Writes `<n>-obs.gc` (GOAL source — contains addon-generated types + any custom GOAL code blocks)
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
      <n>-obs.gc         ← GOAL source: addon types + injected custom GOAL code blocks
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

### Actor rotation
As of v1.9.0, actor rotation is correctly exported. Rotate an `ACTOR_` empty in Blender and it will spawn facing that direction in-game. No changes to existing actors needed — rotation is read live from `matrix_world` at export time; unrotated empties produce identity quaternion `[0,0,0,1]` as before.

The remap formula used (same as spawn points, confirmed via nREPL):
```
game_rot = R @ bl_rot @ R^T      # R maps Blender(x,y,z) → game(x,z,-y)
quat = conjugate(game_rot)        # engine reads quats as conjugate (negate xyz)
```

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


---

## April 2026 Update — v1.7.0 (Doors, Water, Audit, Texturing)

### Addon version history

| Version | Key additions |
|---|---|
| v1.0.0 | Initial release — entity spawn, export, build, play |
| v1.1.0 | UI restructure — per-category sub-panels, Selected Object hub |
| v1.2.0 | Enemies — idle distance, aggro triggers, multi-link volumes |
| v1.3.0 | Lump system, entity links, 147 actor types |
| v1.4.0 | Limit search, quick search dropdown, tpage filter |
| v1.5.0 | Water volumes (water-vol) — working after vol-h.gc patch |
| v1.6.0 | Collections as levels — multi-level .blend, sub-collection export control |
| v1.7.0 | Door system — eco-door, basebutton, launcherdoor, sun-iris-door |
| v1.8.0 | Level Audit panel, Texturing panel |
| v1.9.0 | Texture apply to faces (Edit Mode), actor rotation export |

### Panel layout (v1.8.0)

| Panel | Type | Purpose |
|---|---|---|
| ⚙ Level | parent | Level selector, name, ID, death plane |
| └ 🗺 Level Flow | sub, collapsed | Spawns, checkpoints, bsphere |
| └ 🗂 Level Manager | sub, collapsed | Discovered levels list |
| └ 📂 Collections | sub, collapsed | Sub-collection no-export control |
| └ 💡 Light Baking | sub, collapsed | Vertex color baking |
| └ 🎵 Music | sub, collapsed | Music bank, sound banks |
| └ 🔍 Level Audit | sub, collapsed | Scene health checker (see below) |
| ➕ Spawn Objects | parent, collapsed | Entity placement |
| └ Quick Search | sub | Name search + tpage filter |
| └ ⚔ Enemies / 🟦 Platforms / 📦 Props / 🧍 NPCs / ⭐ Pickups / 🔊 Sound / 💧 Water / ⚙ Custom Types | subs | Per-category spawners + custom GOAL type spawner |
| 🔍 Selected Object | standalone, poll-gated | Context-aware settings hub |
| └ GOAL Code | sub, DEFAULT_CLOSED, polls ACTOR_ | Attach + inject custom GOAL code blocks |
| 〰 Waypoints | standalone, poll-gated | Path waypoints |
| 🔗 Triggers | standalone | Volume linking |
| 📷 Camera | standalone, collapsed | Camera list + settings |
| ▶ Build & Play | standalone | Export, Build, Play |
| 🔧 Developer Tools | standalone, collapsed | Quick open, reload |
| Collision | standalone, poll-gated | Per-object collision flags |
| 🎨 Texturing | standalone, polls mesh | Texture browser + apply (see below) |

### Door system (v1.7.0)

Six door-related actor types:

| etype | Description | Notes |
|---|---|---|
| `eco-door` | Abstract iris door base | Use jng-iris-door or subclass in practice |
| `jng-iris-door` | Jungle iris door | Standard locked/unlocked door |
| `sidedoor` | Jungle side door | Opens sideways |
| `rounddoor` | Misty round door | No actor links — auto-close |
| `sun-iris-door` | Sunken iris door | Opens by proximity or trigger event |
| `launcherdoor` | Launcher door | Links to a checkpoint via continue-name |
| `basebutton` | Wall button | Controls eco-door via state-actor link |

**Key wiring:** eco-door/jng-iris-door/sidedoor use a `state-actor` link pointing to a `basebutton`. The door polls the button's `perm-complete` flag each frame. When the button is pressed, `perm-complete` is set, door reads it and unlocks. No event needed from the button side.

**Flags lump:** auto-generated by the addon. `ecdf00` bit is auto-set when a `state-actor` link exists (door locked until button pressed). `auto-close` and `one-way` are UI toggles.

**launcherdoor** needs an `og_continue_name` property pointing to a `CHECKPOINT_` empty name.

### Water volumes (v1.5.0, engine patch required)

`water-vol` requires:
1. `vol-h.gc` patch (see `known-bugs.md`) — without this vol-count stays 0 and water never activates
2. The addon auto-patches `vol-h.gc` on every export+build (idempotent)
3. Place `ACTOR_water-vol` empty, scale to cover water area (scale = half-extent in meters)
4. Set surface Y, wade, swim depths in Selected Object panel

Water visual (`water-anim`) is NOT yet in the addon — needs a separate implementation session.

### Level Audit panel

Under Level → 🔍 Level Audit (DEFAULT_CLOSED). Press **Run Audit** to check the scene.

Checks:
- Tpage budget (>2 non-global groups = WARNING, =2 = INFO)
- Nav-enemy missing navmesh link (ERROR)
- Actor missing required path waypoints (ERROR)
- Required actor link slots unset (WARNING)
- Broken actor/volume link targets (ERROR)
- Missing or multiple SPAWN_ points (ERROR / WARNING)
- Duplicate ACTOR_ names (ERROR)
- Camera volume link targeting wrong object type (WARNING)
- Door system rules — lonely basebutton, launcherdoor missing checkpoint, etc.
- Custom checks declared in ENTITY_DEFS `"audit"` blocks (future-proof hook)
- Scene summary: actor counts, tpage group breakdown (INFO)

Results are severity-sorted (ERROR → WARNING → INFO). Each result with an offending object has a **select button** that jumps to it in the viewport.

**Audit contract:** Any session adding a new actor type must populate an `"audit"` block in its `ENTITY_DEFS` entry. Any new structural dependency must register a rule. See `CONTRIBUTING.md`.

### Texturing panel (v1.9.0)

🎨 Texturing panel appears when a mesh object is selected (Object Mode) or active (Edit Mode).

**Requirements:** Decompiler must have been run with `save_texture_pngs: true` in `jak1_config.jsonc`. All 4,002 textures from the diagnostic output are supported.

**Texture path:** `<data_path>/data/decompiler_out/jak1/textures/<tpage_name>/<tex_name>.png`

**Usage:**
1. Select a mesh
2. Pick a tpage group (Beach, Jungle, Village, etc.)
3. Press **Load** — fills a 4-column scrollable icon grid
4. Use the search bar to filter by name (live, no reload)
5. Click a texture to select it (20 per page, prev/next pagination)
6. Press **Apply to Selected** / **Apply to Selected Faces**

**Object Mode behaviour:** Creates a Principled BSDF material named `og_<tex_name>`, assigns it to slot 0 of all selected meshes (replaces existing).

**Edit Mode behaviour (v1.9.0):** Assigns material to selected faces only. Materials stack up as additional slots on the object — one slot per unique texture applied. The same material is reused if it already exists on that object. Button label changes to "Apply to Selected Faces" as a mode hint.

Materials are named `og_<texture_name>` and reused across the session if already created.

If textures aren’t found, the panel shows a warning with extraction instructions.

### Object naming conventions (complete)

| Prefix | Type | Purpose |
|---|---|---|
| `ACTOR_<etype>_<uid>` | EMPTY | Any spawnable entity |
| `ACTOR_<etype>_<uid>_wp_<n>` | EMPTY | Path waypoint for that actor |
| `ACTOR_<etype>_<uid>_wpb_<n>` | EMPTY | B-path waypoint (swamp-bat) |
| `SPAWN_<id>` | EMPTY | Player spawn point |
| `CHECKPOINT_<id>` | EMPTY | Checkpoint / continue point |
| `CHECKPOINT_<id>_CAM` | CAMERA | Camera anchor at checkpoint |
| `CAMERA_<id>` | CAMERA | Camera position for trigger |
| `VOL_<id>` | MESH | Trigger volume |
| `AMBIENT_<id>` | EMPTY | Ambient sound emitter |
| `NAVMESH_<id>` | MESH | Navmesh geometry for nav-enemy |
| `WATER_<id>` | MESH | Water volume mesh (for vol planes) |
| `VISMESH_<id>` | MESH | Vis-blocker mesh (feature/vis-blocker, not yet on main) |
| `COLL_*` | MESH | Collision geometry |

### Resolved open questions (previously marked ⚠)

- **vol-control / water volumes** — fixed via vol-h.gc patch (auto-applied by addon)
- **Navmesh** — working via `NAVMESH_` mesh objects and entity.gc codegen
- **Platform sync/path** — fully supported with waypoints and sync lump
- **Multiple continue points** — working, managed via Level Flow sub-panel
- **Crate contents** — `og_crate_type` → `crate-type` lump confirmed working
- **Entity links (alt-actor, state-actor, water-actor)** — working for 23+ etypes
- **Doors** — eco-door family + basebutton confirmed working in-game (v1.7.0)

### GOAL Code panel (feature/goal-code)

Allows attaching arbitrary GOAL source code to any `ACTOR_` empty. The code is appended verbatim to `<n>-obs.gc` on every export, compiled with the level as part of the normal build.

**Where it appears:** Selected Object panel → **GOAL Code** sub-panel (DEFAULT_CLOSED). Polls any `ACTOR_` empty that is not a waypoint.

**Workflow:**
1. Select an `ACTOR_` empty
2. GOAL Code sub-panel → **Create boilerplate block** — creates a Blender text block pre-filled with `deftype` / `defstate` / `init-from-entity!` boilerplate matching the actor's etype
3. Open Text Editor area (Shift+F11) → click **Open in Editor** to switch it to the new block
4. Write or replace the code
5. Export+Build — build log shows `[write_gc] injected N custom GOAL code block(s): <name>`
6. Code compiles with the level; entity types become available in-game

**Key properties:**
- `text_block` — pointer to a `bpy.types.Text` (Blender text block)
- `enabled` — toggle to include/exclude from export without deleting the block
- Shared blocks: multiple actors can reference the same text block — it is emitted only once (deduplicated by name)
- Panel shows line count, enabled/disabled status, and a shared-block warning listing other actors using the same text

**What obs.gc currently contains (always):**
- `camera-marker` deftype (inert camera position holder)
- `camera-trigger` deftype — only if trigger volumes exist
- `checkpoint-trigger` deftype — only if checkpoints exist
- `aggro-trigger` deftype — only if nav-enemy aggro trigger volumes exist
- All enabled custom GOAL code blocks, in order, after the above

**Compile errors** appear in the goalc build log (not in Blender). Common causes: mismatched `:offset-assert` values, missing `(none)` return, `(loop ...)` without `(suspend)`.

**Reference:** `knowledge-base/opengoal/goal-scripting.md` — full language reference, unit system, entity patterns, 5 complete working examples.

---

### Custom Type spawner (feature/goal-code)

Enables placing `ACTOR_` empties for user-defined GOAL types that are not in the addon's built-in entity list.

**Where it appears:** Spawn panel → **⚙ Custom Types** sub-panel (DEFAULT_CLOSED).

**Workflow:**
1. Enter a type name (e.g. `spin-prop`) — must be lowercase + hyphens, not already a built-in
2. Click **Spawn ACTOR_<typename>_N** — places a yellow-green SPHERE empty at the 3D cursor
3. Select the empty → GOAL Code panel → Create/assign a code block
4. In the code block, define `deftype <typename>`, states, and `init-from-entity!`
5. Export+Build — the type definition and the entity actor both go into the level

**How collect_actors handles custom types:** Any `ACTOR_<etype>_<uid>` empty with an etype not in `ENTITY_DEFS` falls through all etype-specific guards in `collect_actors`. It gets a minimal lump dict (`name`, `trans`, `quat`, `bsphere`) and is exported to the JSONC like any other actor. No special DGO wiring needed — `obs.gc` is always compiled into the level DGO.

**Additional lumps:** Use the **Custom Lumps** panel (Selected Object → Lumps) to add any lumps your deftype reads via `res-lump-float` / `res-lump-struct` etc.

**Scene inventory:** The sub-panel lists all custom-type actors in the scene with a ✓/✗ showing whether each has an enabled code block assigned.

**Naming rule:** Type name must match the `deftype` name exactly (`ACTOR_spin-prop_0` → `(deftype spin-prop ...)`).

---

### Still open

- **water-anim** — visual water surface not yet in addon (needs look picker + dense mesh)
- **Bonelurker crash** — type redefinition at link time, still under investigation
- **NPCs with game-task** — dialogue/mission behavior with `(game-task none)` unconfirmed
- **Sky/mood** — hardcoded to village1; other moods documented but untested
- **VISMESH_ vis-blocker** — built on feature/vis-blocker, not yet merged to main
