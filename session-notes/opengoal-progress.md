# OpenGOAL Addon — Session Notes

## Current State (merged to main)
All features below are live on main.

## Features Shipped

### Waypoint Spawn Controls
- All "Add Waypoint at Cursor" buttons → "Spawn Waypoint"
- "Add Path B Waypoint" → "Spawn Path B Waypoint"  
- New "Spawn at Position" checkbox (waypoint_spawn_at_actor BoolProperty)
  - When checked: waypoint spawns at actor's world location
  - When unchecked (default): spawns at 3D cursor
  - Shared across all 6 waypoint buttons in 3 panels

### Duplicate Entity
- "Duplicate" button in Selected Object panel (ACTOR empties only)
- Operator: og.duplicate_entity
- Duplicates empty, strips inherited preview children, re-attaches fresh preview
- Inherits level collection membership from source (export-safe)
- Names follow ACTOR_<etype>_<n> convention

### Empty Fits to Viz Mesh Bounds
- On spawn, empty_display_size auto-set to largest bounding box half-extent
- Only runs on first GLB (double-lurker uses first mesh to size)
- Guarded: no-ops if mesh is degenerate (size <= 0.001)
- Purely cosmetic — never touches .scale, children unaffected

## Bug Fixed
- ctx->scene in _draw_selected_actor (standalone function, no ctx param)
  Would have crashed panel draw for any selected ACTOR entity

## Active Branch
feature/duplicate-entity-preview (merged to main, can be deleted)

## Files Changed
- addons/opengoal_tools/properties.py — waypoint_spawn_at_actor prop
- addons/opengoal_tools/operators.py — OG_OT_AddWaypoint update, OG_OT_DuplicateEntity
- addons/opengoal_tools/panels.py — waypoint buttons, duplicate button
- addons/opengoal_tools/model_preview.py — _fit_empty_to_mesh, fit call in attach_preview
- addons/opengoal_tools/__init__.py — register OG_OT_DuplicateEntity
