# v0.16.5: Geometry-First Loading (built into the addon)

**Date:** 2026-09-16
**Setup:** Blender 4.4.3, RTX 4090.
**Installed:** `%APPDATA%\Blender Foundation\Blender\4.4\scripts\addons\vertex_lit_renderer`
**Repo copy:** `Claude-Relay/addons/vertex_lit_renderer` updated (the old v0.13.8 copy is backed up in the scratchpad).

**Backup:** v0.16.4 is in the scratchpad at `v0164/`.
**Changed files:** only `engine.py` and `__init__.py`. Shadows are untouched as asked (they still work, built from the new cache).

## What changed (engine.py)

| | v0.16.4 | v0.16.5 |
|---|---|---|
| mesh upload | one batch **per material slot**, per-triangle-corner arrays (`batch_for_shader`) | one batch **per mesh**: per-corner position buffer, and a second buffer (normal/vertColor/texCoord) attached with `vertbuf_add`. Triangles are sorted by material in **one index buffer**, and each slot draws its range (`_RangeDraw` → `GPUBatch.draw_range`). Uploaded once. |
| textures | loaded inside extraction (1.7 s on Azola) | `_stream_textures`: after geometry, smallest image files first, 50 ms per frame; F12 loads them all before drawing |
| change-detection hash on load | full buffer hash per object | none on the load path (`_cheap_sig`: counts + modifiers). Edits are still tracked by `view_update` / `_EDITED_WHILE_AWAY` |
| linked-duplicate sharing | content hash for every object | pointer key (`_geo_share_key`) for unmodified duplicates, costing nothing. Objects **with modifiers** are grouped by a cheap key, and only groups of 2+ pay the content hash (`_dup_candidate_key` + `_share_sig`) |
| streaming budget | 0.1 s per frame | 1.5 s per frame (a big load takes one or two short freezes); instances 0.03 s → 0.25 s |
| CPU memory kept per object | full per-slot arrays + `vert_co_local` + `vi_map` | per-corner positions + index buffer only (for the shadow batch) |

Unchanged:
- Draw loops, material programs, the ID/normal/AO passes: slot entries still unpack as `(drawable, material_name, texture)`.
- Edit mode (it still uses `_extract_mesh_data`).
- Fallback to the legacy path if a Blender build lacks `draw_range`/`vertbuf_add`.

Test-only switches, off by default:
- `VLR_KEEP_CPU_ARRAYS=1` keeps normals/UVs/colours on the CPU for the equivalence checks.
- `VLR_PROFILE_EXTRACT=1` records per-stage extraction times in `engine._EXTRACT_PROF`.

## Results

### Azola: viewport entry (394 objects, vegetation unhidden)

| | v0.16.4 | **v0.16.5** |
|---|---|---|
| all geometry on screen | 6.09 s | **2.86 s** |
| fully loaded (textures + material compile) | 6.69 s | **5.17 s** |
| warm re-entry | 0.04 s | 0.06 s |
| unique meshes / triangles | 268 / 12.26M | 269 / 12.76M |
| every cached object vs a fresh `_extract_mesh_data` (positions, normals, UVs, colours, material per slot) | 393/394 | **393/394**: only `Cube.124` colours, the older material-colour issue (see TEST_v0.16.3.md) |

Of the fully-loaded time, 1.7 s is textures streaming in. Three 10,800×7,200 packed JPEGs account for about 1.6 s of that, each causing a ~0.5 s hitch.

### Azola: F12 (25%)

| | v0.16.4 | **v0.16.5** |
|---|---|---|
| wall | 14.58 s | **12.37 s** |
| geometry extraction | 9.24 s (textures included) | **3.52 s** (264 extractions, 17.9M triangles) |
| change-detection hash | 2.97 s | 0 |
| textures | (inside extraction) | 5.45 s (cold image decode) |
| draw | 1.02 s | 0.96 s |
| objects drawn | 382/382 | **382/382** |
| image | mean 0.3987 / std 0.2462 | **identical** |

### Generated scene (`auto_test_v0161.py`)

| check | v0.16.4 | **v0.16.5** |
|---|---|---|
| edits in Rendered (7 types + linked dup) | 12/12 | **12/12** |
| share cache over 20 edits | bounded | **bounded** |
| edit in Solid after 2.5 s, then re-enter | 6/6 | **6/6** |
| instance streaming, 150 unique meshes | 150/150 in 1.3 s | **150/150 in 0.6 s** |
| selection click, 150 instance meshes | 2.5 ms | **2.7 ms** |
| instanced mesh edit (Rendered) | PASS | **PASS** |
| F12 generated | 1.2 s | **0.63 s** |
| edit in Solid **immediately** (2 s window) | 0/6 | 0/6 *(still open from v0.16.4)* |
| instanced mesh edited in Solid | FAIL | FAIL *(still open from v0.16.4)* |

## Things I measured along the way (and fixed before shipping)

- **Sharing:** the first build shared linked duplicates only by evaluated-mesh pointer. Duplicates **with modifiers** each have their own evaluated mesh, so F12 extracted 344 meshes (57M triangles) instead of 264, and took 17.3 s. Fixed by the candidate-group hash described above.
- **Colour fill:** meshes without vertex colours filled per-corner colours by scattering through the triangle indices. Now it's one `np.repeat` of the face material index plus a palette lookup.

## Still open (not part of this change)

1. **Immediate Solid-view edits:** edits made in Solid within 2 s of leaving Rendered are lost (v0.16.4's timestamp guard). The fix is in TEST_v0.16.4.md.
2. **Instanced meshes edited while away** are never refreshed (TEST_v0.16.4.md).
3. **Flat material colour baked into vertex colours:** a material viewport colour change doesn't update loaded objects (`Cube.124`; TEST_v0.16.3.md).
4. **Huge textures:** a downscaled display copy of images over about 16 MP would remove the three 0.5 s texture hitches.
