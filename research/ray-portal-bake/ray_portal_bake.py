bl_info = {
    "name": "Ray Portal Bake",
    "author": "Theory-box / Claude Relay",
    "version": (0, 2, 0),
    "blender": (4, 2, 0),
    "location": "Shader Editor / View3D > Sidebar > Portal Bake",
    "description": "One-shot bake of a mesh's real, lit surface (lighting + normal maps) into UV "
                   "space using the Ray Portal BSDF, rendered in a non-blocking background Cycles worker.",
    "category": "Render",
}

import bpy
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
        umin = min(uv_data[li].uv[0] for p in me.polygons for li in p.loop_indices)
        vmin = min(uv_data[li].uv[1] for p in me.polygons for li in p.loop_indices)
        su = -math.floor(umin); sv = -math.floor(vmin)
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
        # Frame the camera to the object's actual UV bounds (not a fixed 0..1),
        # so objects that only use part of UV space (atlas / thin strips) still
        # fill the image. For a full-0..1 unwrap this is unchanged.
        xs = [v.co.x for v in flat_me.vertices]
        ys = [v.co.y for v in flat_me.vertices]
        umin = min(xs); umax = max(xs); vmin = min(ys); vmax = max(ys)
        cx = (umin + umax) / 2.0; cy = (vmin + vmax) / 2.0
        span = max(umax - umin, vmax - vmin, 1e-4) * 1.05
        fminx = cx - span / 2.0; fminy = cy - span / 2.0
        cam_d = bpy.data.cameras.new("RPBake_Cam"); cam_d.type = "ORTHO"; cam_d.ortho_scale = span
        cam = bpy.data.objects.new("RPBake_Cam", cam_d); cam.location = (cx, cy, z + 5.0)
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
        f.write("%s|%g %g %g" % (dev, fminx, fminy, span))
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


_state = {"job": None, "frame": None}


def _get_device_mode():
    try:
        return bpy.context.preferences.addons[__name__].preferences.device
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
    bl_label = "Bake to UV (Portal)"
    bl_description = "Bake the active object's real, lit surface into UV space (background Cycles)"
    bl_options = {"REGISTER"}

    def execute(self, context):
        if _state["job"] is not None:
            self.report({"WARNING"}, "A bake is already running.")
            return {"CANCELLED"}
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"WARNING"}, "Select a mesh object.")
            return {"CANCELLED"}
        if obj.data.uv_layers.active is None:
            self.report({"WARNING"}, "Object has no UV map.")
            return {"CANCELLED"}
        if not obj.data.materials:
            self.report({"WARNING"}, "Object has no material.")
            return {"CANCELLED"}

        scene = context.scene
        res = int(scene.rpbake_resolution)
        samples = int(scene.rpbake_samples)
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
                         "started": time.time()}
        scene.rpbake_status = "Baking..."
        if not bpy.app.timers.is_registered(_poll):
            bpy.app.timers.register(_poll, first_interval=0.2)
        self.report({"INFO"}, "Baking in background...")
        return {"FINISHED"}


def _poll():
    job = _state["job"]
    if job is None:
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
                dev = status_txt
                _state["frame"] = None
                if "|" in status_txt:
                    dev, bnds = status_txt.split("|", 1)
                    try:
                        fx, fy, sp = (float(x) for x in bnds.split())
                        _state["frame"] = (fx, fy, sp)
                    except Exception:
                        _state["frame"] = None
                _store_result(job["png"])
                _set_status("Baked (%s)" % (dev or "?"))
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


class RPBAKE_OT_show_on_mesh(bpy.types.Operator):
    bl_idname = "rpbake.show_on_mesh"
    bl_label = "Show on Mesh"
    bl_description = ("Add the baked image as an image-texture node on the active object's material "
                     "and make it active, so Solid/Workbench viewport shows it on the mesh")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        res = bpy.data.images.get(RESULT_IMAGE_NAME)
        if res is None:
            self.report({"WARNING"}, "No baked image yet.")
            return {"CANCELLED"}
        obj = context.active_object
        mat = obj.active_material if obj is not None else None
        if mat is None or mat.node_tree is None:
            self.report({"WARNING"}, "Active object has no material.")
            return {"CANCELLED"}
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
            # If the bake was framed to a sub-region of UV space (atlas / thin
            # strip), remap the object's UVs into that region so it lines up.
            # (Shows correctly in Material Preview / Rendered; Solid uses raw UVs.)
            frame = _state.get("frame")
            if frame is not None and (abs(frame[0]) > 1e-4 or abs(frame[1]) > 1e-4
                                      or abs(frame[2] - 1.0) > 1e-3):
                fx, fy, sp = frame
                uvn = nt.nodes.new("ShaderNodeUVMap")
                mapn = nt.nodes.new("ShaderNodeMapping")
                mapn.inputs["Location"].default_value = (-fx / sp, -fy / sp, 0.0)
                mapn.inputs["Scale"].default_value = (1.0 / sp, 1.0 / sp, 1.0)
                uvn.location = (tex.location.x - 400, tex.location.y)
                mapn.location = (tex.location.x - 200, tex.location.y)
                nt.links.new(uvn.outputs["UV"], mapn.inputs["Vector"])
                nt.links.new(mapn.outputs["Vector"], tex.inputs["Vector"])
        nt.nodes.active = tex
        self.report({"INFO"}, "Baked image set as active texture. View in Solid + Texture.")
        return {"FINISHED"}


class RPBAKE_OT_save(bpy.types.Operator):
    bl_idname = "rpbake.save"
    bl_label = "Save Image..."
    bl_description = "Open Blender's Save As dialog for the baked image (choose format, path, options)"
    bl_options = {"REGISTER"}

    def execute(self, context):
        res = bpy.data.images.get(RESULT_IMAGE_NAME)
        if res is None:
            self.report({"WARNING"}, "No baked image yet.")
            return {"CANCELLED"}
        try:
            with context.temp_override(edit_image=res):
                bpy.ops.image.save_as("INVOKE_DEFAULT")
        except Exception as exc:
            self.report({"ERROR"}, "Could not open save dialog: %s" % exc)
            return {"CANCELLED"}
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
        col.prop(sc, "rpbake_resolution")
        col.prop(sc, "rpbake_samples")
        col.prop(sc, "rpbake_epsilon")
        busy = _state["job"] is not None
        r = layout.row()
        r.enabled = not busy
        r.operator("rpbake.bake", icon="RENDER_STILL")
        if sc.rpbake_status:
            layout.label(text=sc.rpbake_status, icon=("SORTTIME" if busy else "CHECKMARK"))
        has_result = bpy.data.images.get(RESULT_IMAGE_NAME) is not None
        col2 = layout.column(align=True)
        col2.enabled = has_result and not busy
        col2.operator("rpbake.show_on_mesh", icon="MESH_DATA")
        col2.operator("rpbake.save", icon="FILE_TICK")


_classes = (RPBAKE_OT_bake, RPBAKE_OT_show_on_mesh, RPBAKE_OT_save, RPBAKE_PT_panel)


def register():
    bpy.types.Scene.rpbake_resolution = bpy.props.IntProperty(name="Resolution", default=1024, min=64, max=8192)
    bpy.types.Scene.rpbake_samples = bpy.props.IntProperty(name="Samples", default=128, min=1, max=4096)
    bpy.types.Scene.rpbake_epsilon = bpy.props.FloatProperty(name="Surface Offset", default=0.02, min=0.0001, max=1.0, precision=4)
    bpy.types.Scene.rpbake_status = bpy.props.StringProperty(name="Status", default="")
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    job = _state["job"]
    if job is not None:
        try:
            job["proc"].kill()
        except Exception:
            pass
        _finish(job)
    if bpy.app.timers.is_registered(_poll):
        bpy.app.timers.unregister(_poll)
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    for p in ("rpbake_resolution", "rpbake_samples", "rpbake_epsilon", "rpbake_status"):
        if hasattr(bpy.types.Scene, p):
            delattr(bpy.types.Scene, p)


if __name__ == "__main__":
    register()
