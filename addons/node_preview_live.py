# SPDX-License-Identifier: GPL-3.0-or-later
#
# Node Preview Live  —  Milestone 1 (background-process build)
# -------------------------------------------------------------------------
# Renders the output of the ACTIVE shader node (Brick, Noise, ColorRamp,
# Hue/Sat, ...) to a persistent image datablock and shows it in the Image
# Editor.
#
# WHY A BACKGROUND PROCESS:
#   Rendering on Blender's main thread FREEZES the whole UI for the entire
#   render (plus first-time kernel/shader compile). So instead we build a
#   tiny temp scene (a copy of your material on a 1x1 plane under an ortho
#   camera), write JUST that scene to a temp .blend, and render it in a
#   separate headless Blender process. The UI stays responsive; a lightweight
#   timer polls for the finished PNG and loads it in.
#
# Your real material is NEVER modified — we always work on a copy.
#
# CONTROLS  (Shader Editor > Sidebar (N) > "Node Preview" tab):
#   * "Refresh Preview" -> render the active node once.
#   * "Start / Stop Live" -> debounced auto-refresh while you edit.
#   * Resolution / Tiling / Debounce sliders.
#
# TILING: the 0..1 swatch is repeated NxN in the final image (numpy), so it
# works regardless of the procedural's coordinate source, and is seamless
# exactly when your swatch is.
#
# MILESTONE 1 SCOPE (intentional): Image-Editor display only (viewport is M2);
# top-level Material nodes only (not node groups, not World/Light); materials
# built purely from procedural nodes are the happy path (image-texture-based
# materials render too, but packed/relative image paths may not resolve in the
# worker).
# -------------------------------------------------------------------------

bl_info = {
    "name": "Node Preview Live",
    "author": "Claude Relay",
    "version": (0, 2, 0),
    "blender": (4, 4, 0),
    "location": "Shader Editor > Sidebar (N) > Node Preview",
    "description": "Live-render the active shader node to an image (background process, non-blocking)",
    "category": "Node",
}

import os
import time
import tempfile
import subprocess

import bpy
import numpy as np

RESULT_IMAGE_NAME = "NodePreview_Result"
JOB_SCENE_NAME = "NP_JOB"
_WORKER_NAME = "np_worker.py"

# The worker runs inside a headless "blender -b job.blend --python np_worker.py -- SCENE OUT".
# It targets the scene by name and renders it to the given path.
_WORKER_SRC = '''import bpy, sys
argv = sys.argv[sys.argv.index("--") + 1:]
scene_name, out_path = argv[0], argv[1]
scene = bpy.data.scenes[scene_name]
# Force Cycles here (the worker always has it), so the main Blender never needs
# the Cycles add-on enabled just to build the job.
try:
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    scene.cycles.device = "CPU"
except Exception:
    pass
scene.render.filepath = out_path
scene.render.use_file_extension = False
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
with bpy.context.temp_override(scene=scene):
    bpy.ops.render.render(write_still=True)
'''

# Live-loop / job state (kept off bpy props so timer + handler can mutate it).
_state = {
    "live_on": False,
    "dirty": False,
    "last_change": 0.0,
    "busy": False,          # True while we build/complete (suppresses self-triggered dirty)
    "cooldown_until": 0.0,
    "job": None,            # dict(proc, blend, png, tiling) or None
    "last_error": "",
    "timer_registered": False,
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _worker_path():
    """Write the worker script to the temp dir (once) and return its path."""
    path = os.path.join(tempfile.gettempdir(), _WORKER_NAME)
    try:
        if not os.path.exists(path):
            with open(path, "w") as f:
                f.write(_WORKER_SRC)
    except Exception:
        # Fall back to a fresh unique file if the shared one can't be written.
        fd, path = tempfile.mkstemp(suffix=".py", prefix="np_worker_")
        with os.fdopen(fd, "w") as f:
            f.write(_WORKER_SRC)
    return path


def _find_target():
    """Return (material, node) for the active shader node, or (None, reason).

    Primary: a Shader node editor's own datablock (respects pinning, detects
    groups). Fallback: the active object's active material — the same node-tree
    datablock the editor edits — so it still works when the editor hasn't
    populated space.id/edit_tree yet.
    """
    ctx = bpy.context
    editor_space = None
    for window in ctx.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "NODE_EDITOR":
                continue
            sp = area.spaces.active
            if sp is not None and getattr(sp, "tree_type", "") == "ShaderNodeTree":
                editor_space = sp
                break
        if editor_space is not None:
            break

    mat = None
    if editor_space is not None and isinstance(getattr(editor_space, "id", None), bpy.types.Material):
        mat = editor_space.id
    if mat is None:
        obj = getattr(ctx, "object", None)
        if obj is not None:
            mat = obj.active_material
    if mat is None:
        return None, "No active material — select an object with a material."
    if mat.node_tree is None:
        return None, "Material has no node tree."

    # If the editor exposes its edited tree and it's a nested group, bail out.
    edit_tree = getattr(editor_space, "edit_tree", None) if editor_space is not None else None
    if edit_tree is not None and edit_tree != mat.node_tree:
        return None, "Node is inside a group; group previews aren't supported yet."

    node = mat.node_tree.nodes.active
    if node is None:
        return None, "No active node — click a node to select it."
    return mat, node


def _choose_output_socket(node):
    for sock in node.outputs:
        if sock.enabled and not sock.hide:
            return sock
    return None


def _build_job_scene(src_mat, node_name, resolution):
    """Create the temp render scene (copied material on a plane + ortho cam).

    Returns (scene, created_datablocks, ok, reason). `created_datablocks` is a
    list to remove from the main file after the .blend is written.
    """
    created = []

    mat = src_mat.copy()
    created.append(("materials", mat))
    nt = mat.node_tree
    node = nt.nodes.get(node_name)
    if node is None:
        return None, created, False, "Could not locate node in material copy."
    sock = _choose_output_socket(node)
    if sock is None:
        return None, created, False, "Selected node has no usable output."

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    if sock.type == "SHADER":
        nt.links.new(sock, out.inputs["Surface"])
    else:
        emis = nt.nodes.new("ShaderNodeEmission")
        nt.links.new(sock, emis.inputs["Color"])
        nt.links.new(emis.outputs["Emission"], out.inputs["Surface"])
    for n in nt.nodes:
        if n.type == "OUTPUT_MATERIAL":
            n.is_active_output = (n == out)

    mesh = bpy.data.meshes.new("NP_plane_mesh")
    created.append(("meshes", mesh))
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    mesh.update()
    uv = mesh.uv_layers.new(name="UVMap")
    for i, c in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
        uv.data[i].uv = c
    mesh.materials.append(mat)
    plane = bpy.data.objects.new("NP_plane", mesh)
    created.append(("objects", plane))

    cam_data = bpy.data.cameras.new("NP_cam_data")
    created.append(("cameras", cam_data))
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 1.0
    cam_data.clip_start = 0.1
    cam_data.clip_end = 10.0
    cam = bpy.data.objects.new("NP_cam", cam_data)
    created.append(("objects", cam))
    cam.location = (0.5, 0.5, 2.0)

    scene = bpy.data.scenes.new(JOB_SCENE_NAME)
    created.append(("scenes", scene))
    scene.collection.objects.link(plane)
    scene.collection.objects.link(cam)
    scene.camera = cam

    # Engine/samples/device are set by the worker (which always has Cycles),
    # so the main Blender needs no render-engine add-on just to build the job.
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False

    return scene, created, True, ""


def _remove_created(created):
    """Remove temp datablocks from the main file (reverse order)."""
    removers = {
        "objects": bpy.data.objects,
        "meshes": bpy.data.meshes,
        "cameras": bpy.data.cameras,
        "materials": bpy.data.materials,
        "scenes": bpy.data.scenes,
    }
    # Objects first so mesh/cam/material user-counts drop to zero.
    order = ["objects", "meshes", "cameras", "materials", "scenes"]
    by_kind = {k: [] for k in order}
    for kind, db in created:
        by_kind.setdefault(kind, []).append(db)
    for kind in order:
        for db in by_kind.get(kind, []):
            try:
                removers[kind].remove(db, do_unlink=True)
            except Exception:
                pass


def start_job(context):
    """Build the temp scene, write it to a .blend, and spawn the worker.

    Returns (ok, message). Non-blocking: does NOT wait for the render.
    """
    if _state["job"] is not None:
        return False, "A preview render is already in progress."

    mat, node = _find_target()
    if mat is None:
        return False, node  # reason string

    resolution = int(context.scene.np_resolution)
    tiling = int(context.scene.np_tiling)

    _state["busy"] = True
    created = []
    try:
        scene, created, ok, reason = _build_job_scene(mat, node.name, resolution)
        if not ok:
            _remove_created(created)
            return False, reason

        tmpdir = tempfile.gettempdir()
        stamp = str(int(time.time() * 1000))
        blend = os.path.join(tmpdir, "np_job_%s.blend" % stamp)
        png = os.path.join(tmpdir, "np_out_%s.png" % stamp)

        bpy.data.libraries.write(blend, {scene}, path_remap="NONE", fake_user=True)
    except Exception as exc:
        _remove_created(created)
        _state["busy"] = False
        return False, "Failed to prepare preview: %s" % exc
    finally:
        # Whether or not write succeeded, the temp datablocks are no longer
        # needed in the main file.
        _remove_created(created)

    try:
        exe = bpy.app.binary_path
        worker = _worker_path()
        kwargs = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        proc = subprocess.Popen(
            [exe, "-b", blend, "--python", worker, "--", JOB_SCENE_NAME, png],
            **kwargs
        )
    except Exception as exc:
        _state["busy"] = False
        try:
            os.remove(blend)
        except Exception:
            pass
        return False, "Could not launch background Blender: %s" % exc

    _state["job"] = {"proc": proc, "blend": blend, "png": png, "tiling": tiling, "started": time.time()}
    _state["busy"] = False
    _state["cooldown_until"] = time.time() + 0.1
    _ensure_timer()
    return True, "Rendering preview..."


def _store_result(png_path, tiling):
    """Load the rendered PNG, tile it, and write into the persistent image."""
    tmp = bpy.data.images.load(png_path)
    try:
        w, h = tmp.size
        if w == 0 or h == 0:
            raise RuntimeError("rendered image is empty")
        buf = np.empty(w * h * 4, dtype=np.float32)
        tmp.pixels.foreach_get(buf)
        img2d = buf.reshape(h, w, 4)
        n = max(1, int(tiling))
        while n > 1 and (w * n > 4096 or h * n > 4096):
            n -= 1
        if n > 1:
            img2d = np.tile(img2d, (n, n, 1))
        out_h, out_w = img2d.shape[0], img2d.shape[1]
        flat = np.ascontiguousarray(img2d, dtype=np.float32).ravel()
    finally:
        bpy.data.images.remove(tmp)

    res_img = bpy.data.images.get(RESULT_IMAGE_NAME)
    if res_img is None:
        res_img = bpy.data.images.new(RESULT_IMAGE_NAME, out_w, out_h, alpha=True)
        res_img.use_fake_user = True
    elif res_img.size[0] != out_w or res_img.size[1] != out_h:
        res_img.scale(out_w, out_h)
    res_img.pixels.foreach_set(flat)
    res_img.update()

    # Show it in any open Image Editor.
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "IMAGE_EDITOR":
                    area.spaces.active.image = res_img
                    area.tag_redraw()
    except Exception:
        pass
    return res_img


def _complete_job():
    """If the in-flight job finished, load its result. Returns True if done."""
    job = _state["job"]
    if job is None:
        return True
    proc = job["proc"]
    if proc.poll() is None:
        # Still rendering. Guard against a hung/very slow process.
        if time.time() - job["started"] > 120.0:
            try:
                proc.kill()
            except Exception:
                pass
            _state["last_error"] = "Preview render timed out."
            _cleanup_job_files(job)
            _state["job"] = None
            return True
        return False

    _state["busy"] = True
    try:
        if proc.returncode == 0 and os.path.exists(job["png"]):
            _store_result(job["png"], job["tiling"])
            _state["last_error"] = ""
        else:
            _state["last_error"] = "Background render failed (code %s)." % proc.returncode
    except Exception as exc:
        _state["last_error"] = "Loading preview failed: %s" % exc
    finally:
        _cleanup_job_files(job)
        _state["job"] = None
        _state["busy"] = False
        _state["cooldown_until"] = time.time() + 0.1
    _redraw_node_editors()
    return True


def _cleanup_job_files(job):
    for key in ("blend", "png"):
        try:
            p = job.get(key)
            if p and os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


def _redraw_node_editors():
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "NODE_EDITOR":
                    area.tag_redraw()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Timer loop + depsgraph dirty flag
# ---------------------------------------------------------------------------

def _timer():
    """Polled on the main thread; never blocks. Returns seconds to next call."""
    # 1) finish an in-flight job if it's ready.
    if _state["job"] is not None:
        _complete_job()

    # 2) in live mode, start a new job after a quiet period.
    if _state["live_on"] and _state["job"] is None:
        now = time.time()
        if _state["dirty"] and (now - _state["last_change"]) >= float(_debounce()):
            _state["dirty"] = False
            ok, msg = start_job(bpy.context)
            if not ok:
                _state["last_error"] = msg
                _redraw_node_editors()

    # 3) decide whether to keep the timer alive.
    if _state["live_on"] or _state["job"] is not None:
        return 0.1
    _state["timer_registered"] = False
    return None


def _debounce():
    try:
        return bpy.context.scene.np_debounce
    except Exception:
        return 0.3


def _ensure_timer():
    if not _state["timer_registered"]:
        bpy.app.timers.register(_timer, first_interval=0.05)
        _state["timer_registered"] = True


def _on_depsgraph_update(scene, depsgraph):
    if _state["busy"] or _state["job"] is not None:
        return
    now = time.time()
    if now < _state["cooldown_until"]:
        return
    _state["dirty"] = True
    _state["last_change"] = now


def _install_handler():
    h = bpy.app.handlers.depsgraph_update_post
    if _on_depsgraph_update not in h:
        h.append(_on_depsgraph_update)


def _remove_handler():
    h = bpy.app.handlers.depsgraph_update_post
    if _on_depsgraph_update in h:
        h.remove(_on_depsgraph_update)


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class NODEPREVIEW_OT_refresh(bpy.types.Operator):
    bl_idname = "nodepreview.refresh"
    bl_label = "Refresh Preview"
    bl_description = "Render the active shader node to the preview image (runs in the background)"
    bl_options = {"REGISTER"}

    def execute(self, context):
        ok, msg = start_job(context)
        if ok:
            _ensure_timer()
            self.report({"INFO"}, msg)
            return {"FINISHED"}
        self.report({"WARNING"}, msg)
        return {"CANCELLED"}


class NODEPREVIEW_OT_toggle_live(bpy.types.Operator):
    bl_idname = "nodepreview.toggle_live"
    bl_label = "Toggle Live Preview"
    bl_description = "Start/stop debounced auto-refresh while you edit nodes"
    bl_options = {"REGISTER"}

    def execute(self, context):
        if _state["live_on"]:
            _state["live_on"] = False
            _remove_handler()
            self.report({"INFO"}, "Live preview stopped.")
        else:
            _state["live_on"] = True
            _state["dirty"] = True
            _state["last_change"] = 0.0   # render once right away
            _install_handler()
            _ensure_timer()
            self.report({"INFO"}, "Live preview started.")
        _redraw_node_editors()
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class NODEPREVIEW_PT_panel(bpy.types.Panel):
    bl_idname = "NODEPREVIEW_PT_panel"
    bl_label = "Node Preview"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Node Preview"

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space is not None and getattr(space, "tree_type", "") == "ShaderNodeTree"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        col = layout.column(align=True)
        col.prop(scene, "np_resolution")
        col.prop(scene, "np_tiling")
        col.prop(scene, "np_debounce")

        layout.separator()
        rendering = _state["job"] is not None
        row = layout.row()
        row.enabled = not rendering
        row.operator("nodepreview.refresh", icon="FILE_REFRESH")

        row = layout.row()
        if _state["live_on"]:
            row.alert = True
            row.operator("nodepreview.toggle_live", text="Stop Live", icon="PAUSE")
        else:
            row.operator("nodepreview.toggle_live", text="Start Live", icon="PLAY")

        box = layout.box()
        if rendering:
            box.label(text="Rendering preview...", icon="SORTTIME")
        mat, node = _find_target()
        if mat is None:
            box.label(text=node, icon="INFO")
        else:
            box.label(text="Material: " + mat.name, icon="MATERIAL")
            box.label(text="Node: " + node.name, icon="NODE")
        if _state["last_error"]:
            box.label(text=_state["last_error"], icon="ERROR")

        res_img = bpy.data.images.get(RESULT_IMAGE_NAME)
        if res_img is not None:
            layout.label(text="Result: %d x %d" % (res_img.size[0], res_img.size[1]))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = (
    NODEPREVIEW_OT_refresh,
    NODEPREVIEW_OT_toggle_live,
    NODEPREVIEW_PT_panel,
)


def register():
    bpy.types.Scene.np_resolution = bpy.props.IntProperty(
        name="Resolution", description="Pixel size of the 0..1 swatch (per tile)",
        default=256, min=32, max=2048,
    )
    bpy.types.Scene.np_tiling = bpy.props.IntProperty(
        name="Tiling", description="Repeat the swatch NxN in the final image",
        default=1, min=1, max=8,
    )
    bpy.types.Scene.np_debounce = bpy.props.FloatProperty(
        name="Debounce (s)", description="Quiet time after your last edit before re-rendering (live mode)",
        default=0.3, min=0.05, max=2.0,
    )
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    _state["live_on"] = False
    _remove_handler()
    job = _state["job"]
    if job is not None:
        try:
            job["proc"].kill()
        except Exception:
            pass
        _cleanup_job_files(job)
        _state["job"] = None
    try:
        if _state["timer_registered"] and bpy.app.timers.is_registered(_timer):
            bpy.app.timers.unregister(_timer)
    except Exception:
        pass
    _state["timer_registered"] = False

    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    for prop in ("np_resolution", "np_tiling", "np_debounce"):
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)


if __name__ == "__main__":
    register()
