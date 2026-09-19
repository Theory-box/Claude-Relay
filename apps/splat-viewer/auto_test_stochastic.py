"""
auto_test_stochastic.py -- unattended check of the v0.16.8 "Stochastic Splats" toggle in the REAL viewport.
Launch a LIVE Blender on a THROWAWAY COPY of a tree .blend:

  blender.exe <copy>.blend --python auto_test_stochastic.py -- <out_dir> <benchmark_splats.py> [per_tree x trees,...]

Per scene (default 1000000x1,1000000x16), with a cube placed in front of part of the trees:
  1. the stochastic path really runs (renderer calls counted, no fallback) and reaches its refinement cap
  2. image: engine screenshot, sorted (toggle OFF) vs stochastic (ON, still view refined) -> mean diff / PSNR
  3. occlusion: the cube must hide the splats behind it exactly as in the sorted image (diff inside cube area)
  4. speed: orbiting redraw time OFF vs ON (whole viewport frame, meshes + splats)
  5. Backface Cull + stochastic runs without error
Writes stochastic_test.txt + auto_status.json + PNGs to <out_dir>, never saves the file, quits.
"""
import bpy, sys, os, json, time, math, statistics, traceback, importlib.util, importlib
import numpy as np
from mathutils import Euler, Quaternion, Vector, Matrix

ARGS = sys.argv[sys.argv.index('--') + 1:]
OUT_DIR, BENCH = ARGS[0], ARGS[1]
SCENES = [tuple(int(v) for v in s.split('x')) for s in (ARGS[2] if len(ARGS) > 2 else '1000000x1,1000000x16').split(',')]
os.makedirs(OUT_DIR, exist_ok=True)
RESULTS = os.path.join(OUT_DIR, 'stochastic_test.txt'); STATUS = os.path.join(OUT_DIR, 'auto_status.json')
ORBIT_FRAMES, ORBIT_STEP = 16, 3.0
status = {'ok': False, 'scenes': []}
L = []; bench = None
_GRAB = {'want': False, 'img': None, 'handle': None}


def log(s=''):
    print('[stoch-test]', s); L.append(str(s))
    with open(RESULTS, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')


def _mod(suffix):
    return importlib.import_module('vertex_lit_renderer.' + suffix)


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


def install_grabber():
    """Observation only: wrap the effects pipeline's render() to keep the engine's final image texture."""
    P = importlib.import_module('vertex_lit_renderer.fx.pipeline').Pipeline
    orig = P.render

    def rec(self, w, h, draw_scene, ctx, vls, blit=True):
        r = orig(self, w, h, draw_scene, ctx, vls, blit=blit)
        if _GRAB['want'] and isinstance(r, tuple):
            tex = r[0]
            buf = tex.read(); buf.dimensions = tex.width * tex.height * 4
            _GRAB['img'] = np.array(buf, dtype=np.float32).reshape(tex.height, tex.width, 4)
            _GRAB['want'] = False
        return r
    P.render = rec


def shot(name):
    _GRAB['want'] = True; _GRAB['img'] = None
    draws(1)
    if _GRAB['img'] is None:
        raise RuntimeError('viewport grab failed')
    img = _GRAB['img'].copy(); img[..., 3] = 1.0
    h, w, _ = img.shape
    im = bpy.data.images.new('vlr_grab', w, h, alpha=True, float_buffer=True)
    im.pixels.foreach_set(np.ascontiguousarray(img).ravel())
    im.filepath_raw = os.path.join(OUT_DIR, name); im.file_format = 'PNG'; im.save(); bpy.data.images.remove(im)
    return img[..., :3].copy()


def psnr(a, b, mask=None):
    d = (np.clip(a, 0, 1) - np.clip(b, 0, 1)) ** 2
    if mask is not None:
        d = d[mask]
    mse = float(d.mean()) if d.size else 0.0
    return 99.0 if mse <= 0 else 10 * math.log10(1.0 / mse)


def convert(tree, count):
    vls = bpy.context.scene.vertex_lit
    win, area, region, rv3d = _view()
    vls.splat_method = 'SURFEL'; vls.splat_count = int(count); vls.splat_color = 'TEXTURE'
    vls.splat_lit = True; vls.splat_hide_src = True; vls.splat_sigma = 2.2
    tree.hide_set(False)
    for o in bpy.context.view_layer.objects:
        if o.select_get(): o.select_set(False)
    tree.select_set(True); bpy.context.view_layer.objects.active = tree
    with bpy.context.temp_override(window=win, area=area, region=region, active_object=tree, object=tree,
                                   selected_objects=[tree]):
        bpy.ops.vertex_lit.generate_splats()
    return bpy.context.view_layer.objects.active


def make_grid(anchor, n, spacing=5.0):
    """Extra anchors (Empties sharing the cloud id) on a grid -- what Shift+D on the anchor gives."""
    cols = int(math.ceil(math.sqrt(n))); out = [anchor]
    for k in range(1, n):
        e = bpy.data.objects.new('stoch_test_anchor_%d' % k, None)
        e['vlr_splat_id'] = anchor['vlr_splat_id']
        e.matrix_world = Matrix.Translation(Vector(((k % cols) * spacing, (k // cols) * spacing, 0.0))) @ anchor.matrix_world
        bpy.context.scene.collection.objects.link(e); out.append(e)
    return out


def frame_view(anchors):
    win, area, region, rv3d = _view()
    cl = _mod("splat_render").SPLAT_CLOUDS[int(anchors[0]["vlr_splat_id"])]
    lo, hi = bench.splat_bounds([(o, cl) for o in anchors])
    rv3d.view_location = (lo + hi) * 0.5; rv3d.view_distance = bench.fill_distance(rv3d, lo, hi) * 0.9
    area.spaces.active.clip_end = max(area.spaces.active.clip_end, 1000.0)
    return lo, hi


def add_cube(lo, hi):
    """A cube between the camera and the trees' centre, covering part of the view."""
    win, area, region, rv3d = _view()
    c = (lo + hi) * 0.5; cam = rv3d.view_matrix.inverted().translation
    p = c + (cam - c) * 0.35
    me = bpy.data.meshes.new('stoch_test_cube_me')
    s = (hi - lo).length * 0.06
    v = [(x * s, y * s, z * s) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    me.from_pydata(v, [], f); me.update()
    ob = bpy.data.objects.new('stoch_test_cube', me); ob.location = p
    bpy.context.scene.collection.objects.link(ob)
    return ob


def cube_mask(cube):
    """Screen pixels covered by the cube (from a grab with everything else hidden)."""
    vls = bpy.context.scene.vertex_lit
    hidden = [o for o in bpy.context.scene.objects if o is not cube and not o.hide_get()]
    for o in hidden: o.hide_set(True)
    draws(2)
    a = shot('cube_only.png')
    for o in hidden: o.hide_set(False)
    draws(2)
    wc = bpy.context.scene.world.color if bpy.context.scene.world else (0.05, 0.05, 0.05)
    return np.abs(a - np.array(wc)[None, None, :3]).max(axis=2) > 0.02


def run_scene(tree, per_tree, n_trees):
    vls = bpy.context.scene.vertex_lit
    SS = _mod('splat_stochastic')
    for o in [o for o in bpy.data.objects if o.name.startswith('stoch_test_') or o.get('vlr_splat_id') is not None]:
        bpy.data.objects.remove(o, do_unlink=True)
    anchor = convert(tree, per_tree)
    anchors = make_grid(anchor, n_trees)
    tag = '%dx%dk' % (n_trees, per_tree // 1000)
    log(''); log('=' * 90); log('SCENE %d x %d = %.1fM splats' % (n_trees, per_tree, n_trees * per_tree / 1e6)); log('=' * 90)
    lo, hi = frame_view(anchors)
    cube = add_cube(lo, hi)
    rec = {'scene': tag}
    mask = cube_mask(cube)
    log('  cube covers %.1f%% of the view' % (100 * float(mask.mean())))
    # ---- sorted (OFF)
    vls.splat_stochastic = False; draws(4)
    ref = shot('sorted_%s.png' % tag)
    rec['off_ms'] = orbit_ms()
    # ---- stochastic (ON)
    vls.splat_stochastic = True
    R = None; calls = {'n': 0, 'more': 0}
    draws(2)
    R = SS.get()
    if R is None:
        raise RuntimeError('stochastic renderer failed to build')
    orig = R.render

    def counted(*a, **k):
        calls['n'] += 1; r = orig(*a, **k)
        if r: calls['more'] += 1
        return r
    R.render = counted
    try:
        rec['on_ms'] = orbit_ms()
        n0 = calls['n']
        one = None
        # still view: first frame after a change, then let it refine (the engine tags redraws itself;
        # here we drive redraws explicitly) and count how many frames it asks for
        win, area, region, rv3d = _view()
        rv3d.view_rotation = rv3d.view_rotation.copy()          # same view
        bpy.context.scene.vertex_lit.splat_backface = bpy.context.scene.vertex_lit.splat_backface
        R.key = None                                            # force a restart of the refinement
        one = shot('stoch_1frame_%s.png' % tag)
        asked = 0
        for i in range(60):
            m0 = calls['more']; draws(1)
            if calls['more'] == m0: break
            asked += 1
        conv = shot('stoch_refined_%s.png' % tag)
        rec['refine_frames'] = R.acc_n
        rec['calls'] = calls['n'] - n0
        # Backface Cull on/off still runs
        vls.splat_backface = True; draws(3); bf = shot('stoch_backface_%s.png' % tag); vls.splat_backface = False; draws(2)
        rec['backface_ok'] = bool(np.isfinite(bf).all())
    finally:
        R.render = orig
        vls.splat_stochastic = False
    notmask = ~mask
    rec['psnr_1'] = psnr(one, ref); rec['psnr_ref'] = psnr(conv, ref)
    rec['psnr_cube'] = psnr(conv, ref, mask) if mask.any() else None
    rec['diff_mean'] = float(np.abs(conv - ref).max(axis=2).mean())
    rec['diff_pct'] = 100.0 * float((np.abs(conv - ref).max(axis=2) > 0.05).mean())
    log('  path: stochastic renderer calls during test %d, refinement frames reached %d/%d, fallback flag %s'
        % (rec['calls'], rec['refine_frames'], SS.ACCUM_FRAMES, SS._FAILED[0]))
    log('  image vs sorted: 1 frame %.1f dB | refined %.1f dB | mean |d| %.4f | px >5%% diff %.2f%%'
        % (rec['psnr_1'], rec['psnr_ref'], rec['diff_mean'], rec['diff_pct']))
    log('  cube area (mesh occlusion): refined vs sorted %s dB' % ('%.1f' % rec['psnr_cube'] if rec['psnr_cube'] is not None else 'n/a'))
    log('  orbit (whole viewport frame): sorted %.2f ms | stochastic %.2f ms | %.2fx'
        % (rec['off_ms'], rec['on_ms'], rec['off_ms'] / rec['on_ms']))
    log('  backface cull + stochastic: %s' % ('ok' if rec['backface_ok'] else 'BAD'))
    status['scenes'].append(rec)


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
        log('STOCHASTIC SPLATS TOGGLE TEST | addon %s | Blender %s | %s' % (ver, bpy.app.version_string, bench.detect_caps()['gpu']))
        rna = vls.bl_rna.properties.get('splat_stochastic')
        log('  property: %s | default %s | tooltip: %s' % (rna.name if rna else 'MISSING', rna.default if rna else '-',
                                                          rna.description if rna else '-'))
        tree = max((o for o in scene.objects if o.type == 'MESH'), key=lambda o: len(o.data.polygons))
        win, area, region, rv3d = _view()
        area.spaces.active.shading.type = 'RENDERED'; rv3d.view_perspective = 'PERSP'
        ov = area.spaces.active.overlay; ov.show_overlays = False
        rv3d.view_rotation = Euler((math.radians(72), 0.0, math.radians(20))).to_quaternion()
        vls.splat_gpu_sort = True; vls.splat_radix = True; vls.splat_unified = True
        log('  viewport %dx%d, sorted path = GPU radix sort + unified' % (region.width, region.height))
        install_grabber()
        for per_tree, n in SCENES:
            try:
                run_scene(tree, per_tree, n)
            except Exception:
                log('  SCENE FAILED:\n' + traceback.format_exc())
        status['ok'] = True
    except Exception:
        status['error'] = traceback.format_exc(); log('!! FAILED:\n' + status['error'])
    with open(STATUS, 'w') as f:
        json.dump(status, f, indent=2, default=str)
    sys.stdout.flush()
    os._exit(0)


bpy.app.timers.register(run, first_interval=4.0)
