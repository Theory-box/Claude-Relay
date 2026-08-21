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
