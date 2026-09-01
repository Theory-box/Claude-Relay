bl_info = {
    "name": "String-Engine JSON (import/export)",
    "author": "—",
    "version": (2, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar (N) > String JSON  |  File > Import/Export",
    "description": "Import a saved string-engine scene, edit the geometry, assign per-object attributes, and export back to JSON.",
    "category": "Import-Export",
}

import bpy
import os
import json
from bpy.props import (BoolProperty, StringProperty, FloatProperty, IntProperty,
                       EnumProperty, CollectionProperty)
from bpy_extras.io_utils import ExportHelper, ImportHelper

MESHABLE = {"MESH", "CURVE", "SURFACE", "FONT", "META"}

# Attributes a user actually sets in Blender. The rest (damping, paddings,
# interactions, self-solid) are tuned in the app and only ride along on round-trip.
DEFAULT_ATTRS = [
    ("thickness", "FLOAT", 3.0), ("stiffness", "FLOAT", 0.1),
    ("curl", "FLOAT", 0.0), ("grow", "FLOAT", 0.0),
    ("solid", "BOOL", 0.0), ("fixed", "BOOL", 0.0),
]
CORE_KEYS = ("thickness", "stiffness", "curl", "grow", "solid", "fixed")
BOOL_KEYS = ("solid", "fixed")
APP_SCALAR_KEYS = ("damp", "padSelf", "padOther", "selfSolid", "interSelf", "color")


def get_prefs(context):
    try:
        return context.preferences.addons[__name__].preferences
    except (KeyError, AttributeError):
        return None


class STRJSON_AttrItem(bpy.types.PropertyGroup):
    name: StringProperty(name="Name", default="attribute")
    atype: EnumProperty(name="Type",
                        items=[("FLOAT", "Float", ""), ("BOOL", "Bool", "")],
                        default="FLOAT")
    value: FloatProperty(name="Value", default=0.0)
    bval: BoolProperty(name="On", default=False)


class STRJSON_UL_attrs(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon="DOT")
        row.prop(item, "atype", text="")


class STRJSON_Prefs(bpy.types.AddonPreferences):
    bl_idname = __name__
    attributes: CollectionProperty(type=STRJSON_AttrItem)
    active_index: IntProperty(default=0)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Assignable attributes (shown in the N-panel):")
        row = layout.row()
        row.template_list("STRJSON_UL_attrs", "", self, "attributes", self, "active_index", rows=6)
        col = row.column(align=True)
        col.operator("strjson.attr_add", icon="ADD", text="")
        col.operator("strjson.attr_remove", icon="REMOVE", text="")
        col.separator()
        col.operator("strjson.attr_defaults", icon="PRESET", text="")


class STRJSON_OT_attr_add(bpy.types.Operator):
    bl_idname = "strjson.attr_add"
    bl_label = "Add Attribute"
    def execute(self, context):
        p = get_prefs(context)
        if p is None:
            return {"CANCELLED"}
        it = p.attributes.add(); it.name = "attribute"
        p.active_index = len(p.attributes) - 1
        return {"FINISHED"}


class STRJSON_OT_attr_remove(bpy.types.Operator):
    bl_idname = "strjson.attr_remove"
    bl_label = "Remove Attribute"
    def execute(self, context):
        p = get_prefs(context)
        if p is None:
            return {"CANCELLED"}
        i = p.active_index
        if 0 <= i < len(p.attributes):
            p.attributes.remove(i)
            p.active_index = min(i, len(p.attributes) - 1)
        return {"FINISHED"}


class STRJSON_OT_attr_defaults(bpy.types.Operator):
    bl_idname = "strjson.attr_defaults"
    bl_label = "Add Default Attributes"
    bl_description = "Add the standard string-engine attributes if missing"
    def execute(self, context):
        p = get_prefs(context)
        if p is None:
            return {"CANCELLED"}
        have = {a.name for a in p.attributes}
        for name, atype, val in DEFAULT_ATTRS:
            if name in have:
                continue
            it = p.attributes.add(); it.name = name; it.atype = atype
            it.value = val; it.bval = bool(val)
        return {"FINISHED"}


def assign_object(context, name, atype, fval, bval):
    val = (1 if bval else 0) if atype == "BOOL" else float(fval)
    n = 0
    for o in context.selected_objects:
        o[name] = val
        n += 1
    return n


class STRJSON_OT_assign(bpy.types.Operator):
    bl_idname = "strjson.assign"
    bl_label = "Assign Attribute"
    bl_description = "Write this attribute to the selected objects"
    idx: IntProperty(default=-1)

    def execute(self, context):
        p = get_prefs(context)
        if p is None or not (0 <= self.idx < len(p.attributes)):
            return {"CANCELLED"}
        it = p.attributes[self.idx]
        n = assign_object(context, it.name, it.atype, it.value, it.bval)
        self.report({"INFO"}, "Set '%s' on %d object(s)" % (it.name, n))
        return {"FINISHED"}


class STRJSON_OT_assign_all(bpy.types.Operator):
    bl_idname = "strjson.assign_all"
    bl_label = "Assign All"
    bl_description = "Write every listed attribute to the selected objects"
    def execute(self, context):
        p = get_prefs(context)
        if p is None:
            return {"CANCELLED"}
        for it in p.attributes:
            assign_object(context, it.name, it.atype, it.value, it.bval)
        self.report({"INFO"}, "Assigned %d attributes" % len(p.attributes))
        return {"FINISHED"}


class STRJSON_PT_panel(bpy.types.Panel):
    bl_label = "String JSON"
    bl_idname = "STRJSON_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "String JSON"

    def draw(self, context):
        layout = self.layout
        p = get_prefs(context)

        col = layout.column(align=True)
        col.operator("import_scene.string_json", text="Import scene...", icon="IMPORT")
        col.operator("export_scene.string_json", text="Export scene...", icon="EXPORT")
        layout.separator()

        box = layout.box()
        n = len(context.selected_objects)
        box.label(text="Attributes -> %d selected object(s)" % n, icon="OBJECT_DATA")

        if p is None:
            layout.label(text="Enable the add-on to manage attributes.", icon="ERROR")
            return
        if len(p.attributes) == 0:
            layout.operator("strjson.attr_defaults", icon="PRESET")
            layout.label(text="...or add your own in Preferences.")
            return

        for i, it in enumerate(p.attributes):
            row = layout.row(align=True)
            row.label(text=it.name)
            if it.atype == "BOOL":
                row.prop(it, "bval", text="")
            else:
                row.prop(it, "value", text="")
            op = row.operator("strjson.assign", text="", icon="CHECKMARK")
            op.idx = i
        layout.separator()
        layout.operator("strjson.assign_all", icon="CHECKMARK")


def to_plain(v):
    if isinstance(v, (bool, int, float, str)):
        return v
    try:
        return [to_plain(x) for x in v]
    except TypeError:
        try:
            return float(v)
        except Exception:
            return str(v)


class IMPORT_OT_string_json(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.string_json"
    bl_label = "Import String Scene (.json)"
    bl_description = "Build meshes from a saved string-engine scene so you can edit and re-export"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    flip_y: BoolProperty(name="Flip Y", default=True,
                         description="Un-flip Y so the layout matches Blender's up-axis (matches the exporter)")
    into_collection: BoolProperty(name="New Collection", default=True,
                                  description="Put imported objects in a collection named after the file")

    def execute(self, context):
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.report({"ERROR"}, "Could not read JSON: %s" % e)
            return {"CANCELLED"}

        objects = data.get("objects", data) if isinstance(data, dict) else data
        if not isinstance(objects, list):
            self.report({"ERROR"}, "No 'objects' array found in the file.")
            return {"CANCELLED"}

        coll = context.collection
        if self.into_collection:
            base = os.path.splitext(os.path.basename(self.filepath))[0] or "scene"
            coll = bpy.data.collections.new(base)
            context.scene.collection.children.link(coll)

        if isinstance(data, dict) and data.get("globals") is not None:
            context.scene["_se_globals"] = json.dumps(data["globals"])

        count = 0
        for od in objects:
            if not isinstance(od, dict):
                continue
            name = od.get("name", "object")
            verts_in = od.get("vertices") or od.get("verts") or []
            edges_in = od.get("edges") or []

            bverts = []
            for v in verts_in:
                x = float(v[0]) if len(v) > 0 else 0.0
                y = float(v[1]) if len(v) > 1 else 0.0
                z = float(v[2]) if len(v) > 2 else 0.0
                if self.flip_y:
                    y = -y
                bverts.append((x, y, z))
            edges = [(int(e[0]), int(e[1])) for e in edges_in if len(e) >= 2]
            faces = [tuple(int(i) for i in fp) for fp in od.get("faces", [])]

            me = bpy.data.meshes.new(name)
            me.from_pydata(bverts, edges, faces)
            me.update()
            obj = bpy.data.objects.new(name, me)
            coll.objects.link(obj)

            settings = od.get("settings")
            if settings is None:
                settings = dict(od.get("attrs") or {})
            settings = settings or {}

            for k in CORE_KEYS:
                if k in settings and settings[k] is not None:
                    val = settings[k]
                    if k in BOOL_KEYS:
                        obj[k] = 1 if val else 0
                    else:
                        try:
                            obj[k] = float(val)
                        except Exception:
                            pass

            for k in APP_SCALAR_KEYS:
                if k in settings and settings[k] is not None:
                    v = settings[k]
                    if isinstance(v, bool):
                        v = 1 if v else 0
                    obj["_se_" + k] = v
            if settings.get("inter"):
                obj["_se_inter"] = json.dumps(settings["inter"])
            if settings.get("ids"):
                obj["_se_ids"] = json.dumps(settings["ids"])
            count += 1

        self.report({"INFO"}, "Imported %d object(s)" % count)
        return {"FINISHED"}


def build_settings(obj):
    s = {
        "thickness": float(obj.get("thickness", 3.0)),
        "stiffness": float(obj.get("stiffness", 0.1)),
        "curl": float(obj.get("curl", 0.0)),
        "grow": float(obj.get("grow", 0.0)),
        "solid": bool(obj.get("solid", 0)),
        "fixed": bool(obj.get("fixed", 0)),
    }
    for k in APP_SCALAR_KEYS:
        pk = "_se_" + k
        if pk in obj.keys():
            v = obj[pk]
            if k == "selfSolid":
                v = bool(v)
            s[k] = to_plain(v)
    if "_se_inter" in obj.keys():
        try:
            s["inter"] = json.loads(obj["_se_inter"])
        except Exception:
            pass
    if "_se_ids" in obj.keys():
        try:
            s["ids"] = json.loads(obj["_se_ids"])
        except Exception:
            pass
    return s


def export_object(obj, depsgraph, opts):
    src = obj.evaluated_get(depsgraph) if opts["apply_modifiers"] else obj
    try:
        mesh = src.to_mesh()
    except Exception:
        return None
    if mesh is None:
        return None
    mw = obj.matrix_world
    flip_y = opts["flip_y"]
    verts = []
    for v in mesh.vertices:
        co = mw @ v.co
        y = -co.y if flip_y else co.y
        verts.append([round(co.x, 4), round(y, 4), round(co.z, 4)])
    edges = [[e.vertices[0], e.vertices[1]] for e in mesh.edges]
    data = {"name": obj.name, "vertices": verts, "edges": edges, "settings": build_settings(obj)}
    if opts["include_faces"]:
        data["faces"] = [list(pp.vertices) for pp in mesh.polygons]
    src.to_mesh_clear()
    return data if verts else None


class EXPORT_OT_string_json(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.string_json"
    bl_label = "Export String Scene (.json)"
    bl_description = "Export selected objects to a string-engine scene the app can load"
    bl_options = {"PRESET"}
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    use_selection: BoolProperty(name="Selection Only", default=True)
    apply_modifiers: BoolProperty(name="Apply Modifiers", default=True)
    flip_y: BoolProperty(name="Flip Y", default=True,
                         description="Negate Y so a top-view layout reads upright in the app's canvas")
    include_faces: BoolProperty(name="Include Faces", default=False)
    include_globals: BoolProperty(name="Include Saved Globals", default=True,
                                  description="Carry along the app globals captured on import, if any")
    pretty: BoolProperty(name="Pretty Print", default=False)

    def execute(self, context):
        opts = {k: getattr(self, k) for k in ("apply_modifiers", "flip_y", "include_faces")}
        pool = context.selected_objects if self.use_selection else context.scene.objects
        targets = [o for o in pool if o.type in MESHABLE]
        if not targets:
            self.report({"WARNING"}, "No mesh/curve objects to export.")
            return {"CANCELLED"}
        depsgraph = context.evaluated_depsgraph_get()
        objects = []
        for obj in targets:
            d = export_object(obj, depsgraph, opts)
            if d is not None:
                objects.append(d)
        out = {"meta": {"generator": "string-engine-save", "version": 1, "flip_y": self.flip_y},
               "objects": objects}
        if self.include_globals:
            gl = context.scene.get("_se_globals")
            if gl:
                try:
                    out["globals"] = json.loads(gl)
                except Exception:
                    pass
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2 if self.pretty else None)
        self.report({"INFO"}, "Exported %d object(s)" % len(objects))
        return {"FINISHED"}


def menu_func_export(self, context):
    self.layout.operator(EXPORT_OT_string_json.bl_idname, text="String Scene (.json)")


def menu_func_import(self, context):
    self.layout.operator(IMPORT_OT_string_json.bl_idname, text="String Scene (.json)")


CLASSES = (
    STRJSON_AttrItem, STRJSON_UL_attrs, STRJSON_Prefs,
    STRJSON_OT_attr_add, STRJSON_OT_attr_remove, STRJSON_OT_attr_defaults,
    STRJSON_OT_assign, STRJSON_OT_assign_all,
    STRJSON_PT_panel, IMPORT_OT_string_json, EXPORT_OT_string_json,
)


def _seed_defaults():
    try:
        prefs = bpy.context.preferences.addons[__name__].preferences
    except Exception:
        return None
    if prefs is not None and len(prefs.attributes) == 0:
        for name, atype, val in DEFAULT_ATTRS:
            it = prefs.attributes.add()
            it.name = name; it.atype = atype; it.value = val; it.bval = bool(val)
    return None


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    try:
        bpy.app.timers.register(_seed_defaults, first_interval=0.1)
    except Exception:
        pass


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
