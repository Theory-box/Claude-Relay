: `_light_dirty` + 0.3s debounce → re-collect lights + restart GI
- Both use `_restart_gi_for_transforms` (fast: retransforms cached verts, no bpy calls)
- No full rebuild on transform — geometry batches stay intact, no grey flash

## Per-Object Cast Shadow

### Object Property (working)
- `bpy.types.Object.vertex_lit_cast_shadow` BoolProperty
- Shown in Object Properties → Vertex Lit panel
- Excludes object from BVH (no shadow casting, no GI blocking)
- Object still receives shadows and GI

### GeoNodes Named Attribute (NOT WORKING — needs fix)
- Intended: Store Named Attribute node, Boolean, Point domain, name='vertex_lit_cast_shadow'
- Code reads `mesh.attributes['vertex_lit_cast_shadow']` in `_extract_mesh_data`
- Stores `gn_cast_shadow` in mesh data dict
- `_build_raw_bvh_data` checks it before Object property
- **BUG: doesn't work in practice — needs debugging next session**
- Possible causes: attribute domain issue, evaluated mesh timing, logic inversion

## Known Issues / Pending
- GeoNodes cast shadow attribute not working (see above)
- GI bounce color might still show subtle own-color tint in some scenes
  (self-intersection bias raised to 0.01, MIN_DIST filter added — may need tuning)
- GPU GI would be 1000x faster but requires architecture rewrite

## Settings (Render Properties)
- Samples Per Cycle: how many samples per viewport update (GI runs indefinitely)
- Rays Per Pass: hemisphere samples per vertex per pass (quality vs update rate)
- Bounce Strength / Sky Color / Ground Color / Energy Scale
- Thread Pause: only shown when embreex unavailable (BVHTree fallback)

## Install Notes
- embreex installs on first addon register (~30s, one time only)
- Blender 4.4, Python 3.11, Windows confirmed working
- embreex-2.17.7 bundles its own Embree + TBB DLLs
: `_light_dirty` + 0.3s debounce → re-collect lights + restart GI
- Both use `_restart_gi_for_transforms` (fast: retransforms cached verts, no bpy calls)
- No full rebuild on transform — geometry batches stay intact, no grey flash

## Per-Object Cast Shadow

### Object Property (working)
- `bpy.types.Object.vertex_lit_cast_shadow` BoolProperty
- Shown in Object Properties → Vertex Lit panel
- Excludes object from BVH (no shadow casting, no GI blocking)
- Object still receives shadows and GI

### GeoNodes Named Attribute (NOT WORKING — needs fix)
- Intended: Store Named Attribute node, Boolean, Point domain, name='vertex_lit_cast_shadow'
- Code reads mesh.attributes['vertex_lit_cast_shadow'] in _extract_mesh_data
- Stores gn_cast_shadow in mesh data dict
- _build_raw_bvh_data checks it before Object property
- BUG: doesn't work in practice — needs debugging next session
- Possible causes: attribute domain issue, evaluated mesh timing, logic inversion

## Known Issues / Pending
- GeoNodes cast shadow attribute not working (see above)
- GI bounce color may still show subtle own-color tint (bias=0.01, MIN_DIST filter added)
- GPU GI would be 1000x faster but requires architecture rewrite

## Settings (Render Properties)
- Samples Per Cycle: samples per viewport update (GI runs indefinitely)
- Rays Per Pass: hemisphere samples per vertex per pass
- Bounce Strength / Sky Color / Ground Color / Energy Scale
- Thread Pause: only shown when embreex unavailable (BVHTree fallback)

## Install Notes
- embreex installs on first addon register (~30s, one time only)
- Blender 4.4, Python 3.11, Windows confirmed working
- embreex-2.17.7 bundles its own Embree + TBB DLLs
