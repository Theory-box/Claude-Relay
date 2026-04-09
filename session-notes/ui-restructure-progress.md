# UI Restructure — Session Notes
Last updated: 2026-04-09 (Opus 4.6 — built Selected Object panel)

## Branch: `feature/ui-restructure`
## Latest commit: 66fcf4f (Selected Object panel)

## Status: READY FOR BLENDER TEST

---

## What Changed This Session

Added `OG_PT_SelectedObject` — a standalone, poll-gated panel that shows
context-sensitive settings for whatever OG-managed object is selected.

### New code added:
- `_og_managed_object(obj)` — returns True for any OG-managed object
- `_draw_selected_actor(layout, sel, scene)` — enemies, platforms, props, NPCs, pickups
- `_draw_selected_spawn(layout, sel, scene)` — camera status + add
- `_draw_selected_checkpoint(layout, sel, scene)` — camera + volume link
- `_draw_selected_emitter(layout, sel)` — sound name, mode, radius
- `_draw_selected_volume(layout, sel, scene)` — linked target display
- `_draw_selected_cam_anchor(layout, sel, scene)` — parent link
- `_draw_selected_navmesh(layout, sel)` — reverse actor lookup, triangle count
- `OG_PT_SelectedObject` — panel class with poll() and dispatch draw()

### Registration order:
SpawnSounds → **SelectedObject** → Waypoints

### What it shows per object type:
- **Nav-enemy actor**: label, navmesh link/unlink, triangle count, fallback radius
- **Platform actor**: delegates to _draw_platform_settings (full sync/path/notice UI)
- **Prop actor**: "idle animation only" info
- **Path enemies**: path requirement warnings
- **Crate actors**: crate type display
- **All actors**: waypoint count, frame/delete buttons
- **Spawn points**: camera status + add button
- **Checkpoints**: camera status + volume link/unlink
- **Sound emitters**: sound name, mode, radius
- **Trigger volumes**: linked target + unlink
- **Camera anchors**: parent object link
- **Navmesh meshes**: which actors reference it, triangle count

---

## Panel Hierarchy (current)

```
📁 Level              OG_PT_Level            (parent, always open)
  🗺 Level Flow        OG_PT_LevelFlow        (sub, DEFAULT_CLOSED)
  🗂 Level Manager     OG_PT_LevelManagerSub  (sub, DEFAULT_CLOSED)
  💡 Light Baking      OG_PT_LightBakingSub   (sub, DEFAULT_CLOSED)
  🎵 Music             OG_PT_Music            (sub, DEFAULT_CLOSED)

📁 Spawn Objects      OG_PT_Spawn            (parent, DEFAULT_CLOSED)
  ⚔ Enemies           OG_PT_SpawnEnemies     (sub, DEFAULT_CLOSED)
  🟦 Platforms         OG_PT_SpawnPlatforms   (sub, DEFAULT_CLOSED)
  📦 Props & Objects   OG_PT_SpawnProps       (sub, DEFAULT_CLOSED)
  🧍 NPCs              OG_PT_SpawnNPCs        (sub, DEFAULT_CLOSED)
  ⭐ Pickups           OG_PT_SpawnPickups     (sub, DEFAULT_CLOSED)
  🔊 Sound Emitters    OG_PT_SpawnSounds      (sub, DEFAULT_CLOSED)

🔍 Selected Object    OG_PT_SelectedObject   (standalone, poll-gated, always open when visible)
〰 Waypoints          OG_PT_Waypoints        (context poll: actor with waypoints selected)
🔗 Triggers           OG_PT_Triggers         (always visible)
📷 Camera             OG_PT_Camera           (DEFAULT_CLOSED)
▶ Build & Play        OG_PT_BuildPlay        (always visible)
🔧 Developer Tools    OG_PT_DevTools         (DEFAULT_CLOSED)
OpenGOAL Collision    OG_PT_Collision        (object context)
```

---

## Known: NavMesh UI duplication

The inline navmesh section still exists in _draw_entity_sub (Enemies sub-panel).
The Selected Object panel now also shows navmesh management.
This is intentional duplication for now — both paths work.

Future cleanup (next session): consider removing the inline navmesh from
_draw_entity_sub since Selected Object now handles it. This would make
Enemies sub-panel purely about spawning.

---

## Dead code to clean up before merge

- `_entity_enum_for_cats()` — replaced by `_build_cat_enum`

---

## Blender Testing Checklist

### Selected Object panel (NEW)
- [ ] Panel hidden when nothing or non-OG object selected
- [ ] Select ACTOR_babak_0 → shows "Babak (Lurker)", NavMesh section, waypoint count
- [ ] NavMesh section: link/unlink works from this panel
- [ ] Select ACTOR_plat_0 → shows platform settings (sync, period, phase, etc.)
- [ ] Select ACTOR_crate_0 → shows crate type
- [ ] Select SPAWN_xxx → shows camera status, add camera button
- [ ] Select CHECKPOINT_xxx → shows camera + volume link status
- [ ] Select AMBIENT_xxx → shows sound name, mode, radius
- [ ] Select VOL_xxx → shows linked target
- [ ] Select *_CAM object → shows parent link
- [ ] Select navmesh mesh → shows linked actors, triangle count
- [ ] Frame and Delete buttons work on all types

### Existing panels (regression check)
- [ ] Level panel and all sub-panels still work
- [ ] Spawn sub-panels still work for placing entities
- [ ] Waypoints still context-sensitive
- [ ] Triggers always visible
- [ ] Camera unchanged
- [ ] Build & Play works
- [ ] Export produces correct .jsonc
