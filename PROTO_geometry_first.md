# Prototype: Geometry-First Loading with Buffer Reuse

## v2 update (2026-09-16): linked-duplicate sharing + texture streaming

Same scene and settings as v1 below.

| milestone | engine today | v1 | **v2** |
|---|---|---|---|
| all geometry on screen | 6.09 s | 1.89 s | **1.32 s** |
| shaded, untextured (normals, UVs, colours attached) | – | – | **1.87 s** |
| fully loaded (textures) | 6.65 s | 4.55 s | **3.59 s** |
| GPU vertex data | 2,674 MB | 1,699 MB | **1,136 MB** (512 + 624) |
| identical to engine data | – | 394/394 | **394/394** (shared objects included) |

**Sharing:**
- **Key:** the evaluated mesh pointer (`eo.data.as_pointer()`). 394 objects become **348 unique meshes** and 12.32M unique triangles (18.57M drawn).
- **Materials stay per object:** colours and textures are draw-time uniforms, so linked duplicates with *different* materials still share geometry.
- **Cost:** the share lookup takes 1 ms. No hashing.
- **Comparison with the engine:** its hash-based share finds 268 unique meshes. That's more merging, but it costs the 0.84 s signature. The triangle totals are almost the same (12.26M vs 12.32M): the extra 80 unique meshes are small.

**Texture streaming does not slow pass 1:** geometry is on screen before any texture work starts. But streaming didn't smooth the load: **5 frames of about 550 ms each**, because a single image can't be split across frames. The cause is concentrated in three images:

| image | size | load |
|---|---|---|
| `02_Drawing Set (2).jpg` | 10799×7199, packed JPEG | 554 ms |
| `02_Drawing Set (2)FITNESS.jpg` | 10799×7199, packed JPEG | 541 ms |
| `02_Drawing Set (2)-0021.jpg` | 10800×7200, packed JPEG | 513 ms |
| all other textures (243 textured material slots) | ≤2048² | ~0.1 s total |

These three ~78-megapixel reference sheets are **1.61 s of the 1.70 s**. Without them, the scene is fully loaded at about **2.0 s**.

**Recommendations for textures:**
- load textures smallest first, so the whole scene is textured at about 2.0 s;
- load huge images (over about 16 MP) last, one per frame;
- or cache a downscaled GPU copy of oversized images (the screen can't show 10.8K texels on a plane anyway), which would remove the half-second hitches entirely.

**Date:** 2026-09-16
**Script:** `apps/splat-viewer/proto_geo_first.py`
**Scene:** Azola, 394 objects with the vegetation unhidden, the same configuration as the 5.86 s / 6.65 s entry numbers.
**Safety:** the engine was not modified, and the file was never saved.

## Result

| | engine v0.16.x today | **prototype** |
|---|---|---|
| **all geometry on screen** | 6.09 s (streamed over 13 frames) | **1.89 s** (one freeze) |
| **fully shaded** (normals, UVs, colours, textures) | 6.65 s | **4.55 s** (+0.32 s material compile, not included in the prototype) |
| GPU vertex data | 2,674 MB (48 B per triangle corner) | **1,699 MB** (751 MB pass 1 + 948 MB pass 2), each uploaded **once** |
| redraw of all objects | – | 3–4 ms (simple shaders) |
| identical to engine data | – | **394/394 objects, 0 mismatches** |

**Breakdown:**
- **Pass 1:** read + material sort 1.25 s, build buffers 0.32 s, first draw (GPU upload) 0.32 s.
- **Pass 2:** read 0.16 s, build + attach 0.34 s, **textures 1.80 s**, first draw 0.37 s.

**Important:** the prototype has **no linked-duplicate sharing**. It processed **18.57M triangles**, while the engine shares down to 12.26M. With sharing, pass 1 should drop further, to about 1.3 s (estimate, scaled by triangle count).

Images: `proto_pass1_geometry.png` (faceted, flat colour) and `proto_pass2_full.png` (same buffers, with normals, UVs and textures added).

## Design

**Pass 1: geometry, all objects in one frame.** Per object:
- **one vertex buffer** of positions **per face corner** (`position[corner_vert]`, read from raw mesh memory);
- **one index buffer** of triangles (corner indices), **sorted by material** with a stable argsort, so each material slot is a contiguous `(start, count)` range;
- drawn with `batch.draw_range(shader, elem_start, elem_count)` per material, using the material's flat viewport colour and faceted normals from `dFdx/dFdy`.

**Pass 2: everything else, reusing pass 1's buffers.** Per object:
- **one more vertex buffer** (corner normals, UVs, vertex colours), same length, attached with `batch.vertbuf_add(vbo2)`;
- base-colour textures.

Positions and indices are never uploaded again.

**Why per-corner vertices (not per-vertex):** UVs and split/sharp normals live on corners. Corner-indexed positions let pass 2 attach them to the same vertices; a per-vertex layout would force a re-upload. Azola has 44M corners against 55.7M triangle corners in the current layout, so this is still smaller.

**Why sorting triangles by material is good:** it costs one stable sort (the engine already does the equivalent). Every material becomes one draw range, with no per-material buffers and no copies.

## API checks (Blender 4.4.3)

- `GPUBatch.draw_range`: works.
- `GPUBatch.vertbuf_add`, after the batch has already been drawn: works.
- `GPUIndexBuf(type='TRIS', seq=<(n,3) uint32 numpy>)`: accepted directly through the buffer protocol, with no Python list.

## Notes for integrating into the engine

1. **Slots become ranges:** `_mesh_cache` slots turn from per-slot flattened arrays into `(material, start, count)` ranges plus the shared buffers. Everything that reads `slot['positions']` etc. must switch to the new layout. That includes the shadow batch builder, `vi_map`/`vert_co_local` users, edit mode, and the test harness's compare.
2. **Shadow pass:** it only needs positions, so it can draw the **same** pass-1 batch. The separate shadow extraction and upload disappear.
3. **Linked duplicates:** share the whole batch (positions, indices and pass-2 buffer) by share signature.
4. **Defer the change-detection signature:** on a cold load nothing is cached, so hashing (0.84 s on Azola) can be skipped in pass 1 and computed afterwards.
5. **Textures are the largest remaining cost (1.8 s):** keep them progressive (per-frame budget) after pass 1. The scene is interactive while they arrive, and pass 2's attribute buffers are cheap enough to attach in one go (0.5 s).
6. **Vertex colours:** the colour-attribute choice (active colour, else the first one; uniform colour counts as none) matches the engine exactly (verified).
