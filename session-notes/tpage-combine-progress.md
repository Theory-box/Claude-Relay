# tpage-combine Session Progress

## Status: Research complete, implementation not started
## Branch: feature/tpage-combine
## Created: April 2026

---

## What This Feature Does

Solves the enemy tpage memory limit: when spawning enemies from multiple source levels
in a custom level, each enemy type loads its full home level's vis-pris tpage (~2MB each)
into the 10MB GOAL level heap, causing crashes or visual corruption when mixing 3+ enemy types.

**Fix:** combine all needed enemy textures into a single skeleton tpage with near-zero
pixel data. The FR3 serves actual pixel data (not heap-constrained). 

---

## Research Findings (full detail in knowledge-base/opengoal/tpage-system.md)

### Key facts confirmed from source
1. `LEVEL_HEAP_SIZE = 10416 * 1024` bytes — same limit on PC as PS2
2. tpage .go pixel data (1-3MB each) is what fills the heap, not link tables (hundreds of bytes)
3. The **remap table** in the BSP is applied at **FR3 build time** by `extract_merc.cpp` — meaning if remap table is correct in BSP, FR3 automatically gets correct texture references
4. PC merc renderer uses `lev->textures[tree_tex_id]` — a **baked index**, no pool lookup at draw time
5. Skeleton tpage with all-`#f` texture slots is valid on PC — GOAL side logs "could not find texture" but PC renderer doesn't use that path for merc draws
6. Python `DataObjectGenerator` implemented and tested — can write valid GOAL v4 .go files

### tpage ID space
- 126 tpages currently in use (IDs 2–1609 with many gaps)
- 1482 gaps available below 1609, everything above 1609 is free
- **Use IDs starting at 1610** for custom combined tpages

### Remap table encoding
- One entry per texture (not per page)
- `orig = (orig_page << 20) | (orig_index << 8)` — already masked, bits[7:0] = 0
- `new = (combined_page << 20) | (new_slot << 8) | 0x14` — 0x14 = required flags
- Table must be **sorted by orig** (binary search in GOAL)

### Enemy texture locations (from tex-info.min.json)
| Enemy | Source tpage | Page ID |
|---|---|---|
| Kermit | swamp-vis-pris | 659 |
| Lurker Crab | beach-vis-pris | 214 |
| Snow Bunny | snow-vis-pris + citadel-vis-pris | 842 + 1417 |
| Hopper/Babak | jungle-vis-pris | 385 |

---

## Implementation Plan

### 1. Python skeleton tpage writer (no C++ needed)
- `DataObjectGenerator` class already written and tested
- `write_skeleton_tpage(tpage_id, name, tex_count, output_path)` → valid .go file
- Output: `<data_path>/custom_levels/<level>/obj/tpage-NNNN.go`

### 2. Remap table generation
- Read `tex-info.min.json` from data dir
- For each enemy type in the level, collect all texture entries
- Assign sequential new slot indices
- Build sorted remap table
- **Open question:** how to pass this into the build pipeline:
  - Option A (preferred): small patch to `build_level.cpp` adding `"custom_tex_remap"` JSON field
  - Option B: write BSP binary directly from addon (bypasses build_level, more work)

### 3. Level JSON changes
- `"tpages": [1610]` instead of multiple source IDs
- `"textures": [[tpage_name, tex_name, ...]]` for selective FR3 extraction

### 4. DGO update
- Add `tpage-NNNN.go` to level .gd file

### 5. dir-tpages update
- Add entry for combined tpage ID with correct length
- `dir-tpages.go` is global (in GAME.DGO) — may need to be rebuilt
- Or: check if OpenGOAL dynamically extends dir at runtime (investigate)

### 6. Addon UI
- Tpage analysis panel: show which tpages each enemy draws from
- Warn when crossing tpage boundaries
- "Combine tpages" button that runs the full pipeline
- Show heap usage estimate before/after

---

## Working Code

### Python DataObjectGenerator
Implemented and tested in scratch. Generates correct v4 .go format.
Key methods: `add_word()`, `add_type_tag()`, `add_symbol_link()`, `add_ref_to_string()`,
`link_word_to_word()`, `link_word_to_byte()`, `align()`, `generate_v4()`

### Skeleton tpage writer
`write_skeleton_tpage(tpage_id, tpage_name, tex_count, output_path)` — tested, produces 480 bytes
for a 17-texture skeleton. Verified header fields and tpage ID/length encoding.

---

## Open Questions / Risks

1. **dir-tpages.go is global** — it lives in GAME.DGO and is loaded at startup before any level.
   If a new tpage ID isn't in dir-tpages, `link-texture-by-id` will silently skip it (bounds check).
   Need to confirm whether OpenGOAL rebuilds dir-tpages as part of the custom level build,
   or whether it needs to be patched separately.

2. **build_level.cpp remap table input** — currently remap is only copied from existing level BSPs.
   Need ~20-line patch or alternative approach to accept custom remap data.

3. **Snow bunny cross-level texture split** — bunny-tan appears in both snow-vis-pris and
   citadel-vis-pris. Remap table must handle multiple source pages → one combined page.
   The per-texture remap approach handles this correctly (each texture gets its own entry).

4. **Art group texture references** — the remap happens in `extract_merc` when processing
   art groups. The art group must be processed with the correct remap table present.
   Ensure the build order is: BSP with remap → extract_merc with that BSP's remap.

---

## Next Steps

1. Write the Python `DataObjectGenerator` and `write_skeleton_tpage` into the addon's `export.py`
2. Write `build_tpage_remap(enemy_list, combined_id)` that reads tex-info and returns sorted table
3. Prototype: patch `build_level.cpp` for `"custom_tex_remap"` field (or test BSP direct write)
4. Test with a minimal level: one kermit + one lurker crab, verify textures show correctly
5. Hook into the Build & Play pipeline

