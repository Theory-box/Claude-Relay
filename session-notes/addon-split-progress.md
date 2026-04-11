# Addon Split — Session Notes

**Branch:** `feature/addon-split`
**Status:** ALL PHASES COMPLETE — split done, ready for regression testing
**Last updated:** 2026-04-11

---

## Final Structure

| File | Lines | Contents |
|---|---|---|
| `__init__.py` | 445 | bl_info, stdlib imports, 7 submodule imports, preview funcs, classes tuple, register(), unregister() |
| `data.py` | 2,704 | All pure data tables and derived constants — no bpy |
| `collections.py` | 324 | Collection path constants, level collection helpers, property accessors |
| `export.py` | 2,253 | Navmesh geometry, collect/write pipeline, actor/volume helpers, path helpers |
| `build.py` | 685 | GOALC process management, build/play pipeline, port file helpers |
| `properties.py` | 254 | OGPreferences, OGProperties, OGLumpRow, OGActorLink, OGVolLink, UIList |
| `operators.py` | 2,468 | All 76 OG_OT_* operators + helper functions + _draw_mat |
| `panels.py` | 3,665 | All 65 OG_PT_* panels + _draw_* helpers + 4 mixed operators |
| **TOTAL** | **12,798** | |

Original monolith: `opengoal_tools.py` — 12,429 lines

---

## Bugs Fixed During Split

- **`_KEY_MAP` duplicate** (Phase 3): Identical dict defined locally in both `_get_level_prop`
  and `_set_level_prop`. Hoisted to module-level `_LEVEL_PROP_KEY_MAP` in `collections.py`.
- **`OGPreferences.bl_idname = __name__`** (Phase 6): Would evaluate to
  `opengoal_tools.properties` in a submodule. Hardcoded to `"opengoal_tools"`.

---

## Regression Test Checklist

Run after installing the package in Blender 4.4:
- [ ] Addon installs without error
- [ ] N-panel shows up in viewport (OpenGOAL category)
- [ ] Level panel shows active level settings
- [ ] Spawn an enemy — routes to correct sub-collection
- [ ] Build & Play completes without GOAL compile error
- [ ] Camera trigger works in-game
- [ ] Checkpoint trigger fires and re-arms
- [ ] Hot-reload (OG_OT_ReloadAddon) works

## Install method
Zip the `opengoal_tools/` folder (the directory itself, not its contents).
Install via Blender Preferences → Add-ons → Install from file.

---

## Known Notes for Future Work

- Path helpers (`_nick`, `_iso`, `_lname`, `_ldir`, `_goal_src`, `_level_info`,
  `_game_gp`, `_levels_dir`, `_entity_gc`) currently live in `export.py` but
  logically belong in `build.py`. Low priority since both modules are reasonably sized.
- `panels.py` at 3,665 lines is the largest file. Could be split into
  `panels_actor.py` + `panels_level.py` etc if future editing warrants it.
- `operators.py` contains `_draw_mat` (a panel draw callback). Acceptable since
  it's small and tightly coupled to register().

---

## Session Log

- 2026-04-11 (Session 1): Branch created. Analysis complete.
- 2026-04-11 (Session 2): Phases 1-4 complete (scaffold, data, collections, export).
- 2026-04-11 (Session 3): Phases 5-7 complete (build, properties, operators+panels).
  Split complete. All 8 files AST-verified. 285 named imports, all resolved.
