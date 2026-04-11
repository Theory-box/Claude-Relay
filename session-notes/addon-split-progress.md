# Addon Split — Session Notes

**Branch:** `feature/addon-split`
**Status:** Phase 4 complete — 4 of 7 modules extracted
**Last updated:** 2026-04-11

---

## Goal

Split `addons/opengoal_tools.py` (12,429 lines, single file) into a Blender
package (`addons/opengoal_tools/`) with logical sub-modules. Pure refactor —
zero logic changes.

---

## Progress

### ✅ Phase 1 — Scaffold (commit c6d209e)
Created `addons/opengoal_tools/__init__.py` as verbatim copy of the monolith.
Regression baseline: install `opengoal_tools/` folder from `addons/`.

### ✅ Phase 2 — data.py (commit bbb8b62)
Extracted all pure data tables and derived constants into `data.py` (2,704 lines).
36 names explicitly imported. No bpy dependencies. `__init__.py`: 12,429 → 9,783 lines.

### ✅ Phase 3 — collections.py (commit a2d58ad)
Extracted collection path constants and level collection helpers into `collections.py` (324 lines).
**Bug fixed:** `_KEY_MAP` defined identically in both `_get_level_prop` and `_set_level_prop` —
hoisted to module-level `_LEVEL_PROP_KEY_MAP` constant.
33 names imported. `__init__.py`: 9,783 → 9,475 lines.

### ✅ Phase 4 — export.py (commit 383eb06)
Extracted navmesh geometry, collect/write pipeline, and actor/volume helpers into
`export.py` (2,226 lines). Note: path helpers (`_nick`, `_iso`, `_lname`, `_ldir`,
`_goal_src`, `_level_info`, `_game_gp`, `_levels_dir`, `_entity_gc`) are temporarily
in `export.py` — they will move to `build.py` when that phase runs.
45 names imported. `__init__.py`: 9,475 → 7,325 lines.

### Current file sizes
| File           | Lines |
|----------------|-------|
| __init__.py    | 7,325 |
| data.py        | 2,704 |
| collections.py |   324 |
| export.py      | 2,226 |
| **TOTAL**      | **12,579** |

---

## Remaining Phases

### Phase 5 — build.py
Extract GOALC process management, build/play pipeline, port file helpers.
Target lines: ~1,300. Key functions: `launch_goalc`, `launch_gk`, `_bg_build`,
`_bg_build_and_play`, `_bg_geo_rebuild`, `goalc_send`, `goalc_ok`, `kill_gk`,
`kill_goalc`, `_process_running`, `_kill_process`, `write_startup_gc`.
Path helpers (`_nick`, `_iso`, etc.) move here from export.py.
Note: `import sys as _sys` and `import tempfile as _tempfile` mid-file — move here.

**Find these in current __init__.py:**
- `class OGPreferences` — L~152
- `import sys as _sys` — after OGPreferences  
- `GOALC_PORT`, `GOALC_TIMEOUT`, `_PORT_FILE` constants
- `_save_port_file`, `_load_port_file`, `_delete_port_file`, `_find_free_nrepl_port`
- `_exe_root`, `_data_root`, `_gk`, `_goalc`, `_data`
- `_process_running`, `_kill_process`, `kill_gk`, `kill_goalc`
- `goalc_send`, `goalc_ok`, `_user_base`, `_user_dir`, `write_startup_gc`
- `launch_goalc`, `launch_gk`
- `_bg_build`, `_bg_build_and_play`, `_bg_geo_rebuild`, `_build_state`, `_play_state`

### Phase 6 — properties.py
Extract `OGProperties` PropertyGroup (~L260–L485 range in current file).

### Phase 7 — operators.py + panels.py
The 78 operators and 65 panels. May need sub-splitting if still too large.
Final cleanup of `__init__.py` to ~150 lines: bl_info, imports, classes tuple,
register/unregister.

---

## Known Risks Remaining

| Risk | Status |
|---|---|
| `_KEY_MAP` duplicate | ✅ Fixed in Phase 3 |
| Path helpers in export.py (temporary) | Pending Phase 5 |
| `import sys as _sys` / `import tempfile` mid-file | Pending Phase 5 |
| operators.py may exceed 3,500 lines | Will assess in Phase 7 |

---

## Regression Test Checklist (run after each phase)
- [ ] Addon installs without error in Blender 4.4
- [ ] N-panel shows up in viewport
- [ ] Level panel shows active level settings
- [ ] Spawn an enemy — routes to correct sub-collection
- [ ] Build & Play completes without GOAL compile error
- [ ] Camera trigger works in-game
- [ ] Checkpoint trigger fires and re-arms

---

## Files

- `addons/opengoal_tools.py` on `main` — source of truth, do not touch during split
- `addons/opengoal_tools/` on `feature/addon-split` — working directory
- `session-notes/addon-split-progress.md` — this file

---

## Session Log

- 2026-04-11 (Session 1): Branch created. Analysis complete. Dependency graph mapped.
  _KEY_MAP duplicate noted. Implementation plan written.
- 2026-04-11 (Session 2): Phase 1 scaffold. Phase 2 data.py. Phase 3 collections.py
  (fixed _KEY_MAP). Phase 4 export.py. All 4 modules AST-verified. 
  __init__.py: 12,429 → 7,325 lines (-5,104). 
  Next: Phase 5 build.py.
