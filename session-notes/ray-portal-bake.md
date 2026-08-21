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
