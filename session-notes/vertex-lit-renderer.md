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
- **`n_samp` Monte Carlo bookkeeping for soft-shadow sun.** Original code used one jittered sun direction per PASS and wrote `direct * n_samp` for count bookkeeping. For deterministic lights that's correct. For a jittered sun it's wrong — booked 1 real sample as n_samp, so higher n_samp did more work per pass with zero additional sampling. User caught it: n_samp=1 converged faster than n_samp=32 at equal wall time. Fix: `_direct_soft_sun_mc` generates `n_verts × n_samp` independent jittered directions per pass, vectorized shadow-tests all at once, sums the per-sample contributions. Convergence now scales as √(P × n_samp) as expected. Deterministic path still uses the cheap `* n_samp` shortcut.
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

## Optimization work log

- **Tier 1: parallel ray casting via ThreadPoolExecutor.** Tried on `feature/gi-parallel` (commit a52b3e3, archived, not merged). Was SLOWER per pass. Likely causes: embreex doesn't release the GIL as I assumed, OR Embree/embreex is already internally multi-threaded and our outer split fragmented the work, OR per-call fixed overhead paid N× with worse batch-scaling. Dead end without a different approach (multiprocessing with array serialization cost, or GIL-release verification).
- **Direct lighting MC fix.** Unexpected win — not on the optimization roadmap originally. User observed n_samp=1 converging faster than n_samp=32 on soft-shadow scenes. Root cause was the `direct * n_samp` shortcut being wrong for jittered suns (booked 1 real sample as n_samp). Now proper MC with n_samp real samples per vertex per pass — high n_samp finally pays off. Commit b47cc42.
- **Stratified (u, v) sampling.** `_stratified_uv` helper shared by hemisphere bounce and soft-sun disk. Perfect-square n_samp → 2D M×M grid; other n_samp ≥ 2 → 1D strat on u; n_samp=1 → pure random. Measured 1.17-1.63× variance reduction per pass, same CPU. Gotcha in review: first attempt shadowed the disk basis vectors `u, v` with the stratified UV outputs of the same name — crashed via a `(N,N)` broadcast explosion. Renamed basis to `axis_a, axis_b`. Lesson: when adding a helper whose output names already exist in the call site, rename the callee's locals first. Commit 6a3abc5.
- **Bilateral GI denoiser.** Normal-weighted filter over each vertex's 8 nearest neighbors (built once per mesh, cached in `_mesh_cache['denoise_neighbors']`). Weight = `max(0, n·n)^4` so corners/creases/thin geometry preserved — only flat regions mix. Strength ramps quadratically with convergence: `(1 - count/target)^2 × user_strength`. At full convergence the multiplier is zero, output is mathematically the raw ray-traced result — this was explicitly a design requirement (user concerned about final-image blur). scipy.cKDTree if available (~300ms for 71k verts), mathutils.KDTree fallback. UI toggle + always-visible strength slider (greyed when off). Commit 7662db4.
- **Per-vertex adaptive sampling (temporal reuse).** Converged verts stop being traced but still contribute to the shared accumulator via a "replay" synthesis (`avg × n_samp` added to cf each pass) so global count accounting stays consistent. Gather/scatter via `cf[chunk][active_idx] = result` — fancy indexing on a view writes back through to the underlying array, avoiding a full-size allocation. Also fixes a latent de-convergence bug in the old chunk-skip code where skipped chunks had `M2 += (0-mean)²` applied, eventually pushing variance past threshold and re-activating them. Commit e205093.
  - **Convergence criterion bug uncovered in testing.** The original code checked `var(per-pass-samples) / mean² < 0.01`, but for Monte Carlo estimators the per-sample variance has an irreducible floor — penumbra / corner verts never crossed threshold. User saw convergence stall at ~30% indefinitely. Fixed to check `var(mean) = M2 / (n·(n-1))`, which shrinks as 1/N so every vert eventually converges. Validated: old criterion stayed at 3% for 500 passes, new criterion hit 99% by pass 500. Commit 2ca7aff.
  - **Idle-pause when viewport leaves render view.** Blender doesn't reliably call RenderEngine.free() on viewport leave, so the GI thread kept running in the background forever. Added `_last_viewed` timestamp stamped by view_draw on every call, plus a check at each pass boundary — if stale > 2s, the thread enters a sleep loop. On re-entry (fresh timestamp), resumes with all state intact. Prints `viewport idle, GI paused` / `viewport active, resuming GI`. Commit d6b2946.
- **Bake operators (bake.py module).** `vertex_lit.bake_to_vertex_colors` and `vertex_lit.clear_baked_vertex_colors`. Each has a `selected_only` bool prop. UI exposes a 2×2 grid: Bake All / Bake Selected / Clear All / Clear Selected. Bake snapshots `_global_gi._accum / _count × gi_bounce_strength` under the lock, writes a per-vertex POINT FLOAT_COLOR attribute named 'VertexLit_Baked'. Lighting-only bake — no albedo/texture multiplied in, so output is reusable across render engines + non-destructive. Clear dedups by mesh data (linked objects sharing meshes don't double-process). Known gap: bake reads raw accum, ignores the bilateral denoise that render view applies. Only matters mid-convergence — at full convergence denoise strength is 0 anyway. Commits 15e2d65 + d461ce5.

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
