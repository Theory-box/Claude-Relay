# SPDX-License-Identifier: GPL-3.0-or-later
#
# Node Preview Live  —  Milestone 1
# -------------------------------------------------------------------------
# Renders the output of the ACTIVE shader node (Brick, Noise, ColorRamp,
# Hue/Sat, etc.) to a persistent image datablock and shows it live in the
# Image Editor. Designed to be reliable on Blender 4.4.
#
# Design choices (all made for "works out of the box"):
#   * Renders a copy of your material on a temp plane in a temp scene, so
#     your real material is NEVER modified, even if something errors.
#   * Uses whatever render engine is actually available (prefers Cycles,
#     then EEVEE under either 4.2-4.4 identifier), chosen at runtime so we
#     don't hard-code an engine name that changed across versions.
#   * Builds the temp plane + camera from raw data (no bpy.ops mesh calls),
#     avoiding operator-context problems.
#   * Tiling is a pure numpy post-step (np.tile), so it works no matter what
#     coordinate source the procedural reads from, and is guaranteed seamless
#     exactly when your 0..1 swatch is seamless.
#
# Two ways to drive it, both in the Shader Editor N-panel (tab "Node Preview"):
#   * "Refresh Preview"  -> guaranteed, on-demand. Test this FIRST.
#   * "Start Live"       -> debounced auto-refresh while you edit (convenience
#                           layer built on a modal timer; if it ever misbehaves
#                           on your setup, the Refresh button still works).
#
# Milestone 1 scope / known limitations (intentional, documented):
#   * Only nodes in the material's TOP-LEVEL tree (not inside node groups).
#   * Only Material shader trees (not World / Light).
#   * Viewport (Workbench) display is Milestone 2; this is Image-Editor only.
# -------------------------------------------------------------------------

bl_info = {
    "name": "Node Preview Live",
    "author": "Claude Relay",
    "version": (0, 1, 0),
    "blender": (4, 4, 0),
    "location": "Shader Editor > Sidebar (N) > Node Preview",
    "description": "Live-render the active shader node to an image and show it in the Image Editor",
    "category": "Node",
}

import os
import time
import tempfile

import bpy
import numpy as np

RESULT_IMAGE_NAME = "NodePreview_Result"

# Module-level live-loop state (kept out of bpy props so timer/handler can mutate freely)
_state = {
    "running": False,
    "rendering": False,
    "dirty": False,
    "last_change": 0.0,
    "cooldown_until": 0.0,
    "timer": None,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pick_engine():
    """Return an available render engine identifier, robust across versions.

    Cycles is preferred (a flat emission swatch is trivial for it and its
    identifier has never changed). Falls back to whichever EEVEE identifier
    this Blender exposes, then to anything registered.
    """
    try:
        items = bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items.keys()
    except Exception:
        return "CYCLES"
    for candidate in ("CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        if candidate in items:
            return candidate
    return list(items)[0] if items else "CYCLES"


def _find_target():
    """Scan open windows for a shader-node editor and return (material, node).

    Returns (material, node) on success or (None, reason_string) on failure.
    Restricts to nodes living in the material's top-level tree.
    """
    wm = bpy.context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type != "NODE_EDITOR":
                continue
            space = area.spaces.active
            if space is None or getattr(space, "tree_type", "") != "ShaderNodeTree":
                continue
            edit_tree = getattr(space, "edit_tree", None)
            owner = getattr(space, "id", None)  # the datablock that owns the shown tree
            if edit_tree is None:
                continue
            if not isinstance(owner, bpy.types.Material):
                return None, "Active shader tree isn't a material (World/Light not supported yet)."
            mat = owner
            if mat.node_tree is None:
                return None, "Material has no node tree."
            # Nodes inside a group live in a nested tree; require top-level here.
            if edit_tree != mat.node_tree:
                return None, "Node is inside a group; group previews aren't supported yet."
            node = edit_tree.nodes.active
            if node is None:
                return None, "No active node — click a node to select it."
            return mat, node
    return None, "No Shader Editor open."


def _choose_output_socket(node):
    """Pick the first usable (enabled, visible) output socket of a node."""
    for sock in node.outputs:
        if sock.enabled and not sock.hide:
            return sock
    return None


def _build_preview_material(src_mat, node_name):
    """Copy src_mat and rewire node_name's output to a fresh Material Output.

    Non-shader outputs go through an Emission so they show flat/unlit.
    Returns (material_copy, ok, reason).
    """
    mat = src_mat.copy()
    nt = mat.node_tree
    node = nt.nodes.get(node_name)
    if node is None:
        return mat, False, "Could not locate node in material copy."

    sock = _choose_output_socket(node)
    if sock is None:
        return mat, False, "Selected node has no usable output."

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    if sock.type == "SHADER":
        nt.links.new(sock, out.inputs["Surface"])
    else:
        emis = nt.nodes.new("ShaderNodeEmission")
        nt.links.new(sock, emis.inputs["Color"])
        nt.links.new(emis.outputs["Emission"], out.inputs["Surface"])

    # Make our output the active one so the render uses it.
    for n in nt.nodes:
        if n.type == "OUTPUT_MATERIAL":
            n.is_active_output = (n == out)

    return mat, True, ""


def _make_temp_plane(name, material):
    """Create a 1x1 UV-mapped plane mesh object carrying `material`."""
    mesh = bpy.data.meshes.new(name + "_mesh")
    verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    faces = [(0, 1, 2, 3)]
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    uv_layer = mesh.uv_layers.new(name="UVMap")
    # Loop order matches the single quad face 0,1,2,3
    uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    for loop_idx, uv in enumerate(uvs):
        uv_layer.data[loop_idx].uv = uv

    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    return obj


def _make_temp_camera(name):
    """Orthographic camera above the plane framing exactly 0..1 in X and Y."""
    cam_data = bpy.data.cameras.new(name + "_data")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 1.0
    cam_data.clip_start = 0.1
    cam_data.clip_end = 10.0
    cam_obj = bpy.data.objects.new(name, cam_data)
    cam_obj.location = (0.5, 0.5, 2.0)   # centered over the plane, looking down -Z
    cam_obj.rotation_euler = (0.0, 0.0, 0.0)
    return cam_obj


def _render_scene_to_file(context, temp_scene, filepath):
    """Render temp_scene to filepath without disturbing the user's active scene."""
    window = context.window
    try:
        with context.temp_override(window=window, scene=temp_scene):
            bpy.ops.render.render(write_still=True)
        return
    except Exception:
        # Fallback: briefly swap the window scene, then restore no matter what.
        original = window.scene
        window.scene = temp_scene
        try:
            bpy.ops.render.render(write_still=True)
        finally:
            window.scene = original


def _load_and_store(filepath, tiling):
    """Load rendered PNG, tile it, and write into the persistent result image."""
    tmp = bpy.data.images.load(filepath)
    try:
        w, h = tmp.size
        if w == 0 or h == 0:
            raise RuntimeError("Rendered image is empty.")
        buf = np.empty(w * h * 4, dtype=np.float32)
        tmp.pixels.foreach_get(buf)
        img2d = buf.reshape(h, w, 4)

        n = max(1, int(tiling))
        # Clamp so a tiled result never exceeds 4096 px per side.
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
    return res_img


def _show_in_image_editor(image):
    """If an Image Editor is open, point it at the result image."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "IMAGE_EDITOR":
                    area.spaces.active.image = image
    except Exception:
        pass


def render_active(context):
    """Full pipeline: find target -> render swatch -> store -> show.

    Returns (ok, message). Cleans up every temp datablock even on error.
    """
    mat, node = _find_target()
    if mat is None:
        return False, node  # `node` holds the reason string here

    resolution = int(context.scene.np_resolution)
    tiling = int(context.scene.np_tiling)
    node_name = node.name

    prev_mat = None
    temp_scene = None
    plane = None
    cam = None
    tmp_path = None
    try:
        prev_mat, ok, reason = _build_preview_material(mat, node_name)
        if not ok:
            return False, reason

        temp_scene = bpy.data.scenes.new("NodePreview_tmp")
        temp_scene.render.engine = _pick_engine()
        if hasattr(temp_scene, "cycles"):
            try:
                temp_scene.cycles.samples = 1
                temp_scene.cycles.use_denoising = False
            except Exception:
                pass
        r = temp_scene.render
        r.resolution_x = resolution
        r.resolution_y = resolution
        r.resolution_percentage = 100
        r.film_transparent = False
        r.image_settings.file_format = "PNG"
        r.image_settings.color_mode = "RGBA"
        r.image_settings.color_depth = "8"
        # We supply the exact filepath (with .png); don't let Blender append
        # a second extension, or the file we try to load back won't exist.
        r.use_file_extension = False

        plane = _make_temp_plane("NodePreview_plane", prev_mat)
        cam = _make_temp_camera("NodePreview_cam")
        temp_scene.collection.objects.link(plane)
        temp_scene.collection.objects.link(cam)
        temp_scene.camera = cam

        fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="np_")
        os.close(fd)
        r.filepath = tmp_path

        _render_scene_to_file(context, temp_scene, tmp_path)

        result = _load_and_store(tmp_path, tiling)
        _show_in_image_editor(result)
        return True, "Preview updated ({}x tiling, {}px).".format(tiling, resolution)
    except Exception as exc:
        return False, "Render failed: {}".format(exc)
    finally:
        # Tear down every temp datablock we created, in a safe order.
        try:
            if plane is not None:
                m = plane.data
                bpy.data.objects.remove(plane, do_unlink=True)
                if m is not None and m.users == 0:
                    bpy.data.meshes.remove(m)
        except Exception:
            pass
        try:
            if cam is not None:
                cd = cam.data
                bpy.data.objects.remove(cam, do_unlink=True)
                if cd is not None and cd.users == 0:
                    bpy.data.cameras.remove(cd)
        except Exception:
            pass
        try:
            if temp_scene is not None:
                bpy.data.scenes.remove(temp_scene)
        except Exception:
            pass
        try:
            if prev_mat is not None:
                bpy.data.materials.remove(prev_mat, do_unlink=True)
        except Exception:
            pass
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Live loop (depsgraph handler sets a dirty flag; modal timer does the work)
# ---------------------------------------------------------------------------

def _on_depsgraph_update(scene, depsgraph):
    if _state["rendering"]:
        return
    now = time.time()
    if now < _state["cooldown_until"]:
        return
    _state["dirty"] = True
    _state["last_change"] = now


def _install_handler():
    handlers = bpy.app.handlers.depsgraph_update_post
    if _on_depsgraph_update not in handlers:
        handlers.append(_on_depsgraph_update)


def _remove_handler():
    handlers = bpy.app.handlers.depsgraph_update_post
    if _on_depsgraph_update in handlers:
        handlers.remove(_on_depsgraph_update)


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class NODEPREVIEW_OT_refresh(bpy.types.Operator):
    bl_idname = "nodepreview.refresh"
    bl_label = "Refresh Preview"
    bl_description = "Render the active shader node to the preview image now"
    bl_options = {"REGISTER"}

    def execute(self, context):
        ok, msg = render_active(context)
        if ok:
            self.report({"INFO"}, msg)
            return {"FINISHED"}
        self.report({"WARNING"}, msg)
        return {"CANCELLED"}


class NODEPREVIEW_OT_toggle_live(bpy.types.Operator):
    bl_idname = "nodepreview.toggle_live"
    bl_label = "Toggle Live Preview"
    bl_description = "Start/stop debounced auto-refresh while you edit nodes"

    def invoke(self, context, event):
        if _state["running"]:
            # Signal the running modal to stop on its next tick.
            _state["running"] = False
            return {"FINISHED"}

        _state["running"] = True
        _state["dirty"] = True          # render once immediately on start
        _state["rendering"] = False
        _state["cooldown_until"] = 0.0
        _install_handler()
        interval = 0.1
        _state["timer"] = context.window_manager.event_timer_add(interval, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if not _state["running"]:
            return self.cancel(context)

        if event.type == "TIMER":
            debounce = float(context.scene.np_debounce)
            now = time.time()
            if _state["dirty"] and not _state["rendering"] and (now - _state["last_change"]) >= debounce:
                _state["rendering"] = True
                try:
                    ok, msg = render_active(context)
                    if not ok:
                        print("[Node Preview Live]", msg)
                except Exception as exc:
                    print("[Node Preview Live] live render error:", exc)
                finally:
                    _state["dirty"] = False
                    _state["rendering"] = False
                    _state["cooldown_until"] = time.time() + 0.15
        return {"PASS_THROUGH"}

    def cancel(self, context):
        try:
            if _state["timer"] is not None:
                context.window_manager.event_timer_remove(_state["timer"])
        except Exception:
            pass
        _state["timer"] = None
        _state["running"] = False
        _remove_handler()
        # Nudge the UI so the button label updates.
        for area in context.screen.areas:
            if area.type == "NODE_EDITOR":
                area.tag_redraw()
        return {"CANCELLED"}


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
        layout.operator("nodepreview.refresh", icon="FILE_REFRESH")

        row = layout.row()
        if _state["running"]:
            row.alert = True
            row.operator("nodepreview.toggle_live", text="Stop Live", icon="PAUSE")
        else:
            row.operator("nodepreview.toggle_live", text="Start Live", icon="PLAY")

        # Show what's currently targeted, as a sanity readout.
        mat, node = _find_target()
        box = layout.box()
        if mat is None:
            box.label(text=node, icon="INFO")   # `node` is the reason string
        else:
            box.label(text="Material: " + mat.name, icon="MATERIAL")
            box.label(text="Node: " + node.name, icon="NODE")

        res_img = bpy.data.images.get(RESULT_IMAGE_NAME)
        if res_img is not None:
            layout.label(text="Result: {} x {}".format(res_img.size[0], res_img.size[1]))


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
        name="Resolution",
        description="Pixel size of the 0..1 swatch render (per tile)",
        default=256, min=32, max=2048,
    )
    bpy.types.Scene.np_tiling = bpy.props.IntProperty(
        name="Tiling",
        description="Repeat the swatch NxN in the final image (seamless if the swatch is)",
        default=1, min=1, max=8,
    )
    bpy.types.Scene.np_debounce = bpy.props.FloatProperty(
        name="Debounce (s)",
        description="Wait this long after your last edit before re-rendering (live mode)",
        default=0.3, min=0.05, max=2.0,
    )
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    # Make sure the live loop is fully torn down on disable/reload.
    _state["running"] = False
    try:
        if _state["timer"] is not None:
            bpy.context.window_manager.event_timer_remove(_state["timer"])
    except Exception:
        pass
    _state["timer"] = None
    _remove_handler()

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
