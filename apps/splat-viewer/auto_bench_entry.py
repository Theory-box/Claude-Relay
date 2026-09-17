"""
auto_bench_entry.py — where does the time go when a scene enters the Vertex-Lit Rendered view?
Launch a LIVE Blender on a THROWAWAY COPY of a .blend:

  blender.exe <copy>.blend --python auto_bench_entry.py -- <out_dir> <benchmark_splats.py>

Instrumentation only (in-memory wrappers around the engine's own functions; installed files untouched).
Measures, frame by frame, from switching the viewport to RENDERED until geometry streaming and the
progressive material compile are both finished:
  * COLD   first entry in a fresh session (nothing cached)
  * WARM   leave to Solid and re-enter (persisted batches + compiled shaders reused)
  * GEO-COLD  persisted geometry cleared, compiled shaders kept (isolates the geometry share)
and splits the time into mesh extraction / batch_for_shader (CPU vertex-buffer fill) / material
compile / everything else (drawing the partially loaded scene each frame, Python overhead).
Then an A/B of the batch build on the scene's REAL extracted data:
  A  batch_for_shader (current)          B  format computed once + attr_fill(numpy) + GPUBatch
  C  format once + attr_fill(gpu.types.Buffer filled by memcpy)
build time and first-draw (GPU upload) time measured separately; A/B/C images compared with a
shader that consumes all four attributes. Writes entry_results.txt, saves the COPY, quits.
"""
import bpy, sys, os, json, time, math, statistics, traceback, importlib, importlib.util
from collections import defaultdict
import numpy as np

ARGS = sys.argv[sys.argv.index('--') + 1:]
OUT_DIR, BENCH = ARGS[0], ARGS[1]
RESULTS = os.path.join(OUT_DIR, 'entry_results.txt')
STATUS = os.path.join(OUT_DIR, 'auto_status.json')
status = {'steps': [], 'ok': False}
L = []
bench = None
T = defaultdict(float); C = defaultdict(int)
CAP = {'engine': None, 'frame_ms': []}


def log(s=''):
    print('[entry]', s); L.append(str(s))
    with open(RESULTS, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')


# Keep the engine from starting before we measure: put every 3D view in Solid right away.
for _scr in bpy.data.screens:
    for _a in _scr.areas:
        if _a.type == 'VIEW_3D':
            for _s in _a.spaces:
                if _s.type == 'VIEW_3D':
                    _s.shading.type = 'SOLID'


def _view():
    return bench._find_view3d()


def draw1():
    win, area, region, rv3d = _view()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.redraw_timer(type='DRAW', iterations=1)
    bench._gpu_sync()


# ───────────────────────── instrumentation (timing wrappers only) ─────────────────────────
def instrument():
    E = importlib.import_module('vertex_lit_renderer.engine')
    MS = importlib.import_module('vertex_lit_renderer.material_shader')

    def wrap(mod, name, key):
        orig = getattr(mod, name)

        def w(*a, **k):
            t = time.perf_counter()
            try:
                return orig(*a, **k)
            finally:
                T[key] += time.perf_counter() - t; C[key] += 1
        w._orig = orig
        setattr(mod, name, w)
    if hasattr(E, '_extract_geometry'):
        wrap(E, '_extract_mesh_data', 'extract_legacy')
        wrap(E, '_extract_geometry', 'extract')     # v0.16.5+ load path
    else:
        wrap(E, '_extract_mesh_data', 'extract')
    wrap(E, 'batch_for_shader', 'batch_for_shader')
    wrap(E, '_build_object_slots', 'build_slots')
    wrap(E, '_build_shadow_batch_from_cache', 'shadow_batch')
    wrap(MS, '_compile', 'mat_compile')
    wrap(E, '_get_gpu_tex', 'gpu_tex')          # image -> GPU texture (called inside extraction)
    if hasattr(E, '_geo_sig'):
        wrap(E, '_geo_sig', 'geo_sig')          # change-detection signature (full-buffer hash since v0.16.1)
    cls = E.VertexLitEngine
    vd = cls.view_draw; rb = cls._rebuild_inner

    def view_draw(self, context, depsgraph):
        CAP['engine'] = self
        t = time.perf_counter()
        try:
            return vd(self, context, depsgraph)
        finally:
            T['view_draw'] += time.perf_counter() - t; C['view_draw'] += 1

    def rebuild_inner(self, depsgraph, vls):
        t = time.perf_counter()
        try:
            return rb(self, depsgraph, vls)
        finally:
            T['rebuild'] += time.perf_counter() - t; C['rebuild'] += 1
    cls.view_draw = view_draw
    cls._rebuild_inner = rebuild_inner
    return E, MS


def scene_stats(E):
    eng = CAP['engine']
    objs = len(getattr(eng, '_batch_dict', {})) if eng else 0
    tris = 0; slots = 0; uniq = set()
    for name, data in (getattr(eng, '_mesh_cache', {}) or {}).items():
        if id(data) in uniq:
            continue
        uniq.add(id(data))
        if 'ranges' in data:                        # v0.16.5+ shared buffers + material ranges
            tris += int(data.get('n_tris', 0)); slots += len(data['ranges'])
            continue
        for s in data.get('slots', []):
            tris += len(s['positions']) // 3; slots += 1
    return objs, len(uniq), slots, tris


def enter(label, E, max_s=600.0):
    """Switch the view to RENDERED and drive frames until geometry + materials are fully loaded."""
    for k in list(T.keys()): T[k] = 0.0
    for k in list(C.keys()): C[k] = 0
    win, area, region, rv3d = _view()
    space = area.spaces.active
    CAP['engine'] = None
    space.shading.type = 'RENDERED'
    frames = []; t0 = time.perf_counter(); geo_done = None; mat_done = None
    while True:
        t = time.perf_counter(); draw1(); frames.append((time.perf_counter() - t) * 1000.0)
        eng = CAP['engine']
        el = time.perf_counter() - t0
        if eng is not None:
            gp = bool(getattr(eng, '_geo_pending', False)) or bool(getattr(eng, '_dirty', False))
            mp = bool(getattr(eng, '_mat_pending', False)) or bool(getattr(eng, '_tex_pending', False))
            if not gp and geo_done is None: geo_done = (el, len(frames))
            if not gp and not mp and mat_done is None:
                mat_done = (el, len(frames)); break
        if el > max_s:
            break
    total = time.perf_counter() - t0
    objs, uniq, slots, tris = scene_stats(E)
    tt = {k: T[k] * 1000.0 for k in T}
    other = total * 1000.0 - tt.get('rebuild', 0) - tt.get('mat_compile', 0)
    log("")
    log("%s ENTRY: %.2f s total over %d frames (first frame %.0f ms, median frame %.0f ms)"
        % (label, total, len(frames), frames[0], statistics.median(frames)))
    log("  geometry complete at %s | materials complete at %s"
        % ("%.2f s (frame %d)" % geo_done if geo_done else "never", "%.2f s (frame %d)" % mat_done if mat_done else "never (timeout)"))
    log("  loaded: %d objects drawn, %d unique extracted meshes, %d material slots, %.2fM triangles"
        % (objs, uniq, slots, tris / 1e6))
    log("  time split (s):  extraction %.2f (%d calls) | batch_for_shader %.2f (%d calls) | material compile %.2f (%d) | "
        "rest of rebuild %.2f | everything else (drawing partial scene each frame, overhead) %.2f"
        % (tt.get('extract', 0) / 1000, C['extract'], tt.get('batch_for_shader', 0) / 1000, C['batch_for_shader'],
           tt.get('mat_compile', 0) / 1000, C['mat_compile'],
           (tt.get('rebuild', 0) - tt.get('extract', 0) - tt.get('build_slots', 0)) / 1000, other / 1000))
    log("  shares of total: extraction %.0f%% | batch build %.0f%% | material compile %.0f%% | other %.0f%%"
        % tuple(100.0 * x / max(total * 1000.0, 1e-9) for x in
                (tt.get('extract', 0), tt.get('build_slots', 0), tt.get('mat_compile', 0),
                 total * 1000.0 - tt.get('extract', 0) - tt.get('build_slots', 0) - tt.get('mat_compile', 0))))
    log("  image -> GPU texture (inside extraction): %.2f s over %d calls" % (tt.get('gpu_tex', 0) / 1000, C['gpu_tex']))
    log("  _geo_sig (change-detection signature): %.2f s over %d calls" % (tt.get('geo_sig', 0) / 1000, C['geo_sig']))
    vd = tt.get('view_draw', 0)
    log("  per-frame work: engine view_draw %.2f s total = rebuild %.2f + material compile %.2f + drawing/post %.2f s; "
        "driver/overhead outside view_draw %.2f s"
        % (vd / 1000, tt.get('rebuild', 0) / 1000, tt.get('mat_compile', 0) / 1000,
           (vd - tt.get('rebuild', 0) - tt.get('mat_compile', 0)) / 1000, (total * 1000.0 - vd) / 1000))
    if len(frames) > 2:
        fs = sorted(frames)
        log("  frame ms: min %.0f | median %.0f | p90 %.0f | max %.0f | rebuild calls %d"
            % (fs[0], fs[len(fs) // 2], fs[int(len(fs) * 0.9)], fs[-1], C['rebuild']))
    return dict(total=total, frames=len(frames), geo=geo_done, mat=mat_done, tt=tt)


def expand_cached(cached):
    """Per-slot arrays from an engine cache entry (v0.16.5+: shared buffers + material ranges; needs
    VLR_KEEP_CPU_ARRAYS=1 for normals/UVs/colours). Older entries already hold per-slot arrays."""
    if 'ranges' not in cached:
        return cached.get('slots', [])
    flat = cached['idx'].reshape(-1).astype(np.int64)
    out = []
    for (k, st, cnt), entry in zip(cached['ranges'], cached['slots_list']):
        I = flat[st:st + cnt]
        d = dict(positions=cached['pos'][I], material_name=entry[1])
        for src, dst in (('nrm', 'normals'), ('uv', 'uvs'), ('col', 'colors')):
            if src in cached:
                d[dst] = cached[src][I]
        out.append(d)
    return out


def verify_all(E, label):
    """Every cached (non-instance) object vs a fresh extraction: catches wrong signatures / wrong shares."""
    eng = CAP['engine']
    orig = getattr(E._extract_mesh_data, '_orig', E._extract_mesh_data)
    win, area, region, rv3d = _view()
    with bpy.context.temp_override(window=win, area=area, region=region):
        dg = bpy.context.evaluated_depsgraph_get()
    va = getattr(eng, '_view_attr', '')
    n = 0; bad = []; t = time.perf_counter()
    for name, data in list(eng._mesh_cache.items()):
        if not isinstance(name, str) or name.startswith('i:'):
            continue
        ob = bpy.data.objects.get(name)
        if ob is None:
            continue
        fresh = orig(ob, dg, attr_name=va); n += 1
        cs = expand_cached(data) if data else []; fs = fresh.get('slots', []) if fresh else []
        why = None
        if len(cs) != len(fs):
            why = 'slots %d vs %d' % (len(cs), len(fs))
        else:
            for a, b in zip(cs, fs):
                for k in ('positions', 'normals', 'uvs', 'colors'):
                    va_, vb_ = a.get(k), b.get(k)
                    if va_ is None and vb_ is None:
                        continue
                    if va_ is None or vb_ is None or np.shape(va_) != np.shape(vb_) or \
                            (np.size(va_) and float(np.abs(np.asarray(va_, np.float64) - np.asarray(vb_, np.float64)).max()) > 1e-5):
                        why = k; break
                if why: break
        if why:
            bad.append((name, why))
    log("  VERIFY-ALL after %s: %d cached objects vs fresh extraction -> %d mismatches%s  (%.1f s)"
        % (label, n, len(bad), (' ' + str(bad[:6])) if bad else '', time.perf_counter() - t))
    status.setdefault('verify', {})[label] = len(bad)


def leave():
    win, area, region, rv3d = _view()
    area.spaces.active.shading.type = 'SOLID'
    for _ in range(3): draw1()


# ───────────────────────── batch A/B on the real extracted data ─────────────────────────
_AB_VERT = """
uniform mat4 uMVP; in vec3 position; in vec3 normal; in vec4 vertColor; in vec2 texCoord; out vec4 vC;
void main(){ gl_Position = uMVP*vec4(position,1.0);
  vC = vec4(fract(vertColor.rgb + 0.5*normal + vec3(texCoord,0.0)), 1.0); }"""
_AB_FRAG = "in vec4 vC; out vec4 o; void main(){ o = vC; }"


def batch_ab(E, max_slots=400):
    import gpu
    from gpu_extras.batch import batch_for_shader as bfs_orig
    eng = CAP['engine']
    slots = []
    seen = set()
    for name, data in (getattr(eng, '_mesh_cache', {}) or {}).items():
        if id(data) in seen: continue
        seen.add(id(data)); slots.extend(data.get('slots', []))
    slots.sort(key=lambda s: -len(s['positions']))
    slots = slots[:max_slots]
    if not slots:
        log("  batch A/B: no extracted slots"); return
    sh = E._get_main_shader()
    names = ('position', 'normal', 'vertColor', 'texCoord'); keys = ('positions', 'normals', 'colors', 'uvs')
    fmt = sh.format_calc()
    off = gpu.types.GPUOffScreen(64, 64)

    def upload(b):
        with off.bind():
            sh.bind()
            try: b.draw(sh)
            except Exception: pass
        bench._gpu_sync()

    def build_A(s):
        return bfs_orig(sh, 'TRIS', {n: s[k] for n, k in zip(names, keys)})

    def build_B(s):
        vbo = gpu.types.GPUVertBuf(fmt, len(s['positions']))
        for n, k in zip(names, keys):
            vbo.attr_fill(id=n, data=np.ascontiguousarray(s[k], dtype=np.float32))
        return gpu.types.GPUBatch(type='TRIS', buf=vbo)

    def build_C(s):
        vbo = gpu.types.GPUVertBuf(fmt, len(s['positions']))
        for n, k in zip(names, keys):
            a = np.ascontiguousarray(s[k], dtype=np.float32)
            buf = gpu.types.Buffer('FLOAT', a.shape)
            np.frombuffer(buf, dtype=np.float32)[:] = a.ravel()
            vbo.attr_fill(id=n, data=buf)
        return gpu.types.GPUBatch(type='TRIS', buf=vbo)

    res = {}
    for tag, fn in (('A batch_for_shader', build_A), ('B fmt-once + attr_fill(numpy)', build_B),
                    ('C fmt-once + attr_fill(Buffer memcpy)', build_C)):
        bench._gpu_sync()
        tb = 0.0; tu = 0.0; ok = True
        for s in slots:
            t = time.perf_counter()
            try:
                b = fn(s)
            except Exception as e:
                ok = False; log("  %s failed: %s" % (tag, e)); break
            tb += time.perf_counter() - t
            t = time.perf_counter(); upload(b); tu += time.perf_counter() - t
            del b
        res[tag] = (tb, tu, ok)
    verts = sum(len(s['positions']) for s in slots)
    log("")
    log("BATCH BUILD A/B on the %d largest extracted slots (%.2fM vertices, real scene data):" % (len(slots), verts / 1e6))
    for tag, (tb, tu, ok) in res.items():
        log("  %-40s build %7.1f ms (%.1f ns/vertex) | first draw / GPU upload %7.1f ms%s"
            % (tag, tb * 1000, tb * 1e9 / max(verts, 1), tu * 1000, '' if ok else '  [FAILED]'))
    # identical output? render the biggest slot with a shader that consumes all four attributes
    try:
        from mathutils import Matrix, Vector
        s = slots[0]; P = s['positions']; lo = P.min(0); hi = P.max(0); c = (lo + hi) * 0.5
        ext = float(max(hi - lo)) or 1.0
        mvp = Matrix.Diagonal((2.0 / ext, 2.0 / ext, 1.0 / ext, 1.0)) @ Matrix.Translation(Vector((-c[0], -c[1], -c[2])))
        tsh = gpu.types.GPUShader(_AB_VERT, _AB_FRAG); tfmt = tsh.format_calc()
        imgs = {}
        for tag in ('A', 'B', 'C'):
            if tag == 'A':
                b = bfs_orig(tsh, 'TRIS', {n: s[k] for n, k in zip(names, keys)})
            else:
                vbo = gpu.types.GPUVertBuf(tfmt, len(P))
                for n, k in zip(names, keys):
                    a = np.ascontiguousarray(s[k], dtype=np.float32)
                    if tag == 'B':
                        vbo.attr_fill(id=n, data=a)
                    else:
                        buf = gpu.types.Buffer('FLOAT', a.shape); np.frombuffer(buf, dtype=np.float32)[:] = a.ravel()
                        vbo.attr_fill(id=n, data=buf)
                b = gpu.types.GPUBatch(type='TRIS', buf=vbo)
            o2 = gpu.types.GPUOffScreen(512, 512)
            with o2.bind():
                fb = gpu.state.active_framebuffer_get(); fb.clear(color=(0, 0, 0, 0), depth=1.0)
                gpu.state.depth_test_set('LESS_EQUAL'); gpu.state.depth_mask_set(True)
                tsh.bind(); tsh.uniform_float('uMVP', mvp); b.draw(tsh)
                px = fb.read_color(0, 0, 512, 512, 4, 0, 'FLOAT')
                imgs[tag] = np.frombuffer(px, dtype=np.float32).copy()
            gpu.state.depth_test_set('NONE')
            o2.free()
        cov = float((imgs['A'].reshape(-1, 4)[:, 3] > 0).mean())
        log("  image check (biggest slot, all 4 attributes used, %.0f%% coverage): max |A-B| %.6f, max |A-C| %.6f"
            % (100 * cov, float(np.abs(imgs['A'] - imgs['B']).max()), float(np.abs(imgs['A'] - imgs['C']).max())))
    except Exception:
        log("  image check failed:\n" + traceback.format_exc())
    off.free()


def run():
    global bench
    try:
        if bpy.app.background:
            raise RuntimeError('--background has no GPU drawing')
        if not bpy.data.filepath or ('claude' not in bpy.data.filepath.lower()
                                     and os.environ.get('VLR_NO_SAVE') != '1'):
            raise RuntimeError('refusing to run on a non-scratch file without VLR_NO_SAVE=1: %r' % bpy.data.filepath)
        spec = importlib.util.spec_from_file_location('benchmark_splats', BENCH)
        bench = importlib.util.module_from_spec(spec); spec.loader.exec_module(bench)
        scene = bpy.context.scene
        scene.render.engine = 'VERTEX_LIT'
        E, MS = instrument()
        import addon_utils
        ver = next((m.bl_info.get('version') for m in addon_utils.modules() if m.__name__ == 'vertex_lit_renderer'), None)
        win, area, region, rv3d = _view()
        mesh_objs = [o for o in scene.objects if o.type == 'MESH']
        log("RENDER-MODE ENTRY PROFILE — addon %s | Blender %s | %s | viewport %dx%d"
            % (ver, bpy.app.version_string, bench.detect_caps()['gpu'], region.width, region.height))
        log("scene %s: %d objects, %d mesh objects, %d materials, %d unique mesh datablocks"
            % (os.path.basename(bpy.data.filepath), len(scene.objects), len(mesh_objs), len(bpy.data.materials),
               len({o.data.name for o in mesh_objs})))
        vls = scene.vertex_lit
        log("settings: shadows %s | AO %s | cavity %s | outline %s | AA %s | view mode %s"
            % (getattr(vls, 'use_shadows', '?'), getattr(vls, 'use_ao', '?'), getattr(vls, 'use_cavity', '?'),
               getattr(vls, 'use_outline', '?'), getattr(vls, 'aa_method', '?'), getattr(vls, 'view_mode', '?')))
        for _ in range(3): draw1()      # settle the Solid view
        if os.environ.get('VLR_UNHIDE_EYE') == '1':
            # Reproduce a working state: show every eye-hidden mesh object (view-layer hide), IN MEMORY ONLY.
            # Excluded collections stay excluded. Solid-view frames let the depsgraph evaluate the newly
            # visible objects (incl. geometry nodes) BEFORE we time the engine.
            hid = []
            for o in scene.objects:
                if o.type != 'MESH':
                    continue
                try:
                    if o.hide_get(): hid.append(o)
                except Exception:
                    pass                      # not in the view layer (excluded collection)
            t = time.perf_counter()
            for o in hid:
                o.hide_set(False)
            for _ in range(3): draw1()
            log("UNHID %d eye-hidden mesh objects in memory (file is never saved); Solid-view evaluation took %.2f s"
                % (len(hid), time.perf_counter() - t))
        cold = enter("COLD (first entry this session)", E)
        if os.environ.get('VLR_VERIFY_ALL') == '1':
            verify_all(E, 'COLD')
        if os.environ.get('VLR_SKIP_AB') != '1':
            batch_ab(E)
        leave()
        warm = enter("WARM (re-entry: persisted batches + shaders)", E)
        if os.environ.get('VLR_VERIFY_ALL') == '1':
            verify_all(E, 'WARM')
        leave()
        if os.environ.get('VLR_SKIP_GEOCOLD') != '1':
            for d in (E._PERSIST_MESH, E._PERSIST_BATCH, E._PERSIST_SHADOW, E._PERSIST_SIG):
                d.clear()
            geo = enter("GEO-COLD (geometry cleared, compiled shaders kept)", E)
            leave()
        status['ok'] = True
    except Exception:
        status['error'] = traceback.format_exc()
        log("!! FAILED:\n" + status['error'])
    with open(STATUS, 'w') as f:
        json.dump(status, f, indent=2)
    if os.environ.get('VLR_NO_SAVE') == '1':
        # user's own file opened in place: never save, and leave without the "save changes?" prompt
        print('[entry] VLR_NO_SAVE=1 -> exiting without saving'); sys.stdout.flush()
        os._exit(0)
    try: bpy.ops.wm.save_mainfile()
    except Exception as e: print('[entry] save copy failed:', e)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=5.0)
