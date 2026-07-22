# OpenGOAL Jak 1 — Tpage Heap Research
**Researched:** April 2026  
**Branch context:** feature/tpage-combine  
**Sources:** jak-project source (build_level.cpp, texture.gc, level.gc, extract_merc.cpp, merc_replacement.cpp, gltf_util.cpp, Merc2.cpp, LoaderStages.cpp, loader.gc, process-drawable.gc)  
**Confidence:** High — all findings from direct source reading

---

## 1. The Problem

Jak 1 custom levels crash or corrupt when mixing enemies from more than ~2 different source zones. The root cause is the **GOAL level heap**, a fixed-size memory arena that holds level data at runtime.

`LEVEL_HEAP_SIZE = 10416 * 1024` bytes (~10MB), defined as a compile-time constant in `goal_src/jak1/engine/level/level.gc`. This heap holds:
- Level BSP geometry (tfrag, shrub, tie) — typically 2–5MB  
- All tpage `.go` files with PS2 pixel data — **1.7–2.5MB each**
- Entity process heaps, link tables, misc allocations

Each enemy from a different source zone requires its home level's `vis-pris` tpage to be loaded in full:

| Enemy | Tpage | Approx size |
|---|---|---|
| Kermit | swamp-vis-pris (659) | ~1.8MB |
| Lurker Crab | beach-vis-pris (214) | ~2.5MB |
| Hopper/Babak | jungle-vis-pris (385) | ~2MB |
| Snow Bunny | snow-vis-pris (842) | ~1.7MB |

3 cross-zone enemies = ~6MB tpages + geometry + overhead = heap overflow.

---

## 2. Two Completely Separate Texture Pipelines

Understanding the fix requires understanding that OpenGOAL runs two independent texture systems in parallel:

### GOAL/PS2 Pipeline (heap-constrained)
- `texture-ids` array in BSP header → `login-level-textures` → `texture-page-login` → `loado` loads `tpage-NNN.go` binary into level heap
- Each tpage `.go` contains full PS2 GS pixel data (PSMT8+CLUT32, pre-scrambled)
- `adgif-shader-login` → `level-remap-texture` binary-searches `texture-remap-table` in BSP → links merc shader IDs to loaded tpage entries
- **This is what consumes heap and causes the crash**

### PC/FR3 Pipeline (heap-free)
- `.fr3` file contains raw RGBA pixel data in `tfrag3::Texture` structs
- Loaded by `Loader::upload_textures()` → `add_texture()` → `glTexImage2D()` — goes directly to GPU
- Each texture in FR3 has `combo_id` baked at build time by `extract_merc`
- At draw time: `Merc2` does `lev->textures[draw.tree_tex_id]` — a direct GL handle array index. **No pool lookup, no heap**
- GLTF-sourced textures (static meshes, custom models) have `combo_id = 0`, `load_to_pool = false` — they go into FR3 directly with no tpage reference at all

---

## 3. How Tpage Heap Loading Is Triggered

The chain that causes heap cost:

1. Level JSON `"tpages": [214, 659]` → sets `file.texture_ids` in BSP at offset 60
2. BSP is packed into the level DGO
3. At runtime: level DGO loads → BSP header linked → `login-level-textures` called from `level.gc:419`
4. `texture-page-login` called for each ID → `loado` loads `tpage-NNN.go` from DGO into level heap
5. Art group loads from same DGO → merc-ctrl shader slots reference original tpage IDs
6. `adgif-shader-login` links shaders to loaded tpage entries using remap table

**Key:** The heap cost is driven by `texture-ids` in the BSP, which is set by the `"tpages"` JSON field. The `"art_groups"` entry does not directly trigger tpage loads — it loads the art group binary (skeleton, animations, merc-ctrl) which is separate from the tpage pixel data. But the merc-ctrl shader slots reference original tpage IDs, which must be resolved against a loaded tpage or remapped.

---

## 4. Existing Vanilla JSON Fields (No Patching)

### `"textures"` — selective FR3 texture list
```json
"textures": [
  ["swamp-vis-pris", "kermit-ankle", "kermit-back", "kermit-belly"],
  ["beach-vis-pris", "crab-belt", "crab-shell-01"]
]
```
- Controls which textures get baked into the FR3 for the PC renderer
- Reduces FR3 file size — only 8 kermit textures instead of all 93 from swamp-vis-pris
- **Does NOT affect the heap.** GOAL still loads the full tpage `.go`
- Still worth doing — smaller FR3 = faster level load, less GPU memory

### `"tex_remap"` — copy remap table from existing level BSP
```json
"tex_remap": "village1"
```
- Copies village1's `texture-remap-table` from its BSP verbatim into your level's BSP
- Used for sky remapping. When `sky == tex_remap` and `tpages == []`, auto-fills `texture_ids` from the source level too
- **Not useful for cross-zone enemies** — no vanilla level has a remap table that covers enemy textures from other zones

### `"tpages"` — explicit tpage IDs to load
```json
"tpages": [214, 659]
```
- Directly sets `texture_ids` in BSP — each ID causes a full tpage `.go` heap load
- Setting this to `[]` (empty) prevents explicit tpage loads, but then shader links break unless `tex_remap` covers them

---

## 5. Exploits Investigated (No C++ Patching)

### Exploit A: `texture_replacements` (pixel swap — does not help heap)
Drop PNGs at `custom_assets/jak1/texture_replacements/<tpage_name>/<tex_name>.png` or `_all/<tex_name>.png`. The build system replaces pixel data in `tex_db` before `extract_merc` runs — same `combo_id`, different pixels. FR3 gets your art, but GOAL still loads the original tpage on heap. **Useful for reskinning, not memory.**

### Exploit B: `merc_replacements` (mesh+texture swap — does not help heap)
Drop a GLB at `custom_assets/jak1/merc_replacements/kermit-lod0.glb`. The build system replaces the mesh geometry and textures. Replacement textures get `combo_id = 0`, `load_to_pool = false` — **PC-only, no heap cost for the new textures**. Bone weights are automatically transferred by nearest-vertex proximity (`find_closest`) — **you do not need to rig the replacement model**. However the original art group is still processed (to extract old verts for weight transfer), so the tpage still loads on heap. **Useful for custom enemy appearances without rigging, not memory.**

### Exploit C: `custom_models` (GLTF merc — cannot fully replace art_groups)
Level JSON `"custom_models": ["kermit"]` → `add_model_to_level` → `load_merc_model` → GLTF loaded, textures get `combo_id = 0`, `load_to_pool = false` → zero heap cost for textures. However:
- Requires a rigged GLB with `JOINTS_0` / `WEIGHTS_0` data (no auto weight transfer)
- OpenGOAL can export existing enemies as rigged GLBs via `save_level_foreground_as_gltf` — so you're re-importing the game's own data, not rigging from scratch
- **The wall:** `art_groups` entry cannot be removed. `initialize-skeleton` in `process-drawable.gc` calls `load-to-heap-by-name` → `art-group-load-check` → `loado`. Without the art group on heap (skeleton, animations, merc-ctrl), the GOAL entity calls `(go process-drawable-art-error "art-group")` and dies. The PC renderer's `get_merc_model` lookup and the GOAL `art-group-get-by-name` are completely separate systems that happen to use the same name string — they cannot substitute for each other.

**Summary of vanilla exploits:** None eliminate the heap cost. All routes that touch the PC renderer (FR3/GLTF) are heap-free for *their* textures, but the GOAL process mandatorily loads the art group + tpage from DGO.

---

## 6. The Heap Size Itself

`LEVEL_HEAP_SIZE` is defined **once** in `goal_src/jak1/engine/level/level.gc`:

```lisp
(#cond
  (PC_PORT
   (defconstant LEVEL_HEAP_SIZE (* 10416 1024))
   (defconstant LEVEL_HEAP_SIZE_DEBUG (* 11000 1024)))
  (#t
   (defconstant LEVEL_HEAP_SIZE (* 10416 1024))
   (defconstant LEVEL_HEAP_SIZE_DEBUG (* 25600 1024))))
```

`alloc-levels!` is always called with `compact-level-heaps = #f`, meaning it always uses `LEVEL_HEAP_SIZE` (not debug). On the PC port this is still 10416KB — the debug value was not increased for PC. `level.gc` compiles to `level.o`, which is packed into `GAME.CGO` along with the rest of the engine. This means:

- **Increasing `LEVEL_HEAP_SIZE` requires recompiling `level.gc` via the GOAL compiler (`goalc`)** — not rebuilding any C++ code
- `goalc` is already built as part of the standard OpenGOAL install
- The GOAL compile step is what the addon runs for custom levels anyway
- The heap is allocated from the global GOAL heap via `malloc 'global` — on PC there is no 32MB RAM cap, so a larger value should work up to available system RAM

There is also a **VRAM constraint** (`COMMON_SEGMENT_WORDS = #x1c000` ≈ 0.5MB for the common segment that holds pris textures) — but on PC, `__pc-texture-upload-now` calls the PC renderer's `texture_upload_now` hook which uploads directly to OpenGL. The VRAM "overflow" check in `texture-page-size-check` prints a warning but does not crash or block loading on PC. The PS2 VRAM limit is not a real constraint on PC.

---

## 7. Solutions Ranked

### Option 1: Increase `LEVEL_HEAP_SIZE` in level.gc ⭐ Easiest, no C++ patch

**Change:** Edit `goal_src/jak1/engine/level/level.gc` line 827–831:
```lisp
(#cond
  (PC_PORT
   (defconstant LEVEL_HEAP_SIZE (* 24000 1024))   ; was 10416
   (defconstant LEVEL_HEAP_SIZE_DEBUG (* 24000 1024)))
  ...)
```

**What's required:**
- Edit one constant in one `.gc` file
- Re-run the GOAL compiler (`(mi)` in the REPL, or the addon's build pipeline) to recompile `level.gc` → `level.o` → repack `GAME.CGO`
- The addon's build pipeline already triggers this when building a level

**Risks:**
- Two level heaps are allocated simultaneously (`level0` and `level1`). Increasing from 10MB to 24MB doubles that to 48MB total from the global heap — trivial on modern PC
- No PS2 compatibility concern — this is PC-only (guarded by `PC_PORT`)
- Does not require forking jak-project — users can patch their local install
- **This is a one-line GOAL change, not a C++ patch**

**Could be upstreamed:** A PR to increase `LEVEL_HEAP_SIZE` on `PC_PORT` is a completely reasonable ask. The PS2 was constrained to 32MB total RAM; PC has no such constraint. The OpenGOAL team's goal is parity + modding, and this directly enables richer custom levels.

---

### Option 2: `custom_tex_remap` C++ patch (existing tpage-combine branch)

**Change:** 25 lines in `goalc/build_level/jak1/build_level.cpp`. Adds a `"custom_tex_remap"` JSON field to emit a custom remap table + skeleton tpage `.go` file with no pixel data.

**What's required:**
- Patch C++ build tool (goalc)
- Rebuild goalc from source
- Generate skeleton `.go` files for each custom level

**The correct approach:** Submit as PR to jak-project upstream. The patch is clean, well-scoped, and solves a real modding problem. If merged, it becomes available to all modders without forking.

---

### Option 3: `"textures"` selective list (always do this regardless)

Not a heap fix, but should always be used alongside either of the above. Keeps FR3 lean — for each enemy, list only the textures that enemy actually uses:

```json
"textures": [
  ["swamp-vis-pris", "kermit-ankle", "kermit-back", "kermit-belly", "kermit-tan", "kermit-eye-1", "kermit-eye-2", "kermit-mouth"],
  ["beach-vis-pris", "crab-belt", "crab-folds", "crab-shell-01", "crab-shell-02", "crab-shell-03", "crab-tan"]
]
```

This is pure upside — smaller FR3, faster level load time, less GPU memory — and works with vanilla OpenGOAL today, no changes needed.

---

### Option 4: `merc_replacements` for reskinning (no heap benefit, but useful)

If visual variety is the goal rather than cross-zone entity mixing, `merc_replacements` lets you give any enemy custom textures/mesh with zero extra heap cost and no rigging work. The weight transfer is automatic. This is the path for "I want a unique-looking enemy" without touching the memory system.

---

## 8. Recommended Action Plan

**Immediate (no install changes needed):**
1. Add `"textures"` selective lists to all custom levels now — free FR3 savings

**For the heap fix — two parallel tracks:**
- **Track A (local):** Modify `LEVEL_HEAP_SIZE` in `level.gc` on the user's local OpenGOAL install. One-line change, GOAL recompile only. Addon can guide the user through this or even automate it.
- **Track B (upstream):** Open a PR to jak-project proposing `LEVEL_HEAP_SIZE` increase under `PC_PORT` guard. Benefits the entire modding community.

**The `custom_tex_remap` C++ patch** (feature/tpage-combine branch) is the more surgical fix and should be proposed as a separate upstream PR. It's the correct long-term solution for production use because it doesn't inflate heap for levels that don't need it — only the specific textures referenced actually load.

---

## 9. Key Source File Reference

| File | Relevance |
|---|---|
| `goal_src/jak1/engine/level/level.gc:827` | `LEVEL_HEAP_SIZE` constant — the one-line fix |
| `goal_src/jak1/engine/gfx/texture/texture.gc:1290` | `login-level-textures` — tpage heap load trigger |
| `goal_src/jak1/engine/gfx/texture/texture.gc:1806` | `texture-page-login` → `loado` — actual heap alloc |
| `goal_src/jak1/engine/common-obs/process-drawable.gc:337` | `initialize-skeleton` → `load-to-heap-by-name` — why art_groups can't be removed |
| `goalc/build_level/jak1/build_level.cpp:133` | `tex_remap`, `tpages` JSON field parsing |
| `goalc/build_level/jak1/build_level.cpp:266` | `"textures"` selective list — FR3 only |
| `goalc/build_level/common/build_level.cpp:45` | `add_model_to_level` — custom_models path |
| `decompiler/level_extractor/extract_merc.cpp:1621` | `replace_model` — merc_replacements path |
| `decompiler/level_extractor/merc_replacement.cpp:283` | `merc_convert_replacement` — auto weight transfer |
| `common/util/gltf_util.cpp:427` | GLTF textures get `combo_id=0`, `load_to_pool=false` |
| `game/graphics/opengl_renderer/loader/LoaderStages.cpp:12` | `add_texture` — load_to_pool=false means no pool registration |
| `game/graphics/opengl_renderer/foreground/Merc2.cpp:1261` | `lev->textures[draw.texture]` — direct GL handle, no tpage |
| `scratch/build_level_patch.diff` (Claude-Relay) | The existing C++ custom_tex_remap patch |

---

## 10. OOM Crash Budget Correction (source-verified April 2026)

Previous documentation said "~4MB free for tpage data." This was wrong. The correct model:

### Level heap layout during DGO load

```
heap base (0)
  ↓ content loads from bottom upward
  [BSP geometry: tfrag/tie/shrub]
  [tpage .go data — kicked off heap to VRAM after upload]
  [art group .go data — stays on heap]
  [entity process heaps, link tables]
  ↑ current (grows upward)

  ← 6.4MB free gap (roughly) →

  ↓ DGO load buffers allocated from top downward
  [dgo-level-buf-2: 2MB]   ← top - 2MB
  [dgo-level-buf-2: 2MB]   ← top - 4MB (= heap_top_base - 4MB)
heap top_base (10416 * 1024 ≈ 10.4MB)
```

Source: `level.gc` load-begin:
```lisp
(let ((s4-0 (kmalloc (-> this heap) (* 2 1024 1024) (kmalloc-flags align-64 top) "dgo-level-buf-2"))
      (s5-2 (kmalloc (-> this heap) (* 2 1024 1024) (kmalloc-flags align-64 top) "dgo-level-buf-2")))
```

The two 2MB buffers are allocated from the **top** of the heap on every DGO load start, and freed when load completes. The crash occurs when `heap.current` (bottom, growing up) meets the buffer region (top - 4MB = ~6.4MB from base). After load the buffers are freed, so runtime heap is the full 10.4MB.

### tpage data is evicted from heap

`texture-page-default-allocate` calls `remove-from-heap` after uploading to VRAM. In the PC port this still runs (not guarded by `#when PC_PORT`), so tpage `.go` data is evicted from the heap immediately after login. Tpages do NOT permanently occupy the level heap — only art group `.go` data does.

### Revised crash budget

| Component | Heap cost |
|---|---|
| DGO load buffers (temporary) | 4MB from top |
| BSP geometry (tfrag/tie/shrub) | 1–3MB |
| Art groups (.go, stays resident) | ~300–600KB each |
| Tpages (evicted after login) | 0 (transient during load only) |
| **Usable for content before OOM** | **~6.4MB sustained, ~5MB during active load** |

**Practical implication:** The "max 2 tpage groups" limit is primarily about the **load-time** peak when all tpages are loaded simultaneously before eviction, not the runtime steady state. Reducing tpage count helps load-time reliability but not runtime heap.

