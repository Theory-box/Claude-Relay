"""
auto_bench_quinn.py — unattended splat benchmark. Launch a LIVE (not --background) Blender on a
THROWAWAY COPY of a .blend that contains the Quinn mesh:

  blender.exe <copy>.blend --python auto_bench_quinn.py -- <out_dir> <path/to/benchmark_splats.py>

Once the UI + GPU context are up it: sets the Vertex-Lit engine, converts SKM_Quinn_LOD0 to splats
(Surfel, 200k, Texture colour, Scene Lighting on, GPU sort off, source mesh hidden), puts the first 3D
viewport in Rendered + Perspective framed on the splats, runs benchmark_splats.main(), writes
<out_dir>/splat_benchmark_results.txt + <out_dir>/auto_status.json, saves the COPY and quits.
"""
import bpy, sys, os, json, time, math, traceback, importlib.util
from mathutils import Euler

ARGS = sys.argv[sys.argv.index('--') + 1:]
OUT_DIR, BENCH = ARGS[0], ARGS[1]
STATUS = os.path.join(OUT_DIR, 'auto_status.json')
RESULTS = os.path.join(OUT_DIR, 'splat_benchmark_results.txt')
QUINN = 'SKM_Quinn_LOD0'
status = {'steps': [], 'ok': False}


def step(msg):
    print('[auto]', msg)
    status['steps'].append(msg)


def _load_bench():
    spec = importlib.util.spec_from_file_location('benchmark_splats', BENCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run():
    try:
        if bpy.app.background:
            raise RuntimeError('running in --background: no GPU drawing, benchmark impossible')
        if not bpy.data.filepath or 'config' in os.path.dirname(bpy.data.filepath).lower():
            raise RuntimeError('refusing to run on a non-copy file: %r' % bpy.data.filepath)
        bench = _load_bench()
        scene = bpy.context.scene
        step('file %s | %d objects (%d meshes)' % (bpy.data.filepath, len(scene.objects),
             sum(o.type == 'MESH' for o in scene.objects)))

        scene.render.engine = 'VERTEX_LIT'
        step('render engine = %s' % scene.render.engine)

        q = bpy.data.objects.get(QUINN) or next(
            (o for o in scene.objects if o.type == 'MESH' and 'quinn' in o.name.lower()), None)
        if q is None:
            raise RuntimeError('no Quinn mesh; meshes: %s' % [o.name for o in scene.objects if o.type == 'MESH'][:40])
        step('source %s: %d verts, %d faces, materials %s, dims %s' % (
            q.name, len(q.data.vertices), len(q.data.polygons),
            [s.material.name if s.material else None for s in q.material_slots],
            tuple(round(d, 3) for d in q.dimensions)))

        v = bench._find_view3d()
        if v is None:
            raise RuntimeError('no VIEW_3D area in this file\'s UI')
        win, area, region, rv3d = v
        space = area.spaces.active
        ovr = dict(window=win, area=area, region=region)

        with bpy.context.temp_override(**ovr):
            if bpy.context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
        vls = scene.vertex_lit
        vls.splat_method = 'SURFEL'; vls.splat_count = 200000; vls.splat_color = 'TEXTURE'
        vls.splat_lit = True; vls.splat_gpu_sort = False; vls.splat_hide_src = True
        vls.splat_compute = False; vls.splat_tile = False; vls.splat_backface = False
        q.hide_set(False)
        for o in bpy.context.view_layer.objects:
            if o.select_get(): o.select_set(False)
        q.select_set(True); bpy.context.view_layer.objects.active = q
        t = time.perf_counter()
        with bpy.context.temp_override(active_object=q, object=q, selected_objects=[q], **ovr):
            r = bpy.ops.vertex_lit.generate_splats()
        step('generate_splats -> %s in %.1fs' % (set(r), time.perf_counter() - t))

        sr = bench._splat_render_module()
        if sr is None or not sr.SPLAT_CLOUDS:
            raise RuntimeError('SPLAT_CLOUDS is empty after conversion')
        step('SPLAT_CLOUDS: %s' % {k: int(c.d['count']) for k, c in sr.SPLAT_CLOUDS.items()})

        space.shading.type = 'RENDERED'
        rv3d.view_perspective = 'PERSP'
        rv3d.view_rotation = Euler((math.radians(80), 0.0, math.radians(20))).to_quaternion()
        with bpy.context.temp_override(**ovr):
            bpy.ops.wm.redraw_timer(type='DRAW', iterations=3)   # engine up, window_matrix valid
        anchors = bench.visible_anchors()
        lo, hi = bench.splat_bounds(anchors)
        d_fill = bench.fill_distance(rv3d, lo, hi)
        rv3d.view_location = (lo + hi) * 0.5
        rv3d.view_distance = d_fill * 1.6
        space.clip_end = max(space.clip_end, d_fill * 50.0)
        with bpy.context.temp_override(**ovr):
            bpy.ops.wm.redraw_timer(type='DRAW', iterations=10)
        step('viewport %dx%d shading=%s persp=%s anchors=%d fill_dist=%.3f' % (
            region.width, region.height, space.shading.type, rv3d.is_perspective, len(anchors), d_fill))

        with bpy.context.temp_override(**ovr):
            path = bench.main(RESULTS)
        step('benchmark written to %s' % path)
        status['ok'] = True
    except Exception:
        status['error'] = traceback.format_exc()
        print(status['error'])
    with open(STATUS, 'w') as f:
        json.dump(status, f, indent=2)
    try:
        bpy.ops.wm.save_mainfile()   # the throwaway copy: clears the dirty flag so quit won't prompt
    except Exception as e:
        print('[auto] save copy failed:', e)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=5.0)
