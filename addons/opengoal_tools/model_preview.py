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
    return _data_root() / "data" / "decompiler_out" / "jak1" / glb_rel


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
        col["og_no_export"] = True
        return col

    # Use _ensure_sub_collection so the name is level-prefixed (e.g. my-level.Preview Meshes)
    col = _ensure_sub_collection(level_col, _PREVIEW_COL)
    col["og_no_export"] = True
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
    """From the newly imported objects, keep the primary mesh (matched by name),
    hide the armature, and delete any stray objects (icospheres etc).
    Returns the primary mesh Object, or None if none found."""

    mesh_obj  = None
    arm_objs  = []
    junk_objs = []

    for obj in new_objs:
        if obj.type == "MESH":
            # Prefer the mesh whose name starts with the GLB stem (e.g. 'plat-lod0').
            # The GLB importer may also create stray objects like 'Icosphere' from
            # the default fallback material — those should be discarded.
            obj_base = obj.name.split(".")[0]  # strip Blender .001/.002 suffix
            if glb_stem and obj_base == glb_stem:
                mesh_obj = obj
            elif mesh_obj is None and glb_stem and obj_base != "Icosphere":
                mesh_obj = obj  # fallback: any non-icosphere mesh
            elif not glb_stem and mesh_obj is None:
                mesh_obj = obj
            else:
                junk_objs.append(obj)
        elif obj.type == "ARMATURE":
            arm_objs.append(obj)
        else:
            junk_objs.append(obj)

    # Any meshes that lost out to the named match also become junk
    # (catches icosphere and any other stray geometry)
    if mesh_obj is not None:
        for obj in list(junk_objs):
            pass  # already in junk
        # make sure icospheres aren't accidentally kept
        junk_objs = [o for o in new_objs if o is not mesh_obj and o not in arm_objs]

    if mesh_obj is None:
        for obj in new_objs:
            bpy.data.objects.remove(obj, do_unlink=True)
        return None

    # ---- Hide the armature (keeps mesh deformed correctly at bind pose) ----
    for arm in arm_objs:
        arm.hide_viewport  = True
        arm.hide_render    = True
        arm.hide_select    = True
        arm[_PREVIEW_PROP] = True

    # ---- Delete stray objects (icosphere, etc.) ----
    for obj in junk_objs:
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

        attached = True

    return attached


def remove_preview(actor_empty: bpy.types.Object) -> None:
    """Remove all preview mesh children from the given ACTOR empty."""
    children = [c for c in actor_empty.children if c.get(_PREVIEW_PROP)]
    for child in children:
        bpy.data.objects.remove(child, do_unlink=True)


def remove_all_previews(scene) -> int:
    """Remove every preview mesh in the scene. Returns count removed."""
    count = 0
    for obj in list(scene.objects):
        if obj.get(_PREVIEW_PROP):
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
        if obj and obj.get(_PREVIEW_PROP) and obj.parent is None:
            bpy.data.objects.remove(obj, do_unlink=True)
    return None  # don't repeat


def _on_depsgraph_update(scene, depsgraph):
    """Depsgraph handler — detect orphaned preview meshes and schedule removal.
    Kept intentionally cheap: only scans if there are any preview meshes at all."""
    orphans = [
        o.name for o in scene.objects
        if o.get(_PREVIEW_PROP) and o.parent is None
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
