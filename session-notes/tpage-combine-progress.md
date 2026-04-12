# tpage-combine Session Progress

## Status: Research complete, Python implementation complete, C++ patch designed
## Branch: feature/tpage-combine

---

## What This Feature Does

Solves the enemy tpage memory limit: when spawning enemies from multiple source levels
in a custom level, each loads its home level's full vis-pris tpage (~2MB) into the fixed
10MB GOAL level heap. Mixing 3+ enemy types from different source levels causes heap overflow.

**Fix:** one skeleton combined tpage (~1KB, no pixel data) + remap table in BSP.
FR3 serves actual pixel data (not heap-constrained). Heap saving: ~2MB per eliminated tpage.

---

## Open Questions — RESOLVED

### Q1: dir-tpages is global (GAME.DGO) — how to add new tpage ID?
**Resolution:** Write dir-tpages.go directly from Python using DataObjectGenerator.
The file is just a flat array of lengths indexed by tpage ID. We rebuild the full array
from tex-info.min.json (all existing IDs) plus our new combined ID.
Output replaces `out/jak1/obj/dir-tpages.go` before the DGO pack step.
**No upstream changes needed.**

### Q2: Remap table — how to inject into build pipeline?
**Resolution:** Add `"custom_tex_remap": [[orig, new], ...]` field to the level JSON.
Requires ~20-line patch to `goalc/build_level/jak1/build_level.cpp`.
Patch is at `scratch/build_level_patch.diff` — no structural changes, no downstream risk.
The existing `texture_remap_table` field in LevelFile handles all serialization already.

---

## Implementation Complete (Python)

### Files
- `scratch/tpage_combine_full.py` — complete 568-line implementation, all tests passing
- `scratch/build_level_patch.diff` — C++ patch for build_level.cpp
- `scratch/tpage_combine_prototype.py` — earlier prototype (superseded)

### Classes/Functions
- `DataObjectGenerator` — Python port of goalc's .go file writer (v2 + v4)
- `build_skeleton_tpage_go(id, name, count)` → bytes — skeleton tpage .go
- `build_dir_tpages_go(id_to_length)` → bytes — dir-tpages.go
- `TpageCombiner(data_path)` — main entry point
  - `.build(enemy_names, combined_id=1610)` → `TpageCombineResult`
  - `.get_tpage_analysis(enemy_names)` → dict (for UI display)
- `write_tpage_combine_outputs(result, level_obj_dir, game_out_dir)` — writes files
- `ENEMY_TEXTURE_SUBSTRINGS` — maps enemy type names → texture substrings

### Tests confirmed passing
- Skeleton tpage: 480 bytes, correct header (v4), correct id/length
- dir-tpages.go: 22KB for 1611 entries (IDs 0-1610), correct header

---

## Pipeline Summary

```
Addon collects enemy list from Blender scene
          ↓
TpageCombiner.build(enemy_names, id=1610)
  reads tex-info.min.json
  collects all textures for those enemies
  assigns new sequential slots
  builds sorted remap table [(orig, new|0x14), ...]
          ↓
Outputs:
  tpage-1610.go        → level obj/ dir (skeleton, ~1KB vs ~2MB each original)
  dir-tpages.go        → out/jak1/obj/ (replaces global, covers all IDs + 1610)
  level JSON fields:
    "tpages": [1610]                      → one entry instead of N
    "custom_tex_remap": [[o,n], ...]      → for build_level.cpp (patched)
    "textures": [["swamp-vis-pris", ...]] → selective FR3 extraction
          ↓
build_level.cpp (patched):
  reads custom_tex_remap → file.texture_remap_table
  extract_merc() applies remap → bakes correct tex IDs into FR3
          ↓
Runtime:
  GOAL loads tpage-1610.go (skeleton, ~0 heap cost for pixels)
  adgif-shader-login → level-remap-texture → maps orig → combined slot
  PC renderer: FR3 textures at correct slots (baked by extract_merc)
  Net: ~2MB saved per eliminated source tpage
```

---

## Next Steps

1. **Apply C++ patch** to jak-project fork (build_level.cpp, ~20 lines)
2. **Move Python code** from scratch into addon module structure:
   - New file: `addons/opengoal_tools/tpage_combine.py`
   - Import into `export.py` and `operators.py`
3. **Hook into Build & Play** — call `TpageCombiner.build()` before `write_gc()`
4. **Add UI panel** — "Texture Optimization" sub-panel in Level panel:
   - Show tpage analysis (N source tpages, estimated heap saving)
   - Checkbox: "Combine entity tpages" (default on when >1 source tpage detected)
   - Status: "3 tpages → 1 combined (saves ~4MB heap)"
5. **Test** with kermit + lurker-crab in a minimal custom level

## Known Risks
- dir-tpages.go replacement: must happen before DGO pack step. Verify build order.
- Art groups must be extracted AFTER remap table is set (already the case in build_level.cpp).
- Snow bunny has textures in 2 source pages — handled correctly by per-texture remap.
