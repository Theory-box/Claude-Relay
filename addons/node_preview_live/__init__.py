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
_WORKER_SRC = '''import bpy, sys, os

def _setup_and_render(scene_name, out_path, samples, mode):
    scene = bpy.data.scenes[scene_name]
    dev = "CPU"; backend = ""
    try:
        scene.render.engine = "CYCLES"
        scene.cycles.samples = samples
        scene.cycles.use_denoising = False
        if mode != "CPU":
            try:
                prefs = bpy.context.preferences.addons["cycles"].preferences
                pref_type = getattr(prefs, "compute_device_type", "NONE")
                if pref_type and pref_type != "NONE":
                    candidates = [pref_type]
                else:
                    candidates = ["OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"]
                for dtype in candidates:
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
    except Exception:
        pass
    scene.render.filepath = out_path
    scene.render.use_file_extension = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    with bpy.context.temp_override(scene=scene):
        bpy.ops.render.render(write_still=True)
    return dev + ((":" + backend) if backend else "")

argv = sys.argv[sys.argv.index("--") + 1:]

if argv and argv[0] == "--serve":
    # Persistent WARM worker for live mode. Reads one job per line from stdin.
    # SAFETY - it exits on any of:
    #   * stdin EOF  -> the parent Blender died/closed the pipe (dead-man switch)
    #   * idle timeout elapses with no job
    #   * an explicit QUIT line
    import threading
    try:
        import queue
    except ImportError:
        import Queue as queue
    NL = chr(10); TAB = chr(9)
    idle = float(argv[1]) if len(argv) > 1 else 60.0
    jobs = queue.Queue()
    ended = threading.Event()

    def _reader():
        try:
            while True:
                line = sys.stdin.readline()
                if not line:
                    break            # EOF -> parent gone
                jobs.put(line.rstrip(NL))
        except Exception:
            pass
        ended.set()
        try:
            jobs.put_nowait(None)    # wake the main loop so it exits at once
        except Exception:
            pass

    threading.Thread(target=_reader, daemon=True).start()
    try:
        sys.stdout.write("READY" + NL); sys.stdout.flush()
    except Exception:
        pass

    while not ended.is_set():
        try:
            line = jobs.get(timeout=idle)
        except Exception:
            break                    # idle timeout -> exit
        if not line or line == "QUIT":
            break
        parts = line.split(TAB)
        if len(parts) < 6 or parts[0] != "RENDER":
            continue
        _, blend, scene_name, out_path, samples, mode = parts[:6]
        done = out_path + ".done"
        try:
            bpy.ops.wm.open_mainfile(filepath=blend)
            dev = _setup_and_render(scene_name, out_path, int(samples), mode)
            with open(done, "w") as f:
                f.write(dev)
        except Exception as e:
            try:
                with open(done, "w") as f:
                    f.write("ERR:" + str(e))
            except Exception:
                pass
    # falling out of the loop ends the script; blender -b then quits.
else:
    # One-shot (manual refresh): the job .blend is already loaded via the
    # command line, so render directly and write a status sidecar.
    scene_name, out_path, samples, mode, status_path = argv[0], argv[1], int(argv[2]), argv[3], argv[4]
    dev = _setup_and_render(scene_name, out_path, samples, mode)
    try:
        with open(status_path, "w") as f:
            f.write(dev)
    except Exception:
        pass
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
    "locked": False,        # when True, keep previewing the locked node
    "locked_mat": "",
    "locked_node": "",
    "last_target_key": None,  # (material_name, node_name) we last rendered
    "seen_target_key": None,  # (material_name, node_name) last noticed as active
    "last_device": "",        # what the last render actually ran on
    "worker": None,           # persistent warm worker Popen (live mode only)
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _worker_path():
    """Write the worker script to the temp dir and return its path.

    Always rewritten so an add-on update never runs a stale cached worker.
    """
    path = os.path.join(tempfile.gettempdir(), _WORKER_NAME)
    try:
        with open(path, "w") as f:
            f.write(_WORKER_SRC)
    except Exception:
        fd, path = tempfile.mkstemp(suffix=".py", prefix="np_worker_")
        with os.fdopen(fd, "w") as f:
            f.write(_WORKER_SRC)
    return path


def _get_device_mode():
    """AUTO / GPU / CPU from add-on preferences (AUTO if unavailable)."""
    try:
        return bpy.context.preferences.addons[__name__].preferences.device
    except Exception:
        return "AUTO"


# --- Warm worker (live mode only) -----------------------------------------
# A single persistent `blender -b --python worker --serve` process that stays
# up between renders to skip startup/GPU-init cost. It CANNOT outlive us:
#   * its stdin is our pipe; if we die, it hits EOF and exits (dead-man switch)
#   * it self-exits after WARM_IDLE_SECS with no job
#   * we send QUIT and kill+reap it on stop/disable/unregister

WARM_IDLE_SECS = 60

def _warm_alive():
    p = _state["worker"]
    return p is not None and p.poll() is None

def _ensure_warm_worker():
    if _warm_alive():
        return _state["worker"]
    _state["worker"] = None
    try:
        exe = bpy.app.binary_path
        worker = _worker_path()
        kwargs = dict(stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, text=True)
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        p = subprocess.Popen(
            [exe, "-b", "--python", worker, "--", "--serve", str(WARM_IDLE_SECS)],
            **kwargs)
        _state["worker"] = p
        return p
    except Exception:
        _state["worker"] = None
        return None

def _send_warm_job(blend, scene, out, samples, mode):
    p = _ensure_warm_worker()
    if p is None or p.poll() is not None:
        return False
    try:
        p.stdin.write("RENDER\t%s\t%s\t%s\t%s\t%s\n" % (blend, scene, out, samples, mode))
        p.stdin.flush()
        return True
    except Exception:
        # Pipe broke (worker died) — drop the handle so the next call respawns.
        _state["worker"] = None
        return False

def _stop_warm_worker():
    p = _state["worker"]
    _state["worker"] = None
    if p is None:
        return
    try:
        if p.poll() is None:
            try:
                p.stdin.write("QUIT\n"); p.stdin.flush()
            except Exception:
                pass
            try:
                p.stdin.close()   # also triggers the dead-man switch
            except Exception:
                pass
    except Exception:
        pass
    try:
        p.wait(timeout=3)
    except Exception:
        try:
            p.kill(); p.wait(timeout=3)
        except Exception:
            pass


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


def _resolve_target():
    """The node the preview should render: the locked one if locked, else active."""
    if _state["locked"]:
        mat = bpy.data.materials.get(_state["locked_mat"])
        if mat is None or mat.node_tree is None:
            return None, "Locked material no longer exists."
        node = mat.node_tree.nodes.get(_state["locked_node"])
        if node is None:
            return None, "Locked node was renamed or deleted — unlock to continue."
        return mat, node
    return _find_target()


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


def start_job(context, warm=False):
    """Build the temp scene, write it to a .blend, and render it.

    warm=True routes to the persistent live worker; otherwise a one-shot
    Blender is spawned. Returns (ok, message). Non-blocking either way.
    """
    if _state["job"] is not None:
        return False, "A preview render is already in progress."

    mat, node = _resolve_target()
    if mat is None:
        return False, node  # reason string

    resolution = int(context.scene.np_resolution)
    tiling = int(context.scene.np_tiling)
    samples = int(context.scene.np_samples)
    mode = _get_device_mode()
    _state["last_target_key"] = (mat.name, node.name)

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
        status = png + ".status"

        # ABSOLUTE so image textures with relative paths (Blender's default)
        # still resolve from the temp job .blend's location in the worker.
        bpy.data.libraries.write(blend, {scene}, path_remap="ABSOLUTE", fake_user=True)
    except Exception as exc:
        _remove_created(created)
        _state["busy"] = False
        return False, "Failed to prepare preview: %s" % exc
    finally:
        _remove_created(created)

    # --- Warm path (live mode): hand the job to the persistent worker ---
    if warm:
        done = png + ".done"
        try:
            if os.path.exists(done):
                os.remove(done)
        except Exception:
            pass
        if _send_warm_job(blend, JOB_SCENE_NAME, png, samples, mode):
            _state["job"] = {"warm": True, "blend": blend, "png": png, "done": done,
                             "tiling": tiling, "started": time.time()}
            _state["busy"] = False
            _state["cooldown_until"] = time.time() + 0.05
            _ensure_timer()
            return True, "Rendering preview (live)..."
        # Warm worker unavailable — fall through to a one-shot render.

    # --- One-shot path (manual, or warm fallback) ---
    try:
        exe = bpy.app.binary_path
        worker = _worker_path()
        kwargs = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        proc = subprocess.Popen(
            [exe, "-b", blend, "--python", worker, "--",
             JOB_SCENE_NAME, png, str(samples), mode, status],
            **kwargs
        )
    except Exception as exc:
        _state["busy"] = False
        try:
            os.remove(blend)
        except Exception:
            pass
        return False, "Could not launch background Blender: %s" % exc

    _state["job"] = {"warm": False, "proc": proc, "blend": blend, "png": png,
                     "status": status, "tiling": tiling, "started": time.time()}
    _state["busy"] = False
    _state["cooldown_until"] = time.time() + 0.05
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
        while n > 1 and (w * n > 8192 or h * n > 8192):
            n -= 1
        if n > 1:
            img2d = np.tile(img2d, (n, n, 1))
        out_h, out_w = img2d.shape[0], img2d.shape[1]
        flat = np.ascontiguousarray(img2d, dtype=np.float32).ravel()
    finally:
        bpy.data.images.remove(tmp)

    res_img = bpy.data.images.get(RESULT_IMAGE_NAME)
    # If the user has SAVED this preview (Save As gives the datablock a file path
    # and flips its source to FILE), Blender will later reuse it when that file is
    # opened — so their object's node ends up pointing at our preview. To prevent
    # ever overwriting a texture the user has claimed, we "release" such a
    # datablock (rename it aside) and render into a fresh, clean preview instead.
    if res_img is not None and (res_img.filepath or res_img.source != "GENERATED"):
        try:
            base = os.path.basename(res_img.filepath) if res_img.filepath else ""
            res_img.name = base if base else (RESULT_IMAGE_NAME + "_saved")
        except Exception:
            pass
        res_img = None

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

    if job.get("warm"):
        # Warm worker signals completion by writing the .done sidecar.
        if not os.path.exists(job["done"]):
            if time.time() - job["started"] > 120.0:
                # Something stuck — drop this job and recycle the worker.
                _state["last_error"] = "Preview render timed out."
                _stop_warm_worker()
                _cleanup_job_files(job)
                _state["job"] = None
                return True
            return False
        _state["busy"] = True
        try:
            try:
                with open(job["done"], "r") as f:
                    payload = f.read().strip()
            except Exception:
                payload = ""
            if payload.startswith("ERR:"):
                _state["last_error"] = "Background render failed: " + payload[4:]
            elif os.path.exists(job["png"]):
                _state["last_device"] = payload
                _store_result(job["png"], job["tiling"])
                _state["last_error"] = ""
            else:
                _state["last_error"] = "Background render produced no image."
        except Exception as exc:
            _state["last_error"] = "Loading preview failed: %s" % exc
        finally:
            _cleanup_job_files(job)
            _state["job"] = None
            _state["busy"] = False
            _state["cooldown_until"] = time.time() + 0.05
        _redraw_node_editors()
        return True

    # --- One-shot job ---
    proc = job["proc"]
    if proc.poll() is None:
        if time.time() - job["started"] > 120.0:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
            _state["last_error"] = "Preview render timed out."
            _cleanup_job_files(job)
            _state["job"] = None
            return True
        return False

    _state["busy"] = True
    try:
        try:
            with open(job["status"], "r") as f:
                _state["last_device"] = f.read().strip()
        except Exception:
            _state["last_device"] = ""
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
        _state["cooldown_until"] = time.time() + 0.05
    _redraw_node_editors()
    return True


def _cleanup_job_files(job):
    for key in ("blend", "png", "status", "done"):
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

    # 2) in live mode, react to the user switching to a different node.
    #    (Selecting a node does NOT fire a depsgraph update, so we poll for it.)
    if _state["live_on"] and not _state["locked"] and _state["job"] is None:
        mat, node = _find_target()
        if mat is not None:
            key = (mat.name, node.name)
            if key != _state["seen_target_key"]:
                _state["seen_target_key"] = key
                _state["dirty"] = True
                _state["last_change"] = time.time()

    # 3) in live mode, start a new job after a quiet period.
    if _state["live_on"] and _state["job"] is None:
        now = time.time()
        if _state["dirty"] and (now - _state["last_change"]) >= float(_debounce()):
            _state["dirty"] = False
            ok, msg = start_job(bpy.context, warm=True)
            if not ok:
                _state["last_error"] = msg
                _redraw_node_editors()

    # 4) decide whether to keep the timer alive.
    if _state["live_on"] or _state["job"] is not None:
        return 0.1
    # Live is off and nothing is in flight — release the warm worker.
    _stop_warm_worker()
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

class NodePreviewPrefs(bpy.types.AddonPreferences):
    bl_idname = __name__

    device: bpy.props.EnumProperty(
        name="Render Device",
        description="Which device the background preview render uses",
        items=[
            ("AUTO", "Auto (GPU, fall back to CPU)", "Use the GPU if available, otherwise CPU"),
            ("GPU", "GPU", "Force GPU (falls back to CPU only if none is found)"),
            ("CPU", "CPU", "Always render on CPU"),
        ],
        default="AUTO",
    )

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "device")
        col.label(text="GPU uses the backend set in Preferences > System (OptiX, Metal, etc.).",
                  icon="INFO")


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
            if _state["job"] is None:
                _stop_warm_worker()
            self.report({"INFO"}, "Live preview stopped.")
        else:
            _state["live_on"] = True
            _state["dirty"] = True
            _state["last_change"] = 0.0   # render once right away
            _state["seen_target_key"] = None
            _install_handler()
            _ensure_timer()
            self.report({"INFO"}, "Live preview started.")
        _redraw_node_editors()
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class NODEPREVIEW_OT_toggle_lock(bpy.types.Operator):
    bl_idname = "nodepreview.toggle_lock"
    bl_label = "Lock Preview to Node"
    bl_description = "Lock the preview to the current node so you can click other nodes without changing it"
    bl_options = {"REGISTER"}

    def execute(self, context):
        if _state["locked"]:
            _state["locked"] = False
            _state["locked_mat"] = ""
            _state["locked_node"] = ""
            self.report({"INFO"}, "Preview unlocked — following the active node.")
        else:
            mat, node = _find_target()
            if mat is None:
                self.report({"WARNING"}, node)  # reason string
                return {"CANCELLED"}
            _state["locked"] = True
            _state["locked_mat"] = mat.name
            _state["locked_node"] = node.name
            self.report({"INFO"}, "Preview locked to '%s'." % node.name)
        _redraw_node_editors()
        return {"FINISHED"}


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
        col.prop(scene, "np_samples")
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

        row = layout.row()
        if _state["locked"]:
            row.alert = True
            row.operator("nodepreview.toggle_lock", text="Unlock Node", icon="LOCKED")
        else:
            row.operator("nodepreview.toggle_lock", text="Lock to Node", icon="UNLOCKED")

        box = layout.box()
        if rendering:
            box.label(text="Rendering preview...", icon="SORTTIME")
        if _state["locked"]:
            box.label(text="LOCKED: " + _state["locked_node"], icon="LOCKED")
        else:
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

        dev = _state["last_device"]
        if dev:
            if dev.startswith("GPU"):
                pretty = "GPU" + (" (%s)" % dev.split(":", 1)[1] if ":" in dev else "")
                layout.label(text="Rendered on: " + pretty, icon="CHECKMARK")
            else:
                icon = "ERROR" if _get_device_mode() in ("GPU", "AUTO") else "NONE"
                layout.label(text="Rendered on: CPU", icon=icon)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = (
    NodePreviewPrefs,
    NODEPREVIEW_OT_refresh,
    NODEPREVIEW_OT_toggle_live,
    NODEPREVIEW_OT_toggle_lock,
    NODEPREVIEW_PT_panel,
)


def register():
    bpy.types.Scene.np_resolution = bpy.props.IntProperty(
        name="Resolution", description="Pixel size of the 0..1 swatch (per tile)",
        default=256, min=32, max=4096,
    )
    bpy.types.Scene.np_samples = bpy.props.IntProperty(
        name="Samples", description="Cycles samples — raise for smoother (anti-aliased) edges",
        default=1, min=1, max=256,
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
        # One-shot jobs own a process; warm jobs run in the shared worker.
        proc = job.get("proc")
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
        _cleanup_job_files(job)
        _state["job"] = None
    _stop_warm_worker()
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
    for prop in ("np_resolution", "np_samples", "np_tiling", "np_debounce"):
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)


if __name__ == "__main__":
    register()
