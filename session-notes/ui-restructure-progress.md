# UI Restructure — Session Notes
Last updated: 2026-04-09

## Status: ✅ MERGED TO MAIN
## Merged commit: 60d9ffd
## Version: 1.1.0

---

## What Was Done

### Panel Restructure
- Old flat panel list → hierarchical parent/sub-panel layout
- Level parent panel with Level Flow, Level Manager, Light Baking, Music sub-panels
- Spawn Objects parent with Enemies, Platforms, Props, NPCs, Pickups, Sound Emitters sub-panels
- Per-category entity dropdowns (each sub-panel only shows relevant types)

### Selected Object Panel (NEW)
Standalone poll-gated panel — select any OG object → see all its settings.

**Covers:** actors (navmesh, platforms, waypoints, path warnings, crate type),
cameras (mode/blend/FOV/anchor/pivot/look-at/volumes), trigger volumes
(link/unlink), spawns (camera status), checkpoints (camera + volume),
sound emitters (info display), camera anchors (parent link), navmesh meshes
(reverse actor lookup), ALL meshes (collision, visibility, light baking,
navmesh tag).

### Cleanup
- Removed duplicate validate_ambients and patch_entity_gc from main
- Version bump 1.0.0 → 1.1.0

### What Was NOT Changed
- All operator logic, export, build — byte-identical to pre-restructure
- ENTITY_DEFS, register/unregister, all helper functions — identical
- All 42 operators preserved

---

## Dead code still present (minor, harmless)
- `_entity_enum_for_cats()` — replaced by `_build_cat_enum`, can remove anytime

---

## Future Considerations
- Waypoints panel is now partially redundant with Selected Object (both show waypoint management for actors). Could remove Waypoints panel eventually, but keeping it for now since it has poll() gating.
- Camera panel list view and Triggers panel list view are still useful for overview/batch management. Selected Object is for editing the one you've selected.
- Inline navmesh section in _draw_entity_sub (Enemies sub-panel) is duplicated by Selected Object. Could remove from Enemies to keep it spawn-only.
