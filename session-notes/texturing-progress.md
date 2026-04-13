# OpenGOAL Texturing Panel — Session Notes
Last updated: April 8, 2026

---

## Branch: `feature/texturing`

Created from `main`. No working code yet — research + planning phase complete.

---

## What We Know (Research Summary)

### The Texture Data

OpenGOAL's decompiler processes all Jak 1 textures from the ISO. There are:
- **4,003 named textures** across **127 tpages**
- Fully documented in: `decompiler/config/jak1/ntsc_v1/tex-info.min.json` (in jak-project repo)
- Each entry: `[numeric_id, {idx, name, tpage_name}]`
- Example: `[105447426, {"idx": 2, "name": "demo5cj", "tpage_name": "demo5j"}]`

### The PNG Files

The decompiler has a `"save_texture_pngs": false` flag in `jak1_config.jsonc`.
When set to `true`, PNGs are extracted to:
```
<data_folder>/decompiler_out/jak1/textures/<tpage_name>/<texture_name>.png
```
We already store `data_folder` in addon preferences — so we can construct this path.

**Key problem:** Most users will NOT have run decompile with `save_texture_pngs: true`.
The config file lives at: `<data_folder>/data/decompiler/config/jak1/jak1_config.jsonc`

### Tpage Groups (for UI categories)

| Group Label | Tpages |
|---|---|
| Common | `common` |
| Beach | `beach-vis-*` |
| Jungle | `jungle-vis-*`, `jungleb-vis-*` |
| Swamp | `swamp-vis-*` |
| Snow | `snow-vis-*` |
| Misty | `misty-vis-*` |
| Sunken | `sunken-vis-*`, `sunkenb-vis-*` |
| Rolling | `rolling-vis-*` |
| Fire Canyon | `firecanyon-vis-*` |
| Lava Tube | `lavatube-vis-*` |
| Ogre | `ogre-vis-*` |
| Cave | `maincave-vis-*`, `darkcave-vis-*`, `robocave-vis-*` |
| Citadel | `citadel-vis-*` |
| Final Boss | `finalboss-vis-*` |
| Village | `village1-vis-*`, `village2-vis-*`, `village3-vis-*` |
| Training | `training-vis-*` |
| HUD / UI | `Hud`, `zoomerhud`, `gamefontnew` |
| Characters | `eichar`, `sidekick-lod0` |
| Effects | `effects`, `environment-generic`, `ocean` |
| Demo | `demo*` (skip in UI — not useful for modding) |
| Other | `placeholder`, `title-vis-*`, `intro-vis-*` |

### Tpage suffix meanings (for future reference)
- `tfrag` — terrain fragments (ground, walls)
- `pris` — prisms (characters, enemies, objects with lighting)
- `shrub` — foliage/background geometry
- `alpha` — transparent/blended geometry
- `water` — water surfaces

---

## UI Plan

### Panel: "🎨 Texturing" (new tab in N-panel)

```
┌─────────────────────────────┐
│  🎨 Texturing               │
├─────────────────────────────┤
│  Category: [Beach ▼]        │
│  Texture:  [beach-ground ▼] │  ← search popup
│                             │
│  ┌───────────────────────┐  │
│  │   [texture preview]   │  │  ← bpy.utils.previews
│  └───────────────────────┘  │
│                             │
│  [ Apply to Selected ]      │
├─────────────────────────────┤
│  ⚠ Textures not extracted.  │
│  [ Run Texture Extraction ] │  ← auto-decompile button
└─────────────────────────────┘
```

### Error States
1. **PNGs not found** — show warning box + "Run Texture Extraction" button
2. **No object selected** — grey out Apply button, tooltip explains
3. **data_path not set** — redirect to addon preferences (same as current behaviour)

---

## Implementation Plan

### Step 1: Texture Database (static, baked into addon)
- Parse `tex-info.min.json` once offline → generate a Python dict baked into the addon
- Structure: `TEXTURE_DB = { tpage_name: [tex_name, ...], ... }`
- This means no file dependency at runtime for the name list — only for PNG previews
- ~4,000 entries is fine in memory

### Step 2: Auto-Decompile Button
- Operator: `OG_OT_ExtractTextures`
- Steps:
  1. Find `<data_folder>/data/decompiler/config/jak1/jak1_config.jsonc`
  2. Read it, find `"save_texture_pngs": false`, replace with `true`
  3. Write it back
  4. Launch the extractor: `<exe_folder>/extractor.exe <iso_path>` or equivalent OpenGOAL CLI
  5. Show a modal progress dialog or just log output
- **Open question**: What is the exact extractor binary name and CLI args?
  - Likely `extractor` or `jak_extractor` in the exe folder
  - Need to test — may need the original ISO path (user might not have it accessible)
  - Fallback: open a dialog telling user exactly what to do manually

### Step 3: Preview System (bpy.utils.previews)
- Create a global `PreviewCollection` at addon register time
- Load PNGs lazily: only load when a texture is selected/hovered
- Cache by `tpage_name/texture_name` key
- Invalidate cache if data_path changes (use a simple hash/mtime check)
- Display using `layout.template_icon(icon_value=..., scale=8.0)` in the panel

### Step 4: Category + Search Popup
- Category: `EnumProperty` with tpage group names
- Texture picker: `invoke_search_popup` operator (same pattern as sound picker)
  - Filter by selected category
  - Items include preview icon if PNG is available, else default IMAGE_DATA icon
- Selected texture stored as `StringProperty` on scene

### Step 5: Apply to Object
- Operator: `OG_OT_ApplyTexture`
- Creates a new Principled BSDF material
- Adds Image Texture node, loads the PNG from decompiler_out path
- Assigns to active object
- Does NOT add tpages to export yet — that's a future complexity

---

## Known Open Questions

1. **Extractor CLI** — what binary + args does OpenGOAL use to run the decompiler?
   - Probably `extractor.exe <iso_path>` — needs verification against actual install
   - May need to locate the ISO path (user may have moved it)

2. **tpage → export dependency** — when a user applies a texture from e.g. `beach-vis-tfrag`,
   should the addon automatically add beach tpages to the `.gd` export?
   - This is non-trivial: it adds a real runtime dependency
   - Probably phase 2 — for now, just show a note "this texture is from beach tpages"

3. **Preview performance** — 4,003 PNGs is a lot. Loading all previews upfront would be slow.
   - Solution: load only the visible category on category change, lazy-load on selection
   - Blender's own preview system handles this well with `pcoll.load()`

4. **NTSC vs PAL** — tex-info.min.json is in the `ntsc_v1` folder. PAL may differ slightly.
   - For now: target NTSC. PAL support later.

---

## Files

- `addons/opengoal_tools.py` on `feature/texturing` — working file (copy from main, not yet modified)
- `session-notes/texturing-progress.md` — this file
- `knowledge-base/opengoal/modding-addon.md` — existing addon knowledge (do not overwrite)

## Status
- [x] Research complete
- [x] Branch created: `feature/texturing`
- [ ] Texture database dict generated
- [ ] Panel UI skeleton
- [ ] Error handling / extraction button
- [ ] Preview system
- [ ] Apply operator

---

## Implementation Session — April 2026

**Branch:** feature/texturing
**Status:** Built, 35/35 tests passing — awaiting in-Blender test

### What was built

**textures.py** — new standalone module:
- `OG_PT_Texturing` — panel in OpenGOAL tab, polls for mesh selection
- 20 tpage groups matching diagnostic output (Beach, Jungle, Swamp, etc.)
- `OG_OT_LoadTextures` — loads PNGs for selected group into preview collection
- `OG_OT_TexPagePrev` / `OG_OT_TexPageNext` — pagination (20 per page)
- `OG_OT_SelectTexture` — sets tex_selected on click
- `OG_OT_ApplyTexture` — builds Principled BSDF material, assigns to selected meshes
- `_load_group()` — lazy-loads PNGs per group, caches, clears on group change
- Search bar filters loaded items live (no reload needed)
- Graceful WARNING state when textures/ folder missing

**properties.py** — 4 new fields on OGProperties:
- `tex_group` — active tpage group (default: BEACH)
- `tex_page` — current page index
- `tex_search` — live search filter string
- `tex_selected` — name of selected texture

**__init__.py** — TEXTURING_CLASSES tuple, register/unregister_texturing()

### Texture path (confirmed from diagnostic)
`<data_path>/data/decompiler_out/jak1/textures/<tpage_name>/<tex_name>.png`

### Test checklist (to run in real Blender)
- [ ] Panel appears when a mesh is selected
- [ ] Panel hidden when no mesh selected
- [ ] Load button fills grid with texture previews
- [ ] Search filters correctly
- [ ] Pagination works (prev/next, page counter)
- [ ] Click texture → highlights selected, shows name + source tpage below
- [ ] Apply to Selected creates material and assigns it
- [ ] Selecting a different group and pressing Load replaces previews
- [ ] Warning state shown if data_path not set / textures not extracted

