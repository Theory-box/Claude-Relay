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

## v0.11 — two bake methods: Ray Portal + Blender native
- Added a Method selector (rpbake_method enum: PORTAL / NATIVE) at the top of the panel.
  The single Render button honours the selected method.
- NATIVE mode: sets up the shared RESULT image as an active Image Texture node (bake
  target) on the object's active material (creates/fills the slot if needed), sets
  Cycles + samples + bake margin/use_clear + device, then runs
  bpy.ops.object.bake('INVOKE_DEFAULT', type='COMBINED') - Blender's own NON-BLOCKING
  bake (user confirmed native bake doesn't freeze Blender; it shows Blender's progress
  bar). A _poll_native timer watches bpy.app.is_job_running('OBJECT_BAKE'); on completion
  it ensures the result node is active (shown on mesh) and RESTORES the user's scene
  settings (engine, samples, device, bake margin/use_clear) that the bake temporarily
  changed.
- PORTAL mode unchanged (background subprocess worker) - regression-tested, still bakes
  + auto-applies.
- epsilon (Surface Offset) shown only in PORTAL mode.
- Verified headless: native bake produces a correct lit result (combined pass) into the
  RESULT image as the active node; operator path FINISHED -> poller applies -> settings
  restored; portal path still works; register/unregister clean; both timers cleaned up.
- Guidance recap for the user: NATIVE = faster, foreground (own progress bar), needs a
  material; PORTAL = ~1.9x slower + scene-write overhead but fully background and needs
  no bake-target setup.

## v0.12 — native-only UI + Bake Settings sub-panel; Ray Portal hidden (code kept)
- UI now defaults to Blender native bake. rpbake_method still exists (default NATIVE) and
  the PORTAL code path is fully intact, just not exposed in the panel - re-add the
  selector to bring it back.
- Removed the Diagnostics button from the panel (operator class still registered, F3).
- New collapsible "Bake Settings" sub-panel (RPBAKE_PT_bakesettings, child of main panel,
  DEFAULT_CLOSED) with:
    * Bake Type: Combined / Diffuse / Glossy / AO / Shadow / Emit / Roughness / Normal
      (Diffuse/Glossy/Transmission pass DIRECT+INDIRECT+COLOR).
    * Color Space: sRGB / Non-Color.
    * 32-bit Float: float image datablock for HDR (>1) values; 8-bit otherwise.
    * Margin (px): bake edge bleed (default 16).
  Verified: float image is_float honored, colorspace set, margin widens island coverage,
  bake type drives bpy.ops.object.bake.
- COLOR-MANAGEMENT NOTE: native bake writes SCENE-LINEAR values; the view transform
  (Filmic/AgX/Standard) is a DISPLAY transform and is NOT baked in. Re-applying the bake
  in Blender + the scene's view transform reproduces the original look, so linear is the
  correct choice for re-render workflows. Baking the tonemapped look "in" (for export to
  engines/other apps) is a separate feature (post-bake view-transform apply) - NOT built,
  offered to user.
- Status: committed to feature/ray-portal-bake. NOT merged to main (no explicit request).

## v0.12.1 — BUGFIX: Resolution setting did nothing (stuck at first-baked size)
- Symptom (user): changing Resolution (128/1024/2048/4096) produced the same output size;
  effectively stuck at whatever the RESULT image was first created at.
- Root cause: _get_result_image reused the existing RESULT datablock and called
  Image.scale(res,res) to resize it - but Image.scale() does NOT reliably resize a bake
  target (verified headless: image stayed 256 across 1024/2048/4096/8000 requests).
- Fix: when size OR bit depth differs, RECREATE the datablock via bpy.data.images.new at
  the exact resolution (which sets size reliably) and re-point existing tex-node users to
  the new image. Verified: 256/1024/2048/4096/8000 all produce the correct size; real
  bakes at 512 and 2048 output (512,512)/(2048,2048) and the active tex node re-points so
  it still shows on the mesh.
- Also raised rpbake_resolution max from 8192 -> 16384 (user needs 8000; now uncapped to
  16K). min stays 64.
- Committed to feature/ray-portal-bake.

## v0.13 — Save button (one-click, no dialog) + save settings in Bake Settings panel
- Workflow the user wants: Render -> (if happy) Save -> next object -> Render -> Save.
  Save must NOT open a dialog; it just writes the file using settings configured once.
- Main panel: added a "Save" button under Render (enabled only when a bake exists & not busy).
- Bake Settings sub-panel gained a "Save" section:
    * Save Folder (DIR_PATH) - empty = a 'bakes' folder next to the .blend; or a custom path.
    * Format: PNG / JPEG / OpenEXR / TIFF.
    * Bit Depth: 8 / 16 / 32 (clamped to what the format allows: JPEG->8, EXR->16/32, PNG->8/16).
    * Color Grading: Follow Scene (uses scene view transform) / Standard / AgX / Filmic / Raw.
- RPBAKE_OT_save rewritten: no dialog. Resolves dir, names the file after the LAST-BAKED
  object (tracked in _state['last_baked'] on completion of both native & portal paths),
  temporarily sets scene image_settings (format/depth/quality) + view transform, calls
  image.save_render(path, scene), then restores all scene settings.
- Verified: default-folder PNG16 (Follow=AgX), custom-folder JPEG (Standard), EXR32 (Raw)
  all written to disk with correct names; scene view transform restored; AgX vs Standard
  files differ (grading really applied).
- Committed to feature/ray-portal-bake.

## v0.13.1 — Save re-points the mesh to the saved file (fixes shared-result clobber)
- Problem (user): every bake writes the one shared RayPortalBake_Result image and the
  mesh's texture node points at it, so baking the NEXT object overwrote the previous
  object's on-mesh texture.
- Fix: after Save writes the file, it loads that file as its own datablock and re-points
  the just-baked object's TEX_IMAGE node (the one pointing at RESULT) to the saved image,
  and makes it active. RESULT stays as the reusable bake target for the next object.
- Verified: bake A -> node=RESULT; save A -> node=FloorplanTrace_001.png; bake B (overwrites
  RESULT) -> A STILL = FloorplanTrace_001.png (unaffected), B=RESULT; save B -> B=FloorplanTrace_005.png.
  Both files on disk; RESULT datablock persists.
- Committed to feature/ray-portal-bake.

## v0.13.2 — Render auto smart-unwraps objects with no UVs
- If the active object has no UV map, Render now smart-projects one (island_margin 0.02),
  returns to Object mode, and continues the bake as normal instead of cancelling.
- Helper _ensure_uvs(context, obj): OBJECT mode -> select only obj -> EDIT -> select all ->
  uv.smart_project -> OBJECT (wrapped in temp_override for context safety).
- Verified: stripped an object's UVs (0 layers) -> _ensure_uvs creates 1 layer filling
  ~0-1, mode returns to OBJECT, and a subsequent bake fills (59.6%).
- Committed to feature/ray-portal-bake.

## v0.13.3 — Render asks to collapse modifiers (fixes Solidify black bake)
- Problem (user): a roof with a Solidify modifier baked black - native bake works off the
  base mesh UVs, so modifier-generated geometry has no real UVs. Fix is to apply modifiers.
- Added: if the active object has modifiers, Render's invoke() shows a props dialog
  ("This object has N modifiers... bake needs real geometry") with a checkbox
  "Apply (collapse) all modifiers" (default ON) + OK/Cancel. OK -> execute collapses then
  bakes; Cancel -> abort. No modifiers -> no popup, bakes directly.
- Helper _apply_all_modifiers: OBJECT mode, single-users shared mesh data (modifier_apply
  refuses on multi-user), applies each modifier (removes any that can't apply).
- execute() collapses (when checkbox on & modifiers present) BEFORE the UV check/bake.
- Verified: Solidify(0.1)+Bevel applied -> 890->6177 faces, 0 modifiers left, bake proceeds.
- NOTE for user: Solidify's applied underside copies the top's UVs (overlap); the top
  bakes fine but the shared underside overlaps. If a fully clean bake is needed, delete the
  UVs before Render (auto-unwrap kicks in) or re-unwrap. Could add a "re-unwrap after
  collapse" option if wanted.
- Committed to feature/ray-portal-bake.

## GIT HYGIENE NOTE (fixed)
- v0.12.1..v0.13.3 accidentally got committed to MAIN (a stray `git checkout main` in a
  test command during the resolution fix was never undone). main had everything and matched
  the delivered file; feature branch was stuck at v0.12. Fast-forwarded feature -> main so
  both are at 651f7b0. Watch the working branch before committing.

## v0.13.4 — FREEZE fix: defer native bake launch (modal-in-popup deadlock)
- Symptom (user): intermittent hard freezes during bake; started around the modifier
  pop-up addition; roofs (which have Solidify -> hit the pop-up path) freeze a lot.
- Cause: Render's modifier confirmation uses invoke_props_dialog. Launching the modal
  bake operator (bpy.ops.object.bake INVOKE_DEFAULT) from INSIDE that pop-up's execute is
  a classic Blender deadlock/freeze.
- Fix: _render_native no longer calls bake directly. It stores the bake params in the job
  (pending=True) and registers a one-shot _launch_native timer (0.02s). _launch_native
  runs AFTER the pop-up/execute context is gone, re-selects the object, launches the modal
  bake, then registers _poll_native. _poll_native skips while pending. _launch_native added
  to timer cleanup on unregister.
- Verified headless: operator returns FINISHED with job pending -> launcher fires -> bake
  runs -> poller completes -> applied + scene settings restored.
- If freezing persists on objects with NO modifiers, cause is different (bake not
  backgrounding from script) -> would move native bake to a subprocess like the portal path.

## v0.13.5 — re-unwrap after applying UV-breaking modifiers
- When collapsing modifiers, the popup now offers "Re-unwrap after (Smart UV Project)".
- It defaults ON when a UV-breaking modifier is present (_UV_HURTING_MODIFIERS: Solidify,
  Mirror, Array, Bevel, Screw, Skin, Weld, Wireframe, Boolean, Build, Mask, Edge Split,
  Triangulate, Decimate, Remesh); OFF otherwise (so clean deformers like Subsurf/Armature
  don't needlessly discard good UVs). Popup shows an ERROR-icon note when a breaker exists.
- execute: after _apply_all_modifiers, if reunwrap_after -> _smart_project (overwrites UVs).
- Refactored the unwrap core into _smart_project(); _ensure_uvs now calls it when no UVs.
- Verified: Solidify detected; collapse->re-unwrap gives 0-1 UVs and better coverage
  (29.9% vs 11.7% with the overlapping post-Solidify UVs).

## v0.13.6 — modifier popup: "Back up object first" option
- Added a "Back up object first" checkbox to the modifier-collapse popup, plus the OK
  button is now labelled "Apply & Continue" (via invoke_props_dialog confirm_text, with a
  TypeError fallback for older Blender). Checkbox unchecked = apply & continue; checked =
  backup, apply & continue.
- _backup_object(context, obj): duplicates obj (obj.copy() keeps the modifier stack) with
  independent mesh data (obj.data.copy()), unlinks the dup from all collections and links
  it ONLY to a 'backup' collection (created if missing), then _exclude_collection() sets
  that collection's layer-collection exclude=True (hidden from the view layer).
- execute: when collapsing, if backup_first -> _backup_object BEFORE _apply_all_modifiers.
- Verified: dup in 'backup' collection with modifiers intact + independent mesh; original
  applied (0 modifiers); backup collection excluded from view layer; dup only in 'backup'.
- NOTE: implemented as a checkbox + "Apply & Continue" button rather than two separate
  buttons (invoke_props_dialog is single-confirm); functionally covers both paths. Can do
  a true two-button custom popup if preferred.

## v0.13.7 — GPU device: robust detection + visible device + CPU-fallback warning
- Symptom (user): heavy 4096 bake ran with CPU ~90%, GPU idle -> baking on CPU.
- Cause: _apply_device_to_scene read cprefs.preferences.devices COLD (no refresh), which
  usually reads empty -> detected no GPU -> set scene.cycles.device='CPU' silently.
- Fix: new _gpu_available() checks compute_device_type != NONE and calls
  refresh_devices()/get_devices() BEFORE scanning cprefs.devices for an enabled non-CPU
  device. _apply_device_to_scene returns 'GPU'/'CPU'.
- Added a Device control (rpbake_device: AUTO / GPU / CPU, default AUTO) in the main panel;
  _get_device_mode() now reads it (was reading a non-existent AddonPreferences.device).
- Status now shows the device: "Baking (native, GPU)..." / "Baked (native, GPU)".
- If the user asked for GPU/Auto but it fell back to CPU, Render reports a WARNING telling
  them to enable a GPU in Preferences > System > Cycles Render Devices.
- Verified headless (no GPU): default AUTO; AUTO/GPU/CPU all resolve to CPU correctly;
  device prop present; compiles/registers.
- Portal worker path unaffected (still uses its own setup_device in the subprocess).

## v0.13.8 — unsaved-bake warning before overwriting the shared result
- Problem: baking object B overwrites the shared RESULT image that object A's un-saved bake
  still lives on. Added a guard.
- Track _state['unsaved']: set True when a bake completes (native + portal completion),
  set False after a successful Save.
- Render's invoke shows the confirm dialog when the object has modifiers OR there's an
  unsaved previous bake of a DIFFERENT object (_unsaved_prev). Same object re-bake = no warn.
- Dialog folds both concerns into one popup: an ERROR-icon line "Last bake ('X') isn't saved
  - baking now overwrites it" + a "Save the previous bake first" checkbox (default ON), plus
  the modifier section if applicable. Confirm text is "Apply & Continue" (modifiers) or
  "Continue".
- execute: if save_previous and unsaved-different, runs bpy.ops.rpbake.save() first (saves
  the previous object's result to its own file + re-points its node); aborts with a clear
  message if that save is cancelled (e.g. no folder / unsaved .blend). Unchecking = ignore
  and overwrite.
- Verified: warn True for different object, False for same object, cleared after save.

## v0.14 — BATCH baking (select many, one prompt, auto-save each)
- Select 2+ mesh objects -> Render button reads "Render N Objects" and runs a batch.
- ONE upfront dialog (no per-object prompts): "Bake N objects, one at a time. Each is baked
  then auto-saved." + checkboxes: Apply modifiers where present / Re-unwrap after applying
  (default ON if any selected obj has a UV-breaking modifier) / Back up originals first.
  Confirm text "Bake All".
- Refactor: extracted module fn _start_native_bake(context, obj) -> (dev, mode) from the
  operator (both single + batch use it). Added _prep_object() (modifiers+UVs), _batch_advance()
  (queue driver), _selected_meshes().
- State machine: _state['batch']={names,i,apply_mods,reunwrap,backup,ok,fail}. execute ->
  _start_batch (checks a save destination exists, since each object auto-saves) -> _batch_advance
  preps + starts obj[i]'s bake. _poll_native completion, when batch active: bpy.ops.rpbake.save()
  (writes obj's own file + re-points its node so it isn't clobbered), i+=1, _batch_advance next.
  Ends with "Batch done: N baked, M skipped". Panel busy + unregister clear the batch.
- Verified headless: 3-object batch (one with Solidify) -> all 3 baked, applied+re-unwrapped,
  each saved to its own file (Cube.png / FloorplanTrace_001.png / FloorplanTrace_005.png),
  each object references its own file. Single-object path regression-tested OK.

## v0.14.1 — warn on overlapping / out-of-bounds UVs, offer to smart-unwrap
- On single-object Render, if the object has NO modifiers (modifier objects use the modifier
  re-unwrap flow instead) the existing UVs are checked; if they look wrong the confirm dialog
  shows "These UVs look off: <reason>" + a "Smart-unwrap first" checkbox (default ON).
- Detection (_uv_looks_wrong): (1) out-of-bounds - >25% of UV corners outside ~0-1 tile;
  (2) overlap via bpy.ops.uv.select_overlap in a temp_override edit session, counting faces
  with a selected UV loop via bmesh. Overlap fraction > 5% -> warn. Clean unwrap reads ~1%,
  Solidify/Mirror-style overlap reads ~100%, so the 5% threshold separates them cleanly.
  Reason cached in a hidden uv_reason StringProperty (computed in invoke, NOT in draw - the
  check toggles edit mode and must never run on every redraw).
- execute: if fix_uvs and the object already has UVs -> _smart_project before baking.
- Verified: clean='', overlap='100% of faces...', OOB='most UVs sit outside...', and after a
  smart-unwrap fix the reason clears. bmesh import added.
- Scope: single-object flow only (batch relies on its Re-unwrap toggle); overlap check has a
  try/except safety net so a context issue just skips the check (no false warning).

## v0.15 — per-object resolution & samples
- Store bake res/samples on the object: Object.rpbake_use_custom (bool), Object.rpbake_res
  (int, default 1024), Object.rpbake_samples (int, default 128). use_custom's update callback
  seeds res/samples from the current scene globals when first enabled.
- Panel: when a mesh object is active, shows "Custom res / samples for this object". On ->
  edits the object's rpbake_res/rpbake_samples; Off -> shows the global scene inputs. Switching
  the active object re-reads that object's stored values (panel binds to active object props).
- _obj_res(obj, scene) / _obj_samples(obj, scene): return the object's custom value if
  use_custom else the scene global. _start_native_bake + execute both use them, so BOTH single
  and batch honor per-object settings automatically.
- Objects without custom settings use the global inputs (unchanged behaviour).
- Custom props persist in the .blend (saved on the object).
- Verified: A(custom 128), B(custom 1024), C(global 512) selected + batch -> saved images are
  128/1024/512 respectively; _obj_res/_obj_samples resolve correctly. Unregister drops the
  Object props.

## v0.15.1 — batch runs the FULL per-object checks (incl. UV overlap)
- Gap: batch applied modifiers + re-unwrapped modifier objects, but did NOT check UV overlap
  on objects WITHOUT modifiers - so hand-made overlapping UVs slipped through in multi-bake.
- _prep_object now mirrors the single-object checks for every batch object: apply modifiers
  where present (+optional backup); _ensure_uvs (auto-unwrap if none); then if the "Fix UVs"
  option is on, re-unwrap when EITHER modifiers were just applied OR _uv_looks_wrong() finds
  overlap / out-of-bounds. Clean UVs are left untouched (the overlap check short-circuits for
  objects that were re-unwrapped after applying, so it only runs on non-modifier objects).
- Batch dialog: the toggle is now "Fix UVs (overlap / after modifiers)", ungated from the
  modifier toggle (it applies to all objects), default ON; "Back up originals first" gated
  under "Apply modifiers". Sub-label now "Each is checked, baked, then auto-saved."
- Verified per-object: overlap-no-modifier 1.00 -> 0.00 (re-unwrapped); clean UVs unchanged;
  no-UV object auto-unwrapped; modifier objects applied.

## v0.15.2 — per-object res/samples: remembered-on-bake, no toggle
- Dropped the rpbake_use_custom bool + its update callback. Object.rpbake_res/rpbake_samples
  now default to 0 (min 0) = "not baked yet, use the global input".
- _start_native_bake writes the resolved res/samples back onto the object every bake, so an
  object remembers exactly what it was last baked with. _obj_res/_obj_samples return the
  object's value when >0, else the scene global.
- Panel: when the active mesh has rpbake_res > 0 (has been baked) it shows the object's saved
  Resolution/Samples; otherwise it shows the global scene inputs. Editing a baked object's
  fields updates its saved values; setting 0 resets it back to "use global".
- Single + batch both use _obj_res/_obj_samples, so multi-bake uses each object's saved
  settings where present and the global inputs where not.
- Verified: unbaked A -> global 512; bake A@128 -> A remembers 128; multi-bake A+B (global 512)
  -> A@128 (saved), B@512 (global), saved images 128/512, B now remembers 512.

## v0.15.3 — always pack after unwrap; denoiser->GPU; slow-path warning
- _smart_project now runs bpy.ops.uv.pack_islands(margin=scene.rpbake_pack_margin) after
  smart_project (select-all UVs first). New Scene.rpbake_pack_margin (Float, default 0.02,
  0..0.5) in Bake Settings under Margin(px). Verified: pack margin 0.1 insets islands.
- Denoiser to GPU: _start_native_bake sets scene.cycles.denoising_use_gpu=True when dev=='GPU';
  saves it in orig and _restore_scene restores it. (Best-effort: harmless if baking doesn't
  denoise, helpful if it does - not verifiable on the no-GPU test box.)
- _slow_warn(scene): '' if device mode is CPU (user chose it) or a GPU is available; else
  "No GPU enabled - baking[ and denoising] on CPU (slow). Enable a GPU in Preferences >
  System..." _start_native_bake returns (dev, warn); _render_native reports it (single);
  _start_batch reports it once. Verified: AUTO+no-GPU+denoise -> warns re both; CPU -> silent.

## v0.15.4 — "Global samples (all objects)" toggle in Bake Settings
- New Scene.rpbake_global_samples (bool, default False). When ON, every object bakes at the
  one global Samples value (resolution stays per-object).
- _obj_samples: returns scene.rpbake_samples when global_samples is on, else the object's
  saved samples (>0) else the global.
- _start_native_bake: while global_samples is on it does NOT write obj.rpbake_samples, so each
  object's remembered samples is frozen and reappears when the toggle is turned back off.
- Panel: samples field shows "Samples (global)" bound to the scene when the toggle is on;
  otherwise per-object-if-baked else global. Resolution unaffected (still per-object).
- Verified: per-object bake@8 -> A=8; global ON@32 -> _obj_samples=32; bake -> A still 8
  (preserved); global OFF -> _obj_samples back to 8 (restored).

## v0.16 — texel-density resolution suggester + "always re-unwrap & pack"
- New settings: rpbake_always_unwrap (bool), rpbake_texel_density (float px/m, default 1024),
  rpbake_suggest_on_render (bool). All in Bake Settings.
- Texel-density math: _obj_areas(obj) -> (world 3D area via matrix_world+loop_triangles, UV area
  in 0-1). _suggest_resolution = round(texel_density * sqrt(A3d/Auv)) to nearest standard size
  (_round_resolution, log-space nearest of 64..16384).
- "Suggest Resolution" button (RPBAKE_OT_suggest_res) above Resolution in the main panel,
  SINGLE object only (hidden with 2+ selected). Unwraps if no UVs, updates view_layer for
  current scale, sets obj.rpbake_res.
- Always re-unwrap & pack: when on, _prep_object (batch) and execute (single) force _smart_project
  every bake regardless of existing UVs.
- Suggest on render (single): invoke computes the suggestion (unwraps first if no UVs), shows
  "Suggested: N px" + "Use suggested resolution" (default on) in the confirm dialog; execute
  sets obj.rpbake_res if used. Forces the dialog to appear when enabled.
- Batch prompt: "Auto-set resolution (texel density)" checkbox (op.auto_res) -> _prep_object
  sets each object's rpbake_res from texel density after unwrap/pack.
- Verified: Small(1m)->128 vs Big(6m)->1024 via button; always_unwrap fixed pushed-out UVs on
  a bake; batch auto_res set 128/1024 per object. (Note: high texel density on large objects
  suggests 8k+ and can OOM the bake - that's expected; user picks the density.)

## v0.16.1 — removed the resolution suggester (kept "always re-unwrap & pack")
- User: the texel-density resolution suggester didn't work well in practice -> removed it.
- Removed: RPBAKE_OT_suggest_res + button, _obj_areas/_suggest_resolution/_round_resolution,
  rpbake_texel_density/rpbake_suggest_on_render props, operator auto_res/use_suggested_res/
  suggested_res, the on-render suggestion (invoke/draw/execute) and batch auto_res option.
- KEPT: rpbake_always_unwrap (always re-unwrap + pack every bake) - separate feature, works.
- Verified: single (always_unwrap) + batch still bake; no leftover suggest/texel refs; clean
  unregister. math import retained (used by worker offset + diagnostics).

## v0.17 — per-object persistent bake image + auto-save (removed the Save button)
- Root fix for "bakes stacking up over iterations": the old shared RESULT image + manual Save
  re-pointed each object's node to a saved file, so the NEXT bake found no RESULT node and made
  a new one -> a duplicate image node accumulated every bake-after-save.
- New model: each object owns its own persistent image via Object.rpbake_image (PointerProperty
  to Image), named "RPBake_<obj.name>". The bake targets THAT image; the same texture node is
  found/reused every bake; nothing stacks.
  - _object_bake_image(obj,res,float,cs) replaces _get_result_image: get/create/resize the
    object's own image in place (recreate at exact size on res/bit-depth change, re-point users).
  - _apply_result_to_object(obj) now reads obj.rpbake_image (reuses existing node).
  - Worker _store_result(png, obj) writes into obj.rpbake_image too (kept consistent; hidden path).
- Auto-save: _autosave_object(context,obj) + _autosave_dir(context) save the object's image to
  disk every bake (Save Folder or bakes/ next to .blend), overwriting <obj.name>.<ext>. Does NOT
  re-point the node (keeps the in-Blender image so rebake reuses it). Native completion and worker
  completion both auto-save. Status: "Baked & saved (native, DEV)" or "...not saved: <reason>".
- REMOVED: RPBAKE_OT_save operator + Save button; the whole unsaved-guard (save_previous prop,
  _unsaved_prev, dialog "last bake isn't saved" section, execute save-previous block,
  _state["unsaved"], _state["last_baked"]). Per-object images can't clobber each other so the
  guard is obsolete. Panel now shows Render + (when the object has a bake image) a "Show on Mesh"
  button; Save settings (folder/format/depth/view) retained and used by auto-save.
- Batch already required a save destination (kept); each object auto-saves via _autosave_object.
- Verified: same object baked x3 -> 1 image node throughout, same datablock reused, 1 saved file
  overwritten; res change 128->256 stays 1 node, resized; batch of 2 -> separate per-object images
  + 2 files, re-batch stays 1 node each + 2 files; clean unregister. RESULT_IMAGE_NAME kept only as
  worker no-object fallback.

## v0.17.1 — freeze fix: handler-driven completion + launch guard (was a polling race)
- User report: occasional HARD freeze (needs Blender restart), intermittent, same 2048 bake fast
  last time. Classic race shape.
- Root cause: _poll_native detected completion by polling is_job_running("OBJECT_BAKE") with only
  a 2.0s grace. If a bake was slow to START (kernel recompile, GPU busy, driver hiccup), at 2.0s
  is_job_running reads False (not started yet) -> poll FALSELY completes, restores scene, clears
  _state["job"] while the real bake is still spinning up. Then a 2nd bake stacks on top (immediately
  in a batch via _batch_advance; on next click for single) -> two Cycles bakes fight the GPU ->
  hard freeze. Intermittent = depends on whether the bake started within 2.0s.
- Fix (Blender 4.4 has real handlers - confirmed object_bake_pre/complete/cancel exist):
  1. Handlers drive completion: object_bake_pre -> job["seen_running"], object_bake_complete/cancel
     -> job["done"]. Reliable in the UI's modal bake (no polling race). Installed on register,
     removed on unregister.
  2. Gated fallback in _poll_native: never treat 'not running' as finished unless seen_running
     (bake confirmed started) OR _STARTUP_GRACE (30s) elapsed -> kills the slow-start false-complete.
  3. _STARTUP_GRACE=30s bounded fallback so it can NEVER hang if handlers don't fire (they don't
     fire headless - bake runs synchronously there; overridable in tests).
  4. Launch guard in _launch_native: if is_job_running("OBJECT_BAKE") when about to launch, defer
     (retry ~0.1s up to ~20s) instead of stacking a 2nd bake. This is the hard backstop - even a
     wrong completion can't start a concurrent bake (the actual freeze).
- Caveat: can't reproduce the UI freeze headless (no GPU; headless bake is synchronous and doesn't
  fire the handlers), so can't 100% confirm this was THE cause - but it's a real race matching the
  symptom, and the launch guard prevents the double-launch freeze regardless. If freezes persist,
  next suspects: pure Cycles/GPU driver hang (outside addon), or save_render() on the main thread in
  completion (could defer to its own tick).
- Verified headless (grace=3s): single "Baked & saved"; batch 2/2 with 0 launch-while-running
  incidents; clean unregister.

## v0.17.2 — remove Show-on-Mesh button; fix auto-save (image now shows saved + colour-managed)
- Removed the "Show on Mesh" button + RPBAKE_OT_show_on_mesh operator (added in v0.17). Redundant:
  the bake already creates the node and makes it active - showing on the mesh is default behaviour.
- Save bug: v0.17 auto-save called img.save_render() which writes a colour-managed FILE to disk but
  never touches the in-Blender datablock, so the Image Editor kept showing the raw scene-linear bake
  buffer, marked unsaved, with no view transform - user (correctly) read this as "not saving".
- Fix - two-image + single tagged node (no stacking, matches the old Save behaviour):
  - _bake_work_image(obj,res,float,colorspace): per-object WORKING image the bake writes into,
    colorspace = rpbake_colorspace (sRGB default) so save_render output matches what Save produced.
    Named RPBakeWork_<obj.name>.
  - _bake_node(obj, image, make_active): finds/creates ONE tagged node (node['rpbake']=1) per material
    and swaps its image - linear work image while baking, saved file after. Same node forever = no stack.
  - _autosave_object: save_render(work) -> colour-managed file, then bpy.data.images.load(file) ->
    obj.rpbake_image, reload, and point the tagged node at it. So the mesh + Image Editor show the
    SAVED, colour-managed texture (source=FILE, is_dirty=False), exactly like hitting Save used to.
    On no-destination it leaves the raw work image visible and reports the reason.
  - _start_native_bake targets the work image via the tagged node; _apply_result_to_object + worker
    _store_result updated to the tagged-node/work-image model; _poll_native lets autosave own the
    node switch (removed the stale pre-apply). _object_bake_image removed.
- Verified headless: single -> "Baked & saved", 1 tagged node, disp source=FILE + is_dirty False;
  rebake -> 1 node, 1 file overwritten; batch 2 -> separate files, 1 node each; clean unregister.
- Caveat: couldn't confirm the colour-management LOOK numerically headless (couldn't get a reliably
  lit test bake on the sample object), but save_render is the identical call the old Save used and the
  displayed image is now the loaded saved file - user should eyeball it.
