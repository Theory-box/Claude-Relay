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

# --- EDIT THESE ---------------------------------------------------------------
HELPER_PY = r"C:\path\to\cef-venv\Scripts\python.exe"
HELPER_SCRIPT = r"C:\path\to\helper_cefpython.py"
START_URL = "https://example.com"
WIDTH, HEIGHT = 1280, 720          # fixed for the spike; <=1080p stays >60fps (see §17)
PORT = 8765
# ------------------------------------------------------------------------------

HEADER = 64
_S = {"shm": None, "proc": None, "sock": None, "tex": None,
      "last_seq": -1, "handle": None, "shader": None, "batch": None, "fbuf": None}


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


# ---- frame pump (timer, main thread) ----------------------------------------
def _pump():
    shm = _S["shm"]
    if shm is None:
        return None  # stop timer
    buf = shm.buf
    seq = struct.unpack_from("<I", buf, 28)[0]
    if seq != _S["last_seq"]:
        _S["last_seq"] = seq
        active = struct.unpack_from("<I", buf, 24)[0]
        slot_bytes = WIDTH * HEIGHT * 4
        off = HEADER + active * slot_bytes
        raw = bytes(buf[off:off + slot_bytes])
        # BGRA bytes -> RGBA float32 (4.4 forces FLOAT upload). CPU reorder for the spike.
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(HEIGHT, WIDTH, 4)
        rgba = arr[:, :, [2, 1, 0, 3]].astype(np.float32) / 255.0   # BGRA->RGBA + normalize
        fb = gpu.types.Buffer('FLOAT', WIDTH * HEIGHT * 4, rgba.ravel())
        _S["tex"] = gpu.types.GPUTexture((WIDTH, HEIGHT), format='RGBA8', data=fb)
        for area in bpy.context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                area.tag_redraw()
    return 1.0 / 60.0


# ---- lifecycle ---------------------------------------------------------------
def _start():
    name = "blndr_browser_" + uuid.uuid4().hex[:12]
    slot_bytes = WIDTH * HEIGHT * 4
    size = HEADER + 2 * slot_bytes
    _S["shm"] = shared_memory.SharedMemory(create=True, size=size, name=name)  # Blender OWNS it
    _S["proc"] = subprocess.Popen(
        [HELPER_PY, HELPER_SCRIPT, "--shm-name", name, "--width", str(WIDTH),
         "--height", str(HEIGHT), "--port", str(PORT), "--url", START_URL])
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
    for k in ("sock",):
        try:
            _S[k] and _S[k].close()
        except OSError:
            pass
    if _S["proc"]:
        try:
            _S["proc"].wait(timeout=2)
        except Exception:
            _S["proc"].kill()
        _S["proc"] = None
    if _S["shm"]:
        _S["shm"].close(); _S["shm"].unlink(); _S["shm"] = None
    _S["tex"] = None; _S["last_seq"] = -1


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
