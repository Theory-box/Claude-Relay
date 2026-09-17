"""
auto_f12.py: runs F12 on a real scene. Does the render drain the streaming queue and include every object?

  blender.exe <file>.blend --python auto_f12.py -- <out_dir> [resolution_percent]
  env VLR_NO_SAVE=1 : required for a user's own file (never saved; exits with os._exit)
  env VLR_F12_OLD=1 : negative control. Re-creates the v0.16.0 behaviour, where _force_full is only
                      cleared when the queue drains, by removing the v0.16.1 line in memory.

Viewports are forced to Solid on load, so only the F12 engine extracts anything.
"""
import bpy, sys, os, json, time, re, textwrap, inspect, traceback, importlib
from collections import defaultdict
import numpy as np

ARGS = sys.argv[sys.argv.index('--') + 1:]
OUT_DIR = ARGS[0]
PCT = int(ARGS[1]) if len(ARGS) > 1 else 25
os.makedirs(OUT_DIR, exist_ok=True)
OLD = os.environ.get('VLR_F12_OLD') == '1'
RESULTS = os.path.join(OUT_DIR, 'f12_results.txt')
STATUS = os.path.join(OUT_DIR, 'auto_status.json')
L = []; status = {'ok': False}
T = defaultdict(float); C = defaultdict(int)
CAP = {}
PASSES = []


def log(s=''):
    print('[f12]', s); L.append(str(s))
    with open(RESULTS, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')


for _scr in bpy.data.screens:
    for _a in _scr.areas:
        if _a.type == 'VIEW_3D':
            for _s in _a.spaces:
                if _s.type == 'VIEW_3D':
                    _s.shading.type = 'SOLID'


def patch_old(E):
    """Remove v0.16.1's early `self._force_full = False` (the CONSUME IT NOW block) in memory."""
    cls = E.VertexLitEngine
    src = textwrap.dedent(inspect.getsource(cls._rebuild_inner))
    new, n = re.subn(r'\n[ \t]*# CONSUME IT NOW.*?\n[ \t]*self\._force_full = False[ \t]*(?=\n)', '', src, count=1, flags=re.S)
    if n != 1:
        raise RuntimeError('negative-control patch did not match')
    ns = {}
    exec(compile(new, E.__file__, 'exec'), E.__dict__, ns)
    cls._rebuild_inner = ns['_rebuild_inner']
    return src.count('self._force_full = False'), new.count('self._force_full = False')


def instrument(E):
    orig_t = E._get_gpu_tex

    def tw(*a, **k):
        t = time.perf_counter()
        try:
            return orig_t(*a, **k)
        finally:
            T['gpu_tex'] += time.perf_counter() - t; C['gpu_tex'] += 1
    E._get_gpu_tex = tw
    xname = '_extract_geometry' if hasattr(E, '_extract_geometry') else '_extract_mesh_data'
    orig_x = getattr(E, xname)

    def xw(*a, **k):
        t = time.perf_counter()
        try:
            return orig_x(*a, **k)
        finally:
            T['extract'] += time.perf_counter() - t; C['extract'] += 1
    setattr(E, xname, xw)
    if hasattr(E, '_geo_sig'):
        orig_s = E._geo_sig

        def sw(*a, **k):
            t = time.perf_counter()
            try:
                return orig_s(*a, **k)
            finally:
                T['geo_sig'] += time.perf_counter() - t; C['geo_sig'] += 1
        E._geo_sig = sw
    cls = E.VertexLitEngine
    rb = cls._rebuild_inner; rn = cls.render

    def rebuild_inner(self, depsgraph, vls):
        t = time.perf_counter()
        try:
            return rb(self, depsgraph, vls)
        finally:
            dt = time.perf_counter() - t
            T['rebuild'] += dt; C['rebuild'] += 1
            PASSES.append((dt, len(self._batch_dict), bool(getattr(self, '_geo_pending', False)),
                           bool(getattr(self, '_force_full', False)), C['extract']))

    def render(self, depsgraph):
        CAP['engine'] = self
        objs = set(); insts = set()
        for i in depsgraph.object_instances:
            o = i.object
            if o.type != 'MESH' or not i.show_self or not len(getattr(o.data, 'polygons', ())):
                continue              # faceless meshes have nothing to draw
            if getattr(i, 'is_instance', False):
                insts.add(E._draw_key(i))
            else:
                objs.add(o.name)
        CAP['expected'] = (objs, insts)
        t = time.perf_counter()
        try:
            return rn(self, depsgraph)
        finally:
            CAP['render_time'] = time.perf_counter() - t
            # the RenderEngine is freed as soon as render() returns -> capture its state here
            CAP['keys'] = set(self._batch_dict)
            CAP['geo_pending_after'] = bool(getattr(self, '_geo_pending', False))
    cls._rebuild_inner = rebuild_inner; cls.render = render

    def timed(meth, key):
        def w(self, *a, **k):
            t = time.perf_counter()
            try:
                return meth(self, *a, **k)
            finally:
                T[key] += time.perf_counter() - t; C[key] += 1
        return w
    for mname, key in (('_stream_textures', 'textures'), ('_draw_batches', 'draw_batches')):
        if hasattr(cls, mname):
            setattr(cls, mname, timed(getattr(cls, mname), key))
    if hasattr(E, '_RangeDraw'):
        rd = E._RangeDraw.draw

        def rdw(self, shader):
            t = time.perf_counter()
            try:
                return rd(self, shader)
            finally:
                T['range_draw'] += time.perf_counter() - t; C['range_draw'] += 1
        E._RangeDraw.draw = rdw


def run():
    try:
        if bpy.app.background:
            raise RuntimeError('--background: F12 in this engine needs the GPU context of a live session')
        if not bpy.data.filepath or ('claude' not in bpy.data.filepath.lower() and os.environ.get('VLR_NO_SAVE') != '1'):
            raise RuntimeError('refusing to run on a non-scratch file without VLR_NO_SAVE=1')
        import addon_utils
        E = importlib.import_module('vertex_lit_renderer.engine')
        ver = next((m.bl_info.get('version') for m in addon_utils.modules() if m.__name__ == 'vertex_lit_renderer'), None)
        pat = patch_old(E) if OLD else None
        instrument(E)
        scene = bpy.context.scene
        scene.render.engine = 'VERTEX_LIT'
        scene.render.resolution_percentage = PCT
        if scene.camera is None:                  # in memory only; the file is never saved
            cd = bpy.data.cameras.new('VLR_T_Cam'); co = bpy.data.objects.new('VLR_T_Cam', cd)
            co.location = (0.0, -60.0, 30.0); co.rotation_euler = (1.1, 0.0, 0.0)
            scene.collection.objects.link(co); scene.camera = co
            log("(scene had no camera: added a temporary one in memory)")
        r = scene.render
        log("F12 DRAIN TEST: addon %s%s | Blender %s | %s" % (
            ver, ' + NEGATIVE CONTROL (v0.16.0 _force_full behaviour; lines %d -> %d)' % pat if OLD else '',
            bpy.app.version_string, os.path.basename(bpy.data.filepath)))
        log("render %dx%d at %d%% | camera %s" % (r.resolution_x, r.resolution_y, PCT, scene.camera.name if scene.camera else None))
        t = time.perf_counter()
        bpy.ops.render.render()
        wall = time.perf_counter() - t
        objs, insts = CAP.get('expected', (set(), set()))
        keys = CAP.get('keys', set()); gp = CAP.get('geo_pending_after')
        mo = sorted(objs - keys); mi = sorted(insts - keys)
        log("")
        log("F12 wall %.2f s | render() %.2f s | %d rebuild passes (%.2f s) | %d extractions (%.2f s)"
            % (wall, CAP.get('render_time', -1), C['rebuild'], T['rebuild'], C['extract'], T['extract']))
        log("_geo_sig %.2f s over %d calls | rebuild time outside extraction + _geo_sig: %.2f s"
            % (T['geo_sig'], C['geo_sig'], T['rebuild'] - T['extract'] - T['geo_sig']))
        log("image -> GPU texture (_get_gpu_tex, wherever called: extraction, streaming or draw): %.2f s over %d calls"
            % (T['gpu_tex'], C['gpu_tex']))
        prof = getattr(E, '_EXTRACT_PROF', None)
        if prof:
            log("extraction stages: " + " | ".join(
                ("%s %.2f s" % (k, v)) if isinstance(v, float) else ("%s %s" % (k, v)) for k, v in prof.items()))
        if C['range_draw']:
            log("range draws (CPU time incl. first-draw uploads): %.2f s over %d calls" % (T['range_draw'], C['range_draw']))
        log("texture streaming %.2f s (%d calls) | _draw_batches %.2f s (%d calls) | render() outside rebuild+textures+draw: %.2f s"
            % (T['textures'], C['textures'], T['draw_batches'], C['draw_batches'],
               CAP.get('render_time', 0) - T['rebuild'] - T['textures'] - T['draw_batches']))
        log("expected (render depsgraph): %d mesh objects + %d unique instance meshes" % (len(objs), len(insts)))
        log("drawn: objects %d/%d | instance meshes %d/%d | _geo_pending after render: %s"
            % (len(objs) - len(mo), len(objs), len(insts) - len(mi), len(insts), gp))
        if mo or mi:
            log("MISSING (first 12): %s" % (mo + mi)[:12])
        log("RESULT: %s" % ('PASS (everything drawn, queue drained)' if 'keys' in CAP and not mo and not mi
                             and not gp else 'FAIL'))
        log("")
        log("passes (seconds, cached entries, _geo_pending, _force_full, cumulative extractions):")
        show = PASSES if len(PASSES) <= 12 else PASSES[:6] + [None] + PASSES[-5:]
        for i, p in enumerate(show):
            if p is None:
                log("   ... (%d passes omitted)" % (len(PASSES) - 11)); continue
            log("   %.3f  %4d  %-5s %-5s %d" % p)
        status.update(ok=True, wall=wall, passes=C['rebuild'], extractions=C['extract'],
                      objects=[len(objs) - len(mo), len(objs)], instances=[len(insts) - len(mi), len(insts)])
        try:
            img = bpy.data.images['Render Result']
            p = os.path.join(OUT_DIR, 'f12.png'); img.save_render(p)
            im = bpy.data.images.load(p); px = np.array(im.pixels[:], np.float32).reshape(-1, 4)
            log("saved %s: mean RGB %.4f, std %.4f" % (p, float(px[:, :3].mean()), float(px[:, :3].std())))
        except Exception as ex:
            log("render save failed: %s" % ex)
    except Exception:
        status['error'] = traceback.format_exc()
        log("!! FAILED:\n" + status['error'])
    with open(STATUS, 'w') as f:
        json.dump(status, f, indent=2)
    print('[f12] exiting without saving'); sys.stdout.flush()
    os._exit(0)


bpy.app.timers.register(run, first_interval=5.0)
