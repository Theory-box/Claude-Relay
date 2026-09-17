# Vertex-Lit Renderer v0.16.0: Code Review

**Date:** 2026-09-15
**Scope:** the full installed addon (`%APPDATA%\Blender Foundation\Blender\4.4\scripts\addons\vertex_lit_renderer\`, 25 files)
**Method:** six parallel read-only reviews (engine ×2, splat sort/draw, splat gen/ops/tile, fx/props/ui, materials/shaders). Every critical and high claim was then re-checked by reading the code directly.

**Status: nothing has been fixed.** This is a record only.

**Confidence tags:**

- **[C] Confirmed.** I read the code and the failure follows directly from it.
- **[L] Likely.** The reasoning is sound but I didn't reproduce it.
- **[S] Speculative.**

Line numbers refer to the v0.16.0 files as installed.

---

## CRITICAL

### C1. `_force_full` never clears while streaming, so the load loops forever [C]
- **Location:** `engine.py:969-973, 984-985, 1024-1033` (the comment at `:706` is wrong)
- **Cause:** When `_force_full` is set, `to_do` is every visible object and `_geo_share` is wiped. `_force_full` is cleared only in the `else` branch (`:1031`), which runs only when nothing is left in the queue. While streaming, every following pass is "full" again, so the same first objects are re-extracted each frame. A set of the same keys iterates in the same order within a session, so the tail never loads.
- **Paths that set it:**
  - F12 `render()` (`:700`)
  - a colour-attribute change: `props.py:8` → `_FORCE_REEXTRACT` → `:1576`

  Normal viewport entry does **not** set it, which is why the Azola entry benchmarks streamed correctly.
- **Scenario:**
  - **F12:** a scene whose extraction takes more than 100 ms hangs F12 for the full 120 s deadline (`:704`), then renders with objects missing.
  - **Colour attribute:** changing the attribute on a heavy scene pegs the CPU with constant redraws, and most objects never come back.
- **Fix:** clear `_force_full` after the first pass has seeded the queue, and let `_dirty_objects` drain the rest. Also build `_geo_share` once per full load, not once per pass.

### C2. `_geo_share` hands stale geometry to edited objects [C]
- **Location:** `engine.py:984-1009`, with the signatures at `engine.py:103-130`
- **Cause:** `_geo_share` is reset only when `full` is set, so it effectively lives for the session. It is consulted **unconditionally**, even for objects explicitly in `_dirty_objects`.
  - `_geo_sig` contains only: mesh name, vertex and face counts, modifier type and visibility, and the rounded sum of 3 sampled vertices.
  - `_share_sig` adds materials and the view attribute.
  - Neither covers colours, UVs, material indices, smooth/flat shading, modifier parameters, or any vertex other than the 3 samples.
- **Scenario:** each of these hits the share cache and gets the **old** data back:
  - vertex paint (only the first stroke ever shows);
  - UV edits;
  - sculpting;
  - shape-key sliders;
  - Displace strength changes;
  - moving edit-mode vertices other than the first, middle and last (the edit reverts on Tab-out and flickers during editing, because the `_rebuild` at `:1598` overwrites the edit-path batch).

  It also leaks memory, since every signature ever seen is kept.
- **Fix:** reset `_geo_share` on every `_rebuild`, and never share-lookup a name that is in `_dirty_objects`. Sharing only needs to exist within one pass, for linked duplicates.

---

## HIGH

### H1. Deferred geometry-node/collection instances are dropped [C]
- **Location:** `engine.py:925-927` vs `engine.py:1029-1033`
- **Cause:** When the instance loop runs past its 30 ms budget, it sets `_geo_pending` and `_dirty`. The end of `_rebuild_inner` then clears both whenever the *non-instance* queue is empty.
- **Scenario:** a scatter with many unique meshes loads only the first ~30 ms of instances. The rest stay missing until some unrelated edit. F12 is affected too, because its drain loop checks `_geo_pending`.
- **Fix:** keep a separate `_inst_pending` flag and OR it into the final state.

### H2. Unified sort caches "done" before the sort succeeds [C]
- **Location:** `splat_unified.py:275` (`self._last = ...`) vs `:289` (`sort_existing` failure returns False)
- **Cause:** The throttle key is stored before key generation and sorting.
- **Scenario:** a sort fails once, or the first frame falls back. The next still frame matches `_last`, skips the sort, and draws an unfilled or stale index. The result is garbage or missing splats until the camera moves.
- **Fix:** set `_last` only after `sort_existing` returns True.

### H3. Film Transparent renders opaque [C]
- **Location:** `engine.py:1546` (`'clear_color': (wc[0], wc[1], wc[2], 1.0)`), used by `fx/pipeline.py:76`
- **Cause:** The G-buffer is always cleared to alpha 1.
- **Scenario:** with Film > Transparent on, the F12 result has the world colour baked in, so compositing over another plate doesn't work.
- **Fix:** use alpha 0 when `scene.render.film_transparent` is on, and skip the background draw.

### H4. Viewport colour management is not applied [C]
- **Location:** `engine.py:1742-1751`
- **Cause:** Both the raw and the managed branch finish with `gpu_extras.presets.draw_texture_2d`, which binds its own builtin `IMAGE` shader (`gpu_extras/presets.py:79/89`). That replaces the shader bound by `bind_display_space_shader`.
- **Scenario:** the Filmic/AgX view transform, Look, Exposure and Gamma have no effect in the viewport, so the viewport and F12 or Material Preview can disagree.
- **Fix:** draw the final quad yourself with a batch while the display-space shader is bound (the `bind_display_space_shader` → `batch.draw()` pattern), not with `draw_texture_2d`.

### H5. Geometry-node instances with the same mesh name collide [L]
- **Location:** `engine.py:916-936`, `_draw_key` at `engine.py:133-143`
- **Cause:** The instance key is `'i:' + mesh name`, and the first instance seen per frame wins.
- **Scenario:**
  - Two objects in a collection instance share the mesh "Cube", but one has a Bevel/Displace modifier or object-linked materials: both draw the same geometry.
  - Their signatures differ, so the entry flip-flops and re-extracts on every rebuild.
  - Different GN-generated meshes that happen to share a name also collide.
- **Fix:** include the source object and modifier state, or the evaluated mesh pointer, in the key.

### H6. Stale image references after undo blank the viewport [L]
- **Location:** `engine.py:1268-1269`
- **Cause:** `prog['samplers']` holds `bpy.types.Image` references across undo. `material_shader.invalidate()` runs only on file load, and `_get_gpu_tex(image)` is outside any try.
- **Scenario:** after undo, `image.name` raises `ReferenceError`. `view_draw` aborts on both the post and direct paths, and the viewport shows nothing.
- **Fix:** store image names and resolve them per frame, and invalidate on `undo_post`/`redo_post`.

### H7. Splat IDs restart at 1 each session, so stale anchors adopt the wrong cloud [C]
- **Location:** `splat_render.py:24-28` (`_next_id = [1]`), the anchor check at `engine.py:1698-1716`
- **Cause:** Clouds live only in memory, while anchors (`vlr_splat_id`) are saved in the .blend. After a reload the IDs restart.
- **Scenario:** open a file that has old anchors (for example `Tree example.blend`, with `_Splat.002`) and generate a new cloud. It gets id 1 or 2, and an old anchor with that id now draws the new cloud at the old anchor's transform.
- **Fix:** seed `_next_id` from the maximum `vlr_splat_id` in the file on load. Better still, key clouds by a UUID stored on the anchor, and mark anchors with no cloud as stale.

---

## MEDIUM: engine and streaming

### M1. Instance keys force a full rebuild on every depsgraph update [C]
- **Location:** `engine.py:861-864`
- **Cause:** `'i:<mesh>'` keys are never in `bpy.data.objects`, so the "deleted object" check always fires.
- **Scenario:** in a scatter scene, every selection click runs a full `_rebuild` plus a shadow re-render.
- **Fix:** skip keys that start with `i:`.

### M2. Shared `_PERSIST_*` caches across viewports and F12 [C]
- **Location:** `engine.py:945-950`, `1572-1576`, `698`
- **Cause:**
  - Every engine instance aliases the same dicts, and each prunes them against only its own visible set.
  - F12 clears them and refills them with render-depsgraph data without dirtying the viewports.
  - `_FORCE_REEXTRACT` clears them for everyone but only dirties the first engine that draws.
- **Scenario:**
  - Two viewports with different view layers evict each other's objects.
  - After F12 or a colour-attribute change, other viewports show render-resolution geometry or go blank until an edit.
- **Fix:** use per-engine caches, or a generation counter that every engine checks.

### M3. One global shadow map for all viewports [C for viewports / L for windows]
- **Location:** `engine.py:287` (global `_shadow_map`), `1044-1073`
- **Cause:** There is one map, but each engine has its own `_shadow_dirty` and `ls_mat`.
- **Scenario:**
  - Orbiting viewport A re-fits the map, and viewport B samples it with its own matrix, giving garbage shadows.
  - The FBO is created in one GL context, but framebuffers are not shared between contexts, so a viewport in a second window binds an invalid FBO.
- **Fix:** make the shadow map per engine.

### M4. Edit mode redraws and extracts every frame [C]
- **Location:** `engine.py:1579-1598`
- **Cause:**
  - `tag_redraw` is unconditional, and every frame does a full `to_mesh`, extract and upload.
  - It extracts the base mesh without modifiers.
  - The shadow batch is never updated.
- **Scenario:**
  - A 1M-poly object in edit mode burns CPU and GPU while idle, multiplied by the number of viewports.
  - Mirror and Subsurf results disappear while editing.
  - Shadows keep the pre-edit shape.
- **Fix:** extract only on a depsgraph geometry update, and tag a redraw only then.

### M5. Re-entry verify misses colour, UV and material changes [C]
- **Location:** `engine.py:955-965`
- **Cause:** The re-entry check compares `_geo_sig`, which has no colours, UVs or materials.
- **Scenario:** vertex paint in Solid mode, or reassign a material, then switch to Rendered: the old look is shown.
- **Fix:** add a colour/UV hash and the slot materials to the signature, or re-extract dirty-on-exit objects on re-entry.

### M6. F12 path issues [C]
- `engine.py:698` clears the shared viewport caches from the render thread (see M2).
- `engine.py:779` `rl.rect = arr.reshape(-1,4).tolist()` builds a Python list of float64 values. At 4K that is about 8.3M floats and several GB of transient memory, which is slow. Use `rl.rect = arr` directly, or a `foreach_set`-style buffer.
- The instance budget still applies during F12, so combined with H1, instances can be missing from the render.
- Render border and crop are not accounted for in the result size (reported by engine part 1; worth checking with a border render).

### M7. A huge single mesh stalls a frame (known) [C]
- **Location:** `engine.py:988`, `925`
- **Cause:** The budget is checked only between objects.
- **Scenario:** Tree example (325k faces) or any large object blocks one frame for its whole extraction time.

### M8. Material compile waits for geometry streaming (known) [C]
- **Location:** `engine.py:1205`
- H1 can also clear `_geo_pending` early, which is harmless here but shows the flags are unreliable.

### M9. Blended (transparent) materials are wrong in the auxiliary passes [C]
- **Location:** `engine.py:1328-1341`, `1478-1540`
- **Cause:**
  - The ID, normal and AO-occluder passes draw Blended objects as opaque, so outline and cavity are computed on glass, while the scene depth has none.
  - Splats draw after Blended meshes, so splats behind glass overwrite it (known).
- **Fix:** skip Blended materials in the aux passes, and draw splats before the transparent mesh pass.

## MEDIUM: splats

### M10. Sort direction uses M⁻¹ instead of Mᵀ [C]
- **Location:** `splat_render.py:431, 484, 499, 566` (`fwd_l = minv.to_3x3() @ fwd`)
- **Cause:** A view direction transforms into local space with the transpose of the linear part. The inverse is only equivalent for uniform scale without shear.
- **Scenario:** a splat anchor with non-uniform scale (a tree scaled 1×1×2) sorts in the wrong order, with visible popping and back splats drawn over front ones. The unified path uses world depth and is unaffected.
- **Fix:** `fwd_l = (mw.to_3x3().transposed() @ fwd).normalized()`.

### M11. The unified-sort throttle ignores projection, viewport size and scale [L]
- **Location:** `splat_unified.py:241-289`
- **Cause:**
  - The key is only camera position/forward, the instance matrices and the total.
  - A lens/FOV zoom or a viewport resize doesn't re-sort. The order barely depends on it, but the per-viewport cache is shared by every viewport through the global `SORTER`.
  - The movement threshold is absolute, so it doesn't scale with scene size.
- **Scenario:** two viewports looking from different angles each see the other's order on still frames.
- **Fix:** keep the sorter state per viewport (per region pointer), and make the threshold relative to scene extent.

### M12. The cavity normal pass uses CPU sort on the unified path [L]
- **Cause:** `_gpu_sort` is set on the `clouds` list (`engine.py:1360-1361`), but the unified path draws anchors from `SPLAT_CLOUDS`, which never get the flag.
- **Scenario:** the normal pass falls back to CPU sort, which is slow with Cavity on.
- **Fix:** set the flags on every anchored cloud.

### M13. Splat memory is never released [C]
- **Cause:**
  - `SPLAT_CLOUDS` entries are never removed; there is no free when an anchor is deleted.
  - Per-anchor sort caches (`splat_render.py:344-380`) are keyed by object name and never evicted.
  - `SORTER` textures grow to the largest total seen.
- **Scenario:** repeatedly generating and deleting clouds (or Shift+D, then delete) leaks GPU memory, which piles up over a session.
- **Fix:** prune to the live anchors each frame (or on a depsgraph update), and free the GPU textures.

### M14. The tile rasterizer ignores scene depth, and one success hides failed clouds [C]
- **Location:** `splat_tile.py:305-326`, `engine.py:1362-1387`
- **Cause:**
  - `composite()` draws a quad at `z=0.0` (window depth 0.5) with the depth test still set to LESS_EQUAL from the mesh pass.
  - The tile output has no depth.
  - `any_ok` returns after the first cloud succeeds.
- **Scenario:**
  - Scene geometry closer than depth 0.5 hides the whole splat image, and geometry beyond it never occludes the splats, so trees paint over a house in front of them.
  - A cloud whose tile render failed is not drawn at all.
- **Other tile issues:**
  - Tile resources are sized at the first viewport size, and the reuse key is stale.
  - The pair buffer can overflow with many splats per tile.
  - There is no per-cloud depth compositing.
- Only relevant when the tile option is on.

### M15. Splat generation robustness [C/L]
- **Decimate modifier leak** (`splat_gen.py:199-235`) [C]: `_vlr_dec` is not removed in `try/finally`, so an exception leaves the modifier on the user's mesh.
- **Alpha dropped** (`splat_gen.py:26`) [C]: `_bilinear(...)[:,:3]` discards alpha, so leaf cards with alpha-cut textures produce opaque rectangles of splats. This is a major quality issue for foliage.
- **Collection linking** (`splat_ops.py:38`) [C]: the operator links the anchor into `context.collection`. If the active collection is excluded, hidden or linked (read-only), the link fails or the anchor is invisible.
- **Undo** (`splat_ops.py:10`) [C]: the operator has no `'UNDO'` in `bl_options`, so Ctrl+Z after Convert behaves unpredictably. The cloud stays in memory while the anchor comes back, or the other way round.
- **Baking** [L]:
  - Materials without a Principled BSDF are not baked, and fall back silently.
  - The bake is RGBA8 (8-bit quantized, clipped linear) at a fixed 1024 (`splat_gen.py:91`), so splat colours band in the darks. See MS2.
  - Baking happens in world space.
- **"Vertex Color" option** [C per the reviewer]: the colour-source option is exposed but not implemented.
- **Clear operator:** leaves the anchor empties behind.
- **Material index:** out-of-range indices are clamped silently.
- **Failures:** many are caught and printed only.

---

## MEDIUM: fx / post pipeline

### M16. The supersampling downscale is point-sampled [L]
- **Location:** `fx/pipeline.py:134`
- **Cause:** `draw_texture_2d(cur, (0,0), w, h)` samples a 1.5×/2× texture with no `filter_mode(True)` and no box filter. The addon never sets `filter_mode` anywhere.
- **Scenario:** SSAA at 2× gives an aliased, nearest-sampled result, and 1.5× gives uneven sampling, so the setting buys little quality for its cost.
- **Fix:** add a real downsample pass (box, or a bilinear tap at pixel centres), which also fixes H4 if you draw it with the display shader.

### M17. SSAO exclusion compares non-linear depth [L]
- **Cause:** the exclusion test compares hardware (non-linear) depth values from the occluder buffer and the main buffer with a fixed epsilon.
- **Scenario:** it works near the camera and falsely excludes or includes objects in the distance.
- **Fix:** linearize both depths before comparing.

### M18. The occluder/ID/normal passes diverge from the main pass [L]
- **Cause:** the aux passes don't use the same cull, alpha-clip and instance handling as the main draw (see also M9).
- **Scenario:** outlines and AO appear on culled back faces or alpha-clipped holes.

---

## LOW

- **L1** `engine.py:1275, 1286`: the batch-failure self-heal pops `obj.name`, but instances are stored under `'i:<mesh>'`. The broken instance is never healed, the instancer's own entry is evicted, and no redraw is tagged. [C]
- **L2** `engine.py:1727-1728`: the code checks `post is not None`, which is always true, while the comment says `any_enabled(vls)`. Every frame goes through the offscreen pipeline. [C]
- **L3** `engine.py:1304, 1470, 1478-1539`:
  - `bpy.data.materials.get()` runs per slot per instance per frame;
  - with post effects on, `object_instances` is iterated 3-4 extra times per frame;
  - CPU cost grows with instance count. [C]
- **L4** `engine.py:1282` (`_slot` at `:576`): the legacy slot path uses the GPU texture captured at extraction, and `_invalidate_tex` doesn't update slots. Texture paint or image reload doesn't show until re-extract. [C]
- **L5** `engine.py:1304 / :856`, and `_tex_cache` keyed by name:
  - after renaming a material, it draws as base texture, and Blended turns opaque until re-extract;
  - after renaming an image, it can be missed. [C]
- **L6** `engine.py:1698-1716`: one `try` wraps the whole anchor loop, so a single anchor with a non-int `vlr_splat_id` hides **every** splat. [C]
- **L7** `_extract_mesh_data`, empty mesh: returns None, so the object keeps its old cached batch (a ghost of the deleted geometry). [L]
- **L8** `_extract_mesh_data`, colour attribute: a uniform colour attribute is treated as "no colour" (reported by engine part 1; behaviour choice, check intent). [S]
- **L9** `_extract_mesh_data` performance (the fast-extract code I added):
  - one `np.flatnonzero(tri_mi==k)` per material slot is O(tris × mats);
  - it's fine at typical slot counts, but an object with 50+ slots would be faster with one stable `argsort(tri_mi, kind='stable')` plus `bincount`;
  - output would be identical. [C, perf only]
- **L10** Raw-memory attribute access (`_raw_attr`, `_raw_corner_tris`): this relies on the Blender 4.x internal layout. It is covered by `tests/test_extract_identical.py`, so rerun that test on any Blender upgrade. [S]
- **L11** Splat radix: `_SCAN_FIX` cost is quadratic in blocks. It's fine at current sizes, but watch it above ~16M keys. [L]
- **L12** Splat radix: 7 shader compiles per anchor rather than once globally, which is a first-draw hitch per new cloud. [L]
- **L13** Splat radix: duplicate per-cloud upload, and 2× peak VRAM during rebuild. [L]
- **L14** Splat radix: the compute path shares `projtex` between clouds. It's latent today because draws are serialized. [S]
- **L15** `fx/pipeline.py:137-141`: `free()` doesn't release `_nrm`/`_nrm_depth`/`_nrm_fb`, so it leaks until garbage collection. [C]
- **L16** `fx/pipeline.py:70`: `ctx['texel']` is the supersampled texel size, so effect radii given in pixels shrink by the SS factor. AO and outline look thinner at 2×. [L]
- **L17** SSAO: possible NaN from `normalize(0)` / derivatives at depth discontinuities, which shows as isolated black pixels. [S]
- **L18** `bake.py:68`: `img.pixels = arr.reshape(-1).tolist()` is slow. Use `img.pixels.foreach_set(arr.ravel())`. [C]
- **L19** `engine.py:1789`: `bpy.types.Panel.__subclasses__()` is not recursive, so panels subclassed from an intermediate class are missed. Errors there are swallowed. [C]
- **L20** The view-mode memory is seeded incorrectly on first use (reported by the fx/props/ui reviewer). [S]

---

## Known limitations (by design, re-confirmed)

- **Backface Cull and Compute:** the unified path ignores both options (`SORTER.draw` has no parameter for them, `splat_unified.py:241`).
- **Splat softness:** one sigma for all clouds (`engine.py:1406`), although the comment above it claims per-cloud softness.
- **Unified instance cap:** `MAX_INSTANCES = 32` (`splat_unified.py:30`). Beyond that it falls back silently, with no UI warning.
- **Payload limit:** the payload is `inst<<24 | id`, so the unified path supports at most 16,777,215 splats per cloud and 256 instances. Nothing checks it.
- **`_failed_sig`:** after a unified failure, it stays on per-cloud mode until the signature changes. There is no retry and no message.
- **Stale splat anchors:** only `int(sid) in SPLAT_CLOUDS` is checked (see H7).

## Checked and OK

- GPU state (blend, depth mask, colour mask, viewport) is restored after the transparent pass, the background draw, splat draws and the shadow pass.
- The shadow batch's `vi_map` and `vert_co_local` are consistent with each other.
- Programs resolve once per frame, material params are set once per shader, and progressive compile always makes progress.
- `free()` releases the post pipeline and the edit temp mesh. `unregister` releases the GPU caches and the load handler.
- A post-pipeline exception falls back to a direct draw.
- Radix sort is correct: it matched CPU argsort in the earlier tests. The unified cross-cloud order is correct at all angles since v0.15.3.
- Fast extraction output is identical to v0.15.3 on all 394 + 247 + 1 test objects.

---

## Materials / shaders (`node_transpiler.py`, `material_shader.py`, `bake.py`, `glsl_lib.py`, `shaders.py`)

### MS1 (HIGH). Double type coercion produces GLSL that doesn't compile [C]
- **Location:** `node_transpiler.py:156-167, 205-226, 247-256`
- **Cause:** `_coerce` returns swizzles like `(e).x` and `(e).xyz`. `_typeof` doesn't recognise that form and falls through to `"vec4"` (`:167`). Group-input values are coerced once to the socket type (`:254`), and then again by the consumer inside the group.
- **Scenario:**
  - A Separate XYZ/Color, RGB node or Image Alpha feeds a *Float* group input, which inside drives a vector socket. The code produces `((…).x).xyz`, which is illegal GLSL.
  - A Tex Coord output feeds a *Vector* group input and is used as a colour, producing `(vec3).a`.
  - In both cases the whole material compile fails and quietly falls back to the legacy base-texture look. Any user node group with typed interface sockets can hit this.
- **Fix:** emit typed constructors (`float((e).x)`, `vec3((e).xyz)`), or record the result type of every coerced expression.

### MS2 (HIGH). Bakes are 8-bit and in the wrong colour space [C]
- **Location:** `bake.py:33, 66-68`
- **Cause:** `GPUOffScreen(res, res)` defaults to RGBA8, so linear shader output is clamped to [0,1] and quantized to 8 bits.
- **Scenario:**
  - `bake_material_to_image` writes those raw linear values into an 8-bit image that is tagged sRGB, so re-using the bake in a material decodes it a second time. It looks darker and more contrasty.
  - The splat bake (`splat_gen.py:91`) uses the same function, so splat colours show banding in the darks. Anything over 1.0 is clipped.
  - `.tolist()` at 4096 is about 67M Python floats, multiple GB.
- **Fix:** use `GPUOffScreen(res, res, format='RGBA16F')`, a float image (or encode linear→sRGB before writing to 8-bit), and `img.pixels.foreach_set(arr.ravel())`.

### MS3 (MED). Principled Alpha is frozen at compile time [C]
- **Location:** `node_transpiler.py:1140-1150`
- **Cause:** The alpha multiply is emitted only if `default_value < 0.999` at transpile time, and `topo_signature` ignores it.
- **Scenario:** a material is compiled at Alpha 1, then set to Blended and dragged to 0.3. It stays opaque until a structural edit.
- **Fix:** always emit the alpha multiply (it's already a uniform).

### MS4 (MED). The Mix (Vector) node reads the wrong sockets [C]
- **Location:** `node_transpiler.py:414-417`
- **Cause:** In 4.x `Factor_Vector` is a VECTOR socket, so `va[0]` is the factor, not A.
- **Scenario:** a Mix blending two UV sets gives wrong coordinates.
- **Fix:** select sockets by identifier (`A_Vector` / `B_Vector` / `Factor_Vector`), and honour `factor_mode` and `clamp_factor`.

### MS5 (MED). Mapping node is incomplete [C]
- **Location:** `node_transpiler.py:304-318`
- **Cause:**
  - Only Z rotation is applied; X/Y rotation is dropped, even though `_euler_xyz` exists.
  - VECTOR, NORMAL and TEXTURE types are all computed as POINT, so VECTOR wrongly adds Location and TEXTURE isn't inverted.
- **Fix:** apply the full Euler matrix and the per-type Blender formulas.

### MS6 (MED). Muted and invalid nodes and links are ignored [C]
- **Location:** `node_transpiler.py:177-181, 1210-1216`
- **Cause:** `node.mute`, `link.is_muted` and `link.is_valid` are never checked, and none of them is in the signature.
- **Scenario:**
  - Muting a node or link (M) has no effect in the viewport.
  - A cyclic (red) link recurses until `RecursionError`, which is swallowed, so the material silently falls back.
- **Fix:** skip muted/invalid links, pass muted nodes through `internal_links`, and add the mute flags to the signature.

### MS7 (MED). Group uniforms bind by socket index, and the interface isn't in the signature [C]
- **Location:** `node_transpiler.py:197, 64-93, 1196-1209`
- **Cause:** An external group input's `Param` stores the socket index, and `_tree_sig` doesn't include `nt.interface`.
- **Scenario:**
  - Reordering a group's interface sockets means no recompile, so the uniform reads the neighbouring socket's value.
  - Changing a socket's type also doesn't recompile.
  - Swapping the trees of two group nodes gives the same signature, so the program is stale.
- **Fix:** store the socket identifier, hash the interface items (identifier, type, order), and add `node_tree.name` to the GROUP variant.

### MS8 (MED). Program cache keyed by material name; bpy references kept across undo [C key / S crash]
- **Location:** `material_shader.py:22-23, 107-108` (with `engine.py:1238, 1304`)
- **Scenario:**
  - A library-linked "Mat" next to a local "Mat" share one program.
  - Renaming a material leaks the old entry.
  - `Sampler.image` references survive undo (same root cause as H6), and a dangling ID could crash Blender.
- **Fix:** key by `(name, library)` or `session_uid`, store image names, and invalidate on `undo_post` / `redo_post`.

### MS9 (LOW-MED). Divide and normalize differ from Blender's safe maths [C]
- **Location:** `node_transpiler.py:520, 523, 526, 446, 453-454`
- **Cause:**
  - `max(b, 1e-6)` turns negative divisors into 1e-6, so dividing by -2 gives a×1e6 with the wrong sign.
  - `normalize(0)` gives NaN, and REFLECT with its second input unlinked produces NaN by default.
- **Fix:** divide per component with a `b == 0 → 0` rule, and use a safe normalize.

### Lower-severity node accuracy issues [C unless noted]
- **ColorRamp** (`:671-696`): the Alpha output returns the colour's red channel. B_SPLINE/CARDINAL fall back to linear. HSV/HSL mode is ignored.
- **Voronoi** (`:930` vs `:1252`): `normalize` isn't in the signature, so toggling it doesn't recompile.
- **Vector Rotate** (`:997-1000`): `invert` is a node property in 4.x, not a socket, so it is always off. [L]
- **Checker** (`:888-889`): missing `abs(floor(p))`, and GLSL `%` on negative ints is undefined, so the pattern flips in quadrants with mixed signs.
- **Gradient** (`:902-915`): Fac isn't clamped to [0,1], and Color is clamped at the bottom only. [L]
- **Vector Curves** (`:741-747`): the lookup range is wrong, so only the identity curve is correct.
- **RGB Curves:** the C curve is applied after the channels instead of before. [L]
- **Curve signature:** includes point locations only, not handle types, extend mode or clipping.
- **Blend modes** (`glsl_lib.py:53, 55`): Hue/Color with a grey B pushes A's hue to red (Blender keeps A's hue), and Soft Light uses a different formula.
- **Clamp MINMAX** with min>max: the result is undefined.
- **Map Range:** VECTOR data type is computed as float.
- **Math:** the safe variants (POWER with a negative base, LOG ≤0, INVERSE_SQRT ≤0, COMPARE's epsilon, ARCSINE out of range, FLOORED_MODULO with b=0) all differ from Blender.
- **Noise:** type, dimensions and normalize are ignored, and Detail<0 gives NaN.
- **Mix:** `clamp_factor` is ignored.
- **Vertex colour** (`shaders.py:179, 190`): the PIXEL main multiplies by `vColor.rgb` while the Workbench material main doesn't. A graph that already uses Vertex Color gets it squared in PIXEL mode. [S/design]

### Checked and OK (materials)
- **Group handling:**
  - the group stack pops the frame before resolving external inputs, so there is no aliasing or recursion;
  - the `as_pointer` + instance-context cache key prevents exponential blow-up on shared or deep subgraphs;
  - reroute passthrough keeps types.
- **Generated code:**
  - no identifier collisions between generated names and the helper chunks;
  - no integer division, and no `%` on floats;
  - `glsl_lib.collect` resolves dependencies correctly and `CHUNK_ORDER` respects them.
- **Binding and compile:**
  - binding value-only params vs rebuilding on a structural change works as intended;
  - compile errors are printed, not hidden.
- **Maths matching Blender:** Brick, Magic, Wave, integer_noise, Bright/Contrast, Hue/Sat, most Mix blend modes, the Map Range smooth modes, ColorRamp Constant/Linear/Ease, and Math WRAP/PINGPONG/SMOOTH_MIN/TRUNC/MODULO.
- **Bake geometry:** the plane UV/Generated/Object setup is fine, and read-back needs no flip.

---

## Suggested fix order

1. **C1 + C2 + H1.** These all live in the streaming loop and are one coherent rewrite of the `_rebuild_inner` state flags.
2. **H2** (one-line move) and **L6** (per-anchor try).
3. **H4 + M16** (one final-blit rewrite), and **H3**.
4. **M1** (one line), **M10** (one line), and the **M15** alpha and Decimate `try/finally`.
5. **MS1** (typed coercion; silently breaks node-group materials), then **MS2** (a float offscreen for bakes, which also improves splat colour).
6. **H6 + MS8** (one undo-handler + image-name change), then **H7** (ID seeding).
7. **M2/M3** (per-engine state), then **MS3-MS7** (node-accuracy batch).
