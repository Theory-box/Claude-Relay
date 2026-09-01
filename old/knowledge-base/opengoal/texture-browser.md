# OpenGOAL Texture Browser — Addon Reference

**Added:** April 2026 (v1.8.0)
**Module:** `addons/opengoal_tools/textures.py`

---

## Overview

The Texturing panel provides an in-Blender browser for all 4,002 extracted Jak 1 textures. It allows previewing and applying textures directly to mesh objects without leaving Blender.

---

## Requirements

The decompiler must have been run with `save_texture_pngs: true`. This is **not** the default. To enable:

1. Edit `<data_path>/data/decompiler/config/jak1/jak1_config.jsonc`
2. Find `"save_texture_pngs": false` and change to `true`
3. Re-run the decompiler/extractor on the ISO

Once extracted, all PNGs live at:
```
<data_path>/data/decompiler_out/jak1/textures/<tpage_name>/<texture_name>.png
```

A confirmed working install has 4,002 PNGs across 126 tpage folders.

---

## Tpage Groups

| Group | Tpage folder prefixes |
|---|---|
| All | (all folders) |
| Common | `common` |
| Effects | `effects`, `environment-generic`, `ocean` |
| Characters | `eichar`, `sidekick-lod0` |
| Beach | `beach-vis-*` |
| Jungle | `jungle-vis-*`, `jungleb-vis-*` |
| Swamp | `swamp-vis-*` |
| Misty | `misty-vis-*` |
| Snow | `snow-vis-*` |
| Fire Canyon | `firecanyon-vis-*` |
| Lava Tube | `lavatube-vis-*` |
| Ogre | `ogre-vis-*` |
| Sunken | `sunken-vis-*`, `sunkenb-vis-*` |
| Rolling | `rolling-vis-*` |
| Cave | `maincave-vis-*`, `darkcave-vis-*`, `robocave-vis-*` |
| Village | `village1-vis-*`, `village2-vis-*`, `village3-vis-*` |
| Training | `training-vis-*` |
| Citadel | `citadel-vis-*` |
| Final Boss | `finalboss-vis-*` |
| HUD / UI | `Hud`, `zoomerhud`, `gamefontnew` |

### Tpage suffix meanings
- `pris` — entity/character textures (enemies, NPCs, objects)
- `tfrag` — terrain geometry (ground, walls, floors)
- `shrub` — foliage and background geometry
- `alpha` — transparent/blended surfaces
- `water` — water surfaces

---

## Panel Behaviour

- **Poll:** Only visible when at least one mesh object is selected
- **Load:** Lazy-loads PNGs for the selected group into Blender's preview collection. Cached — switching back to an already-loaded group is instant
- **Search:** Live filter on the loaded group's textures — no reload needed
- **Grid:** 4 columns, 20 textures per page. Selected texture is highlighted with a box
- **Pagination:** Prev/next buttons with `Page N / M (X textures)` counter. Page resets to 0 on new Load or search change
- **Apply to Selected:** Creates a `Principled BSDF + Image Texture` material named `og_<texture_name>`. Reuses existing material if already created this session. Assigns to slot 0 of all selected mesh objects

---

## Material Created

```
[Image Texture node] → Base Color → [Principled BSDF] → [Material Output]
```

- Material name: `og_<texture_name>` (e.g. `og_bab-allfur`)
- Image colorspace: sRGB
- Image block name: `<texture_name>.png`
- The PNG path is absolute — materials reference the decompiler_out folder directly

**Note:** These materials are for visual reference only. They do not affect texture IDs in the JSONC export or the FR3 texture pipeline. Tpage selection for the level build is controlled by the actor types placed, not by materials assigned to meshes.

---

## Preview Collection

One global `bpy.utils.previews.ImagePreviewCollection` is used. It is:
- Created in `register_texturing()` at addon load
- Cleared and refilled on each `Load` press (group change)
- Fully released in `unregister_texturing()` at addon unload

Loading a large group (e.g. "All" — 4,002 textures) takes a few seconds on first load. Subsequent opens of the same group are instant.

---

## Scene Properties (on `og_props`)

| Property | Type | Default | Purpose |
|---|---|---|---|
| `tex_group` | EnumProperty | `"BEACH"` | Active tpage group |
| `tex_page` | IntProperty | `0` | Current page index |
| `tex_search` | StringProperty | `""` | Live search filter |
| `tex_selected` | StringProperty | `""` | Name of selected texture |

---

## Diagnostic Script

`scratch/texture_diagnostic.py` — run in Blender Scripting tab to confirm:
- Addon is enabled and `data_path` is set
- Decompiler output structure is correct
- Texture folders exist and PNGs are present
- `tex-info.min.json` is findable
- GLB probe passes (confirms path pattern)

Paste the output when debugging path issues.
