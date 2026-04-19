# Vertex Lit Renderer — session notes

**Active branch:** main (all work merged). No feature branch currently in flight.

## Architecture quick reference

Custom Blender RenderEngine. Per-vertex Gouraud shading (direct lighting in vertex shader). Background GI thread uses Intel Embree via embreex for hemisphere ray casting; Welford variance tracks per-vertex convergence and skips converged chunks.

Key files in `vertex_lit_renderer/`:
- `engine.py` — VertexLitEngine, mesh extraction, view_update/view_draw, depsgraph handler, GI restart plumbing
- `gi.py` — ProgressiveGI class, _run_embree, _gi_pass_embree, BVH builders
- `shaders.py` — MAIN_VERT/MAIN_FRAG GLSL (bounceColor VBO gated by uHasGI)
- `props.py` — VertexLitSettings PropertyGroup on Scene
- `ui.py` — render panel, object panel, COMPAT_ENGINES registration for borrowed light/material/world panels
- `__init__.py` — register/unregister

`_batch_dict` entries are `(batch, static_vbo, texture)` 3-tuples. Static data uploaded once; bounce VBO rebuilt each GI publish (can't reuse STATIC-usage VBO for attr_fill after first draw — Blender API limitation).

## Update paths (merged + working)

Single-frame summary of what sets what and where it's picked up:

- **Object transform** → view_update sees is_updated_transform on MESH Object → `_transform_dirty = True` → view_draw picks up after 0.3s → `_restart_gi_for_transforms(decay=0.1)`. Prints `transform-dirty pickup`.
- **Edit-mode commit / geometry change** → `_edit_depsgraph_post` handler adds name to `_edit_dirty` set → view_draw picks up after 0.2s → `_incremental_rebuild` on those objects. Prints `edit-dirty pickup: N objects`.
- **Light change (any kind)** → `_edit_depsgraph_post` handler flips `_lights_dirty = True` → view_draw top promotes it to `self._light_dirty` AND **clears `_transform_dirty`** to prevent mesh-dependent transform events from winning the restart race with wrong decay → picks up after 0.3s → `_restart_gi_for_transforms(decay=0.0)`. Prints `light change -> GI restart`.
- **Scene membership (delete/unhide)** — scene-diff block in view_update. Delete: pop from caches, `_restart_gi_for_transforms(decay=1.0)`, no rebuild. Unhide: queue to `_edit_dirty` for incremental rebuild.
- **Material / mesh datablock** → `_dirty = True` → full `_rebuild_inner`. Prints `rebuilt N objs`.

Edit-mode global pause: if `bpy.context.active_object.mode != 'OBJECT'`, both the handler AND view_update return early. Catches scatter/GeoNodes dependents of an edited curve/mesh as well.

## Three detection paths, ordered by reliability

1. `_edit_depsgraph_post` — fires on every depsgraph update regardless of render engine callbacks. Most reliable. Now catches both mesh geometry AND lights (Object and Light datablock updates).
2. `view_update` — fires when Blender calls it. In some Blender 4.4 sessions, not called for light operations at all. Don't rely exclusively.
3. `_lights_differ` defensive poll in view_draw — fingerprint (location, rotation_euler, energy, color) rounded for FP stability, checked every 0.2s. Backup for exotic cases the handler might miss (collection instance lights, linked lights).

## Subtle things that bit us along the way

- **STATIC-usage VBO can't be re-filled** after first draw. `attr_fill` throws "Can't fill, static buffer already in use." Workaround: rebuild bounce VBO + batch each GI update (keep static_vbo cached, reuse it via `batch.vertbuf_add`).
- **Scene-diff type filter must match `_rebuild_inner`** — curve/surface/meta/font all get evaluated→mesh and cached. Filtering scene-diff on `type=='MESH'` alone breaks GI updates (curves show as "always deleted"). Use the `_NON_GEOMETRY_OBJ_TYPES` constant.
- **decay=0.1 default is wrong for light changes** — with preserve_existing=True, the new accumulation is 96% old-lighting / 4% new-lighting per pass. Hundreds of passes to dilute out. Light path uses decay=0.0 to fully reset.
- **inst.matrix_world fingerprint drifts** between depsgraph queries even with no change. Use base `obj.location` + `obj.rotation_euler` (rounded) for change-detection fingerprints.
- **Blender fires is_updated_transform on dependent meshes when lights change.** If not explicitly overridden, the transform path wins the debounce race with the wrong decay. Fix: handler-flagged light dirty takes priority in view_draw and clears `_transform_dirty`.
- **COMPAT_ENGINES registration** — adding `'VERTEX_LIT'` to built-in panels (light/mesh/material/world) lets users access standard settings (light power, sun angle, color, size) without us writing UI. Done in ui.py on register.

## Console diagnostic prints (useful when debugging)

All active in current code:
- `[VertexLit] rebuilt N objs (Xs)` — full _rebuild fired
- `[VertexLit] GI started (N samples)` — GI target sample count set
- `[VertexLit] Embree scene: V verts, T tris` — new Embree scene built (every restart)
- `[VertexLit] GI (embreex): N verts` — thread launched with vertex count
- `[VertexLit] GI sample N applied` — main thread consumed a pass
- `[VertexLit] edit-dirty pickup: N objects -> incremental rebuild`
- `[VertexLit] transform-dirty pickup -> GI restart (decay=0.1)`
- `[VertexLit] light change -> GI restart (decay=0, N lights)`
- `[VertexLit] defensive poll: lights changed` — backup poll caught something the handler missed
- `[VertexLit] GI fully converged after N passes` — thread idling

**Diagnostic heuristic:** if user reports "X change doesn't update", ask for the console log around the time they made the change. The print tells us which path fired (or if none did), which narrows the bug in one shot. Don't add more prints on speculation — these are enough.

## Settings (Render Properties panel)
- `use_gi` — toggle GI bounce
- `gi_samples` — target convergence samples
- `gi_rays_per_pass` — hemisphere samples per pass per vertex (quality vs update rate)
- `gi_thread_pause` — only visible if embreex unavailable (BVHTree fallback path)
- `gi_bounce_strength` — multiplier on bounce color
- `sky_color` / `ground_color` — hemisphere fill
- `energy_scale` — global multiplier on light intensities

Per-object: `vertex_lit_cast_shadow` — if False, excluded from GI BVH (doesn't cast shadow or block bounces, still receives).

## Roadmap (user-expressed interest, not yet scheduled)

- **Soft sun shadows** — jittered direction within cone angle (uses existing `light.angle` prop that COMPAT_ENGINES now exposes). Natural fit for accumulating GI; ~40 lines in `_gi_pass_embree`.
- **Point-light size for soft shadows** — same jitter technique, sphere sampling. Uses `light.shadow_soft_size`.
- **Emissive materials** — detect emission on extract (material.emission_color/strength or Principled BSDF's emission), store `gi_face_emission`, include in hemisphere bounce as `albedo * incoming + emission`. Good for large area emitters. Small bright emitters converge slowly without MIS (would need significant rewrite).
- **Re-evaluate edit-mode pause** — now that numpy extraction is fast, tabbing out of edit may not hitch anymore. Could unpause for a smoother experience. Requires testing.

## Known not-done
- GeoNodes named attribute for cast shadow (`vertex_lit_cast_shadow` on Point domain) was attempted but never worked. Object property works fine. Worth revisiting if user asks.
- Own-color tint on bounces in some scenes — self-intersection bias is 0.01 + MIN_DIST filter. May need further tuning on specific scenes.

## Active branches
- `feature/audio` — audio panel, sound emitters
- `feature/camera` — camera trigger system
- (not touched this session)
