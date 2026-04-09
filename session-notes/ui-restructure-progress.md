# UI Restructure — Session Notes
Last updated: 2026-04-09

## Branch: `feature/ui-restructure`

## Status: BUILT, SYNTAX VERIFIED — needs in-Blender testing

## What Was Done

Restructured the N-panel from ~12 flat panels into two organised groups
plus kept standalone panels where they make sense.

### New panel hierarchy

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

〰 Waypoints          OG_PT_Waypoints        (context-sensitive poll)
🔗 Triggers           OG_PT_Triggers         (always visible, no DEFAULT_CLOSED)
📷 Camera             OG_PT_Camera           (DEFAULT_CLOSED)
▶ Build & Play        OG_PT_BuildPlay        (always visible)
🔧 Developer Tools    OG_PT_DevTools         (DEFAULT_CLOSED)
OpenGOAL Collision    OG_PT_Collision        (object context)
```

### Key design decisions
- Triggers: always visible (removed DEFAULT_CLOSED) — general purpose, frequently needed
- Camera: unchanged, kept as own panel
- Navmesh: removed as standalone panel. Enemy sub-panel shows inline navmesh
  link UI when a nav-enemy entity type is selected AND an ACTOR_ object is active
- Music + sound banks moved into Level > Music sub-panel
- Sound emitters moved into Spawn > Sound Emitters sub-panel
- OG_PT_Audio fully removed
- Entity picker in Spawn sub-panels reuses existing `entity_type` prop —
  shows hint if selected type is outside that sub-panel's category

### Entity category routing
- Enemies sub: cats = {"Enemies", "Bosses"}
- Platforms sub: separate platform_type prop (unchanged from feature/platforms)
- Props sub: cats = {"Props", "Objects", "Debug"}
- NPCs sub: cats = {"NPCs"}
- Pickups sub: cats = {"Pickups"}

### idnames (all unique)
- OG_PT_level, OG_PT_level_flow, OG_PT_level_manager_sub
- OG_PT_lightbaking_sub, OG_PT_music
- OG_PT_spawn, OG_PT_spawn_enemies, OG_PT_spawn_platforms
- OG_PT_spawn_props, OG_PT_spawn_npcs, OG_PT_spawn_pickups, OG_PT_spawn_sounds

## Known Limitations / Follow-up

- [ ] Entity type picker in spawn sub-panels still uses the single shared `entity_type`
  prop — switching sub-panel doesn't reset it, so user might see a "wrong category" hint.
  Could be improved with per-category props later, but hint is friendly enough for now.

- [ ] Inline navmesh in Enemies sub-panel shows context when active object's etype
  matches selected entity_type. If user selects a babak actor but has hopper in the
  dropdown, the link UI won't show. Acceptable UX — select the actor first.

- [ ] No in-Blender testing done yet — syntax verified only via ast.parse()

## Testing Checklist
- [ ] Level panel opens, shows name/ID/death plane fields
- [ ] Level Flow sub-panel collapses, shows spawn/checkpoint operators
- [ ] Level Manager sub-panel shows level list + remove/refresh
- [ ] Light Baking sub-panel shows bake controls
- [ ] Music sub-panel shows bank selectors with live sound counts
- [ ] Spawn parent panel collapses
- [ ] Enemies sub: entity picker filtered to enemies only (shows hint for others)
- [ ] Enemies sub: inline navmesh appears when nav-enemy selected in scene
- [ ] Platforms sub: spawn + active settings works as before
- [ ] Props/NPCs/Pickups subs: entity picker + Add Entity works
- [ ] Sound Emitters sub: pick sound + add emitter + emitter list works
- [ ] Waypoints still shows when enemy with waypoints is active
- [ ] Triggers always visible, no arrow to expand
- [ ] Camera panel unchanged and working
- [ ] Build & Play always visible
- [ ] Collision still shows on mesh objects

## Commit
f9e08a9 on feature/ui-restructure
