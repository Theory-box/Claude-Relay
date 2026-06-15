"""
Phase 1b Blender add-on (SPIKE) — owns SHM, spawns helper, pumps frames to a GPUTexture,
draws it in the Image Editor, forwards input.

Runs in Blender 4.4's Python (3.11). Pairs with helper_cefpython.py and SHM_CONTRACT.md.
FIRST-DRAFT scaffold — success criterion: a live page appears in the Image Editor and a
click registers. Not production; expect on-machine iteration (paths, timings, Y-flip).

SETUP (edit these two paths for your machine):
    HELPER_PY     = path to the cef-venv python.exe (Py3.9/3.10 with cefpython3)
    HELPER_SCRIPT = path to helper_cefpython.py
Then: install as add-on (or run in Text Editor), open an Image Editor, run
`browser.open` (search F3 -> "Browser: Open").
"""
bl_info = {"name": "Browser Spike (Phase 1b)", "blender": (4, 4, 0), "category": "Development"}

import os, sys, json, socket, struct, subprocess, uuid
from multiprocessing import shared_memory
import numpy as np
import bpy, gpu
from gpu_extras.batch import batch_for_shader

# --- Auto-discovered when installed as an add-on (no manual path editing) ------
# The helper script and a bundled Python runtime live inside the add-on folder.
# (If you run this from the Text Editor instead of installing it, __file__ may be
#  unset — only then set ADDON_DIR by hand below.)
try:
    ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    ADDON_DIR = r"C:\path\to\this\addon\folder"   # ONLY needed if run from Text Editor
HELPER_SCRIPT = os.path.join(ADDON_DIR, "helper_cefpython.py")
HELPER_PY = os.path.join(ADDON_DIR, "runtime", "Scripts", "python.exe")  # bundled runtime
START_URL = "https://example.com"
WIDTH, HEIGHT = 1280, 720          # fixed for the spike; <=1080p stays >60fps (see §17)
PORT = 8765
# ------------------------------------------------------------------------------

HEADER = 64
_S = {"shm": None, "proc": None, "sock": None, "tex": None, "last_seq": -1,
      "handle": None, "shader": None, "batch": None, "dirty": False,
      "log": None, "hidden": False}


# ---- control socket ----------------------------------------------------------
def _send(msg: dict):
    s = _S["sock"]
    if not s:
        return
    body = json.dumps(msg).encode("utf-8")
    try:
        s.sendall(struct.pack(">I", len(body)) + body)
    except OSError:
        pass


# ---- GPU draw ----------------------------------------------------------------
def _ensure_shader():
    if _S["shader"]:
        return
    _S["shader"] = gpu.shader.from_builtin('IMAGE')
    # Y-flip handled here: web is top-left origin, Blender region bottom-left.
    _S["batch"] = batch_for_shader(
        _S["shader"], 'TRI_FAN',
        {"pos": [(0, 0), (1, 0), (1, 1), (0, 1)],
         "texCoord": [(0, 1), (1, 1), (1, 0), (0, 0)]})


def _draw():
    # Build the texture HERE (draw handler = valid GPU context). Timers have none. [B-5 #1]
    shm = _S["shm"]
    if shm is not None and _S.get("dirty"):
        buf = shm.buf
        active = struct.unpack_from("<I", buf, 24)[0]
        off = HEADER + active * (WIDTH * HEIGHT * 16)
        arr = np.frombuffer(buf, dtype=np.float32, count=WIDTH * HEIGHT * 4, offset=off)
        fb = gpu.types.Buffer('FLOAT', WIDTH * HEIGHT * 4, arr)
        _S["tex"] = gpu.types.GPUTexture((WIDTH, HEIGHT), format='RGBA8', data=fb)
        _S["dirty"] = False
    tex = _S["tex"]
    if tex is None:
        return
    _ensure_shader()
    region = bpy.context.region
    if region is None:
        return
    with gpu.matrix.push_pop():
        gpu.matrix.load_identity()
        gpu.matrix.load_projection_matrix(_ortho(region.width, region.height))
        # draw the texture stretched across the region (1:1 if region matches WIDTHxHEIGHT)
        sh = _S["shader"]; sh.bind(); sh.uniform_sampler("image", tex)
        # scale unit quad to region size via a simple matrix
        gpu.matrix.scale((region.width, region.height))  # TODO: aspect-correct fit
        _S["batch"].draw(sh)


def _ortho(w, h):
    from mathutils import Matrix
    return Matrix((( 2.0 / w, 0, 0, -1),
                   (0,  2.0 / h, 0, -1),
                   (0, 0, -1, 0),
                   (0, 0, 0, 1)))


# ---- frame pump (timer, main thread; NO gpu calls — see _draw) --------------
def _pump():
    shm = _S["shm"]
    if shm is None:
        return None  # stop timer
    # idle-suspend: tell helper when no browser panel is visible (drives WasHidden) [A-5]
    visible = any(a.type == 'IMAGE_EDITOR'
                  for w in bpy.context.window_manager.windows for a in w.screen.areas)
    if visible == _S["hidden"]:               # state changed
        _S["hidden"] = not visible
        _send({"t": "set_hidden", "on": not visible})
    seq = struct.unpack_from("<I", shm.buf, 28)[0]
    if seq != _S["last_seq"]:
        _S["last_seq"] = seq
        _S["dirty"] = True                    # _draw will view+upload in a valid context
        for w in bpy.context.window_manager.windows:
            for a in w.screen.areas:
                if a.type == 'IMAGE_EDITOR':
                    a.tag_redraw()
    return 1.0 / 60.0


# ---- lifecycle ---------------------------------------------------------------
def _start():
    name = "blndr_browser_" + uuid.uuid4().hex[:12]
    slot_bytes = WIDTH * HEIGHT * 16            # RGBA32F (helper writes FLOAT)
    size = HEADER + 2 * slot_bytes
    _S["shm"] = shared_memory.SharedMemory(create=True, size=size, name=name)  # Blender OWNS it
    logpath = os.path.join(bpy.app.tempdir, "browser_helper.log")
    _S["log"] = open(logpath, "w")
    print("[browser] helper log ->", logpath)
    _S["proc"] = subprocess.Popen(
        [HELPER_PY, HELPER_SCRIPT, "--shm-name", name, "--width", str(WIDTH),
         "--height", str(HEIGHT), "--port", str(PORT), "--url", START_URL],
        stdout=_S["log"], stderr=subprocess.STDOUT)
    # connect control socket (retry until helper's server is up)
    import time
    for _ in range(50):
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=0.2)
            _S["sock"] = s; break
        except OSError:
            time.sleep(0.1)
    _S["handle"] = bpy.types.SpaceImageEditor.draw_handler_add(_draw, (), 'WINDOW', 'POST_PIXEL')
    bpy.app.timers.register(_pump, first_interval=0.1)


def _stop():
    _send({"t": "shutdown"})
    if _S["handle"]:
        bpy.types.SpaceImageEditor.draw_handler_remove(_S["handle"], 'WINDOW'); _S["handle"] = None
    shm = _S["shm"]; _S["shm"] = None          # null first so timer/draw callbacks bail [B-5 #8]
    _S["tex"] = None; _S["last_seq"] = -1; _S["dirty"] = False
    try:
        _S["sock"] and _S["sock"].close()
    except OSError:
        pass
    _S["sock"] = None
    if _S["proc"]:
        try:
            _S["proc"].wait(timeout=2)
        except Exception:
            _S["proc"].kill()
        _S["proc"] = None
    if _S.get("log"):
        try:
            _S["log"].close()
        except Exception:
            pass
        _S["log"] = None
    if shm:
        shm.close()
        try:
            shm.unlink()                       # no-op on Windows; harmless
        except Exception:
            pass


# ---- operators ---------------------------------------------------------------
class BROWSER_OT_open(bpy.types.Operator):
    bl_idname = "browser.open"; bl_label = "Browser: Open"
    def execute(self, context):
        _start()
        bpy.ops.browser.input('INVOKE_DEFAULT')
        return {'FINISHED'}


class BROWSER_OT_close(bpy.types.Operator):
    bl_idname = "browser.close"; bl_label = "Browser: Close"
    def execute(self, context):
        _stop(); return {'FINISHED'}


# Input capture (per Instance B's B-3 skeleton; hot-region gating + PASS_THROUGH).
PASSTHROUGH = {'ESC'}
class BROWSER_OT_input(bpy.types.Operator):
    bl_idname = "browser.input"; bl_label = "Browser: Input"
    def invoke(self, context, event):
        self._focused = False
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    def _hot(self, context, event):
        r = context.region
        return r and 0 <= event.mouse_region_x < r.width and 0 <= event.mouse_region_y < r.height
    def modal(self, context, event):
        if _S["shm"] is None:
            return {'CANCELLED'}
        hot = self._hot(context, event)
        if hot and not self._focused:
            self._focused = True; _send({"t": "focus", "on": True})
        elif not hot and self._focused:
            self._focused = False; _send({"t": "focus", "on": False})
        if not hot or event.type in PASSTHROUGH:
            return {'PASS_THROUGH'}
        r = context.region
        x = event.mouse_region_x
        y = r.height - event.mouse_region_y    # flip to web top-left origin
        # scale region coords -> page coords
        px = int(x / r.width * WIDTH); py = int(y / r.height * HEIGHT)
        et = event.type
        if et == 'MOUSEMOVE':
            _send({"t": "mouse_move", "x": px, "y": py}); return {'RUNNING_MODAL'}
        if et in {'LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE'}:
            btn = {'LEFTMOUSE': 'left', 'RIGHTMOUSE': 'right', 'MIDDLEMOUSE': 'middle'}[et]
            _send({"t": "mouse_button", "x": px, "y": py, "button": btn,
                   "down": event.value == 'PRESS', "clicks": 1}); return {'RUNNING_MODAL'}
        if et in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            _send({"t": "wheel", "x": px, "y": py, "dx": 0,
                   "dy": 120 if et == 'WHEELUPMOUSE' else -120}); return {'RUNNING_MODAL'}
        if event.value in {'PRESS', 'RELEASE'}:
            mods = (event.shift << 1) | (event.ctrl << 2) | (event.alt << 3) | (event.oskey << 7)
            _send({"t": "key", "down": event.value == 'PRESS', "vk": 0,
                   "char": (event.unicode or None), "mods": mods}); return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}


_CLASSES = (BROWSER_OT_open, BROWSER_OT_close, BROWSER_OT_input)
def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)
def unregister():
    _stop()
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)

if __name__ == "__main__":
    register()
