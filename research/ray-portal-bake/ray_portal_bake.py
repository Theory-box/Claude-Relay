bl_info = {
    "name": "Ray Portal Bake",
    "author": "Theory-box / Claude Relay",
    "version": (0, 8, 0),
    "blender": (4, 2, 0),
    "location": "Shader Editor / View3D > Sidebar > Portal Bake",
    "description": "One-shot bake of a mesh's real, lit surface (lighting + normal maps) into UV "
                   "space using the Ray Portal BSDF, rendered in a non-blocking background Cycles worker.",
    "category": "Render",
}

import bpy
import bmesh
import os
import time
import tempfile
import subprocess

RESULT_IMAGE_NAME = "RayPortalBake_Result"

# --- background worker -----------------------------------------------------
# Runs in its own `blender -b --factory-startup` process on a copy of the scene.
# It flattens the target object into UV space (per-corner, seam-safe, UV-tile
# shifted), assigns a Ray Portal material that redirects each UV point's ray back
# onto the real 3D surface, and renders that through an ortho camera -> the real
# lit surface laid out in UV space. Judged by PNG existence (Node Preview lesson:
# third-party add-ons can crash Blender at shutdown after a good render).
_BAKE_WORKER_SRC = '''import bpy, sys, os, math, mathutils
try:
    import addon_utils
    addon_utils.enable("cycles")
except Exception:
    pass

ATTR_POS = "rpbake_pos"
ATTR_NRM = "rpbake_nrm"

def build_flat(obj, depsgraph):
    eval_obj = obj.evaluated_get(depsgraph)
    me = eval_obj.to_mesh()
    try:
        uvl = me.uv_layers.active
        if uvl is None:
            return None
        uv_data = uvl.data
        mw = eval_obj.matrix_world
        nmat = mw.to_3x3().inverted_safe().transposed()
        try:
            corner_normals = me.corner_normals if len(me.corner_normals) else None
        except Exception:
            corner_normals = None
        _us = [uv_data[li].uv[0] for p in me.polygons for li in p.loop_indices]
        _vs = [uv_data[li].uv[1] for p in me.polygons for li in p.loop_indices]
        # Shift the UVs so their bounding-box CENTRE lands in the 0..1 tile. Using
        # the centre (not the min) means a UV that dips a hair below 0 - common with
        # smart-project margins - does NOT shove the whole island up a tile and clip
        # it out of frame. For normal 0..1 UVs this is a no-op (shift 0).
        su = -math.floor((min(_us) + max(_us)) * 0.5)
        sv = -math.floor((min(_vs) + max(_vs)) * 0.5)
        verts = []; faces = []; pos = []; nrm = []
        for poly in me.polygons:
            fidx = []
            for li in poly.loop_indices:
                loop = me.loops[li]
                vi = loop.vertex_index
                uv = uv_data[li].uv
                verts.append((uv.x + su, uv.y + sv, 0.0))
                w = mw @ me.vertices[vi].co
                pos.append((w.x, w.y, w.z))
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
    flat = bpy.data.meshes.new("RPBake_Flat")
    flat.from_pydata(verts, [], faces)
    flat.update()
    ap = flat.attributes.new(ATTR_POS, "FLOAT_VECTOR", "POINT")
    ap.data.foreach_set("vector", [c for v in pos for c in v])
    an = flat.attributes.new(ATTR_NRM, "FLOAT_VECTOR", "POINT")
    an.data.foreach_set("vector", [c for v in nrm for c in v])
    return flat

def portal_mat(eps):
    mat = bpy.data.materials.new("RPBake_PortalMat")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    a_pos = nt.nodes.new("ShaderNodeAttribute"); a_pos.attribute_name = ATTR_POS
    a_nrm = nt.nodes.new("ShaderNodeAttribute"); a_nrm.attribute_name = ATTR_NRM
    off = nt.nodes.new("ShaderNodeVectorMath"); off.operation = "SCALE"
    off.inputs["Scale"].default_value = eps
    nt.links.new(a_nrm.outputs["Vector"], off.inputs[0])
    pos = nt.nodes.new("ShaderNodeVectorMath"); pos.operation = "ADD"
    nt.links.new(a_pos.outputs["Vector"], pos.inputs[0])
    nt.links.new(off.outputs["Vector"], pos.inputs[1])
    neg = nt.nodes.new("ShaderNodeVectorMath"); neg.operation = "SCALE"
    neg.inputs["Scale"].default_value = -1.0
    nt.links.new(a_nrm.outputs["Vector"], neg.inputs[0])
    rp = nt.nodes.new("ShaderNodeBsdfRayPortal")
    nt.links.new(pos.outputs["Vector"], rp.inputs["Position"])
    nt.links.new(neg.outputs["Vector"], rp.inputs["Direction"])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(rp.outputs["BSDF"], out.inputs["Surface"])
    return mat

def setup_device(scene, mode):
    dev = "CPU"; backend = ""
    if mode != "CPU":
        try:
            prefs = bpy.context.preferences.addons["cycles"].preferences
            for dtype in ["OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"]:
                try:
                    prefs.compute_device_type = dtype
                except TypeError:
                    continue
                try:
                    prefs.refresh_devices()
                except Exception:
                    pass
                gpus = [d for d in prefs.devices if getattr(d, "type", "") == dtype]
                if gpus:
                    for d in prefs.devices:
                        if getattr(d, "type", "") == dtype:
                            d.use = True
                    dev = "GPU"; backend = dtype
                    break
        except Exception:
            dev = "CPU"
    scene.cycles.device = dev
    return dev + ((":" + backend) if backend else "")

argv = sys.argv[sys.argv.index("--") + 1:]
scene_name, obj_name, out_png, res, samples, eps, device, status = argv[:8]
res = int(res); samples = int(samples); eps = float(eps)

try:
    scene = bpy.data.scenes[scene_name]
    obj = bpy.data.objects[obj_name]
    with bpy.context.temp_override(scene=scene):
        depsgraph = bpy.context.evaluated_depsgraph_get()
        flat_me = build_flat(obj, depsgraph)
        if flat_me is None:
            raise RuntimeError("no active UV map on " + obj_name)
        flat_obj = bpy.data.objects.new("RPBake_Flat", flat_me)
        flat_obj.data.materials.append(portal_mat(eps))
        scene.collection.objects.link(flat_obj)
        zmax = 0.0; found = False
        for ob in scene.objects:
            if ob.type != "MESH":
                continue
            for c in ob.bound_box:
                wz = (ob.matrix_world @ mathutils.Vector(c)).z
                zmax = wz if not found else max(zmax, wz); found = True
        z = (zmax if found else 0.0) + 10.0
        flat_obj.location = (0.0, 0.0, z)
        cam_d = bpy.data.cameras.new("RPBake_Cam"); cam_d.type = "ORTHO"; cam_d.ortho_scale = 1.0
        cam_d.clip_start = 0.001; cam_d.clip_end = 1.0e9
        cam = bpy.data.objects.new("RPBake_Cam", cam_d); cam.location = (0.5, 0.5, z + 5.0)
        scene.collection.objects.link(cam)
        scene.camera = cam
        scene.render.engine = "CYCLES"
        scene.cycles.samples = samples
        scene.cycles.use_denoising = True
        dev = setup_device(scene, device)
        try:
            scene.view_settings.view_transform = "Standard"
            scene.view_settings.look = "None"
            scene.view_settings.exposure = 0.0
            scene.view_settings.gamma = 1.0
        except Exception:
            pass
        scene.render.resolution_x = res
        scene.render.resolution_y = res
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = True
        scene.render.filepath = out_png
        scene.render.use_file_extension = False
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGBA"
        bpy.ops.render.render(write_still=True)
    with open(status, "w") as f:
        f.write(dev)
except Exception:
    import traceback
    try:
        with open(status, "w") as f:
            f.write("ERR:" + traceback.format_exc()[-500:])
    except Exception:
        pass
'''


def _worker_path():
    p = os.path.join(tempfile.gettempdir(), "rpbake_worker.py")
    with open(p, "w") as f:
        f.write(_BAKE_WORKER_SRC)
    return p


_state = {"job": None, "batch": None}


def _get_device_mode():
    try:
        return bpy.context.scene.rpbake_device
    except Exception:
        return "AUTO"


def _store_result(png_path):
    tmp = bpy.data.images.load(png_path)
    try:
        w, h = tmp.size
        res = bpy.data.images.get(RESULT_IMAGE_NAME)
        if res is None:
            res = bpy.data.images.new(RESULT_IMAGE_NAME, w, h, alpha=True)
            res.use_fake_user = True
        elif tuple(res.size) != (w, h):
            res.scale(w, h)
        buf = [0.0] * (w * h * 4)
        tmp.pixels.foreach_get(buf)
        res.pixels.foreach_set(buf)
        res.update()
    finally:
        bpy.data.images.remove(tmp)
    return res


class RPBAKE_OT_bake(bpy.types.Operator):
    bl_idname = "rpbake.bake"
    bl_label = "Render"
    bl_description = ("Bake the active object's real, lit surface into its UV space, then "
                      "apply the result back onto the mesh when done (background Cycles)")
    bl_options = {"REGISTER"}

    collapse_modifiers: bpy.props.BoolProperty(
        name="Apply (collapse) all modifiers",
        description=("Permanently apply every modifier so the bake sees real geometry. "
                     "Modifier-made geometry (e.g. Solidify) has no real UVs and bakes "
                     "black. Uncheck to bake the object as-is"),
        default=True)

    reunwrap_after: bpy.props.BoolProperty(
        name="Re-unwrap after (Smart UV Project)",
        description=("Some modifiers (Solidify, Mirror, Array, Bevel...) leave overlapping "
                     "or broken UVs once applied. Re-unwrap replaces the UV map with a fresh "
                     "Smart UV Project so the bake is clean. This discards the current UVs"),
        default=False)

    backup_first: bpy.props.BoolProperty(
        name="Back up object first",
        description=("Before applying, duplicate this object (modifiers intact) into a "
                     "'backup' collection that is excluded from the view layer, so you can "
                     "recover the un-applied version later"),
        default=False)

    save_previous: bpy.props.BoolProperty(
        name="Save the previous bake first",
        description=("The last bake hasn't been saved yet. Save it to its own file (and lock "
                     "it onto its object) before this bake overwrites the shared result image"),
        default=True)

    fix_uvs: bpy.props.BoolProperty(
        name="Smart-unwrap first",
        description=("The current UVs look overlapping or out of bounds, which bakes wrong. "
                     "Replace them with a fresh Smart UV Project before baking"),
        default=False)

    uv_reason: bpy.props.StringProperty(default="", options={"HIDDEN"})

    def _unsaved_prev(self, obj):
        last = _state.get("last_baked")
        return bool(_state.get("unsaved") and last and (obj is None or last != obj.name))

    def invoke(self, context, event):
        sel = _selected_meshes(context)
        if len(sel) >= 2:
            self.collapse_modifiers = True
            self.reunwrap_after = True
            self.backup_first = False
            try:
                return context.window_manager.invoke_props_dialog(
                    self, width=340, title="Bake %d objects" % len(sel), confirm_text="Bake All")
            except TypeError:
                return context.window_manager.invoke_props_dialog(self, width=340)
        obj = context.active_object
        has_mods = obj is not None and obj.type == "MESH" and len(obj.modifiers) > 0
        unsaved = self._unsaved_prev(obj)
        uv_problem = ""
        if obj is not None and obj.type == "MESH" and not has_mods:
            uv_problem = _uv_looks_wrong(context, obj)
        self.uv_reason = uv_problem
        self.fix_uvs = bool(uv_problem)
        if has_mods or unsaved or uv_problem:
            if has_mods:
                self.reunwrap_after = _has_uv_hurting_modifier(obj)
                self.backup_first = False
            self.save_previous = unsaved
            confirm = "Apply & Continue" if has_mods else "Continue"
            try:
                return context.window_manager.invoke_props_dialog(
                    self, width=340, title="Bake", confirm_text=confirm)
            except TypeError:
                return context.window_manager.invoke_props_dialog(self, width=340)
        return self.execute(context)

    def draw(self, context):
        col = self.layout.column()
        sel = _selected_meshes(context)
        if len(sel) >= 2:
            col.label(text="Bake %d objects, one at a time." % len(sel), icon="RENDERLAYERS")
            col.label(text="Each is checked, baked, then auto-saved.")
            col.separator()
            col.prop(self, "collapse_modifiers", text="Apply modifiers where present")
            s = col.column()
            s.enabled = self.collapse_modifiers
            s.prop(self, "backup_first", text="Back up originals first")
            col.prop(self, "reunwrap_after", text="Fix UVs (overlap / after modifiers)")
            return
        obj = context.active_object
        last = _state.get("last_baked")
        if self._unsaved_prev(obj):
            col.label(text="Last bake ('%s') isn't saved." % last, icon="ERROR")
            col.label(text="Baking now overwrites it.")
            col.prop(self, "save_previous")
            col.separator()
        if self.uv_reason:
            col.label(text="These UVs look off:", icon="ERROR")
            col.label(text=self.uv_reason + ".")
            col.prop(self, "fix_uvs")
            col.separator()
        n = len(obj.modifiers) if (obj is not None and obj.type == "MESH") else 0
        if n > 0:
            col.label(text="This object has %d modifier%s." % (n, "s" if n != 1 else ""), icon="MODIFIER")
            col.label(text="Baking needs real geometry - modifier-made")
            col.label(text="geometry (e.g. Solidify) can bake black.")
            col.separator()
            col.prop(self, "collapse_modifiers")
            sub = col.column()
            sub.enabled = self.collapse_modifiers
            sub.prop(self, "reunwrap_after")
            sub.prop(self, "backup_first")
            if obj is not None and _has_uv_hurting_modifier(obj):
                col.separator()
                col.label(text="A modifier here breaks UVs -", icon="ERROR")
                col.label(text="re-unwrap is recommended.")

    def execute(self, context):
        if _state["job"] is not None or _state.get("batch") is not None:
            self.report({"WARNING"}, "A bake is already running.")
            return {"CANCELLED"}
        sel = _selected_meshes(context)
        if len(sel) >= 2:
            return self._start_batch(context, sel)
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"WARNING"}, "Select a mesh object.")
            return {"CANCELLED"}
        if self.save_previous and self._unsaved_prev(obj):
            r = bpy.ops.rpbake.save()
            if "CANCELLED" in r:
                self.report({"ERROR"}, "Couldn't save the previous bake - aborting. Set a "
                            "Save Folder in Bake Settings, or save your .blend first.")
                return {"CANCELLED"}
        if self.collapse_modifiers and len(obj.modifiers) > 0:
            if self.backup_first:
                _backup_object(context, obj)
            _apply_all_modifiers(context, obj)
            if self.reunwrap_after:
                _smart_project(context, obj)
        if obj.data.uv_layers.active is None:
            if not _ensure_uvs(context, obj):
                self.report({"WARNING"}, "Object has no UV map and auto smart-unwrap failed.")
                return {"CANCELLED"}
            self.report({"INFO"}, "No UV map found - auto smart-unwrapped.")
        elif self.fix_uvs:
            _smart_project(context, obj)
            self.report({"INFO"}, "Smart-unwrapped before baking.")

        scene = context.scene
        res = _obj_res(obj, scene)
        samples = _obj_samples(obj, scene)

        if scene.rpbake_method == "NATIVE":
            return self._render_native(context, obj, res, samples)

        if not obj.data.materials:
            self.report({"WARNING"}, "Object has no material.")
            return {"CANCELLED"}
        eps = float(scene.rpbake_epsilon)
        mode = _get_device_mode()

        tmpdir = tempfile.gettempdir()
        stamp = str(int(time.time() * 1000))
        blend = os.path.join(tmpdir, "rpbake_%s.blend" % stamp)
        png = os.path.join(tmpdir, "rpbake_%s.png" % stamp)
        status = png + ".status"

        try:
            bpy.data.libraries.write(blend, {scene}, path_remap="ABSOLUTE", fake_user=True)
        except Exception as exc:
            self.report({"ERROR"}, "Could not prepare scene: %s" % exc)
            return {"CANCELLED"}

        try:
            exe = bpy.app.binary_path
            worker = _worker_path()
            kwargs = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.name == "nt":
                kwargs["creationflags"] = 0x08000000
            proc = subprocess.Popen(
                [exe, "-b", "--factory-startup", blend, "--python", worker, "--",
                 scene.name, obj.name, png, str(res), str(samples), str(eps), mode, status],
                **kwargs)
        except Exception as exc:
            self.report({"ERROR"}, "Could not launch worker: %s" % exc)
            return {"CANCELLED"}

        _state["job"] = {"proc": proc, "blend": blend, "png": png, "status": status,
                         "obj": obj.name, "started": time.time()}
        scene.rpbake_status = "Rendering..."
        if not bpy.app.timers.is_registered(_poll):
            bpy.app.timers.register(_poll, first_interval=0.2)
        self.report({"INFO"}, "Rendering in background (Ray Portal)...")
        return {"FINISHED"}

    def _render_native(self, context, obj, res, samples):
        dev, mode = _start_native_bake(context, obj)
        if mode != "CPU" and dev == "CPU":
            self.report({"WARNING"},
                        "GPU not available - baking on CPU. Enable a GPU in "
                        "Preferences > System > Cycles Render Devices.")
        self.report({"INFO"}, "Native bake started in background.")
        return {"FINISHED"}

    def _start_batch(self, context, sel):
        scene = context.scene
        # every object auto-saves, so a destination must exist
        if not scene.rpbake_save_dir.strip() and not bpy.data.filepath:
            self.report({"ERROR"}, "Batch baking auto-saves each object - set a Save Folder "
                        "in Bake Settings, or save your .blend first.")
            return {"CANCELLED"}
        _state["batch"] = {"names": [o.name for o in sel], "i": 0,
                           "apply_mods": self.collapse_modifiers,
                           "reunwrap": self.reunwrap_after,
                           "backup": self.backup_first, "ok": 0, "fail": 0}
        _set_status("Baking 1/%d..." % len(sel))
        _batch_advance(context)
        self.report({"INFO"}, "Batch baking %d objects in the background..." % len(sel))
        return {"FINISHED"}


def _poll():
    job = _state["job"]
    if job is None or job.get("native"):
        return None
    proc = job["proc"]
    done = proc.poll() is not None
    have_png = os.path.exists(job["png"])
    have_status = os.path.exists(job["status"])
    if have_png and (done or have_status):
        status_txt = ""
        try:
            with open(job["status"], "r") as f:
                status_txt = f.read().strip()
        except Exception:
            pass
        try:
            if not status_txt.startswith("ERR:"):
                _store_result(job["png"])
                obj = bpy.data.objects.get(job.get("obj", ""))
                applied = False
                try:
                    applied = _apply_result_to_object(obj)
                except Exception:
                    applied = False
                if applied:
                    _set_status("Rendered (%s) - applied to mesh" % (status_txt.strip() or "?"))
                else:
                    _set_status("Rendered (%s) - image ready" % (status_txt.strip() or "?"))
                if job.get("obj"):
                    _state["last_baked"] = job["obj"]
                    _state["unsaved"] = True
            else:
                _set_status("Failed: " + status_txt[4:70])
        except Exception as exc:
            _set_status("Load failed: %s" % exc)
        _finish(job)
        return None
    if done and not have_png:
        status_txt = ""
        try:
            with open(job["status"], "r") as f:
                status_txt = f.read().strip()
        except Exception:
            pass
        _set_status(("Failed: " + status_txt[4:70]) if status_txt.startswith("ERR:") else "Failed (no image).")
        _finish(job)
        return None
    if time.time() - job["started"] > 600:
        try:
            proc.kill()
        except Exception:
            pass
        _set_status("Timed out.")
        _finish(job)
        return None
    return 0.25


def _set_status(msg):
    for sc in bpy.data.scenes:
        try:
            sc.rpbake_status = msg
        except Exception:
            pass


def _finish(job):
    for k in ("blend", "png", "status"):
        try:
            p = job.get(k)
            if p and os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
    _state["job"] = None
    try:
        for area in bpy.context.screen.areas:
            area.tag_redraw()
    except Exception:
        pass


def _apply_result_to_object(obj):
    """Put the baked RESULT image on obj as its active image-texture node.
    The image IS the object's 0..1 UV space, so no mapping node is needed."""
    res = bpy.data.images.get(RESULT_IMAGE_NAME)
    if res is None or obj is None or obj.type != "MESH":
        return False
    mat = obj.active_material
    if mat is None:
        mat = bpy.data.materials.new(obj.name + "_RPBake")
        mat.use_nodes = True
        if len(obj.data.materials) == 0:
            obj.data.materials.append(mat)
        else:
            # object has an empty slot that is the active one - fill it, so the
            # new material actually becomes the object's active material.
            obj.data.materials[obj.active_material_index] = mat
    elif not mat.use_nodes:
        mat.use_nodes = True
    nt = mat.node_tree
    tex = None
    for n in nt.nodes:
        if n.type == "TEX_IMAGE" and n.image == res:
            tex = n
            break
    if tex is None:
        anchor = nt.nodes.active
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = res
        if anchor is not None and anchor != tex:
            tex.location = (anchor.location.x - 400, anchor.location.y)
    nt.nodes.active = tex
    return True


def _exclude_collection(context, coll):
    """Set the given collection's layer-collection to excluded in the active view layer."""
    def find(lc):
        if lc.collection == coll:
            return lc
        for child in lc.children:
            r = find(child)
            if r is not None:
                return r
        return None
    lc = find(context.view_layer.layer_collection)
    if lc is not None:
        lc.exclude = True


def _backup_object(context, obj):
    """Duplicate obj (with its modifiers + independent mesh data) into a 'backup'
    collection, and exclude that collection from the view layer. Returns the copy."""
    backup_coll = bpy.data.collections.get("backup")
    if backup_coll is None:
        backup_coll = bpy.data.collections.new("backup")
        context.scene.collection.children.link(backup_coll)
    dup = obj.copy()                 # copies the modifier stack too
    if obj.data is not None:
        dup.data = obj.data.copy()   # independent mesh data
    dup.name = obj.name + "_backup"
    for c in list(dup.users_collection):
        c.objects.unlink(dup)
    backup_coll.objects.link(dup)
    _exclude_collection(context, backup_coll)
    return dup


def _apply_all_modifiers(context, obj):
    """Permanently apply (collapse) every modifier on obj so the bake sees real geometry."""
    if not obj.modifiers:
        return True
    try:
        if context.object is not None and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    if obj.data.users > 1:  # modifier_apply refuses on shared mesh data
        obj.data = obj.data.copy()
    for o in list(context.view_layer.objects.selected):
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    ok = True
    with context.temp_override(active_object=obj, selected_objects=[obj], object=obj):
        for mod in list(obj.modifiers):
            try:
                bpy.ops.object.modifier_apply(modifier=mod.name)
            except Exception:
                try:
                    obj.modifiers.remove(mod)  # e.g. disabled/invalid - drop it
                except Exception:
                    ok = False
    return ok


_UV_HURTING_MODIFIERS = {
    "SOLIDIFY", "MIRROR", "ARRAY", "BEVEL", "SCREW", "SKIN", "WELD", "WIREFRAME",
    "BOOLEAN", "BUILD", "MASK", "EDGE_SPLIT", "TRIANGULATE", "DECIMATE", "REMESH",
}


def _has_uv_hurting_modifier(obj):
    return any(m.type in _UV_HURTING_MODIFIERS for m in obj.modifiers)


def _smart_project(context, obj):
    """Smart-UV-project obj (overwrites the active UV map), then return to Object mode."""
    try:
        if context.object is not None and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    for o in list(context.view_layer.objects.selected):
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    try:
        with context.temp_override(active_object=obj, selected_objects=[obj], object=obj):
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.uv.smart_project(island_margin=0.02)
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
    return obj.data.uv_layers.active is not None


def _ensure_uvs(context, obj):
    """If the object has no active UV map, smart-project one. Returns True if UVs exist."""
    if obj.data.uv_layers.active is not None:
        return True
    return _smart_project(context, obj)


def _uv_overlap_fraction(context, obj):
    """Fraction (0..1) of faces flagged overlapping by uv.select_overlap; -1 if it can't run.
    A clean unwrap reads ~0-0.01; Solidify/Mirror-style overlap reads near 1.0."""
    me = obj.data
    if me.uv_layers.active is None or len(me.polygons) == 0:
        return 0.0
    frac = -1.0
    try:
        if context.object is not None and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for o in list(context.view_layer.objects.selected):
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        with context.temp_override(active_object=obj, selected_objects=[obj], object=obj):
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            try:
                bpy.ops.uv.select_all(action="SELECT")
            except Exception:
                pass
            bpy.ops.uv.select_overlap()
            bm = bmesh.from_edit_mesh(me)
            uv = bm.loops.layers.uv.active
            total = len(bm.faces)
            if uv is not None and total:
                cnt = sum(1 for f in bm.faces if any(l[uv].select for l in f.loops))
                frac = cnt / total
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
    return frac


def _uv_looks_wrong(context, obj):
    """Short reason string if the active UV map looks broken (overlap / out of bounds), else ''."""
    me = obj.data
    uvl = me.uv_layers.active
    if uvl is None or len(me.polygons) == 0:
        return ""
    data = uvl.data
    n = len(data)
    if n:
        oob = sum(1 for d in data
                  if not (-0.002 <= d.uv[0] <= 1.002 and -0.002 <= d.uv[1] <= 1.002))
        if oob / n > 0.25:
            return "most UVs sit outside the 0-1 image area"
    frac = _uv_overlap_fraction(context, obj)
    if frac > 0.05:
        return "%d%% of faces have overlapping UVs" % round(100 * frac)
    return ""


def _gpu_available():
    """(has_gpu, backend): True if a usable non-CPU compute device is enabled in Cycles
    prefs. Refreshes the device list first - reading prefs.devices cold often reads empty."""
    try:
        cprefs = bpy.context.preferences.addons["cycles"].preferences
    except Exception:
        return False, "NONE"
    backend = getattr(cprefs, "compute_device_type", "NONE") or "NONE"
    if backend in ("NONE", ""):
        return False, "NONE"
    for fn in ("refresh_devices", "get_devices"):
        f = getattr(cprefs, fn, None)
        if f is not None:
            try:
                f()
                break
            except Exception:
                continue
    try:
        for d in cprefs.devices:
            if getattr(d, "type", "CPU") != "CPU" and getattr(d, "use", False):
                return True, backend
    except Exception:
        pass
    return False, backend


def _apply_device_to_scene(scene):
    """Set scene.cycles.device honouring the addon device mode. Returns 'GPU' or 'CPU'."""
    mode = _get_device_mode()
    if mode == "CPU":
        scene.cycles.device = "CPU"
        return "CPU"
    has_gpu, _backend = _gpu_available()
    if has_gpu:
        scene.cycles.device = "GPU"
        return "GPU"
    scene.cycles.device = "CPU"
    return "CPU"


def _rpbake_use_custom_update(self, context):
    # when enabling custom settings, seed them from the current global inputs
    if getattr(self, "rpbake_use_custom", False):
        try:
            self.rpbake_res = context.scene.rpbake_resolution
            self.rpbake_samples = context.scene.rpbake_samples
        except Exception:
            pass


def _obj_res(obj, scene):
    if obj is not None and getattr(obj, "rpbake_use_custom", False):
        return int(obj.rpbake_res)
    return int(scene.rpbake_resolution)


def _obj_samples(obj, scene):
    if obj is not None and getattr(obj, "rpbake_use_custom", False):
        return int(obj.rpbake_samples)
    return int(scene.rpbake_samples)


def _selected_meshes(context):
    return [o for o in context.selected_objects if o.type == "MESH"]


def _start_native_bake(context, obj):
    """Set up the RESULT image + bake target on obj and launch a deferred native bake.
    Returns (device_label, requested_mode). Shared by single + batch baking."""
    scene = context.scene
    if context.object is not None and context.object.mode != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
    mat = obj.active_material
    if mat is None:
        mat = bpy.data.materials.new(obj.name + "_RPBake")
        mat.use_nodes = True
        if len(obj.data.materials) == 0:
            obj.data.materials.append(mat)
        else:
            obj.data.materials[obj.active_material_index] = mat
    elif not mat.use_nodes:
        mat.use_nodes = True
    nt = mat.node_tree
    res = _obj_res(obj, scene)
    samples = _obj_samples(obj, scene)
    res_img = _get_result_image(res, scene.rpbake_float, scene.rpbake_colorspace)
    tex = None
    for n in nt.nodes:
        if n.type == "TEX_IMAGE" and n.image == res_img:
            tex = n
            break
    if tex is None:
        anchor = nt.nodes.active
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = res_img
        if anchor is not None and anchor != tex:
            tex.location = (anchor.location.x - 400, anchor.location.y)
    nt.nodes.active = tex
    orig = {"scene": scene.name, "engine": scene.render.engine,
            "samples": scene.cycles.samples, "device": scene.cycles.device,
            "margin": scene.render.bake.margin, "use_clear": scene.render.bake.use_clear}
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    mode = _get_device_mode()
    dev = _apply_device_to_scene(scene)
    try:
        scene.render.bake.margin = max(0, scene.rpbake_margin)
        scene.render.bake.use_clear = True
    except Exception:
        pass
    for o in list(context.view_layer.objects.selected):
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    bake_type = scene.rpbake_bake_type
    bake_kwargs = {}
    if bake_type in ("DIFFUSE", "GLOSSY", "TRANSMISSION"):
        bake_kwargs["pass_filter"] = {"DIRECT", "INDIRECT", "COLOR"}
    # Defer the modal bake to a one-shot timer (never launch it from inside a pop-up's
    # execute - that deadlocks Blender).
    _state["job"] = {"native": True, "pending": True, "obj": obj.name, "orig": orig,
                     "bake_type": bake_type, "bake_kwargs": bake_kwargs,
                     "device": dev, "started": time.time()}
    scene.rpbake_status = "Baking (native, %s)..." % dev
    if not bpy.app.timers.is_registered(_launch_native):
        bpy.app.timers.register(_launch_native, first_interval=0.02)
    return dev, mode


def _prep_object(context, obj, apply_mods, fix_uvs, backup):
    """Per-object batch prep - the same checks the single-object flow runs:
    apply modifiers where present, ensure UVs, and repair (smart-unwrap) UVs that are
    missing, overlapping, or out of bounds - or that were just made by applying modifiers."""
    applied = False
    if apply_mods and len(obj.modifiers) > 0:
        if backup:
            _backup_object(context, obj)
        _apply_all_modifiers(context, obj)
        applied = True
    _ensure_uvs(context, obj)  # smart-projects if the object had no UVs at all
    if fix_uvs and obj.data.uv_layers.active is not None:
        # re-unwrap if we just applied modifiers (Solidify etc. overlaps), or the
        # existing UVs look overlapping / out of bounds
        if applied or _uv_looks_wrong(context, obj):
            _smart_project(context, obj)


def _batch_advance(context):
    """Drive the batch queue: prep + start the next object's bake, or finish."""
    batch = _state.get("batch")
    if batch is None:
        return
    names = batch["names"]
    while batch["i"] < len(names):
        obj = bpy.data.objects.get(names[batch["i"]])
        if obj is None or obj.type != "MESH":
            batch["i"] += 1
            continue
        try:
            _prep_object(context, obj, batch["apply_mods"], batch["reunwrap"], batch["backup"])
        except Exception:
            pass
        if obj.data.uv_layers.active is None:
            batch["i"] += 1
            batch["fail"] += 1
            continue
        _set_status("Baking %d/%d: %s" % (batch["i"] + 1, len(names), obj.name))
        _start_native_bake(context, obj)
        return  # bake started; completion handler saves it + calls back here
    _set_status("Batch done: %d baked, %d skipped" % (batch["ok"], batch["fail"]))
    _state["batch"] = None


def _launch_native():
    """One-shot: actually start the native bake, decoupled from the pop-up/execute
    context that would otherwise deadlock a modal operator."""
    job = _state["job"]
    if job is None or not job.get("native") or not job.get("pending"):
        return None
    obj = bpy.data.objects.get(job.get("obj", "") or "")
    try:
        if obj is not None:
            for o in list(bpy.context.view_layer.objects.selected):
                o.select_set(False)
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
        bpy.ops.object.bake("INVOKE_DEFAULT", type=job["bake_type"], **job.get("bake_kwargs", {}))
    except Exception as exc:
        _restore_scene(job.get("orig"))
        _set_status("Native bake failed: %s" % (str(exc)[:50]))
        _state["job"] = None
        return None
    job["pending"] = False
    job["started"] = time.time()
    if not bpy.app.timers.is_registered(_poll_native):
        bpy.app.timers.register(_poll_native, first_interval=0.5)
    return None


def _poll_native():
    """Watch Blender's own (non-blocking) bake job; when it ends, apply + restore."""
    job = _state["job"]
    if job is None or not job.get("native") or job.get("pending"):
        return None
    try:
        running = bpy.app.is_job_running("OBJECT_BAKE")
    except Exception:
        running = False
    # is_job_running can read False in the instant before the job thread spins up,
    # so give it a short grace period before trusting a "finished" reading.
    if not running and time.time() - job["started"] > 2.0:
        obj = bpy.data.objects.get(job.get("obj", ""))
        try:
            _apply_result_to_object(obj)
        except Exception:
            pass
        if job.get("obj"):
            _state["last_baked"] = job["obj"]
            _state["unsaved"] = True
        _restore_scene(job.get("orig"))
        _state["job"] = None
        batch = _state.get("batch")
        if batch is not None:
            try:
                r = bpy.ops.rpbake.save()
                if "CANCELLED" in r:
                    batch["fail"] += 1
                else:
                    batch["ok"] += 1
            except Exception:
                batch["fail"] += 1
            batch["i"] += 1
            _batch_advance(bpy.context)
        else:
            _set_status("Baked (native, %s)" % (job.get("device") or "?"))
        try:
            for area in bpy.context.screen.areas:
                area.tag_redraw()
        except Exception:
            pass
        return None
    if time.time() - job["started"] > 3600:
        _restore_scene(job.get("orig"))
        _set_status("Native bake timed out.")
        _state["job"] = None
        return None
    return 0.5


def _restore_scene(orig):
    if not orig:
        return
    sc = bpy.data.scenes.get(orig.get("scene", ""))
    if sc is None:
        return
    try:
        sc.render.engine = orig["engine"]
        sc.cycles.samples = orig["samples"]
        sc.cycles.device = orig["device"]
        sc.render.bake.margin = orig["margin"]
        sc.render.bake.use_clear = orig["use_clear"]
    except Exception:
        pass


def _get_result_image(res, float_buf, colorspace):
    """Return the shared RESULT image at the requested size/bit-depth/colorspace.
    If size or bit depth changed, make a fresh datablock at the exact resolution and
    re-point existing users - bpy.data.images.new sets the size reliably, whereas
    Image.scale() does not resize a bake target dependably."""
    img = bpy.data.images.get(RESULT_IMAGE_NAME)
    if img is not None and (img.is_float != float_buf or tuple(img.size) != (res, res)):
        new = bpy.data.images.new(RESULT_IMAGE_NAME + "__new", res, res, alpha=True, float_buffer=float_buf)
        for m in bpy.data.materials:
            if m.use_nodes and m.node_tree:
                for n in m.node_tree.nodes:
                    if getattr(n, "image", None) == img:
                        n.image = new
        bpy.data.images.remove(img)
        new.name = RESULT_IMAGE_NAME
        img = new
    if img is None:
        img = bpy.data.images.new(RESULT_IMAGE_NAME, res, res, alpha=True, float_buffer=float_buf)
    img.use_fake_user = True
    try:
        img.colorspace_settings.name = colorspace
    except Exception:
        pass
    return img


class RPBAKE_OT_show_on_mesh(bpy.types.Operator):
    bl_idname = "rpbake.show_on_mesh"
    bl_label = "Show on Mesh"
    bl_description = ("Add the baked image as an image-texture node on the active object's material "
                     "and make it active, so Solid/Workbench viewport shows it on the mesh")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if bpy.data.images.get(RESULT_IMAGE_NAME) is None:
            self.report({"WARNING"}, "No baked image yet.")
            return {"CANCELLED"}
        if not _apply_result_to_object(context.active_object):
            self.report({"WARNING"}, "Need an active mesh object.")
            return {"CANCELLED"}
        self.report({"INFO"}, "Baked image applied to mesh.")
        return {"FINISHED"}


class RPBAKE_OT_save(bpy.types.Operator):
    bl_idname = "rpbake.save"
    bl_label = "Save"
    bl_description = ("Save the baked image straight to disk using the Save settings below "
                      "(no dialog). Defaults to a 'bakes' folder next to your .blend file")
    bl_options = {"REGISTER"}

    _ext = {"PNG": "png", "JPEG": "jpg", "OPEN_EXR": "exr", "TIFF": "tif"}
    _allowed = {"PNG": ("8", "16"), "JPEG": ("8",), "OPEN_EXR": ("16", "32"),
                "TIFF": ("8", "16", "32")}

    def execute(self, context):
        res = bpy.data.images.get(RESULT_IMAGE_NAME)
        if res is None:
            self.report({"WARNING"}, "Nothing baked yet - hit Render first.")
            return {"CANCELLED"}
        sc = context.scene
        d = sc.rpbake_save_dir.strip()
        if d:
            directory = bpy.path.abspath(d)
        else:
            if not bpy.data.filepath:
                self.report({"WARNING"}, "Save your .blend first, or set a Save Folder in Bake Settings.")
                return {"CANCELLED"}
            directory = os.path.join(os.path.dirname(bpy.data.filepath), "bakes")
        try:
            os.makedirs(directory, exist_ok=True)
        except Exception as exc:
            self.report({"ERROR"}, "Could not create folder: %s" % exc)
            return {"CANCELLED"}
        name = _state.get("last_baked")
        if not name:
            name = context.active_object.name if context.active_object else "bake"
        fmt = sc.rpbake_save_format
        ext = self._ext.get(fmt, "png")
        filepath = os.path.join(directory, "%s.%s" % (bpy.path.clean_name(name), ext))
        depth = sc.rpbake_save_depth
        allowed = self._allowed.get(fmt, ("8",))
        if depth not in allowed:
            depth = allowed[-1]
        o_vt = sc.view_settings.view_transform
        o_fmt = sc.render.image_settings.file_format
        o_depth = sc.render.image_settings.color_depth
        o_q = sc.render.image_settings.quality
        try:
            if sc.rpbake_save_view != "FOLLOW":
                try:
                    sc.view_settings.view_transform = sc.rpbake_save_view
                except Exception:
                    pass  # transform not present in this OCIO config; fall back to scene
            sc.render.image_settings.file_format = fmt
            try:
                sc.render.image_settings.color_depth = depth
            except Exception:
                pass
            if fmt == "JPEG":
                sc.render.image_settings.quality = 95
            res.save_render(filepath, scene=sc)
        except Exception as exc:
            self.report({"ERROR"}, "Save failed: %s" % exc)
            return {"CANCELLED"}
        finally:
            sc.view_settings.view_transform = o_vt
            sc.render.image_settings.file_format = o_fmt
            try:
                sc.render.image_settings.color_depth = o_depth
            except Exception:
                pass
            sc.render.image_settings.quality = o_q
        # Re-point the just-baked object's texture from the shared RESULT image to the
        # freshly-saved file, so the NEXT bake (which overwrites RESULT) can't replace
        # this object's texture. The RESULT datablock stays as the reusable bake target.
        try:
            saved = bpy.data.images.load(filepath, check_existing=True)
            try:
                saved.reload()
            except Exception:
                pass
            target = bpy.data.objects.get(_state.get("last_baked", "") or "")
            if target is None:
                target = context.active_object
            if (target is not None and target.type == "MESH"
                    and target.active_material and target.active_material.use_nodes):
                nt = target.active_material.node_tree
                for n in nt.nodes:
                    if n.type == "TEX_IMAGE" and n.image == res:
                        n.image = saved
                        nt.nodes.active = n
        except Exception:
            pass
        _state["unsaved"] = False
        self.report({"INFO"}, "Saved: %s" % filepath)
        return {"FINISHED"}


class RPBAKE_OT_diagnostics(bpy.types.Operator):
    bl_idname = "rpbake.diagnostics"
    bl_label = "Copy Diagnostics"
    bl_description = ("Gather everything about the active object relevant to baking (UVs, transform, "
                     "normals, materials, scene lighting) and copy it to the clipboard to paste back")
    bl_options = {"REGISTER"}

    def execute(self, context):
        import math
        obj = context.active_object
        L = []
        def p(s=""):
            L.append(str(s))

        p("=== RAY PORTAL BAKE DIAGNOSTICS ===")
        try:
            p("Blender: %s" % bpy.app.version_string)
        except Exception:
            pass
        if obj is None or obj.type != "MESH":
            p("No active MESH object selected.")
            context.window_manager.clipboard = "\n".join(L)
            self.report({"WARNING"}, "Select a mesh object.")
            return {"CANCELLED"}

        me = obj.data
        mw = obj.matrix_world
        det = mw.determinant()
        p("")
        p("[OBJECT] %s" % obj.name)
        p("  location = %s" % [round(v, 4) for v in obj.location])
        p("  scale    = %s" % [round(v, 4) for v in obj.scale])
        p("  rotation = %s (deg)" % [round(math.degrees(v), 2) for v in obj.rotation_euler])
        p("  dimensions = %s" % [round(v, 4) for v in obj.dimensions])
        p("  matrix_world determinant = %.5f  %s" % (det, "(NEGATIVE -> mirrored/flipped)" if det < 0 else ""))
        p("  verts=%d polys=%d loops=%d" % (len(me.vertices), len(me.polygons), len(me.loops)))
        p("  modifiers = %s" % [(m.name, m.type) for m in obj.modifiers])

        # UV maps
        p("")
        p("[UV MAPS] count=%d" % len(me.uv_layers))
        p("  active = %s | active_render = %s" % (
            me.uv_layers.active.name if me.uv_layers.active else None,
            next((l.name for l in me.uv_layers if l.active_render), None)))
        for layer in me.uv_layers:
            data = layer.data
            if not len(data):
                p("  '%s': empty" % layer.name)
                continue
            us = [d.uv[0] for d in data]; vs = [d.uv[1] for d in data]
            umin, umax, vmin, vmax = min(us), max(us), min(vs), max(vs)
            area = 0.0
            for poly in me.polygons:
                pts = [data[li].uv for li in poly.loop_indices]
                for i in range(1, len(pts) - 1):
                    area += abs((pts[i] - pts[0]).cross(pts[i + 1] - pts[0])) / 2.0
            inside = sum(1 for i in range(len(us)) if -1e-4 <= us[i] <= 1.0001 and -1e-4 <= vs[i] <= 1.0001)
            p("  '%s': u[%.4f..%.4f] v[%.4f..%.4f]  bbox=%.3fx%.3f  uv_area=%.4f  in_0..1=%d%%" % (
                layer.name, umin, umax, vmin, vmax, umax - umin, vmax - vmin, area,
                round(100 * inside / len(us))))

        # normals (world space)
        p("")
        nmat = mw.to_3x3().inverted_safe().transposed()
        up = down = 0
        for poly in me.polygons:
            wn = (nmat @ poly.normal).normalized()
            if wn.z > 0.3:
                up += 1
            elif wn.z < -0.3:
                down += 1
        p("[NORMALS] faces pointing up(+Z)=%d down(-Z)=%d other=%d  (world space)" % (
            up, down, len(me.polygons) - up - down))
        if det < 0:
            p("  NOTE: negative object scale flips normals in render.")

        # materials
        p("")
        p("[MATERIALS] %s" % [m.name if m else None for m in me.materials])
        for m in me.materials:
            if not m or not m.use_nodes:
                continue
            out = next((n for n in m.node_tree.nodes if n.type == "OUTPUT_MATERIAL"), None)
            surf = None
            if out and out.inputs["Surface"].links:
                surf = out.inputs["Surface"].links[0].from_node.type
            teximgs = [n.image.name for n in m.node_tree.nodes if n.type == "TEX_IMAGE" and n.image]
            p("  '%s': surface=%s node_types=%s images=%s" % (
                m.name, surf, sorted(set(n.type for n in m.node_tree.nodes)), teximgs))

        # scene lighting (why it might be dark)
        p("")
        sc = context.scene
        lights = [o for o in sc.objects if o.type == "LIGHT"]
        p("[SCENE] engine=%s" % sc.render.engine)
        p("  lights=%d %s" % (len(lights), [(l.name, l.data.type, round(l.data.energy, 1)) for l in lights][:8]))
        wstr = None
        try:
            if sc.world and sc.world.use_nodes:
                bg = next((n for n in sc.world.node_tree.nodes if n.type == "BACKGROUND"), None)
                if bg:
                    wstr = round(bg.inputs["Strength"].default_value, 3)
        except Exception:
            pass
        p("  world background strength=%s" % wstr)
        p("  view_transform=%s" % sc.view_settings.view_transform)

        # addon settings
        p("")
        p("[BAKE SETTINGS] resolution=%d samples=%d surface_offset=%.4f device=%s" % (
            sc.rpbake_resolution, sc.rpbake_samples, sc.rpbake_epsilon, _get_device_mode()))
        p("  last status: %s" % (sc.rpbake_status or "(none)"))

        text = "\n".join(L)
        context.window_manager.clipboard = text
        # also drop into a text datablock in case clipboard is awkward
        tname = "RPBake_Diagnostics"
        txt = bpy.data.texts.get(tname) or bpy.data.texts.new(tname)
        txt.clear(); txt.write(text)
        print(text)
        self.report({"INFO"}, "Diagnostics copied to clipboard (and text '%s')." % tname)
        return {"FINISHED"}


class RPBAKE_PT_panel(bpy.types.Panel):
    bl_label = "Ray Portal Bake"
    bl_idname = "RPBAKE_PT_panel"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Portal Bake"

    @classmethod
    def poll(cls, context):
        sd = context.space_data
        return sd is not None and getattr(sd, "tree_type", "") == "ShaderNodeTree"

    def draw(self, context):
        layout = self.layout
        sc = context.scene
        col = layout.column(align=True)
        aobj = context.active_object
        if aobj is not None and aobj.type == "MESH":
            col.prop(aobj, "rpbake_use_custom")
            if aobj.rpbake_use_custom:
                col.prop(aobj, "rpbake_res", text="Resolution")
                col.prop(aobj, "rpbake_samples", text="Samples")
            else:
                col.prop(sc, "rpbake_resolution")
                col.prop(sc, "rpbake_samples")
        else:
            col.prop(sc, "rpbake_resolution")
            col.prop(sc, "rpbake_samples")
        col.prop(sc, "rpbake_device")
        busy = _state["job"] is not None or _state.get("batch") is not None
        sel = [o for o in context.selected_objects if o.type == "MESH"]
        r = layout.row()
        r.enabled = not busy
        r.scale_y = 1.4
        if len(sel) >= 2:
            r.operator("rpbake.bake", text="Render %d Objects" % len(sel), icon="RENDER_STILL")
        else:
            r.operator("rpbake.bake", text="Render", icon="RENDER_STILL")
        rs = layout.row()
        rs.enabled = (bpy.data.images.get(RESULT_IMAGE_NAME) is not None) and not busy
        rs.operator("rpbake.save", text="Save", icon="FILE_TICK")
        if sc.rpbake_status:
            layout.label(text=sc.rpbake_status, icon=("SORTTIME" if busy else "CHECKMARK"))


class RPBAKE_PT_bakesettings(bpy.types.Panel):
    bl_label = "Bake Settings"
    bl_idname = "RPBAKE_PT_bakesettings"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Portal Bake"
    bl_parent_id = "RPBAKE_PT_panel"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        sd = context.space_data
        return sd is not None and getattr(sd, "tree_type", "") == "ShaderNodeTree"

    def draw(self, context):
        layout = self.layout
        sc = context.scene
        col = layout.column(align=True)
        col.prop(sc, "rpbake_bake_type")
        col.prop(sc, "rpbake_colorspace")
        col.prop(sc, "rpbake_float")
        col.prop(sc, "rpbake_margin")
        layout.separator()
        layout.label(text="Save", icon="FILE_TICK")
        s = layout.column(align=True)
        s.prop(sc, "rpbake_save_dir")
        s.prop(sc, "rpbake_save_format")
        s.prop(sc, "rpbake_save_depth")
        s.prop(sc, "rpbake_save_view")


_classes = (RPBAKE_OT_bake, RPBAKE_OT_show_on_mesh, RPBAKE_OT_save,
            RPBAKE_OT_diagnostics, RPBAKE_PT_panel, RPBAKE_PT_bakesettings)


def register():
    bpy.types.Scene.rpbake_method = bpy.props.EnumProperty(
        name="Method", default="NATIVE",
        items=[
            ("PORTAL", "Ray Portal",
             "Bake the lit surface via the Ray Portal BSDF in a background process "
             "(non-blocking; needs no bake-target setup on the object)"),
            ("NATIVE", "Blender Bake",
             "Use Blender's native bake (faster; runs in the background with "
             "Blender's own progress bar)"),
        ])
    bpy.types.Scene.rpbake_resolution = bpy.props.IntProperty(name="Resolution", default=1024, min=64, max=16384)
    bpy.types.Scene.rpbake_samples = bpy.props.IntProperty(name="Samples", default=128, min=1, max=4096)
    bpy.types.Scene.rpbake_device = bpy.props.EnumProperty(
        name="Device", default="AUTO",
        items=[
            ("AUTO", "Auto (GPU if available)",
             "Use the GPU if one is enabled in Preferences > System, otherwise CPU"),
            ("GPU", "GPU",
             "Force GPU. Falls back to CPU with a warning if no GPU is enabled"),
            ("CPU", "CPU", "Force CPU"),
        ])
    bpy.types.Scene.rpbake_epsilon = bpy.props.FloatProperty(name="Surface Offset", default=0.02, min=0.0001, max=1.0, precision=4)
    bpy.types.Scene.rpbake_status = bpy.props.StringProperty(name="Status", default="")
    bpy.types.Scene.rpbake_bake_type = bpy.props.EnumProperty(
        name="Bake Type", default="COMBINED",
        items=[
            ("COMBINED", "Combined", "Full lit result: direct + indirect light and all shading"),
            ("DIFFUSE", "Diffuse", "Diffuse lighting and colour"),
            ("GLOSSY", "Glossy", "Glossy / specular response"),
            ("AO", "Ambient Occlusion", "Ambient occlusion only"),
            ("SHADOW", "Shadow", "Shadowing only"),
            ("EMIT", "Emission", "Emission only"),
            ("ROUGHNESS", "Roughness", "Surface roughness"),
            ("NORMAL", "Normal", "Tangent-space normal map"),
        ])
    bpy.types.Scene.rpbake_float = bpy.props.BoolProperty(
        name="32-bit Float", default=False,
        description=("Store the result as a 32-bit float image so HDR values above 1 "
                     "(bright sun, highlights) survive. Off = 8-bit. 16-bit is chosen "
                     "when you save (PNG 16-bit / EXR half)"))
    bpy.types.Scene.rpbake_colorspace = bpy.props.EnumProperty(
        name="Color Space", default="sRGB",
        items=[
            ("sRGB", "sRGB", "Standard colour-texture encoding - use for a normal lit/diffuse bake"),
            ("Non-Color", "Non-Color (raw/linear)", "Store raw linear values - use for data passes or accurate re-lighting"),
        ])
    bpy.types.Scene.rpbake_margin = bpy.props.IntProperty(
        name="Margin (px)", default=16, min=0, max=64,
        description="Bleed the baked result this many pixels past each UV island edge to hide seams")
    bpy.types.Scene.rpbake_save_dir = bpy.props.StringProperty(
        name="Save Folder", subtype="DIR_PATH", default="",
        description="Where Save writes the image. Leave empty to use a 'bakes' folder next to your .blend file")
    bpy.types.Scene.rpbake_save_format = bpy.props.EnumProperty(
        name="Format", default="PNG",
        items=[
            ("PNG", "PNG", "Lossless, 8 or 16-bit"),
            ("JPEG", "JPEG", "Lossy, 8-bit, small files"),
            ("OPEN_EXR", "OpenEXR", "Float HDR, 16 or 32-bit"),
            ("TIFF", "TIFF", "Lossless, 8 / 16 / 32-bit"),
        ])
    bpy.types.Scene.rpbake_save_depth = bpy.props.EnumProperty(
        name="Bit Depth", default="16",
        items=[("8", "8-bit", ""), ("16", "16-bit", ""), ("32", "32-bit float", "")])
    bpy.types.Scene.rpbake_save_view = bpy.props.EnumProperty(
        name="Color Grading", default="FOLLOW",
        items=[
            ("FOLLOW", "Follow Scene", "Use whatever view transform the scene is set to - matches your render look"),
            ("Standard", "Standard (sRGB)", "Plain sRGB, no filmic tone mapping"),
            ("AgX", "AgX", "Bake the AgX look into the file"),
            ("Filmic", "Filmic", "Bake the Filmic look into the file"),
            ("Raw", "Raw (linear)", "No colour management - raw linear values (best with EXR / 32-bit)"),
        ])
    bpy.types.Object.rpbake_use_custom = bpy.props.BoolProperty(
        name="Custom res / samples for this object", default=False,
        description=("Give this object its own bake resolution and samples. Objects without "
                     "this use the global inputs above. Batch baking respects each object's own "
                     "settings"),
        update=_rpbake_use_custom_update)
    bpy.types.Object.rpbake_res = bpy.props.IntProperty(name="Resolution", default=1024, min=64, max=16384)
    bpy.types.Object.rpbake_samples = bpy.props.IntProperty(name="Samples", default=128, min=1, max=4096)
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    job = _state["job"]
    if job is not None:
        if not job.get("native"):
            try:
                job["proc"].kill()
            except Exception:
                pass
            _finish(job)
        else:
            _restore_scene(job.get("orig"))
            _state["job"] = None
    _state["batch"] = None
    for t in (_poll, _poll_native, _launch_native):
        if bpy.app.timers.is_registered(t):
            bpy.app.timers.unregister(t)
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    for p in ("rpbake_use_custom", "rpbake_res", "rpbake_samples"):
        if hasattr(bpy.types.Object, p):
            delattr(bpy.types.Object, p)
    for p in ("rpbake_method", "rpbake_resolution", "rpbake_samples", "rpbake_device",
              "rpbake_epsilon", "rpbake_status", "rpbake_bake_type", "rpbake_float",
              "rpbake_colorspace", "rpbake_margin", "rpbake_save_dir", "rpbake_save_format",
              "rpbake_save_depth", "rpbake_save_view"):
        if hasattr(bpy.types.Scene, p):
            delattr(bpy.types.Scene, p)


if __name__ == "__main__":
    register()
