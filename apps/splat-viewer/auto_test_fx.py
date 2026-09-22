"""
auto_test_fx.py -- cost of the screen-space effects (Cavity World / Cavity Screen / Outline) on a HEAVY
mesh scene, and the image they produce. Run the SAME script against two installed addon versions and
diff the results to prove a change is free of visual difference.

  blender.exe <scratch .blend with 'claude' in the name> --python auto_test_fx.py -- <out_dir> <benchmark_splats.py>
  env VLR_OBJ   objects in the generated scene (default 200)
  env VLR_SUB   ico-sphere subdivisions per object (default 5 ~ 20k tris each)
  env VLR_TAG   label for the output files (e.g. the addon version)

Per configuration (effects off / cavity screen / cavity world / both / both+outline):
  - median viewport frame time while orbiting
  - the engine's final image, saved as .npy + .png for a cross-version diff
Writes fx_results.txt + auto_status.json. Never saves the .blend.
"""
import bpy, sys, os, json, time, math, statistics, traceback, importlib, importlib.util
import numpy as np
from mathutils import Euler, Quaternion, Vector

ARGS = sys.argv[sys.argv.index('--') + 1:]
OUT_DIR, BENCH = ARGS[0], ARGS[1]
os.makedirs(OUT_DIR, exist_ok=True)
N_OBJ = int(os.environ.get('VLR_OBJ', '200'))
SUBDIV = int(os.environ.get('VLR_SUB', '5'))
TAG = os.environ.get('VLR_TAG', 'cur')
ORBIT_FRAMES, ORBIT_STEP = 12, 3.0
RESULTS = os.path.join(OUT_DIR, 'fx_results.txt'); STATUS = os.path.join(OUT_DIR, 'auto_status.json')
status = {'ok': False, 'tag': TAG, 'configs': {}}
L = []; bench = None
_GRAB = {'want': False, 'img': None}

CONFIGS = [
    ('effects off',   dict(use_ao=False, use_cavity=False, use_outline=False)),
    ('cavity screen', dict(use_ao=False, use_cavity=True,  use_outline=False)),
    ('cavity world',  dict(use_ao=True,  use_cavity=False, use_outline=False)),
    ('both cavities', dict(use_ao=True,  use_cavity=True,  use_outline=False)),
    ('both + outline', dict(use_ao=True, use_cavity=True,  use_outline=True)),
]


def log(s=''):
    print('[fx]', s); L.append(str(s))
    with open(RESULTS, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')


def _view():
    return bench._find_view3d()


def draws(n):
    win, area, region, rv3d = _view()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.redraw_timer(type='DRAW', iterations=n)
    bench._gpu_sync()


def orbit_ms():
    win, area, region, rv3d = _view()
    base = rv3d.view_rotation.copy(); ts = []
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.redraw_timer(type='DRAW', iterations=3); bench._gpu_sync()
        for i in range(ORBIT_FRAMES):
            rv3d.view_rotation = Quaternion((0.0, 0.0, 1.0), math.radians(ORBIT_STEP * (i + 1))) @ base
            t = time.perf_counter()
            bpy.ops.wm.redraw_timer(type='DRAW', iterations=1); bench._gpu_sync()
            ts.append((time.perf_counter() - t) * 1000.0)
        rv3d.view_rotation = base
        bpy.ops.wm.redraw_timer(type='DRAW', iterations=1)
    bench._gpu_sync()
    return statistics.median(ts)


_TIMES = {'scene': [], 'total': []}


def _sync():
    """Block until the GPU caught up, without binding anything (safe inside a bound framebuffer)."""
    import gpu
    try:
        fb = gpu.state.active_framebuffer_get()
        fb.read_color(0, 0, 1, 1, 4, 0, 'FLOAT')
    except Exception:
        pass


def install_grabber():
    """Observation only: time the pipeline (scene draw vs everything else) and keep its final image."""
    P = importlib.import_module('vertex_lit_renderer.fx.pipeline').Pipeline
    orig = P.render

    def rec(self, w, h, draw_scene, ctx, vls, blit=True):
        def timed_scene():
            _sync(); t = time.perf_counter()
            draw_scene()
            _sync(); _TIMES['scene'].append((time.perf_counter() - t) * 1000.0)
        _sync(); t0 = time.perf_counter()
        r = orig(self, w, h, timed_scene, ctx, vls, blit=blit)
        _sync(); _TIMES['total'].append((time.perf_counter() - t0) * 1000.0)
        if False:
            pass
        if _GRAB['want'] and isinstance(r, tuple):
            tex = r[0]
            buf = tex.read(); buf.dimensions = tex.width * tex.height * 4
            _GRAB['img'] = np.array(buf, dtype=np.float32).reshape(tex.height, tex.width, 4)
            _GRAB['want'] = False
        return r
    P.render = rec


def shot(name):
    draws(8)          # let a still view settle (temporal effects refine over a few frames)
    _GRAB['want'] = True; _GRAB['img'] = None
    draws(1)
    if _GRAB['img'] is None:
        return None
    img = _GRAB['img'][..., :3].copy()
    np.save(os.path.join(OUT_DIR, name + '.npy'), img)
    h, w, _ = img.shape
    im = bpy.data.images.new('fx_grab', w, h, alpha=True, float_buffer=True)
    rgba = np.concatenate([np.clip(img, 0, 1), np.ones((h, w, 1), np.float32)], axis=-1)
    im.pixels.foreach_set(np.ascontiguousarray(rgba).ravel())
    im.filepath_raw = os.path.join(OUT_DIR, name + '.png'); im.file_format = 'PNG'; im.save()
    bpy.data.images.remove(im)
    return img


def build_scene():
    """A heavy mesh scene: many separate objects (each extracted + drawn on its own)."""
    scene = bpy.context.scene
    for o in [o for o in scene.objects if o.name.startswith('fx_')]:
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=SUBDIV, radius=0.5, location=(0, 0, -1000))
    src = bpy.context.active_object; src.name = 'fx_src'
    me = src.data
    tris = len(me.polygons)
    cols = int(math.ceil(math.sqrt(N_OBJ)))
    for k in range(N_OBJ):
        ob = bpy.data.objects.new('fx_obj_%d' % k, me)          # shared mesh, own object + transform
        ob.location = ((k % cols) * 1.3, (k // cols) * 1.3, 0.0)
        scene.collection.objects.link(ob)
    bpy.data.objects.remove(src, do_unlink=True)
    return N_OBJ, tris


def frame_view():
    win, area, region, rv3d = _view()
    objs = [o for o in bpy.context.scene.objects if o.name.startswith('fx_obj')]
    lo = Vector((1e30,) * 3); hi = Vector((-1e30,) * 3)
    for o in objs:
        for c in o.bound_box:
            p = o.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, p)); hi = Vector(map(max, hi, p))
    rv3d.view_location = (lo + hi) * 0.5
    rv3d.view_distance = bench.fill_distance(rv3d, lo, hi) * 0.9
    area.spaces.active.clip_end = max(area.spaces.active.clip_end, 1000.0)


def run():
    global bench
    try:
        if bpy.app.background:
            raise RuntimeError('needs a live GPU session')
        if not bpy.data.filepath or 'claude' not in bpy.data.filepath.lower():
            raise RuntimeError('refusing to run on a non-scratch file: %r' % bpy.data.filepath)
        spec = importlib.util.spec_from_file_location('benchmark_splats', BENCH)
        bench = importlib.util.module_from_spec(spec); spec.loader.exec_module(bench)
        scene = bpy.context.scene; vls = scene.vertex_lit
        scene.render.engine = 'VERTEX_LIT'
        import addon_utils
        ver = next((m.bl_info.get('version') for m in addon_utils.modules() if m.__name__ == 'vertex_lit_renderer'), None)
        # hide everything that was already in the file; this test is about meshes only
        for o in scene.objects:
            if not o.name.startswith('fx_'):
                try: o.hide_set(True)
                except Exception: pass
        n, tris = build_scene()
        win, area, region, rv3d = _view()
        area.spaces.active.shading.type = 'RENDERED'; rv3d.view_perspective = 'PERSP'
        area.spaces.active.overlay.show_overlays = False
        rv3d.view_rotation = Euler((math.radians(65), 0.0, math.radians(25))).to_quaternion()
        frame_view()
        install_grabber()
        log('SCREEN-SPACE EFFECTS COST | addon %s | tag %s | Blender %s | %s'
            % (ver, TAG, bpy.app.version_string, bench.detect_caps()['gpu']))
        log('scene: %d objects x %d tris = %.1fM tris | viewport %dx%d | supersampling %s'
            % (n, tris, n * tris / 1e6, region.width, region.height, getattr(vls, 'supersampling', '1')))
        log('')
        if os.environ.get('VLR_SS'):
            vls.supersampling = os.environ['VLR_SS']
        if os.environ.get('VLR_AOQ'):
            vls.ao_samples = os.environ['VLR_AOQ']
        log('  supersampling %s | ao_samples %s' % (getattr(vls, 'supersampling', '1'), getattr(vls, 'ao_samples', '?')))
        draws(6)
        base = None
        for name, cfg in CONFIGS:
            for k, v in cfg.items():
                setattr(vls, k, v)
            draws(4)
            _TIMES['scene'].clear(); _TIMES['total'].clear()
            ms = orbit_ms()
            fx_ms = 0.0
            if _TIMES['total'] and len(_TIMES['total']) == len(_TIMES['scene']):
                d = [t - sc for t, sc in zip(_TIMES['total'], _TIMES['scene'])]
                d.sort(); fx_ms = d[len(d) // 2]
            img = shot('%s_%s' % (TAG, name.replace(' ', '_').replace('+', 'plus')))
            if base is None:
                base = ms
            status['configs'][name] = {'frame_ms': ms, 'fx_ms': fx_ms}
            log('  %-15s frame %7.2f ms | effects+aux passes %6.2f ms' % (name, ms, fx_ms))
        status['ok'] = True
    except Exception:
        status['error'] = traceback.format_exc(); log('!! FAILED:\n' + status['error'])
    with open(STATUS, 'w') as f:
        json.dump(status, f, indent=2, default=str)
    sys.stdout.flush()
    os._exit(0)


bpy.app.timers.register(run, first_interval=4.0)
