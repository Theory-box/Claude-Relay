# Session notes — Ray Portal UV Baking

Branch: **feature/ray-portal-bake**
At the start of a session on this topic: `git checkout feature/ray-portal-bake && git pull && git merge main`

## Status
- **Research complete and verified** (Cycles CPU, Blender 4.4.0). Full writeup in
  `research/ray-portal-bake/FINDINGS.md`; working prototypes in
  `research/ray-portal-bake/prototypes/` (4 headless render tests, all pass).
- Technique = bbbn19's "Blender 5.0 Ray Portal Baking": render a UV-flattened
  copy of the mesh whose Ray Portal material redirects each UV point's ray back
  onto the real 3D surface → live, fully-lit bake into UV space. Cycles only.
- Next: **build the add-on** (see FINDINGS.md §7 for the design plan).

## Key facts (so we don't re-derive them)
- Node id: `ShaderNodeBsdfRayPortal`; inputs Color/Position/Direction/Weight.
- Portal material: Position = orig_pos + orig_nrm·ε (~0.02), Direction = −orig_nrm.
- `orig_pos`/`orig_nrm` = FLOAT_VECTOR point attributes captured BEFORE flattening.
- Real mesh must stay visible to the post-portal ray — do NOT use
  visible_camera=False (post-portal ray is still primary). Separate flat copy in Z.
- Real meshes need per-island UV handling (Split Edges by seams) + per-corner UVs;
  prototypes used per-vertex single-island for simplicity.

## Next-session TODO
- [ ] Decide GN vs bmesh for the per-island UV flatten.
- [ ] Build the portal material as a shipped node group.
- [ ] Operator: duplicate object → GN flatten (+capture attrs) → portal mat → ortho cam.
- [ ] Live look-dev mode vs capture-to-image mode (reuse Node Preview save path?).
- [ ] Cleanup operator.

## v0.1 addon — WORKING (research/ray-portal-bake/ray_portal_bake.py)
- Operator "Set Up Portal Bake": builds a per-CORNER UV-flattened copy of the
  active object (one vert per loop → seams/islands handled), stores world-space
  rpbake_pos + rpbake_nrm attributes, assigns the portal material, and adds an
  ortho bake camera placed above the scene (no occlusion). Sets Cycles + neutral
  colour mgmt. "Clear Portal Bake" removes it all. Panel in View3D > Portal Bake.
- Verified headless: lit grid plane bakes lighting into UV (coverage 1.0, near-
  light corner brightest); curved + Suzanne (seamed) both render fine; flat_verts
  == loop count confirms per-corner split. Cleanup leaves nothing behind.
- World-space attrs mean object transforms are handled. Multi-material on the real
  mesh works for free (portal samples the real surface, whatever materials it has).
- NEXT: capture-to-image button (render bake cam → packable file, reuse Node
  Preview save path); portal material as a shipped node group; denoise defaults
  for cleaner live view; UI to pick the bake resolution; test hard-surface normals.

## v0.2 addon — WORKER-BASED ONE-SHOT BAKE (works!)
- Confirmed Ray Portal is in Blender 4.2+, so this runs in 4.4 (user's version).
  No Blender-5 / cross-version worker needed.
- Architecture (mirrors Node Preview): "Bake to UV (Portal)" operator writes the
  whole scene via libraries.write(path_remap=ABSOLUTE) so textures/normal maps
  resolve, spawns `blender -b --factory-startup <blend> --python worker` (no user
  add-ons -> no shutdown crash, fast), worker flattens the object to UV + portal
  material + ortho cam and renders the FULL LIT SCENE to PNG; main polls (non-
  blocking timer), loads into RayPortalBake_Result image. Judged by PNG existence.
- Panel: Resolution / Samples / Surface Offset + Bake button + status. View3D
  sidebar "Portal Bake" tab. film_transparent so unused UV = alpha 0.
- Verified headless on the KhronosDamagedHelmet.glb: operator -> worker -> result
  image is a correct lit UV atlas (91% coverage, HUD emission + lighting baked).
- NEXT: Show-on-Mesh (add result as active image texture) + Save-to-File
  (packable) operators — reuse Node Preview patterns; shader-editor panel; GPU
  device pref; denoise/quality note; then consider merge into Node Preview.

## v0.3 addon — Show on Mesh + native Save + shader-editor panel
- Panel moved to Shader Editor N-panel (NODE_EDITOR, ShaderNodeTree poll), tab
  "Portal Bake". (Per user: shader panel not 3D viewport for now.)
- "Show on Mesh": adds RayPortalBake_Result as an image-texture node on the
  active object's material and makes it active (Solid+Texture shows it). No dup.
- "Save Image...": opens Blender's NATIVE image Save As dialog via
  temp_override(edit_image=result)+image.save_as INVOKE_DEFAULT (gives format /
  bit-depth / path options). No custom save UI (user saves via Blender's popup).
- Verified headless: show-on-mesh adds+activates node, save guards no-image,
  register/unregister clean, panel in shader editor.
- DEFERRED (user asked for later, not now): 32-bit/raw output, JPG/other formats,
  follow scene colour grading (currently forces neutral Standard). Basic first.
- NEXT: try on real scenes/GPU; GPU device pref; then consider Node Preview merge.

## v0.4 — frame to UV bounds (fixes "black/transparent" on atlas objects)
- REPORT (user's Exterior_78_Farmington.blend, roof FloorplanTrace.006): bake
  looked black/transparent. Diagnosis: object uses a SHARED texture atlas so its
  UVs are a tiny thin strip (UV area 0.0008, bounds u[0.13..0.24] v[0.41..0.48]);
  at the old fixed 0..1 framing it was a ~0.08%-coverage speck. Also dark shingle
  material. It was baking correctly, just invisible.
- FIX: worker now frames the ortho camera to the object's actual UV bounds
  (centre + max-extent square, 5% margin) instead of 0..1. Full-0..1 unwraps
  (helmet) unchanged (frame ~0..1, coverage 0.87). Atlas objects now fill frame.
- Worker reports frame (fminx fminy span) in the status; Show-on-Mesh adds a
  Mapping node remapping the object's UVs into that framed region so it lines up
  (correct in Material Preview/Rendered; Solid uses raw UVs so atlas objects
  won't match there).
- Verified: roof now visible (shingles), helmet unregressed.
- Notes for user: dark = the roof's dark material + scene lighting (not a bug);
  a full-res per-object bake still wants a proper 0..1 unwrap. Possible future:
  warn on tiny UV coverage; optional auto-unwrap-for-bake mode.

## v0.5 — revert to exact 0..1 bake (no Mapping node)
- User feedback: bake must be the 0..1 UV tile directly, NO Mapping node. The
  v0.4 frame-to-bounds was wrong: its 5% margin made span!=1 even for full 0..1
  UVs, so it always injected a Mapping node into Show-on-Mesh.
- REVERTED: worker frames exactly 0..1 (ortho 1.0 @ (0.5,0.5)); status = device
  only; Show-on-Mesh adds only the image-texture node (raw UVs). Bake is now a
  standard 0..1 texture that drops in against the object's real UVs.
- Note re uploaded Exterior_78_Farmington.blend: roof FloorplanTrace.006's UV
  island is objectively a small sliver at u[0.13..0.24] v[0.40..0.48] (rendered
  the layout to confirm; no modifiers; material samples page-4.jpg there). So a
  0..1 bake of THAT file places the roof small/correct. If the user has since
  unwrapped the roof to fill 0..1, the 0..1 bake fills the frame with no Mapping.
- Verified: 0..1 UV plane -> coverage 1.0; Show-on-Mesh adds only TEX_IMAGE.
- ATLAS/partial-UV support (frame-to-bounds or auto-unwrap) is a FUTURE OPTION,
  off by default; the correct default is a straight 0..1 bake.

## v0.6 — Smart Unwrap (fills 0..1) + segfault fix
- Root of "nothing/black": ALL FloorplanTrace roof pieces share a photo-texture
  atlas (UVs a small sub-region), no modifiers. Per user: Smart UV Project them.
- ADDED "Smart Unwrap" toggle (default ON) + "Unwrap Margin": creates a dedicated
  RPBake_UV map via bpy.ops.uv.smart_project, then NORMALIZES it to fill 0..1.
  The object's original/active UV map is left untouched (RPBake_UV is separate).
  Worker now bakes through a named UV map (arg 9); Show-on-Mesh adds a UVMap node
  pointing at RPBake_UV so it lines up. Toggle OFF to bake existing UVs.
- BUG FIXED: segfault — the RPBake_UV layer reference was fetched BEFORE the
  edit-mode round-trip (smart_project enters/exits Edit), which rebuilds mesh UV
  data and invalidates the pointer; the normalize loop then read freed memory.
  Fix: re-fetch me.uv_layers.get(BAKE_UV_NAME) AFTER mode_set OBJECT.
- Verified on roof FloorplanTrace.006: coverage 0.0008 -> 0.72, original UVMap
  still active, RPBake_UV added. Dark = the roof's dark material + scene light.
- Note: normalize stretches non-square islands to fill 0..1 (consistent with the
  RPBake_UV it bakes through, so Show-on-Mesh via that map lines up).

## v0.7 — removed Smart Unwrap; added Diagnostics button
- Per user: NO smart-unwrap option. Reverted addon to clean v0.5 (exact 0..1 bake,
  no Mapping node). Added "Copy Diagnostics" operator: dumps object transform
  (incl. matrix determinant / negative-scale check), all UV maps + bounds + uv_area
  + %in-0..1, world-space normal up/down counts, materials (surface/node types/
  images), SCENE lights + world strength + engine + view_transform, and bake
  settings -> clipboard + a RPBake_Diagnostics text block.
- FIT TEST (repro of user workflow: manual smart_project active UV -> bake 0..1 ->
  re-apply via RAW UVs, no mapping): re-applied roof lands EXACTLY on the object
  (visually correct position/scale). So there is NO coordinate/scaling bug in the
  0..1 path; it fits per UVs already.
- Diagnostics on uploaded Exterior_78_Farmington.blend / FloorplanTrace.006 reveal
  the real causes of "black/empty":
  * SCENE HAS 0 LIGHTS (engine EEVEE, world strength 1.0, view AgX) -> dim/dark bake.
  * roof UVMap is the tiny atlas sliver (uv_area 0.0008) in THIS file -> empty-looking.
  * normals mostly point DOWN (108 down / 24 up) -> portal may sample underside.
- NEXT: get user's Diagnostics dump from THEIR object (post their manual unwrap) to
  see if it differs. Candidate real fix if normals are down: bake the camera-facing
  / opposite side (flip option) — but confirm from their data first.

## v0.8 — frame-to-bounds auto-scaling (VERIFIED exact) + mapping on Show-on-Mesh
- Root cause of user's "transparent for any object": their objects have sub-region /
  atlas UVs, so a plain 0..1 bake renders them as a tiny speck (looks empty). The
  "black on re-apply" (38.6%) seen on FloorplanTrace.006/.002 was those meshes'
  overlapping/degenerate atlas UVs, NOT a coordinate bug.
- Proved the auto-scaling math is exact on a CLEAN unwrap (helmet UVs shrunk to a
  sub-region incl. negative V): frame-to-bounds bake + inverse Mapping node re-apply =
  diff 0.0055. The old v0.4 "padding" error was the 5% margin (span*=1.05); removing
  it makes the fit exact.
- IMPLEMENTED: build_flat now uses RAW uv coords (no floor-shift) and returns UV
  bounds. Worker frames an ORTHO cam exactly to the square UV bbox (ortho_scale=span,
  NO margin, clip_end 1e9) and writes "DEV FRAME fminx fminy span" to status. Main
  parses it, stores rpbake_fminx/fminy/span as custom props on RPBake_Result. Show-on-
  Mesh rebuilds UVMap->Mapping(Location=-fmin/span, Scale=1/span)->ImageTexture, the
  exact inverse -> fits the object's own UVs with no manual work.
- Verified END-TO-END through the actual addon (bake op + show_on_mesh op) on a clean
  sub-region object: diff 0.0022 (exact).
- NOTE for messy/overlapping atlas UVs: bake still visible, but faces that overlap in
  UV can't all round-trip (physics of shared UV space, not a bug). Clean unwraps fit.

## v0.8.1 — tested on CORRECT file (Exterior_78_Farmington_v4.blend)
- v4 file IS lit: Cycles, Sun (energy 1.0) + world 0.051 strength 3.9. 64 mesh objects.
- Ran the ACTUAL addon bake on a smart-projected object: NOT transparent. Coverage
  23.7% (the smart-project islands; gaps between islands are transparent, normal),
  lit gray ~0.44, frame captured (fx0.007 fy0.011 span0.978). Bake image shows the
  page-4 surface correctly in each island.
- Fit on the real file (FloorplanTrace.006, smart-projected, has page-4 material):
  bake + Show-on-Mesh lands EXACTLY on the mesh (shape/seams/position match). Residual
  0.17 diff is view-dependent shading (lit bake head-on vs viewed at an angle), not a
  coordinate error.
- FIX: some objects (e.g. FloorplanTrace.001) have NO material -> Show-on-Mesh used to
  cancel. Now it creates a material if the object has none.
- CONCLUSION: v0.8 resolves the "transparent for any object" (was 0-1 framing on sub-
  region UVs). Frame-to-bounds + inverse Mapping = visible bake that fits the object's
  own UVs.

## v0.9 — REVERTED to 0-1 tile bake (the actual fix for "offset")
- User reported OFFSET with v0.8 frame-to-bounds+mapping. Root realization: user's
  stated ideal is "fits exactly by UVs WITHOUT a mapping node" = the standard 0-1 tile
  bake (image IS UV space), which is what Blender's own baker does. Frame-to-bounds +
  mapping was over-engineering; applied without the mapping node (or when the object
  fills <100% of 0-1) it reads as an offset.
- Reverted: build_flat floor-shifts UVs into the 0-1 tile again; worker camera is ortho
  1.0 @ (0.5,0.5); no frame reporting; Show-on-Mesh just adds the image (default UV
  input, no Mapping node). Kept: diagnostics button, material-creation-if-missing.
- VERIFIED with a COLOR/UV grid on v4 FloorplanTrace.006 (smart-projected): 0-1 tile
  bake re-applied with RAW UVs (no mapping) = grid lines match perfectly, diff 0.0079.
  Zero offset.
- Worker path on v4 confirmed: coverage 70.5% (NOT transparent), status Baked.
- OPEN ISSUE: v4 .006 bake is very DARK (mean 0.065). Likely the portal samples the
  +normal side and this roof's normals point down/inward -> samples shadowed underside,
  while a normal camera render sees the lit top (Cycles flips backface normals to
  camera). Investigating normal-direction handling next.
- NOTE: v4 file has NO image textures on materials (plain), Sun energy 1.0, world 0.051
  x3.9. Dim scene.

## v0.9.1 — OFFSET root-caused & fixed (measured in UV space)
- User screenshot: to align the baked walls they moved UVs by X=0.0076, Y=0.1526
  (translation only, scaling correct).
- DIRECT UV-space offset measurement (bake a COLOR_GRID onto a wall, cross-correlate
  baked vs reference):
    * 0-1 TILE (current build): dx=0.0000 dy=0.0000  -> ZERO offset.
    * FRAME-TO-BOUNDS (old v0.8): dx=-0.0078 (== user's X) ; dy grows to ~(span-h)/2,
      = ~0.15 when the UV box is non-square (walls pack wider than tall). Cube packed
      near-square so its dy was only 0.002, but the mechanism matches the user's 0.15.
- CONCLUSION: the user is still running the OLD frame-to-bounds build. The reverted
  0-1 tile build (image IS UV space) removes the offset entirely. Re-delivered.
- Also hardened build_flat: shift by the UV bbox CENTRE's tile, not floor(min), so a
  UV dipping just below 0 no longer jumps the island up a tile and clips it.
- NOTE (separate, non-blocking): on objects COINCIDENT with other geometry (e.g. a
  flat FloorplanTrace sitting on a building block), the portal ray can hit the block
  instead of the trace -> dark bake. User confirmed this is NOT their normal case
  ("bakes the right object fine"); logged for later robustness.

## RESOLVED & SHIPPED — offset fixed, merged to main
- User confirmed: "working like a charm now." Baked textures drop onto existing UVs
  with no move and no mapping node.
- ROOT CAUSE of the offset: the old frame-to-bounds build aimed the bake camera at a
  SQUARE region of side span=max(uv_w, uv_h). Non-square UVs (walls packed wider than
  tall) got padding of (span-height)/2 on the short axis, which read as a pure
  translation (big in Y, ~0 in X) when applied to raw UVs - scaling stayed correct.
- FIX: bake straight to the 0-1 UV tile (image IS UV space, Blender-native convention).
  Measured offset dx=0.0000 dy=0.0000. No frame-to-bounds, no mapping node.
- Status: feature/ray-portal-bake merged to main. Addon complete.
- DEFERRED (only if user hits it): coincident-geometry safeguard so a flat trace sitting
  on a building block doesn't bake the block instead of the trace (portal ray hits the
  coincident object -> dark). Fix path identified; not implemented per user request.
- Other deferred niceties: albedo/unlit mode, edge-padding/dilation for inter-island
  gaps, 32-bit/other formats, GPU device pref, eventual merge into Node Preview.

## v0.10 — single Render button + auto-apply, and native-vs-portal benchmark
- UI: collapsed to ONE "Render" button. It bakes, then auto-applies the result onto the
  mesh (the old Show-on-Mesh logic) when the worker finishes. Save is manual (Image
  editor) for now. Show-on-Mesh + Save operators still registered (F3) but off the panel.
  Diagnostics button kept.
- Refactored apply into _apply_result_to_object(obj); _poll calls it on completion using
  the target object name stored in the job.
- BUGFIX found while testing: objects with an EMPTY material slot (slot present, no
  material, active) - append() added the new material at a new index while the active
  slot stayed empty, so nothing showed. Now fills the active slot instead.
- BENCHMARK (CPU, FloorplanTrace.001 isolated, gray Principled):
    res/samples | native Combined bake | portal core render | ratio
    512 @ 32    | 2.7s                 | 5.0s               | 1.84x slower
    1024 @ 64   | 20.1s                | 38.6s              | 1.92x slower
  Full addon Render (worker: 44MB scene write + subprocess startup + render) at 512@32
  = 15.7s (the ~10s over the 5s core render is writing the whole scene + launching a
  background Blender; scales with scene size).
- TAKEAWAY: our method is SLOWER than native baking - ~1.9x for the raw Cycles work
  (the ray-portal teleport roughly doubles ray cost), and more in practice because the
  addon writes the whole scene and spawns a subprocess. The tradeoffs it buys: runs in
  the BACKGROUND (native bake blocks the UI), one-click + auto-apply, and no per-object
  bake-target setup. Speedup options if wanted: write only needed objects instead of the
  whole scene; optional in-process mode (faster, but freezes UI); or a native-bake mode.
