bl_info = {
    "name": "Ray Portal Bake",
    "author": "Theory-box / Claude Relay",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Portal Bake",
    "description": "Live-bake a mesh's real, lit surface into UV space using the Ray Portal BSDF (Cycles).",
    "category": "Render",
}

import bpy
import mathutils

FLAT_NAME = "RPBake_Flat"
CAM_NAME = "RPBake_Cam"
MAT_NAME = "RPBake_PortalMat"
COLL_NAME = "RPBake"
ATTR_POS = "rpbake_pos"
ATTR_NRM = "rpbake_nrm"


# --- build the flattened UV copy -------------------------------------------
def _build_flat_mesh(obj, depsgraph):
    """Per-corner flatten: every face corner becomes a vertex at its UV, carrying
    the corner's WORLD position + normal. Handles seams/islands (corners at a seam
    simply land at different UVs) and per-corner UVs correctly."""
    eval_obj = obj.evaluated_get(depsgraph)
    me = eval_obj.to_mesh()
    try:
        uv_layer = me.uv_layers.active
        if uv_layer is None:
            return None, "Object has no active UV map."
        uv_data = uv_layer.data

        mw = eval_obj.matrix_world
        nmat = mw.to_3x3().inverted_safe().transposed()

        # per-loop (corner) normals if available, else vertex normals
        try:
            me.calc_normals_split()
        except Exception:
            pass
        corner_normals = None
        if hasattr(me, "corner_normals") and len(me.corner_normals):
            corner_normals = me.corner_normals

        verts = []
        faces = []
        pos = []
        nrm = []
        # UVs may sit in a tile offset from 0..1 (glTF imports often land V in
        # [-1,0]). Shift by the integer offset so the layout fills the 0..1 tile;
        # because it's a whole-tile shift, texture repeat still maps it back
        # correctly when the baked image is applied with the original UVs.
        import math
        umin = min(uv_data[li].uv[0] for p in me.polygons for li in p.loop_indices)
        vmin = min(uv_data[li].uv[1] for p in me.polygons for li in p.loop_indices)
        su = -math.floor(umin)
        sv = -math.floor(vmin)
        for poly in me.polygons:
            fidx = []
            for li in poly.loop_indices:
                loop = me.loops[li]
                vi = loop.vertex_index
                uv = uv_data[li].uv
                verts.append((uv.x + su, uv.y + sv, 0.0))
                world_co = mw @ me.vertices[vi].co
                pos.append((world_co.x, world_co.y, world_co.z))
                if corner_normals is not None:
                    ln = corner_normals[li].vector
                else:
                    ln = me.vertices[vi].normal
                wn = (nmat @ mathutils.Vector(ln)).normalized()
                nrm.append((wn.x, wn.y, wn.z))
                fidx.append(len(verts) - 1)
            faces.append(tuple(fidx))
    finally:
        eval_obj.to_mesh_clear()

    flat = bpy.data.meshes.new(FLAT_NAME)
    flat.from_pydata(verts, [], faces)
    flat.update()
    ap = flat.attributes.new(ATTR_POS, "FLOAT_VECTOR", "POINT")
    ap.data.foreach_set("vector", [c for v in pos for c in v])
    an = flat.attributes.new(ATTR_NRM, "FLOAT_VECTOR", "POINT")
    an.data.foreach_set("vector", [c for v in nrm for c in v])
    return flat, None


# --- portal material --------------------------------------------------------
def _make_portal_material(epsilon):
    mat = bpy.data.materials.get(MAT_NAME)
    if mat is None:
        mat = bpy.data.materials.new(MAT_NAME)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)

    a_pos = nt.nodes.new("ShaderNodeAttribute")
    a_pos.attribute_name = ATTR_POS
    a_nrm = nt.nodes.new("ShaderNodeAttribute")
    a_nrm.attribute_name = ATTR_NRM

    off = nt.nodes.new("ShaderNodeVectorMath")
    off.operation = "SCALE"
    off.inputs["Scale"].default_value = epsilon
    nt.links.new(a_nrm.outputs["Vector"], off.inputs[0])

    pos = nt.nodes.new("ShaderNodeVectorMath")
    pos.operation = "ADD"
    nt.links.new(a_pos.outputs["Vector"], pos.inputs[0])
    nt.links.new(off.outputs["Vector"], pos.inputs[1])

    neg = nt.nodes.new("ShaderNodeVectorMath")
    neg.operation = "SCALE"
    neg.inputs["Scale"].default_value = -1.0
    nt.links.new(a_nrm.outputs["Vector"], neg.inputs[0])

    rp = nt.nodes.new("ShaderNodeBsdfRayPortal")
    nt.links.new(pos.outputs["Vector"], rp.inputs["Position"])
    nt.links.new(neg.outputs["Vector"], rp.inputs["Direction"])

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(rp.outputs["BSDF"], out.inputs["Surface"])
    return mat


def _scene_top_z(context):
    zmax = 0.0
    found = False
    for ob in context.scene.objects:
        if ob.type != "MESH":
            continue
        for corner in ob.bound_box:
            wz = (ob.matrix_world @ mathutils.Vector(corner)).z
            zmax = wz if not found else max(zmax, wz)
            found = True
    return zmax if found else 0.0


def _get_coll(context):
    coll = bpy.data.collections.get(COLL_NAME)
    if coll is None:
        coll = bpy.data.collections.new(COLL_NAME)
        context.scene.collection.children.link(coll)
    return coll


# --- operators --------------------------------------------------------------
class RPBAKE_OT_setup(bpy.types.Operator):
    bl_idname = "rpbake.setup"
    bl_label = "Set Up Portal Bake"
    bl_description = "Build the UV-flattened portal copy + bake camera for the active object"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"WARNING"}, "Select a mesh object.")
            return {"CANCELLED"}
        if not obj.data.materials:
            self.report({"WARNING"}, "Object has no material to bake.")
            return {"CANCELLED"}

        _clear(context)  # start clean

        depsgraph = context.evaluated_depsgraph_get()
        flat_me, err = _build_flat_mesh(obj, depsgraph)
        if flat_me is None:
            self.report({"WARNING"}, err)
            return {"CANCELLED"}

        coll = _get_coll(context)
        eps = context.scene.rpbake_epsilon
        mat = _make_portal_material(eps)

        flat_obj = bpy.data.objects.new(FLAT_NAME, flat_me)
        flat_obj.data.materials.append(mat)
        coll.objects.link(flat_obj)

        # place the flat copy + camera above everything so nothing occludes it
        z = _scene_top_z(context) + 10.0
        flat_obj.location = (0.0, 0.0, z)

        cam_data = bpy.data.cameras.new(CAM_NAME)
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = 1.0
        cam = bpy.data.objects.new(CAM_NAME, cam_data)
        cam.location = (0.5, 0.5, z + 5.0)  # look straight down at the 0..1 square
        coll.objects.link(cam)

        # neutral colour management + Cycles
        sc = context.scene
        sc.render.engine = "CYCLES"
        try:
            sc.view_settings.view_transform = "Standard"
            sc.view_settings.look = "None"
            sc.view_settings.exposure = 0.0
            sc.view_settings.gamma = 1.0
        except Exception:
            pass

        self.report({"INFO"}, "Portal bake set up. Set the '%s' camera as active "
                              "and view in Rendered (Cycles) to see the live bake." % CAM_NAME)
        return {"FINISHED"}


class RPBAKE_OT_clear(bpy.types.Operator):
    bl_idname = "rpbake.clear"
    bl_label = "Clear Portal Bake"
    bl_description = "Remove the portal copy, camera, and collection"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _clear(context)
        self.report({"INFO"}, "Portal bake cleared.")
        return {"FINISHED"}


def _clear(context):
    for name in (FLAT_NAME, CAM_NAME):
        ob = bpy.data.objects.get(name)
        if ob is not None:
            data = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            try:
                if isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
                elif isinstance(data, bpy.types.Camera):
                    bpy.data.cameras.remove(data)
            except Exception:
                pass
    coll = bpy.data.collections.get(COLL_NAME)
    if coll is not None and not coll.objects:
        bpy.data.collections.remove(coll)


# --- panel ------------------------------------------------------------------
class RPBAKE_PT_panel(bpy.types.Panel):
    bl_label = "Ray Portal Bake"
    bl_idname = "RPBAKE_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Portal Bake"

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "rpbake_epsilon")
        layout.operator("rpbake.setup", icon="RENDER_STILL")
        layout.operator("rpbake.clear", icon="TRASH")
        if bpy.data.objects.get(FLAT_NAME) is not None:
            layout.label(text="Active: view '%s' in Rendered." % CAM_NAME, icon="INFO")


_classes = (RPBAKE_OT_setup, RPBAKE_OT_clear, RPBAKE_PT_panel)


def register():
    bpy.types.Scene.rpbake_epsilon = bpy.props.FloatProperty(
        name="Surface Offset",
        description="How far above the surface the portal ray starts (world units)",
        default=0.02, min=0.0001, max=1.0, precision=4)
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    if hasattr(bpy.types.Scene, "rpbake_epsilon"):
        del bpy.types.Scene.rpbake_epsilon


if __name__ == "__main__":
    register()
