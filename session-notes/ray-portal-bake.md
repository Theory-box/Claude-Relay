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
