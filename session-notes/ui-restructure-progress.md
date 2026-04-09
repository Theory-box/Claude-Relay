# UI Restructure — Session Notes
Last updated: 2026-04-09

## Branch: `feature/ui-restructure`
## Latest commit: 22aa7e9
## Addon version: 1.1.0

## Status: ALL TESTS PASS — ready for Blender install test

---

## Panel Hierarchy

```
📁 Level              OG_PT_Level            (parent, always open)
  🗺 Level Flow        OG_PT_LevelFlow        (sub, DEFAULT_CLOSED)  idname: OG_PT_level_flow
  🗂 Level Manager     OG_PT_LevelManagerSub  (sub, DEFAULT_CLOSED)  idname: OG_PT_level_manager_sub
  💡 Light Baking      OG_PT_LightBakingSub   (sub, DEFAULT_CLOSED)  idname: OG_PT_lightbaking_sub
  🎵 Music             OG_PT_Music            (sub, DEFAULT_CLOSED)  idname: OG_PT_music

📁 Spawn Objects      OG_PT_Spawn            (parent, DEFAULT_CLOSED)
  ⚔ Enemies           OG_PT_SpawnEnemies     (sub, DEFAULT_CLOSED)  prop: enemy_type
  🟦 Platforms         OG_PT_SpawnPlatforms   (sub, DEFAULT_CLOSED)  prop: platform_type
  📦 Props & Objects   OG_PT_SpawnProps       (sub, DEFAULT_CLOSED)  prop: prop_type
  🧍 NPCs              OG_PT_SpawnNPCs        (sub, DEFAULT_CLOSED)  prop: npc_type
  ⭐ Pickups           OG_PT_SpawnPickups     (sub, DEFAULT_CLOSED)  prop: pickup_type
  🔊 Sound Emitters    OG_PT_SpawnSounds      (sub, DEFAULT_CLOSED)

〰 Waypoints          OG_PT_Waypoints        (context poll: actor with waypoints selected)
🔗 Triggers           OG_PT_Triggers         (always visible — no DEFAULT_CLOSED)
📷 Camera             OG_PT_Camera           (DEFAULT_CLOSED, unchanged)
▶ Build & Play        OG_PT_BuildPlay        (always visible)
🔧 Developer Tools    OG_PT_DevTools         (DEFAULT_CLOSED)
OpenGOAL Collision    OG_PT_Collision        (object context)
```

---

## Key Features

### Per-category entity dropdowns
Each Spawn sub-panel has its own filtered dropdown — Enemies only shows
enemies/bosses, NPCs only shows NPCs, etc. No more scrolling through 90 entities.

- `enemy_type`  → ENEMY_ENUM_ITEMS  (Enemies + Bosses, grouped by tpage)
- `prop_type`   → PROP_ENUM_ITEMS   (Props + Objects + Debug)
- `npc_type`    → NPC_ENUM_ITEMS    (NPCs)
- `pickup_type` → PICKUP_ENUM_ITEMS (Pickups)

SpawnEntity operator reads from `source_prop` (set by each sub-panel button),
then syncs `entity_type` so export logic stays compatible.

### Inline navmesh (Enemies sub-panel)
Appears when ANY nav-enemy ACTOR_ is the active object, regardless of dropdown.
Shows actor name in header, link/unlink buttons. No separate NavMesh panel needed.

### Triggers always visible
No DEFAULT_CLOSED — always expanded so volumes are always one click away.

---

## Bugs Fixed During This Session

| Bug | Severity | Fix |
|---|---|---|
| 17 operators dropped during UI splice | Critical | Restored from main |
| Duplicate OG_PT_LightBaking panel | Critical | Removed |
| Duplicate validate_ambients fragment | Critical | Removed |
| Duplicate bl_idname conflicts | Critical | Renamed sub-panel idnames |
| Navmesh inline matched dropdown not actor | UX | Fixed to use actor's actual type |
| All spawn sub-panels shared one dropdown | UX | Per-category props + filtered enums |
| prop_name missing from Props/NPC/Pickup panels | Bug | Added to all call sites |

---

## Test Suite Results: 37/37 PASS

Structural (8): syntax, duplicates, bl_idnames, registration, parent IDs, op refs
OGProperties (25): all 24 props + no missing show_ props
Per-cat enums (4): all defined, ordered before OGProperties, referenced correctly
SpawnEntity (3): source_prop, getattr fallback, try/except sync
Edge cases (9): ENTITY_WIKI order, enum build order, body completeness, f-strings,
                panel order, icons, guards, collision context, install audit

---

## Orphaned Operators (pre-existing, harmless)
- og.mark_navmesh, og.unmark_navmesh, og.pick_navmesh — were in old NavMesh panel
- og.export_build_play, og.play_autoload — BuildPlay panel shows 3 buttons only

---

## Blender Testing Checklist

### Level panel
- [ ] Name, Base ID, death plane visible at top (no sub-panel)
- [ ] ISO/Nick preview row appears when name is set
- [ ] Level Flow sub: spawns, checkpoints, bsphere row
- [ ] Level Manager sub: level list, trash + refresh buttons
- [ ] Light Baking sub: sample count, bake button (greyed when nothing selected)
- [ ] Music sub: music bank + bank 1/2 dropdowns + live sound count

### Spawn panel
- [ ] Enemies sub: dropdown shows ONLY enemies/bosses with [Beach]/[Jungle] etc prefixes
- [ ] Enemies sub: with babak ACTOR_ selected → navmesh section appears with actor name
- [ ] Enemies sub: link navmesh works (shift-select enemy + quad, click Link)
- [ ] Platforms sub: type dropdown, Add Platform, settings appear when platform selected
- [ ] Props & Objects sub: dropdown shows only Props/Objects/Debug
- [ ] NPCs sub: dropdown shows only NPCs
- [ ] Pickups sub: dropdown shows only pickups (fuel-cell, money, crate, etc)
- [ ] Sound Emitters sub: pick sound, add emitter, emitter list

### Add Entity cross-check
- [ ] Select enemy in Enemies sub → click Add Entity → correct actor spawned
- [ ] Select NPC in NPCs sub → click Add Entity → correct NPC spawned
- [ ] entity_type syncs correctly (check export works after spawning via sub-panel)

### Standalone panels
- [ ] Waypoints: appears when enemy/platform with waypoints is active
- [ ] Triggers: ALWAYS visible (not collapsed), add volume works
- [ ] Camera: unchanged, add camera + volume works
- [ ] Build & Play: 3 buttons always visible
- [ ] Collision: appears on mesh objects in properties panel

