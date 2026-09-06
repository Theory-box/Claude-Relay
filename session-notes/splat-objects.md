# Branch: feature/splat-objects  (v0.13.1 — WORKING)

Goal: splats become selectable + duplicatable scene objects.

## Done
- Generation creates an Empty anchor (empty_display_type SPHERE) with custom prop `vlr_splat_id`.
- Cloud geometry stored in LOCAL space (world - anchor translation) in splat_render.SPLAT_CLOUDS[id].
- Engine collects anchors from the depsgraph (objects with vlr_splat_id) + draws each at its
  matrix_world; billboard _VERT applies uModel (transforms centre + covariance basis + normal).
- Sort runs in the object's LOCAL space (camera transformed to local — cheap), cached per object
  (CPU sort) / run per object per frame (GPU sort). GPU sort culling works per object.
- Shift+D duplicates the Empty (inherits vlr_splat_id) -> same cloud drawn at the new transform.
- Fixed: _draw_splats early-returned on empty SCENE_CLOUDS (legacy list); now also checks anchors.

## uModel now in ALL paths (v0.13.2): billboard colour/depth, AO (rides depth), cavity normals
   (_NRM), compute pre-pass (params[56:72]), tile rasterizer (via uMdl image + per-object render).
   Every splat effect now follows the object transform for moved/duplicated clouds.
- Non-uniform anchor scale slightly distorts splat normals (lighting); rot+uniform-scale+translate OK.
- Pixel-picking (click splats to select) NOT done — selection is via the Empty gizmo / outliner.
  True pixel selection = separate GPU-picking feature.

## Not yet merged to main (main is at v0.12.6 with GPU sort). Awaiting user OK.
