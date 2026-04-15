# OpenGOAL Addon — Session Notes

---

## Current Branch: `research/community-feedback-apr15`

All active work from tester feedback is on this branch. Not yet merged to main.

---

## ✅ COMPLETED THIS SESSION SERIES

### Path Bug (Critical)
- `_data()` auto-detect via `(root / "goal_src" / "jak1").exists()` in `export.py`, `build.py`
- Cached result per unique data_path — no repeated stat() on panel redraws
- Vol-h.gc inverse bug fixed (was working on dev, broken on release)
- `_user_base()`, `model_preview.py`, `textures.py`, `panels.py` Game logs button all fixed
- Preferences UI shows detected path with `✓ goal_src found here/in data/` label
- Dev Tools panel shows `resolved: /path/` line

### Build Pipeline Fixes
- `patch_level_info`, `patch_game_gp`, `patch_entity_gc` now raise instead of silently skipping
- Build & Play panel: specific per-path error messages, buttons properly disabled
- `_bg_build_and_play` was missing `_apply_engine_patches()` call — added
- REPL warning "Compilation generated code, but wasn't supposed to" — fixed by removing
  `define-extern` from `user.gc` (compiled with allow_emit=false)
- Vol-h patch gated by `patch_vol_h: BoolProperty` in OGPreferences

### og_no_export Bug
- `_level_objects` / `_recursive_col_objects` defaults changed to `exclude_no_export=False`
- No-export flag now ONLY affects GLB geometry export
- Was silently dropping checkpoints, triggers, actors from entire collections

### Level Name Validation
- Min 3 chars (DGO nickname needs 3), max 10, `^[a-z][a-z0-9-]*$` regex
- `export_build_play` operator was missing the check entirely
- Duplicate len>10 check removed from two operators
- `vis_nick_override` and spawn/checkpoint uid sanitised before GOAL output

### Object Naming
- All 9 object-spawning operators now use scene-wide counters (not level-scoped)
- Prevents Blender .001/.002 auto-suffix collisions in multi-level .blend files

### Checkpoints / Spawns UX
- "Level Flow" → "🚩 Checkpoints"
- "Player Spawn" → "Entry Spawn" throughout (labels, audit, enum descriptions)
- Checkpoint empty: `SINGLE_ARROW` → `ARROWS` display
- `spawn_cam_anchor` now parents camera to spawn/checkpoint empty
- `collect_spawns` uses `matrix_world.translation` for spawn and camera positions
- Multiple-spawn audit downgraded from WARNING to INFO (multiple entry spawns is valid)

### Misc
- `_apply_engine_patches()` missing from `_bg_build_and_play` — added
- Silent-fail → raise in all patch functions (level-info, game.gp, entity.gc)
- `_data_cache` in export.py and build.py prevents repeated stat() calls
- `user.gc` cleaned up (no more `define-extern` generating code in allow_emit=false context)

---

## 🔴 OPEN — NEXT PRIORITY

### 1. Checkpoint Quaternion Rotation Bug
Tester reports rotation only works on global-axis alignment.
- Math verified correct for single-axis rotations
- May be combined-axis issue or user expectation (green +Y = forward, not blue +Z)
- Need tester to provide a specific reproducible case
- **Ask tester:** rotate 90° around global Z and around global X simultaneously — does it break?

### 2. Checkpoint Radius Verification
Almost certainly masked by the og_no_export bug. Verify after that fix is deployed.
Code looks correct: `["meters", r]` lump → `res-lump-float` with `:default 12288.0`.

### 3. Per-Checkpoint lev1/disp1 Exposure
Low effort. Add `og_lev1` / `og_disp1` to SPAWN_/CHECKPOINT_ empties.
Read in `_make_continues()`. Needed for levels adjacent to vanilla geometry.

### 4. Debug Spawn Selector
Low–medium effort. Expose a "Default Spawn" dropdown. Reorder `:continues` list at export.
Bonus: patch `mod-settings.gc` for mod-base users.

---

## 🏗 FUTURE WORK (significant scope)

### Native Volume System
Replace AABB-only triggers with game's native vol-control system.
Tester Discord script: https://discord.com/channels/967812267351605298/973327696459358218/1280548232283557938
Required for: water volumes, concave trigger shapes, vol-mark debug display.

### Per-Blend Path Override
`data_path_override: StringProperty` on `OGProperties` (scene-level override).
Needed for multi-project workflows.

### Extracted Game Models Folder  
Third preference pointing to decompiler output.
Infrastructure already exists in `model_preview.py` for enemy GLBs.

---

## Features Shipped (on main before this branch)
- Waypoint Spawn Controls
- Duplicate Entity operator
- Empty fits to viz mesh bounds
- All previously documented features
