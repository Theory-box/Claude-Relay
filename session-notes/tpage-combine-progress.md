# tpage-combine Session Progress

## Status: Addon integration complete. C++ patch ready to apply.
## Branch: feature/tpage-combine

---

## What This Feature Does

Solves the 10MB level heap limit when mixing enemies from multiple source levels.
Each source vis-pris tpage is ~2MB. This replaces them all with a single skeleton
tpage (~1KB) + remap table. Heap saving: ~2MB per eliminated source tpage group.

---

## Resolved Questions

### Q1 dir-tpages: write directly in Python — no upstream changes needed
### Q2 remap table: "custom_tex_remap" JSON field + 20-line C++ patch

---

## Implementation Status

### Addon (Python) — COMPLETE
All files syntax-checked and tested.

| File | Change |
|---|---|
| `tpage_combine.py` | New module — DataObjectGenerator, skeleton tpage writer, dir-tpages writer, TpageCombiner, ENEMY_TEX_SUBSTRINGS |
| `build.py` | Import wired, _run_tpage_combine() helper, all 3 build paths wired |
| `export.py` | write_jsonc() gains extra_fields= kwarg |
| `properties.py` | OGProperties.combine_tpages BoolProperty |
| `panels.py` | OG_PT_TextureMemorySub — live analysis, toggle, per-group detail |
| `__init__.py` | Import + registration of OG_PT_TextureMemorySub |

### Engine (C++) — READY TO APPLY
`scratch/build_level_patch.diff` — apply with `git apply` from jak-project root.
Adds `custom_tex_remap` JSON field to `goalc/build_level/jak1/build_level.cpp`.
~20 lines, no structural changes.

---

## Full Pipeline

```
User places kermit (Swamp group) + lurkercrab (Beach group) in Blender
        ↓
On any build trigger:
  _run_tpage_combine() detects 2 tpage groups
  TpageCombiner reads tex-info.min.json
  Assigns new sequential slots (kermit: 0-7, crab: 8-16)
  Builds sorted remap table [(orig, new|0x14), ...]
        ↓
Writes to disk:
  custom_assets/jak1/levels/<name>/tpage-1610.go  (~480 bytes, no pixel data)
  data/out/jak1/obj/dir-tpages.go                 (rebuilt, includes ID 1610)
        ↓
Level JSON gets:
  "tpages": [1610]
  "custom_tex_remap": [[0x0D604F00, 0x64A00814], ...]   ← sorted
  "textures": [["swamp-vis-pris","kermit-ankle",...], ...]
        ↓
build_level.cpp (patched):
  Reads custom_tex_remap → file.texture_remap_table
  extract_merc applies remap → bakes correct IDs into .fr3 MercDraw.tree_tex_id
        ↓
Runtime:
  GOAL loads tpage-1610.go (skeleton, ~0 heap cost for pixels)
  adgif-shader-login → level-remap-texture → maps orig IDs → combined slots
  PC renderer: .fr3 textures at correct baked indices, direct GL bind
  Result: ~4MB heap freed (2 groups eliminated)
```

---

## UI — OG_PT_TextureMemorySub

Sub-panel under "Level" (DEFAULT_CLOSED):
- "Combine Entity Tpages" toggle (BoolProperty)
- Live analysis: reads actors from scene, shows tpage group count
- If 1 group: "no combine needed" with checkmark
- If >1 groups: red alert, estimated MB saved, per-tpage-name breakdown
- Falls back gracefully if tex-info.min.json not yet extracted

---

## Next Steps (for testing)

1. Apply `scratch/build_level_patch.diff` to jak-project fork
2. Rebuild jak-project (just goalc target, not full)
3. Open a .blend with kermit + lurkercrab actors
4. Verify "Texture Memory" sub-panel shows 2 groups detected
5. Run "Export & Compile" — check log for [tpage-combine] lines
6. Load level in game — verify textures visible on both enemy types
7. Check heap usage hasn't crashed (watch for GOAL heap errors in terminal)

---

## Key Source References
- `knowledge-base/opengoal/tpage-system.md` — complete system reference
- `scratch/build_level_patch.diff` — C++ patch to apply
- `scratch/tpage_combine_full.py` — original prototype (superseded by module)

