# ---------------------------------------------------------------------------
# model_preview.py — OpenGOAL Level Tools
# Enemy model preview — imports the decompiler's GLB as a static stand-in
# mesh parented to the ACTOR empty.  No armature, no animations, viewport only.
#
# Requires rip_levels: true in jak1_config.jsonc and a decompiler run.
# GLB path pattern:
#   <data_root>/data/decompiler_out/jak1/levels/<level>/<model>-lod0-mg.glb
# ---------------------------------------------------------------------------

import bpy
import bmesh
import mathutils
from pathlib import Path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_PREVIEW_COL   = "Preview Meshes"   # sub-collection name (no-export)
_PREVIEW_PROP  = "og_preview_mesh"  # custom property key on each mesh object


def _data_root() -> Path:
    """Return the addon data_path preference as a Path (mirrors build.py)."""
    prefs = bpy.context.preferences.addons.get("opengoal_tools")
    p = prefs.preferences.data_path if prefs else ""
    p = p.strip().rstrip("\\").rstrip("/")
    return Path(p) if p else Path(".")


def _glb_path(glb_rel: str) -> Path:
    """Resolve a relative glb path (e.g. 'levels/beach/babak-lod0.glb')
    against the decompiler output directory."""
    from .build import _decompiler_path
    return _decompiler_path() / glb_rel


def models_available() -> bool:
    """Return True if at least one enemy GLB exists (rip_levels was run)."""
    probe = _glb_path("levels/beach/babak-lod0.glb")
    return probe.exists()


def models_probe_path() -> str:
    """Return the path being probed, for display in warning messages."""
    return str(_glb_path("levels/beach/babak-lod0.glb"))


def _get_viewport_override(ctx):
    """Return (window, area, region) for the first VIEW_3D area found,
    or (None, None, None) if none exists.  Required for import_scene.gltf."""
    for window in ctx.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        return window, area, region
    return None, None, None


def _ensure_preview_collection(scene) -> bpy.types.Collection:
    """Find or create the level-local 'Preview Meshes' sub-collection,
    marked og_no_export so export_glb() skips it entirely."""
    from .collections import _active_level_col, _ensure_sub_collection

    level_col = _active_level_col(scene)
    if level_col is None:
        # No level collection — fall back to scene root collection
        col_name = _PREVIEW_COL
        col = bpy.data.collections.get(col_name)
        if col is None:
            col = bpy.data.collections.new(col_name)
            scene.collection.children.link(col)
        col.og_no_export = True
        return col

    # Use _ensure_sub_collection so the name is level-prefixed (e.g. my-level.Preview Meshes)
    col = _ensure_sub_collection(level_col, _PREVIEW_COL)
    col.og_no_export = True
    return col


def _import_glb(ctx, glb_path: Path) -> list:
    """Import a GLB file and return the list of newly created objects.
    Uses temp_override to satisfy the VIEW_3D context requirement."""
    window, area, region = _get_viewport_override(ctx)

    before = set(bpy.data.objects)

    if window and area and region:
        with ctx.temp_override(window=window, area=area, region=region):
            bpy.ops.import_scene.gltf(filepath=str(glb_path))
    else:
        # Fallback — may fail without a viewport, but worth trying
        bpy.ops.import_scene.gltf(filepath=str(glb_path))

    return [o for o in bpy.data.objects if o not in before]


def _strip_and_keep_mesh(new_objs: list, glb_stem: str = "") -> bpy.types.Object | None:
    """From the newly imported objects, keep the primary mesh (matched by GLB stem name).
    Removes the armature modifier, deletes the armature and all other stray objects
    (icospheres etc). Returns the primary mesh Object, or None if none found."""

    mesh_obj = None

    # Pick the mesh whose base name matches the GLB stem.
    # Fall back to any non-Icosphere mesh if no exact match found.
    for obj in new_objs:
        if obj.type != "MESH":
            continue
        obj_base = obj.name.split(".")[0]
        if glb_stem and obj_base == glb_stem:
            mesh_obj = obj
            break
        if mesh_obj is None and obj_base != "Icosphere":
            mesh_obj = obj

    if mesh_obj is None:
        for obj in new_objs:
            bpy.data.objects.remove(obj, do_unlink=True)
        return None

    # ---- Strip armature modifier from the chosen mesh ----
    for mod in list(mesh_obj.modifiers):
        if mod.type == "ARMATURE":
            mesh_obj.modifiers.remove(mod)

    # ---- Delete everything else (armatures, icospheres, other meshes) ----
    for obj in new_objs:
        if obj is not mesh_obj:
            bpy.data.objects.remove(obj, do_unlink=True)

    # ---- Recalculate normals ----
    bm = bmesh.new()
    bm.from_mesh(mesh_obj.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh_obj.data)
    bm.free()
    mesh_obj.data.update()

    return mesh_obj


def _reuse_or_import(ctx, glb_path: Path, mesh_name: str) -> bpy.types.Object | None:
    """Return a mesh object for the given GLB.
    If mesh data already exists in bpy.data.meshes (from a previous import),
    creates a linked duplicate instead of re-importing — O(1) memory cost."""

    # Check for existing mesh data (handles 'babak-lod0-mg', 'babak-lod0-mg.001', etc.)
    existing_mesh_data = bpy.data.meshes.get(mesh_name)
    if existing_mesh_data is None:
        # Also check for .001 suffix variants created by Blender on repeated import
        for md in bpy.data.meshes:
            base = md.name.split(".")[0]
            if base == mesh_name:
                existing_mesh_data = md
                break

    if existing_mesh_data is not None:
        # Linked duplicate — shares mesh data, materials, etc.
        new_obj = bpy.data.objects.new(mesh_name, existing_mesh_data)
        # Link into scene so it exists
        ctx.scene.collection.objects.link(new_obj)
        return new_obj

    # Full import
    if not glb_path.exists():
        return None

    new_objs = _import_glb(ctx, glb_path)
    if not new_objs:
        return None

    return _strip_and_keep_mesh(new_objs, glb_stem=mesh_name)



def _fit_empty_to_mesh(actor_empty: bpy.types.Object, mesh_obj: bpy.types.Object) -> None:
    """Resize the actor empty so its display gizmo wraps the viz mesh bounds.
    Uses the mesh local bounding box (8 corners) to find the largest half-extent
    across all axes, then sets empty_display_size to that value.
    No-ops if the mesh has zero-size bounds (degenerate geometry)."""
    corners = [mathutils.Vector(c) for c in mesh_obj.bound_box]
    if not corners:
        return
    # Find min/max per axis
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    zs = [c.z for c in corners]
    half_x = (max(xs) - min(xs)) * 0.5
    half_y = (max(ys) - min(ys)) * 0.5
    half_z = (max(zs) - min(zs)) * 0.5
    size = max(half_x, half_y, half_z)
    if size > 0.001:  # guard against degenerate/empty mesh
        actor_empty.empty_display_size = size

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def attach_preview(ctx, etype: str, actor_empty: bpy.types.Object) -> bool:
    """Import and attach a preview mesh to the given ACTOR empty.

    Returns True if a preview was attached, False if GLBs aren't available
    or this etype has no GLB mapping.

    Handles both single-GLB enemies and double-lurker (list of GLBs).
    """
    from .data import ENTITY_DEFS

    info = ENTITY_DEFS.get(etype, {})
    glb_rel = info.get("glb")

    if not glb_rel:
        return False  # etype has no GLB (lightning-mole, ice-cube, etc.)

    # Normalise to list so double-lurker and singles use the same loop
    if isinstance(glb_rel, str):
        glb_rels = [glb_rel]
    else:
        glb_rels = list(glb_rel)

    preview_col = _ensure_preview_collection(ctx.scene)
    attached    = False

    for rel in glb_rels:
        glb_path  = _glb_path(rel)
        mesh_name = Path(rel).stem  # e.g. "babak-lod0-mg"

        mesh_obj = _reuse_or_import(ctx, glb_path, mesh_name)
        if mesh_obj is None:
            continue

        # ---- Parent to actor empty ----
        # The actor_empty is already at cursor_loc.
        # Set mesh local position to (0,0,0) so it sits exactly at the empty,
        # then use identity matrix_parent_inverse so no extra offset is applied.
        mesh_obj.location              = (0.0, 0.0, 0.0)
        mesh_obj.parent                = actor_empty
        mesh_obj.matrix_parent_inverse = mathutils.Matrix()  # identity

        # ---- Tag as preview (export exclusion + identification) ----
        mesh_obj[_PREVIEW_PROP] = True

        # ---- Move into preview collection ----
        # Unlink from wherever Blender auto-placed it, re-link into preview col
        for col in list(mesh_obj.users_collection):
            col.objects.unlink(mesh_obj)
        preview_col.objects.link(mesh_obj)

        # ---- Display settings ----
        mesh_obj.show_in_front     = False
        mesh_obj.display_type      = "TEXTURED"
        mesh_obj.hide_select       = True   # non-selectable — move the ACTOR empty instead

        # ---- Fit empty display size to mesh bounds (first GLB only) ----
        if not attached:  # only on the first mesh so double-lurker doesn't overwrite
            _fit_empty_to_mesh(actor_empty, mesh_obj)

        attached = True

    return attached


_WAYPOINT_PREVIEW_PROP = "og_waypoint_preview_mesh"
_WAYPOINT_GHOST_MAT    = "OG_WaypointGhost"


def _get_or_create_ghost_material() -> bpy.types.Material:
    """Return the shared waypoint ghost material (white, 50% transparent, no textures).
    Creates it once and reuses across all waypoint previews."""
    mat = bpy.data.materials.get(_WAYPOINT_GHOST_MAT)
    if mat is not None:
        return mat

    mat = bpy.data.materials.new(name=_WAYPOINT_GHOST_MAT)
    mat.use_nodes = True
    mat.blend_method = "BLEND"          # Alpha blend in EEVEE
    mat.shadow_method = "NONE"          # No shadow casting
    mat.use_backface_culling = False

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Principled BSDF — white, no roughness texture, 50% alpha
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    bsdf.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    bsdf.inputs["Roughness"].default_value  = 0.8
    bsdf.inputs["Metallic"].default_value   = 0.0
    bsdf.inputs["Alpha"].default_value      = 0.5

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (300, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    return mat


def _apply_ghost_material(mesh_obj: bpy.types.Object) -> None:
    """Replace all materials on mesh_obj with the ghost material."""
    ghost = _get_or_create_ghost_material()
    mesh_obj.data.materials.clear()
    mesh_obj.data.materials.append(ghost)


def attach_waypoint_preview(ctx, etype: str, waypoint_empty: bpy.types.Object) -> bool:
    """Import and attach a ghost (white, 50% transparent) preview mesh to the
    given WAYPOINT empty.

    Mirrors attach_preview() but uses a unique property tag and ghost material
    so the two types can be cleaned up independently.

    Returns True if a preview was attached.
    """
    from .data import ENTITY_DEFS

    info    = ENTITY_DEFS.get(etype, {})
    glb_rel = info.get("glb")

    if not glb_rel:
        return False

    # Normalise to list (double-lurker has two GLBs; only take the first for waypoints)
    if isinstance(glb_rel, list):
        glb_rel = glb_rel[0]

    glb_path  = _glb_path(glb_rel)
    mesh_name = Path(glb_rel).stem + "_wp_ghost"  # distinct name so mesh data is separate

    # --- Reuse existing ghost mesh data if already in bpy.data.meshes ---
    existing_mesh_data = None
    for md in bpy.data.meshes:
        if md.name.split(".")[0] == mesh_name:
            existing_mesh_data = md
            break

    if existing_mesh_data is not None:
        mesh_obj = bpy.data.objects.new(mesh_name, existing_mesh_data)
        ctx.scene.collection.objects.link(mesh_obj)
    else:
        if not glb_path.exists():
            return False
        new_objs = _import_glb(ctx, glb_path)
        if not new_objs:
            return False
        raw_stem = Path(glb_rel).stem
        mesh_obj = _strip_and_keep_mesh(new_objs, glb_stem=raw_stem)
        if mesh_obj is None:
            return False
        # Rename mesh data so future waypoints reuse it cleanly
        mesh_obj.data.name = mesh_name
        mesh_obj.name      = mesh_name

    # ---- Apply ghost material (white, 50% alpha, no textures) ----
    _apply_ghost_material(mesh_obj)

    # ---- Parent to waypoint empty ----
    mesh_obj.location              = (0.0, 0.0, 0.0)
    mesh_obj.parent                = waypoint_empty
    mesh_obj.matrix_parent_inverse = mathutils.Matrix()

    # ---- Tag as waypoint preview ----
    mesh_obj[_WAYPOINT_PREVIEW_PROP] = True

    # ---- Route into preview collection ----
    preview_col = _ensure_preview_collection(ctx.scene)
    for col in list(mesh_obj.users_collection):
        col.objects.unlink(mesh_obj)
    preview_col.objects.link(mesh_obj)

    # ---- Display settings ----
    mesh_obj.show_in_front = False
    mesh_obj.display_type  = "TEXTURED"
    mesh_obj.hide_select   = True

    return True


def _is_any_preview(obj) -> bool:
    """Return True if obj is either an actor preview or a waypoint ghost preview."""
    return bool(obj.get(_PREVIEW_PROP) or obj.get(_WAYPOINT_PREVIEW_PROP))


def remove_preview(actor_empty: bpy.types.Object) -> None:
    """Remove all preview mesh children from the given ACTOR or WAYPOINT empty."""
    children = [c for c in actor_empty.children if _is_any_preview(c)]
    for child in children:
        bpy.data.objects.remove(child, do_unlink=True)


def remove_all_previews(scene) -> int:
    """Remove every preview mesh (actor or waypoint ghost) in the scene.
    Returns count removed."""
    count = 0
    for obj in list(scene.objects):
        if _is_any_preview(obj):
            bpy.data.objects.remove(obj, do_unlink=True)
            count += 1
    return count


# ---------------------------------------------------------------------------
# Orphan cleanup — auto-delete preview meshes when their parent is deleted
# ---------------------------------------------------------------------------

def _cleanup_orphans(names: list) -> None:
    """Timer callback: remove any preview meshes that lost their parent.
    Runs outside the depsgraph update so object removal is safe."""
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj and _is_any_preview(obj) and obj.parent is None:
            bpy.data.objects.remove(obj, do_unlink=True)
    return None  # don't repeat


def _on_depsgraph_update(scene, depsgraph):
    """Depsgraph handler — detect orphaned preview meshes and schedule removal.
    Kept intentionally cheap: only scans if there are any preview meshes at all."""
    orphans = [
        o.name for o in scene.objects
        if _is_any_preview(o) and o.parent is None
    ]
    if orphans:
        bpy.app.timers.register(
            lambda: _cleanup_orphans(orphans),
            first_interval=0.0,
        )


def register_handler() -> None:
    """Call from addon register() to enable auto-cleanup."""
    if _on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)


def unregister_handler() -> None:
    """Call from addon unregister() to remove the handler cleanly."""
    if _on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update)
