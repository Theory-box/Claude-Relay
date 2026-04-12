# OpenGOAL Texture Page (tpage) System — Complete Reference

**Researched:** April 2026  
**Source:** jak-project source code (tpage.cpp, texture.gc, bsp.gc, extract_merc.cpp, Merc2.cpp, TexturePool.cpp, build_level.cpp, DataObjectGenerator.cpp)  
**Confidence:** High — all findings from direct source reading, no guesswork

---

## 1. What Is a tpage?

A **texture page** (tpage) is the atomic unit of texture loading in Jak 1. It is a numbered binary `.go` object file (e.g. `tpage-385.go`) that the GOAL engine loads into its level heap when a level becomes active. Each tpage contains:

- A `texture-page` GOAL basic (header struct)
- Up to N `texture` entries, each describing one texture's PS2 GS format, dimensions, mip data, and VRAM block address
- Raw pixel data in PS2 GS format (PSMT8 + CLUT32 for most entity textures, packed 128px wide)

The PS2 VRAM is 4MB. Textures are uploaded to VRAM in 128-pixel-wide strips. Each tpage has 3 segments (near, common, shrub-style) for LOD management.

---

## 2. The Level Heap Constraint

Every custom level has a fixed **`LEVEL_HEAP_SIZE = 10416 * 1024` bytes (~10MB)**. This heap holds:
- Level BSP geometry (tfrag, shrub, tie drawables) — typically 2–5MB
- All loaded tpage `.go` files with their pixel data — 1–3MB each
- Entity process heaps, link tables, game-save data, etc.

**This is why mixing enemies from multiple source levels causes crashes or visual bugs.** Each enemy type from a different source level requires loading its home level's `vis-pris` tpage into the heap:

| Tpage | Source | Textures | Typical .go size |
|---|---|---|---|
| `jungle-vis-pris` | tpage-385 | 82 textures, includes hopper/babak | ~2MB |
| `beach-vis-pris` | tpage-214 | 160 textures, includes lurker crab | ~2.5MB |
| `swamp-vis-pris` | tpage-659 | 93 textures, includes kermit | ~1.8MB |
| `snow-vis-pris` | tpage-842 | 85 textures, includes snow bunny | ~1.7MB |

Loading 3 enemy types from different source levels = 3 full vis-pris tpages = ~6MB just for textures, leaving ~4MB for geometry — barely enough for a non-trivial level.

---

## 3. Texture-ID Encoding

The GOAL `texture-id` is a `uint32` with this bit layout:

```
bits [31:20] = tpage page number   (12 bits, max 4095)
bits [19:8]  = texture index       (12 bits, index within tpage)
bits [7:0]   = unused              (always 0)
```

The PC combo_id (used in tex-info.min.json and FR3 files) packs differently:
```
combo_id upper16 = page number
combo_id lower16 = texture index
```

Both refer to the same page number and index values.

---

## 4. Two Separate Texture Systems

OpenGOAL runs two completely parallel texture pipelines:

### 4A. GOAL/PS2 Path
- GOAL engine loads `tpage-NNN.go` into level heap during level load
- `login-level-textures` (texture.gc:1290) registers each tpage into 5 named slots per level:
  - Slot 0: tfrag (level geometry near)
  - Slot 1: pris (entity/enemy textures) ← the relevant one
  - Slot 2: shrub
  - Slot 3: alpha
  - Slot 4: water
- `adgif-shader-login` → `level-remap-texture` → `link-texture-by-id` → links draw shaders to tpage entries
- `texture-page-dir` global: maps page ID → loaded texture-page object

### 4B. PC/FR3 Path  
- `.fr3` file contains `tfrag3::Texture` structs with raw RGBA pixels
- Loaded at level load time by `Loader::upload_textures()` → `add_texture()` → `glTexImage2D()`
- Each texture registered in `TexturePool` under `PcTextureId(page, tex_idx)`
- `Merc2::alloc_normal_draw()` sets `draw.texture = mdraw.tree_tex_id`
- At draw time: `glBindTexture(lev->textures[draw.texture])` — **direct GL handle, no pool lookup**
- `tree_tex_id` is an index into the flat `lev->textures[]` array, baked at build time

**The PC merc renderer NEVER calls TexturePool::lookup at draw time.** The texture index is baked into the `.fr3` at decompiler/extract time.

---

## 5. The Remap Table

The BSP header contains a `texture-remap-table` — a sorted array of 8-byte entries:

```c
struct TextureRemap {
    u32 original_texid;  // masked GOAL texture-id (bits[31:8] only, bits[7:0] = 0)
    u32 new_texid;       // replacement GOAL texture-id | 0x14
};
```

At runtime (`adgif-shader-login`), `level-remap-texture` does a **binary search** on this table (sorted by orig) and replaces the shader's texture-id before linking. The `| 0x14` sets bits 2 and 4 as internal flags.

**Critically: `extract_merc.cpp` applies this same remap at FR3 build time**, converting remapped GOAL texture-ids to PC combo_ids that get baked into `MercDraw.tree_tex_id`. So if the remap table is correct in the BSP, the FR3 automatically gets correct texture references — no manual FR3 work needed.

```cpp
// extract_merc.cpp:1007-1013
u32 new_tex = remap_texture(shader.original_tex, map);
u32 tpage = new_tex >> 20;
u32 tidx = (new_tex >> 8) & 0b1111'1111'1111;
u32 tex_combo = (((u32)tpage) << 16) | tidx;
merc_state.merc_draw_mode.pc_combo_tex_id = tex_combo;
```

---

## 6. The Fix: Combined Custom Tpage

### Concept
Instead of loading 3+ full vis-pris tpages (~6MB), create one skeleton combined tpage with near-zero pixel data. All enemy textures reference this single page via the remap table. The actual pixel data is served by the FR3 file (which is not heap-constrained).

### What Gets Built

**1. A skeleton `tpage-NNNN.go` file**
- Valid GOAL object file format (v4 link format)
- Correct tpage ID (any unused ID — 1482 gaps exist below 1609, plus everything above)
- `length` = total combined texture count
- All texture slots = `#f` (null) — no pixel data needed
- Segment sizes = minimal (1 word dummy data)
- File-info version = 7 (Jak1 `TX_PAGE_VERSION`)

**2. A remap table in the BSP**
- One entry per texture being remapped (not per page)
- `original_texid = (orig_page << 20) | (orig_index << 8)` — the full masked GOAL texture-id
- `new_texid = (combined_page << 20) | (new_slot << 8) | 0x14`
- Table MUST be sorted by original_texid for binary search to work
- Generates automatically from tex-info.min.json lookups

**3. Updated level JSON fields**
```json
"tpages": [1610],
"textures": [
    ["swamp-vis-pris", "kermit-ankle", "kermit-back", "kermit-belly", ...],
    ["beach-vis-pris", "crab-belt", "crab-folds", "crab-shell-01", ...]
]
```
- `tpages`: only the combined tpage ID — replaces all original source tpage IDs
- `textures`: selective extraction of only the needed textures for the FR3 file

**4. Updated `dir-tpages`**
- The `dir-tpages.go` file must include the combined tpage ID with correct `length` entry
- Generated by existing `compile_dir_tpages` tool — just needs the length array updated

---

## 7. The .go Binary Format (for Python writer)

GOAL object files use the v4 link format. Structure:

```
[LinkHeaderV4 16 bytes]  type_tag=0xFFFFFFFF, length=link_data_len, version=4, code_size=align16(words*4)
[object data]            raw u32 words  
[padding]                align to 16 bytes
[LinkHeaderV2 12 bytes]  type_tag=0xFFFFFFFF, length=same, version=2
[link table]             variable-length encoding of pointer/symbol/type links
```

The link table encodes:
- **Pointer links**: word offsets where pointers live, sorted, delta-encoded with variable-length integers
- **Symbol links**: name string (ASCII+null), then sorted delta-encoded word offsets
- **Type links**: 0x80 prefix, then same format as symbol links

String data (GOAL `string` basics) is appended at the end of the object data by the generator.

### Python DataObjectGenerator
A complete Python implementation of `DataObjectGenerator` was prototyped and confirmed working (generates correct v4 format, handles string pool, type tags, symbol links, pointer links). See `scratch/tpage_combine_prototype.py` (to be committed).

### Skeleton tpage-NNNN.go structure (word layout)
```
Word  0:    type-tag 'texture-page'
Word  1:    ptr → file-info basic
Word  2:    ptr → name string
Word  3:    id (u32) = new tpage ID
Word  4:    length (s32) = total texture count
Word  5:    mip0_size = 1 (placeholder)
Word  6:    size = 1 (placeholder)
Word  7:    seg0.block_data ptr → dummy pixel data
Word  8:    seg0.size = 1
Word  9:    seg0.dest = 0
Word 10-15: seg1, seg2 (all zeros)
Word 16-31: pad[16] = all zeros
Word 32+:   data[N] entries — all #f (symbol link to #f)
[align to 4]
[file-info basic]
  type-tag 'file-info'
  symbol 'texture-page'  (file_type)
  ptr → name string      (file_name)
  u32 7                  (major_version = TX_PAGE_VERSION Jak1)
  u32 0                  (minor_version)
  ptr → 'Unknown'        (maya_file_name)
  ptr → 'og-custom'      (tool_debug)
  u32 0                  (mdb_file_name)
[dummy pixel data: 1 word = 0]
[strings: tpage_name, 'Unknown', 'og-custom']
```

---

## 8. Enemy Texture Map (from tex-info.min.json)

Format: `combo_id = (page << 16) | idx`. The GOAL texture-id = `(page << 20) | (idx << 8)`.

| Enemy | Tpage Name | Page ID | Texture Count | Example textures |
|---|---|---|---|---|
| Kermit | swamp-vis-pris | 659 | 8 | kermit-ankle (idx 57) … kermit-tan (idx 64) |
| Lurker Crab | beach-vis-pris | 214 | 9 | crab-belt (idx 79) … crab-shell-03 (idx 87) |
| Snow Bunny | snow-vis-pris | 842 | 7 | bunny-body (idx 64) … bunny-tan (idx 65) |
| Snow Bunny | citadel-vis-pris | 1417 | 1 | bunny-tan (idx 50) — duplicate across levels |
| Hopper | jungle-vis-pris | 385 | (verify) | hopper-* |
| Babak | jungle-vis-pris | 385 | (verify) | babak-* |

**Note:** Some enemies appear in multiple source levels and thus have textures in multiple source tpages (e.g. snow bunny in both snow and citadel). The remap table handles this: multiple source page entries all map to the combined page.

---

## 9. Texture Count per Tpage (for dir-tpages length entries)

| Tpage | Page ID | Total textures in that page |
|---|---|---|
| beach-vis-pris | 214 | 160 |
| swamp-vis-pris | 659 | 93 |
| snow-vis-pris | 842 | 85 |
| citadel-vis-pris | 1417 | 170 |
| jungle-vis-pris | 385 | 82 |

The `dir-tpages.go` length entry for each page controls the size of the link table malloc: `length * 4` bytes per page per level load. This is negligible. The big saving is eliminating the pixel data payload of each full vis-pris `.go`.

---

## 10. Implementation Plan (Addon Side)

### New addon functionality needed

**Step 1: Enemy texture analysis**
- Read `tex-info.min.json` from the OpenGOAL data directory
- Map each enemy type in the level to its source tpage(s) and texture indices
- Detect when enemies cross tpage boundaries (warn user)
- Show estimated heap usage

**Step 2: Remap table generation**
- For each enemy in the level, collect all texture entries from tex-info
- Assign new sequential slot indices within the combined tpage
- Build sorted remap table: `(orig_masked_goal_texid → new_goal_texid | 0x14)`
- Emit into level JSON as `"texture_remap_table"` (needs build_level.cpp support, or emit as a separate file the BSP writer reads)

**Step 3: Skeleton tpage .go writer**
- Pure Python, no C++ dependency
- DataObjectGenerator class (already implemented and tested)
- `write_skeleton_tpage(tpage_id, tpage_name, tex_count, output_path)`
- Output goes to the custom level's obj/ directory alongside other .go files

**Step 4: DGO manifest update**  
- Add `tpage-NNNN.go` to the level's DGO file (`.gd`)
- Replace the multiple source tpage references with just the combined one

**Step 5: Level JSON generation**
- `"tpages": [combined_id]` instead of multiple source IDs
- `"textures": [[tpage_name, tex_name, ...], ...]` — selective per-enemy extraction
- Emit remap table data (format TBD — may need build_level.cpp patch)

### Key open question
The remap table in the BSP is currently only sourced by copying from an existing level's BSP (`"tex_remap": "level-name"`). To emit a custom remap table, either:
- A) Add a `"custom_tex_remap"` JSON field to build_level.cpp that accepts the table directly (small C++ patch, clean)
- B) Write a minimal custom BSP that has the remap table baked in (more work)
- C) The addon writes the remap table into the `.go` BSP file directly (bypasses build_level.cpp entirely — most work but no engine changes)

Option A is cleanest. The patch to `build_level.cpp` would be ~20 lines reading a JSON array of `[orig, new]` pairs into `file.texture_remap_table`.

---

## 11. Files and IDs

- `dir-tpages.go` — the texture-page-dir object, lives in `GAME.DGO`, loaded globally at startup
- `tpage-NNN.go` — individual tpage objects, packed into level DGOs
- Available combined tpage IDs: any integer not in the existing 126 tpage IDs. 1482 gaps exist below 1609. IDs 1610+ are all free.
- Recommended: use IDs starting at 1610 for custom combined tpages (one per custom level)

---

## 12. Key Source File Reference

| File | Purpose |
|---|---|
| `goal_src/jak1/engine/gfx/texture/texture.gc` | Runtime texture pool, login, link, remap logic |
| `goal_src/jak1/engine/level/bsp.gc` | `level-remap-texture` binary search function |
| `goal_src/jak1/engine/gfx/texture/texture-h.gc` | `texture-id` struct definition (bits 31:20=page, 19:8=index) |
| `decompiler/data/tpage.cpp` | tpage .go binary decoder (read) |
| `decompiler/data/TextureDB.h` | In-memory texture database |
| `decompiler/level_extractor/extract_merc.cpp` | Applies remap at FR3 build time, bakes tree_tex_id |
| `decompiler/level_extractor/common_formats.h` | `TextureRemap` struct definition |
| `goalc/build_level/jak1/build_level.cpp` | Level JSON → BSP pipeline, `tpages` and `textures` fields |
| `goalc/build_level/jak1/LevelFile.h` | `TexRemap`, `LevelFile` structs |
| `goalc/data_compiler/DataObjectGenerator.h/.cpp` | .go file binary writer |
| `goalc/data_compiler/dir_tpages.cpp` | dir-tpages.go writer (reference for format) |
| `game/graphics/opengl_renderer/loader/LoaderStages.cpp` | `add_texture()` — FR3 → GPU upload |
| `game/graphics/opengl_renderer/foreground/Merc2.cpp` | PC merc draw, texture binding |
| `game/graphics/texture/TexturePool.cpp` | PC texture pool, VRAM simulation |
| `game/graphics/texture/TextureID.h` | `PcTextureId` struct |
| `common/texture/texture_conversion.h` | PS2 address functions (psmct32_addr, psmt8_addr, etc.) |
| `common/versions/versions.h` | `TX_PAGE_VERSION = 7` for Jak1 |
| `decompiler/config/jak1/ntsc_v1/tex-info.min.json` | combo_id → texture name/tpage mapping for all ~4000 textures |
