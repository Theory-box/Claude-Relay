# Collections as Levels — Session Progress

## Status: Design finalized. Ready for implementation.

## Active Branch: `feature/collections`
## Addon file: `addons/opengoal_tools.py`

---

## Goal

Each Blender collection becomes a self-contained level with its own settings (name, base ID, death plane, etc.). Spawning objects auto-organizes into sub-collections by category. Multiple levels can coexist in a single `.blend`. The active level selection drives all addon behavior.

---

## Current Architecture (what we're changing)

### How it works today (v1.1.0)
- **One level per scene.** `OGProperties` lives on `ctx.scene.og_props` — level name, base_id, death plane, music banks, etc.
- **Actors found by name prefix.** `_canonical_actor_objects(scene)` scans `scene.objects` for `ACTOR_*` empties. Same for `SPAWN_*`, `CHECKPOINT_*`, `AMBIENT_*`, `CAMERA_*`, `CAMVOL_*`, `VOL_*`.
- **GLB export: entire scene.** `export_glb()` calls `bpy.ops.export_scene.gltf(use_selection=False)` — exports everything visible.
- **No collection awareness.** Objects float in the scene root or arbitrary user collections. The addon never reads or writes collection membership.

### Key functions that must be scoped to collection
1. `_canonical_actor_objects(scene)` — actor ordering + AID assignment
2. `collect_actors(scene)` — builds JSONC actor list
3. `collect_ambients(scene)` — builds JSONC ambient list
4. `collect_spawns(scene)` — builds continue-point data
5. `collect_cameras(scene)` — camera actors + trigger volumes
6. `collect_nav_mesh_geometry(scene, level_name)` — navmesh triangles
7. `_collect_navmesh_actors(scene)` — navmesh-linked actors for entity.gc patch
8. `export_glb(ctx, name)` — exports entire scene as GLB
9. Various panel draws that count SPAWN_, CHECKPOINT_, ACTOR_ etc. objects

### Key properties on OGProperties (currently scene-level, moving to collection)
- `level_name`, `base_id`, `bottom_height`, `vis_nick_override`
- `sound_bank_1`, `sound_bank_2`, `music_bank`

### Properties staying on OGProperties (UI state, not level-specific)
- All UI collapse bools (`show_spawn_list`, etc.)
- Entity type pickers (per-category) — these are UI state, not level data

---

## Finalized Workflow Design

### Fresh scene — no levels exist

User opens a new `.blend`, goes to the OpenGOAL N-panel.

- **Level panel**: shows only an "Add Level" button. No settings fields.
- **Level Manager sub-panel**: also shows "Add Level" button with a note that no levels exist.

Clicking "Add Level" from either place opens a popup: set a name (and base ID). This creates a top-level collection named after the level, sets it as active, and the full Level panel appears with all settings.

### Level Manager — the hub for multi-level work

The existing Level Manager sub-panel is repurposed. Instead of showing custom levels on disk, it shows all level collections in the current `.blend` file.

- Each entry is clickable — clicking one makes that level active
- The active level drives everything: panel settings, spawn targets, export scope
- "Add Level" button always available here too
- Future: delete/duplicate level operations

### Active level drives all addon behavior

If `cave-test` is the active level:
- Level panel shows `cave-test`'s settings (death plane, music, etc.)
- Spawning an enemy → object goes into `cave-test > Spawnables > Enemies`
- Spawning a platform → `cave-test > Spawnables > Platforms`
- Adding a trigger volume → `cave-test > Triggers`
- Export & Build scopes to only `cave-test`'s geometry and entities

---

## Collection Hierarchy

```
📁 Scene Collection
  📁 my-level                    ← Level collection (og_is_level=True)
    📁 Geometry
      📁 Terrain                 ← Standard meshes (visible + collision) — DEFAULT
      📁 Collision Only          ← Invisible walls, kill planes (og_invisible)
      📁 Visual Only             ← Decorations, no collision (og_ignore)
      📁 Reference               ← Not exported (og_no_export) — vanilla imports, blockouts
    📁 Spawnables
      📁 Enemies                 ← ACTOR_ empties where cat ∈ {Enemies, Bosses}
      📁 Platforms               ← ACTOR_ empties where cat = Platforms
      📁 Props & Objects         ← ACTOR_ empties where cat ∈ {Props, Objects, Debug}
      📁 NPCs                   ← ACTOR_ empties where cat = NPCs
      📁 Pickups                ← ACTOR_ empties where cat = Pickups
    📁 Triggers                  ← CAMVOL_ / VOL_ trigger volumes
    📁 Cameras                   ← CAMERA_ empties + camera anchors
    📁 Spawns                    ← SPAWN_ / CHECKPOINT_ empties (+ _CAM anchors)
    📁 Sound Emitters            ← AMBIENT_snd* empties
  📁 cave-test                   ← Another level collection
    📁 Geometry
      ...
```

### Sub-collection rules
- Created **on demand** — first spawn of an enemy creates `Spawnables > Enemies`
- Fresh level starts as just the empty level collection
- Geometry sub-collections: auto-sort on creation only, manual after that
- "Reference" geometry is excluded from GLB export entirely

### Geometry sorting logic
| Mesh characteristics | Sub-collection |
|---|---|
| Normal mesh (visible + collision) | Terrain |
| All faces invisible flag | Collision Only |
| All faces ignore flag | Visual Only |
| User manually marks no-export | Reference |
| Invisible + ignore (nonsensical) | Stays in Terrain, show warning |

---

## Settings Storage

**Custom properties on the Collection object:**
- `og_is_level` (bool) — marks this as a level collection
- `og_level_name` (string) — level name
- `og_base_id` (int) — starting actor ID
- `og_bottom_height` (float) — death plane
- `og_vis_nick_override` (string)
- `og_sound_bank_1`, `og_sound_bank_2`, `og_music_bank` (string)

Why custom props instead of PropertyGroup? Blender doesn't support `PointerProperty` on `bpy.types.Collection` for addon-registered groups. Custom properties survive save/load natively.

### Active Level Selection
- `active_level` EnumProperty on OGProperties — dynamically populated from collections where `og_is_level=True`
- Switching `active_level` = switching which collection the addon reads/writes
- Panels use a helper `_active_level_col(scene)` that returns the Collection object

---

## Backward Compatibility

**Critical**: existing `.blend` files with no level collections must still work.

- If no collection has `og_is_level=True`, addon behaves exactly as v1.1.0
- Reads from `scene.og_props`, scans `scene.objects`, exports everything
- Zero breakage for existing users

Migration: "Convert to Collection Level" operator moves existing objects into the new structure.

---

## Implementation Plan

### Phase 1 — Foundation (~200 lines)
- [ ] Collection helpers: `_active_level_col(scene)`, `_level_objects(scene)`, `_recursive_col_objects(col)`
- [ ] `_ensure_sub_collection(parent_col, *path)` — finds or creates nested sub-collections
- [ ] `OG_OT_CreateLevel` operator — popup with name field, creates level collection, sets active
- [ ] `active_level` EnumProperty on OGProperties (dynamic items callback)
- [ ] Level panel: "Add Level" button when no levels exist, full settings when active level exists
- [ ] Level panel: reads/writes collection custom props instead of scene props in collection mode
- [ ] Level Manager sub-panel: repurposed to list level collections, click-to-activate

### Phase 2 — Export Scoping (~150 lines)
- [ ] Refactor `_canonical_actor_objects` → accepts optional objects list
- [ ] Refactor `collect_actors`, `collect_ambients`, `collect_spawns`, `collect_cameras` → accept objects list
- [ ] Refactor `export_glb` → selection-based export scoped to Geometry sub-collection (excludes Reference)
- [ ] `_bg_build` reads from active level collection
- [ ] Fallback: no level collections → existing behavior

### Phase 3 — Auto-Organization (~150 lines)
- [ ] All spawn operators auto-link to correct sub-collection path
- [ ] Mapping: entity category → sub-collection path (e.g. Enemies → Spawnables/Enemies)
- [ ] Spawn/checkpoint operators → Spawns sub-collection
- [ ] Camera operators → Cameras sub-collection
- [ ] Sound emitter operators → Sound Emitters sub-collection
- [ ] Trigger volume operators → Triggers sub-collection

### Phase 4 — Geometry Organization (~80 lines)
- [ ] New meshes default to Geometry/Terrain
- [ ] Geometry sorting helpers (invisible → Collision Only, ignore → Visual Only)
- [ ] Reference (og_no_export) marking — excluded from GLB export
- [ ] Warning for nonsensical combos (invisible + ignore)

### Phase 5 — Migration (~80 lines)
- [ ] `OG_OT_MigrateSceneToCollection` operator
- [ ] Moves existing objects by prefix into sub-collections
- [ ] Copies scene og_props to collection custom props
- [ ] Info popup explaining what happened

### Phase 6 — Multi-Level Build (future, not this PR)
- [ ] "Build All Levels" operator iterating level collections
- [ ] Per-level GLB + JSONC + GD + GC export
- [ ] Shared game.gp patching for all levels

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Breaking existing files | Fallback: no level collections → v1.1.0 behavior |
| AID collision between levels | Each level collection has its own base_id |
| GLB export picking up wrong meshes | Selection-based export scoped to Geometry (minus Reference) |
| Panel draws breaking when no level selected | All helpers guard with `if col is None: return` |
| Object in multiple collections | Blender allows this — helpers deduplicate by object identity |
| User drags object to wrong collection | Respect wherever it is — addon reads collection membership, doesn't fight the user |

---

## Files

- `addons/opengoal_tools.py` on `feature/collections` — working file
- `session-notes/collections-progress.md` — this file

---

## Session Log

- 2026-04-09: Branch created from main. Full codebase audit complete.
- 2026-04-09: Design finalized after workflow discussion. Key decisions:
  - Level panel shows "Add Level" when empty, full settings when active level exists
  - Level Manager repurposed to list/switch level collections in the .blend
  - Sub-collection hierarchy: Geometry (Terrain/Collision Only/Visual Only/Reference), Spawnables (Enemies/Platforms/Props/NPCs/Pickups), Triggers, Cameras, Spawns, Sound Emitters
  - Created on demand — no empty folders
  - Auto-sort geometry on creation only, manual after
  - Backward compat: no level collections = v1.1.0 behavior
- 2026-04-09: Full functionality wiring complete (commit a1d5bb8). Session log:

  UI polish (commit 0a29a6b):
  - Level panel: pencil icon right of dropdown, ID/ISO/Nick on one row,
    death plane as layout.prop float field (getter/setter bridging to
    collection custom prop), duplicate name label removed
  - Level Manager: checkbox-style list (CHECKBOX_HLT/DEHLT), no X button,
    matches Collection Properties aesthetic

  Functionality wiring (commit a1d5bb8):
  Export pipeline fully scoped:
    collect_actors, collect_ambients, collect_spawns, collect_cameras,
    collect_nav_mesh_geometry, _collect_navmesh_actors,
    _clean_orphaned_vol_links, _vol_for_target — all use _level_objects()
  patch_level_info reads via _get_level_prop (no more og_props direct reads)
  All three build functions (_bg_build, _bg_build_and_play, _bg_geo_rebuild)
    use _get_level_prop for base_id and _level_objects for checkpoint check
  export_glb scoped to Geometry sub-collection (use_selection=True),
    excludes Reference, saves/restores full selection state; fallback intact
  Spawn operator uid counters all scoped to _level_objects:
    SpawnPlayer, SpawnCheckpoint, SpawnEntity, SpawnPlatform,
    AddSoundEmitter, AddCamera, SpawnVolume, SpawnVolumeAutoLink
  Spawn collection routing wired:
    SpawnPlatform -> Spawnables/Platforms
    SpawnVolume -> Triggers
  All panel object lists scoped: LevelFlow, platform, sound emitter,
    waypoints, camera, triggers, _draw_vol_settings, OG_OT_DeleteObject
  OG_OT_CleanLevelFiles + dev tools Quick Open use _lname(ctx)

  Automated test results: 8/8 tests pass, 0 regressions, syntax clean.
  4 intentional scene.objects references confirmed and documented:
    - L853, L1027: docstrings only
    - L3723, L3739: export_glb selection save/restore (must be scene-wide)

  Phase 1 (Foundation) ✅ complete
  Phase 2 (Export Scoping) ✅ complete
  Phase 3 (Auto-Organization) ✅ complete
  Phase 4 (Geometry Organization) — not yet started
  Phase 5 (Migration) — not yet started

- 2026-04-09: Additional changes post-wiring (all committed, merged to main):

  Routing fixes (commit 15a69e5):
  - SpawnCamAnchor → Spawns sub-collection (was unrouted)
  - SpawnVolumeAutoLink → Triggers sub-collection (was unrouted)
  - AddWaypoint → Waypoints sub-collection (was dumping to active collection)
    uid scan scoped to _level_objects (was global bpy.data.objects)
  - New constant: _COL_PATH_WAYPOINTS = ("Waypoints",)
  - Renamed Terrain → Solid (_COL_PATH_GEO_SOLID, sub-col name "Solid")

  Sub-collection prefixing + Sort operator (commit 645c83f):
  - _ensure_sub_collection: all sub-col names now prefixed with level name
    e.g. cave-test.Spawnables, cave-test.Spawnables.Enemies
    Guarantees uniqueness across multiple levels in one .blend
  - New helper _classify_object(obj): returns correct _COL_PATH_* for any object
  - OG_OT_SortLevelObjects: walks all level objects, classifies, moves misplaced ones
  - OG_PT_CleanSub: 🧹 Clean sub-panel under Collections → Sort Collection Objects button

  UI restructure (commits ae51ffe, dfe4f74):
  - Camera + Triggers moved under Spawn Objects as sub-panels
  - Camera label → "Cameras"
  - "OpenGOAL Collision" → "Collision"
  - "Collection Properties" → "Collections"
  - Death plane removed from Level panel, moved into pencil-icon edit dialog
  - Level Flow panel removed from Level group
  - OG_PT_SpawnLevelFlow: new sub-panel under Spawn Objects
    Dropdown: Player Spawn / Checkpoint + Add button
    Collapsible lists + context actions preserved
  - spawn_flow_type EnumProperty added to OGProperties

  NavMesh collection routing + UI improvements (commit cc28381):
  - _COL_PATH_NAVMESHES = ("NavMeshes",) constant added
  - _classify_object: NAVMESH_ prefix / og_navmesh tag → NavMeshes
  - OG_OT_MarkNavMesh: prefixes NAVMESH_, routes into NavMeshes
  - OG_OT_UnmarkNavMesh: strips NAVMESH_, moves to Geometry/Solid
  - OG_OT_LinkNavMesh: routes mesh into NavMeshes after linking
  - OG_OT_UnlinkNavMesh: strips NAVMESH_, moves mesh to Geometry/Solid, removes tag
  - Link NavMesh button guarded in both enemy panel and Selected Object panel
    Only shows when a mesh is shift-selected; otherwise shows "Shift-select a mesh"
  - Selected Object panel always visible (poll = True)
    Handles None → "Select an object to inspect"
    Handles non-OG object → name + "Not an OpenGOAL-managed object"
  - Mesh settings converted to collapsible sub-panels under Selected Object:
    OG_PT_SelectedCollision (Collision + Visibility)
    OG_PT_SelectedLightBaking (Light Baking)
    OG_PT_SelectedNavMeshTag (NavMesh tag)

  Merge (commit 113b0c0):
  - feature/collections merged to main
  - Backup: addons/opengoal_tools_v1.1.0_pre_collections_backup.py
  - Final addon: 8125 lines, syntax clean

  Final collection hierarchy (shipped):
  📁 my-level
    📁 Geometry / Solid, Collision Only, Visual Only, Reference
    📁 Spawnables / Enemies, Platforms, Props & Objects, NPCs, Pickups
    📁 Spawns
    📁 Cameras
    📁 Sound Emitters
    📁 Triggers
    📁 Waypoints
    📁 NavMeshes

  Phase 4 (Geometry Organization) — not started
  Phase 5 (Migration) — not started
  Phase 6 (Multi-Level Build) — not started
