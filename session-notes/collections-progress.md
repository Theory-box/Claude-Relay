# Collections as Levels — Session Progress

## Status: Design phase complete. Ready for implementation.

## Active Branch: `feature/collections`
## Addon file: `addons/opengoal_tools.py`

---

## Goal

Each Blender collection becomes a self-contained level with its own settings (name, base ID, death plane, etc.). Spawning objects auto-organizes into sub-collections. Collections can be marked "no export" to exclude from build output. Enables multi-level workflows in a single `.blend`.

---

## Current Architecture (what we're changing)

### How it works today (v1.1.0)
- **One level per scene.** `OGProperties` lives on `ctx.scene.og_props` — level name, base_id, death plane, music banks, etc.
- **Actors found by name prefix.** `_canonical_actor_objects(scene)` scans `scene.objects` for `ACTOR_*` empties. Same for `SPAWN_*`, `CHECKPOINT_*`, `AMBIENT_*`, `CAMERA_*`, `CAMVOL_*`, `VOL_*`.
- **GLB export: entire scene.** `export_glb()` calls `bpy.ops.export_scene.gltf(use_selection=False)` — exports everything visible.
- **No collection awareness.** Objects float in the scene root or whatever collection the user manually placed them in. The addon never reads or writes collection membership.

### Key functions that scan scene.objects (must be scoped to collection)
1. `_canonical_actor_objects(scene)` — actor ordering + AID assignment
2. `collect_actors(scene)` — builds JSONC actor list
3. `collect_ambients(scene)` — builds JSONC ambient list
4. `collect_spawns(scene)` — builds continue-point data
5. `collect_cameras(scene)` — camera actors + trigger volumes
6. `collect_nav_mesh_geometry(scene, level_name)` — navmesh triangles
7. `_collect_navmesh_actors(scene)` — navmesh-linked actors for entity.gc patch
8. `export_glb(ctx, name)` — exports entire scene as GLB
9. Various panel draws that count SPAWN_, CHECKPOINT_, ACTOR_ etc. objects

### Key properties on OGProperties (currently scene-level)
- `level_name`, `base_id`, `bottom_height`, `vis_nick_override`
- `sound_bank_1`, `sound_bank_2`, `music_bank`
- All UI state bools (`show_spawn_list`, etc.)
- Entity type pickers (per-category)

---

## Design

### Core Concept: Collection = Level

A top-level collection in the scene acts as a "level container." Each level collection stores its own settings (name, base_id, death plane, etc.) via **custom properties on the collection object** (not the scene).

### Level Collection Structure
```
📁 Scene Collection
  📁 my-level          ← Level collection (og_is_level=True)
    📁 Geometry         ← Meshes exported as GLB (auto-created sub-collection)
    📁 Actors           ← ACTOR_ empties (auto-created)
    📁 Spawns           ← SPAWN_ / CHECKPOINT_ empties (auto-created)
    📁 Ambients         ← AMBIENT_ empties (auto-created)
    📁 Cameras          ← CAMERA_ / CAMVOL_ / VOL_ empties (auto-created)
    📁 Reference (no export)  ← User can mark any sub-collection as no-export
  📁 test-arena        ← Another level collection
    📁 Geometry
    📁 Actors
    ...
```

### Settings Storage

**Option A: Custom properties on Collection** (chosen)
- `collection["og_is_level"] = True`
- `collection["og_level_name"] = "my-level"`
- `collection["og_base_id"] = 10000`
- `collection["og_bottom_height"] = -20.0`
- etc.

Why not a PropertyGroup on Collection? Blender doesn't support `PointerProperty` on `bpy.types.Collection` for addon-registered PropertyGroups without hacks. Custom properties are simpler and survive file save/load natively.

### Active Level Selection

- New `EnumProperty` on OGProperties: `active_level` — dynamically populated from collections where `og_is_level=True`
- All panels read from the active level collection's custom props instead of scene props
- Switching active level = switching which collection's settings are shown

### Object Scoping

Replace all `scene.objects` scans with a helper:
```python
def _level_objects(scene, level_col=None):
    """Return all objects belonging to the active level collection (recursive)."""
    if level_col is None:
        level_col = _active_level_collection(scene)
    if level_col is None:
        return []  # fallback: empty
    return _recursive_collection_objects(level_col)
```

Objects in sub-collections marked `og_no_export=True` are excluded from export but still visible in panels for reference.

### GLB Export Scoping

Two approaches:
- **A) Selection-based**: select all meshes in the level collection's Geometry sub-collection, export with `use_selection=True`
- **B) Visibility-based**: hide all non-level collections, export with `use_selection=False`, restore visibility

Option A is cleaner — no side effects on user's viewport state.

### Auto-Organization on Spawn

When any spawn operator runs (SpawnEntity, SpawnPlatform, SpawnPlayer, etc.):
1. Determine the active level collection
2. Find or create the appropriate sub-collection (Actors, Spawns, etc.)
3. Link the new object into that sub-collection
4. Unlink from Scene Collection root if needed

### Backward Compatibility

**Critical requirement**: existing `.blend` files with no collections must still work.

Fallback: if no collection has `og_is_level=True`, the addon behaves exactly as v1.1.0 — reads from `scene.og_props`, scans `scene.objects`, exports everything. Zero breakage.

Migration path: a "Convert Scene to Collection Level" operator that:
1. Creates a level collection with current scene settings
2. Creates sub-collections (Geometry, Actors, Spawns, Ambients, Cameras)
3. Moves existing objects into appropriate sub-collections by prefix
4. Copies `og_props` values to collection custom properties

---

## Implementation Plan

### Phase 1 — Foundation (~200 lines)
- [ ] `_active_level_collection(scene)` helper
- [ ] `_level_objects(scene)` helper (replaces `scene.objects` in collectors)
- [ ] `_recursive_collection_objects(col, exclude_no_export=True)` helper
- [ ] `OG_OT_CreateLevelCollection` operator — creates level collection + sub-collections
- [ ] `active_level` EnumProperty on OGProperties (dynamic items callback)
- [ ] Level panel: show active_level selector at top when ≥1 level collection exists
- [ ] Level panel: read/write collection custom props instead of scene props when collection mode is active

### Phase 2 — Export Scoping (~150 lines)
- [ ] Refactor `_canonical_actor_objects` to accept optional `objects` list
- [ ] Refactor `collect_actors`, `collect_ambients`, `collect_spawns`, `collect_cameras` to accept objects list
- [ ] Refactor `export_glb` to use selection-based export scoped to level collection
- [ ] `_bg_build` reads from active level collection

### Phase 3 — Auto-Organization (~100 lines)
- [ ] All spawn operators auto-link to correct sub-collection
- [ ] `_ensure_sub_collection(level_col, name)` helper
- [ ] Sub-collection naming: "Geometry", "Actors", "Spawns", "Ambients", "Cameras"

### Phase 4 — No-Export Marking (~50 lines)
- [ ] `og_no_export` custom property on collections
- [ ] Toggle operator in panel
- [ ] Collectors skip objects in no-export collections
- [ ] Visual indicator in panel (strikethrough or icon)

### Phase 5 — Migration (~80 lines)
- [ ] `OG_OT_MigrateSceneToCollection` operator
- [ ] Moves objects by prefix into sub-collections
- [ ] Copies scene props to collection custom props
- [ ] Info dialog explaining what happened

### Phase 6 — Multi-Level Build (future, not this PR)
- [ ] "Build All Levels" operator that iterates level collections
- [ ] Per-level GLB + JSONC + GD + GC export
- [ ] Shared game.gp patching for all levels

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Breaking existing files | Fallback mode: no level collections → v1.1.0 behavior |
| AID collision between levels | Each level collection has its own base_id |
| GLB export picking up wrong meshes | Selection-based export scoped to Geometry sub-collection |
| Panel draws breaking when no level selected | All panel helpers guard with `if level_col is None: return` |
| Object in multiple collections | Blender allows this — our helpers deduplicate |

---

## Files

- `addons/opengoal_tools.py` on `feature/collections` — working file
- `session-notes/collections-progress.md` — this file

---

## Session Log

- 2026-04-09: Branch created from main. Full codebase audit complete. Design document written. Ready to start Phase 1.
