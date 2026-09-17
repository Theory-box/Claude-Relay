"""
auto_test_v0161.py: validates the v0.16.1 audit fixes on a small generated scene (needs a LIVE GPU).

  blender.exe --python auto_test_v0161.py -- <out_dir> <benchmark_splats.py>
  env VLR_OLDSIG=1  -> negative control: swap in the v0.16.0 3-vertex _geo_sig (in memory only)

Runs on the default startup scene. Nothing is ever saved (it exits with os._exit).
 1. EDIT-THEN-LOOK: edit meshes while in Rendered view. After the engine settles, its cached data for
    the object must equal a fresh _extract_mesh_data of the same object (and of a linked duplicate).
 2. share-cache growth over repeated edits.
 3. INSTANCE STREAMING: a collection instance of N unique meshes (more than one 30 ms budget).
    All N must load in the viewport and in F12.
 4. selection-click cost with instances cached (rebuild + _geo_sig time).
 5. viewport state after an F12 render.
"""
import bpy, bmesh, sys, os, json, time, traceback, importlib, importlib.util
from collections import defaultdict
import numpy as np

ARGS = sys.argv[sys.argv.index('--') + 1:]
OUT_DIR, BENCH = ARGS[0], ARGS[1]
os.makedirs(OUT_DIR, exist_ok=True)
OLDSIG = os.environ.get('VLR_OLDSIG') == '1'
N_INST = int(os.environ.get('VLR_N_INST', '150'))
RESULTS = os.path.join(OUT_DIR, 'v0161_results.txt')
STATUS = os.path.join(OUT_DIR, 'auto_status.json')
L = []
status = {'ok': False, 'checks': {}}
T = defaultdict(float); C = defaultdict(int)
CAP = {'engine': None}
ORIG = {}
bench = None
E = None


def log(s=''):
    print('[v0161]', s); L.append(str(s))
    with open(RESULTS, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')


for _scr in bpy.data.screens:
    for _a in _scr.areas:
        if _a.type == 'VIEW_3D':
            for _s in _a.spaces:
                if _s.type == 'VIEW_3D':
                    _s.shading.type = 'SOLID'


def _old_geo_sig(obj, mesh):
    """v0.16.0 _geo_sig, verbatim (negative control)."""
    try:
        mods = tuple((m.type, bool(m.show_viewport)) for m in obj.modifiers)
        nv = len(mesh.vertices)
        s = 0.0
        if nv:
            vs = mesh.vertices
            for i in (0, nv // 2, nv - 1):
                c = vs[i].co; s += c.x * 1.1 + c.y * 2.3 + c.z * 3.7
        base = getattr(getattr(obj, 'data', None), 'name', '')   # stable original name
        return (base, nv, len(mesh.polygons), mods, round(s, 3))
    except Exception:
        return None


def instrument():
    global E
    E = importlib.import_module('vertex_lit_renderer.engine')
    if OLDSIG:
        E._geo_sig = _old_geo_sig

    def wrap(name, key):
        orig = getattr(E, name); ORIG[key] = orig

        def w(*a, **k):
            t = time.perf_counter()
            try:
                return orig(*a, **k)
            finally:
                T[key] += time.perf_counter() - t; C[key] += 1
        setattr(E, name, w)
    wrap('_geo_sig', 'geo_sig')
    wrap('_extract_mesh_data', 'extract_legacy')          # also the reference for compare()
    if hasattr(E, '_extract_geometry'):
        wrap('_extract_geometry', 'extract')               # v0.16.5+ load path
    else:
        ORIG['extract'] = ORIG['extract_legacy']
    cls = E.VertexLitEngine
    vd = cls.view_draw; rb = cls._rebuild_inner; rn = cls.render

    def view_draw(self, context, depsgraph):
        CAP['engine'] = self
        return vd(self, context, depsgraph)

    def rebuild_inner(self, depsgraph, vls):
        t = time.perf_counter()
        try:
            return rb(self, depsgraph, vls)
        finally:
            T['rebuild'] += time.perf_counter() - t; C['rebuild'] += 1

    def render(self, depsgraph):
        CAP['f12_engine'] = self
        objs = set(); insts = set()
        for i in depsgraph.object_instances:
            o = i.object
            if o.type != 'MESH' or not i.show_self or not len(getattr(o.data, 'polygons', ())):
                continue              # faceless meshes have nothing to draw
            if getattr(i, 'is_instance', False):
                insts.add(E._draw_key(i))
            else:
                objs.add(o.name)
        CAP['f12_expected'] = (objs, insts)
        t = time.perf_counter()
        try:
            return rn(self, depsgraph)
        finally:
            CAP['f12_time'] = time.perf_counter() - t
            # the RenderEngine is freed as soon as render() returns -> capture its state here
            CAP['f12_keys'] = set(self._batch_dict)
            CAP['f12_geo_pending'] = bool(getattr(self, '_geo_pending', False))
    cls.view_draw = view_draw; cls._rebuild_inner = rebuild_inner; cls.render = render


def draw1():
    win, area, region, rv3d = bench._find_view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.redraw_timer(type='DRAW', iterations=1)
    bench._gpu_sync()


def busy(e):
    return bool(e._dirty or getattr(e, '_geo_pending', False) or getattr(e, '_mat_pending', False))


def settle(max_frames=120, min_frames=3, max_s=60.0):
    t0 = time.perf_counter(); n = 0
    while True:
        draw1(); n += 1
        e = CAP['engine']
        if e is not None and n >= min_frames and not busy(e):
            return n, time.perf_counter() - t0, True
        if n >= max_frames or time.perf_counter() - t0 > max_s:
            return n, time.perf_counter() - t0, False


def dgraph():
    win, area, region, rv3d = bench._find_view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        return bpy.context.evaluated_depsgraph_get()


def expand_cached(cached):
    """Per-slot arrays from an engine cache entry. v0.16.5+ entries hold shared per-corner buffers +
    material index ranges (needs VLR_KEEP_CPU_ARRAYS=1 for normals/UVs/colours); older entries hold
    per-slot arrays already."""
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


def compare(name, key=None, mesh=None):
    """Engine's cached data (under `key`, default the object name) vs a fresh LEGACY extraction."""
    e = CAP['engine']
    cached = e._mesh_cache.get(key or name)
    kw = {'mesh': mesh} if mesh is not None else {}
    fresh = ORIG['extract_legacy'](bpy.data.objects[name], dgraph(), attr_name=getattr(e, '_view_attr', ''), **kw)
    if cached is None or fresh is None:
        return False, 'missing (cached %s, fresh %s)' % (cached is not None, fresh is not None)
    cs = expand_cached(cached); fs = fresh.get('slots', [])
    if len(cs) != len(fs):
        return False, 'slot count %d vs fresh %d' % (len(cs), len(fs))
    notes = []
    for i, (a, b) in enumerate(zip(cs, fs)):
        for k in sorted(set(a) | set(b)):
            va, vb = a.get(k), b.get(k)
            if isinstance(va, np.ndarray) or isinstance(vb, np.ndarray):
                if va is None or vb is None or np.shape(va) != np.shape(vb):
                    notes.append('slot%d.%s shape %s vs %s' % (i, k, np.shape(va), np.shape(vb))); continue
                if np.size(va):
                    d = float(np.abs(np.asarray(va, np.float64) - np.asarray(vb, np.float64)).max())
                    if d > 1e-5:
                        notes.append('slot%d.%s max|d| %.4g' % (i, k, d))
            elif isinstance(va, str) or isinstance(vb, str):
                if va != vb:
                    notes.append('slot%d.%s %r vs %r' % (i, k, va, vb))
    return (not notes), ('; '.join(notes) if notes else 'identical')


# ───────────────────────── scene ─────────────────────────
def make_grid(name, seg=60, size=2.0):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new(); bm.loops.layers.uv.new('UVMap')
    bmesh.ops.create_grid(bm, x_segments=seg, y_segments=seg, size=size, calc_uvs=True)
    bm.to_mesh(me); bm.free()
    co = np.empty(len(me.vertices) * 3, 'f4'); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
    co[:, 2] = 0.15 * np.sin(co[:, 0] * 3.0) * np.cos(co[:, 1] * 3.0)
    me.vertices.foreach_set('co', co.ravel()); me.update()
    return me


def make_mat(name, rgba):
    m = bpy.data.materials.new(name); m.use_nodes = True
    p = m.node_tree.nodes.get('Principled BSDF')
    if p is not None:
        p.inputs['Base Color'].default_value = rgba
    m.diffuse_color = rgba
    return m


def interior(nv, count):
    """Vertex indices that the old 3-vertex signature never samples (0, nv//2, nv-1)."""
    start = nv // 4 + 3
    return [i for i in range(start, start + count) if i not in (0, nv // 2, nv - 1)]


def build_scene(scene):
    for o in list(scene.objects):
        if o.type == 'MESH':
            bpy.data.objects.remove(o)
    ma = make_mat('VLR_T_Red', (0.9, 0.15, 0.1, 1.0)); mb = make_mat('VLR_T_Blue', (0.1, 0.3, 0.9, 1.0))
    me = make_grid('VLR_T_EditMesh')
    me.materials.append(ma); me.materials.append(mb)
    ca = me.color_attributes.new('Col', 'FLOAT_COLOR', 'POINT')
    ca.data.foreach_set('color', np.ones(len(ca.data) * 4, 'f4'))
    try: me.color_attributes.active_color = ca
    except Exception: pass
    for nm, x in (('EditObj', 0.0), ('EditDup', 5.0)):          # EditDup = linked duplicate (same mesh)
        o = bpy.data.objects.new(nm, me); o.location = (x, 0, 0); scene.collection.objects.link(o)
    # shape key that moves only interior vertices
    km = make_grid('VLR_T_KeyMesh'); km.materials.append(ma)
    ko = bpy.data.objects.new('KeyObj', km); ko.location = (0, 5, 0); scene.collection.objects.link(ko)
    ko.shape_key_add(name='Basis'); kb = ko.shape_key_add(name='Up')
    kc = np.empty(len(km.vertices) * 3, 'f4'); kb.data.foreach_get('co', kc); kc = kc.reshape(-1, 3)
    kc[interior(len(km.vertices), 300), 2] += 0.5
    kb.data.foreach_set('co', kc.ravel()); kb.value = 0.0
    # displace limited to interior vertices by a vertex group -> parameter edit that the old sig can't see
    dm = make_grid('VLR_T_ModMesh'); dm.materials.append(mb)
    do = bpy.data.objects.new('ModObj', dm); do.location = (5, 5, 0); scene.collection.objects.link(do)
    vg = do.vertex_groups.new(name='VG'); vg.add(interior(len(dm.vertices), 300), 1.0, 'REPLACE')
    md = do.modifiers.new('Disp', 'DISPLACE'); md.vertex_group = 'VG'; md.mid_level = 0.0; md.strength = 0.1
    return me


def share_stats(e):
    seen = set(); b = 0
    for v in getattr(e, '_geo_share', {}).values():
        d = v[0]
        if id(d) in seen:
            continue
        seen.add(id(d))
        for s in d.get('slots', []):
            for val in s.values():
                if isinstance(val, np.ndarray):
                    b += val.nbytes
        for kk in ('pos', 'idx', 'nrm', 'uv', 'col'):
            if isinstance(d.get(kk), np.ndarray):
                b += d[kk].nbytes
    return len(getattr(e, '_geo_share', {})), b


def n_inst_loaded(e):
    return sum(1 for k in e._batch_dict if isinstance(k, str) and k.startswith('i:'))


# ───────────────────────── tests ─────────────────────────
def edit_tests(scene, me):
    nv = len(me.vertices); npoly = len(me.polygons)
    k = interior(nv, 1)[0]

    def move_vertex():
        me.vertices[k].co.z += 0.4; me.update()

    def uv_edit():
        lay = me.uv_layers.active; uv = np.empty(len(lay.data) * 2, 'f4')
        lay.data.foreach_get('uv', uv); lay.data.foreach_set('uv', uv + 0.125); me.update()

    def material_index():
        mi = np.zeros(npoly, 'i4'); mi[npoly // 4: npoly // 4 + npoly // 3] = 1
        me.polygons.foreach_set('material_index', mi); me.update()

    def smooth():
        try: me.shade_smooth()
        except Exception: me.polygons.foreach_set('use_smooth', np.ones(npoly, bool))
        me.update()

    def vertex_paint():
        ca = me.color_attributes['Col']; c = np.empty(len(ca.data) * 4, 'f4'); ca.data.foreach_get('color', c)
        c = c.reshape(-1, 4); c[interior(nv, 400)] = (1.0, 0.0, 0.0, 1.0)
        ca.data.foreach_set('color', c.ravel()); me.update()

    def shape_key():
        bpy.data.objects['KeyObj'].data.shape_keys.key_blocks['Up'].value = 1.0

    def modifier_param():
        bpy.data.objects['ModObj'].modifiers['Disp'].strength = 0.6

    cases = [('move one interior vertex', move_vertex, ['EditObj', 'EditDup']),
             ('UV edit', uv_edit, ['EditObj', 'EditDup']),
             ('material index change', material_index, ['EditObj', 'EditDup']),
             ('flat -> smooth shading', smooth, ['EditObj', 'EditDup']),
             ('vertex paint (colour attribute)', vertex_paint, ['EditObj', 'EditDup']),
             ('shape-key slider', shape_key, ['KeyObj']),
             ('modifier parameter (Displace strength)', modifier_param, ['ModObj'])]
    log("")
    log("EDIT-THEN-LOOK (engine cache vs fresh extraction after the engine settles):")
    res = []
    for nm in ('EditObj', 'EditDup', 'KeyObj', 'ModObj'):
        ok, note = compare(nm)
        log("  baseline %-8s %s  %s" % (nm, 'PASS' if ok else 'FAIL', note))
    for label, fn, names in cases:
        r0 = C['rebuild']; x0 = C['extract']
        fn()
        n, dt, settled = settle(max_frames=60)
        for nm in names:
            ok, note = compare(nm)
            res.append(ok)
            log("  %-40s %-8s %s  (%d frames, %.2f s, %s, rebuilds %d, extractions %d)  %s"
                % (label, nm, 'PASS' if ok else 'FAIL', n, dt, 'settled' if settled else 'NOT SETTLED',
                   C['rebuild'] - r0, C['extract'] - x0, note))
    status['checks']['edit_then_look'] = '%d/%d pass' % (sum(res), len(res))
    log("  => %d/%d edit checks pass" % (sum(res), len(res)))

    # share-cache growth over repeated edits
    e = CAP['engine']
    n0, b0 = share_stats(e)
    for i in range(20):
        me.vertices[k].co.z += 0.05; me.update(); settle(max_frames=30)
    n1, b1 = share_stats(e)
    ok, note = compare('EditObj')
    log("")
    log("SHARE-CACHE GROWTH over 20 more single-vertex edits: _geo_share entries %d -> %d, "
        "CPU arrays %.1f -> %.1f MB  (object still %s)" % (n0, n1, b0 / 1e6, b1 / 1e6, 'PASS' if ok else 'FAIL: ' + note))
    status['checks']['share_growth'] = [n0, n1]


def instance_test(scene):
    src = bpy.data.collections.new('VLR_T_ScatterSrc')   # NOT linked to the scene: only instanced
    base = make_grid('VLR_T_ScatBase', seg=100)
    for i in range(N_INST):
        m = base.copy(); m.name = 'VLR_T_Scat_%03d' % i
        o = bpy.data.objects.new('VLR_T_ScatObj_%03d' % i, m)
        o.location = ((i % 15) * 2.5, (i // 15) * 2.5, 0.0); src.objects.link(o)
    inst = bpy.data.objects.new('ScatterInstancer', None)
    inst.instance_type = 'COLLECTION'; inst.instance_collection = src; inst.location = (0.0, 12.0, 0.0)
    scene.collection.objects.link(inst)
    log("")
    log("INSTANCE STREAMING: collection instance of %d unique meshes (%d tris each) added while in Rendered view"
        % (N_INST, len(base.polygons) * 2))
    e = CAP['engine']; r0 = C['rebuild']; x0 = C['extract']
    t0 = time.perf_counter(); trace = []
    for f in range(1, 121):
        draw1(); e = CAP['engine']
        if f in (1, 2, 3, 5, 10, 20, 40, 80, 120):
            trace.append("f%d: %d/%d loaded, _geo_pending=%s, _dirty=%s, rebuilds %d"
                         % (f, n_inst_loaded(e), N_INST, getattr(e, '_geo_pending', None), e._dirty, C['rebuild'] - r0))
        if n_inst_loaded(e) >= N_INST and not busy(e):
            trace.append("f%d: all loaded, idle" % f); break
        if time.perf_counter() - t0 > 15:
            break
    for s in trace:
        log("  " + s)
    loaded = n_inst_loaded(e)
    ok = loaded >= N_INST
    status['checks']['instances_viewport'] = '%d/%d' % (loaded, N_INST)
    log("  => viewport: %s (%d/%d instance meshes loaded, %d extractions, %.1f s); final _geo_pending=%s _dirty=%s"
        % ('PASS' if ok else 'FAIL', loaded, N_INST, C['extract'] - x0, time.perf_counter() - t0,
           getattr(e, '_geo_pending', None), e._dirty))
    if not ok:
        forced = 0
        while n_inst_loaded(e) < N_INST and forced < 400:
            e._dirty = True; draw1(); forced += 1
        log("  (forced _dirty=True for %d frames to finish loading: now %d/%d)" % (forced, n_inst_loaded(e), N_INST))


def click_cost(label):
    e = CAP['engine']; o = bpy.data.objects['EditObj']
    for _ in range(3): draw1()
    for k in ('rebuild', 'geo_sig'):
        T[k] = 0.0; C[k] = 0
    t0 = time.perf_counter()
    for i in range(6):
        o.select_set(not o.select_get()); draw1(); draw1()
    tot = time.perf_counter() - t0
    log("")
    log("SELECTION-CLICK COST (%s): 6 selection toggles -> %d rebuilds, rebuild %.1f ms/click, "
        "_geo_sig %.1f ms/click over %d calls, wall %.0f ms/click"
        % (label, C['rebuild'], T['rebuild'] * 1000 / 6, T['geo_sig'] * 1000 / 6, C['geo_sig'], tot * 1000 / 6))
    status['checks']['click_ms_' + label] = round(T['rebuild'] * 1000 / 6, 2)


def ensure_camera(scene):
    if scene.camera is None:                      # in memory only; nothing is saved
        cd = bpy.data.cameras.new('VLR_T_Cam'); co = bpy.data.objects.new('VLR_T_Cam', cd)
        co.location = (18.0, -25.0, 22.0); co.rotation_euler = (0.9, 0.0, 0.55)
        scene.collection.objects.link(co); scene.camera = co


def f12_test(scene):
    ensure_camera(scene)
    scene.render.resolution_percentage = 25
    log("")
    log("F12 (render depsgraph, %d%% resolution, camera %s):" % (scene.render.resolution_percentage,
                                                                  scene.camera.name if scene.camera else None))
    r0 = C['rebuild']; t = time.perf_counter()
    bpy.ops.render.render()
    wall = time.perf_counter() - t
    objs, insts = CAP.get('f12_expected', (set(), set()))
    keys = CAP.get('f12_keys', set()); gp = CAP.get('f12_geo_pending')
    mo = sorted(objs - keys); mi = sorted(insts - keys)
    ok = 'f12_keys' in CAP and not mo and not mi
    status['checks']['f12'] = 'objects %d/%d, instance meshes %d/%d' % (len(objs) - len(mo), len(objs), len(insts) - len(mi), len(insts))
    log("  => %s: %.2f s (render() %.2f s), %d rebuild passes | objects %d/%d | instance meshes %d/%d | _geo_pending after %s%s"
        % ('PASS' if ok else 'FAIL', wall, CAP.get('f12_time', -1), C['rebuild'] - r0, len(objs) - len(mo), len(objs),
           len(insts) - len(mi), len(insts), gp,
           ('  missing: %s' % (mo + mi)[:8]) if (mo or mi) else ''))
    # the viewport after F12 (F12 clears the shared _PERSIST_* dicts)
    v = CAP['engine']
    for _ in range(5): draw1()
    ok_v, note = compare('EditObj')
    log("  viewport after F12 (5 frames, no edits): %d cached entries, %d instance meshes, EditObj %s  %s"
        % (len(v._batch_dict), n_inst_loaded(v), 'PASS' if ok_v else 'FAIL', note))


def away_tests(me, wait=0.0):
    """Edit while the viewport is in SOLID (the viewport engine does not exist then), then re-enter.
    wait: seconds to pause in Solid before editing (v0.16.4's handler ignores edits < 2 s after the
    last view_update)."""
    win, area, region, rv3d = bench._find_view3d(); space = area.spaces.active
    nv = len(me.vertices); k = interior(nv, 1)[0] + 5 + int(wait * 10)

    def mv():
        me.vertices[k].co.z += 0.3; me.update()

    def paint():
        ca = me.color_attributes['Col']; c = np.empty(len(ca.data) * 4, 'f4'); ca.data.foreach_get('color', c)
        c = c.reshape(-1, 4); c[interior(nv, 200)] = (0.0, 1.0, 0.0, 1.0); ca.data.foreach_set('color', c.ravel()); me.update()

    def uv():
        lay = me.uv_layers.active; u = np.empty(len(lay.data) * 2, 'f4'); lay.data.foreach_get('uv', u)
        lay.data.foreach_set('uv', u - 0.05); me.update()
    log("")
    log("EDIT WHILE AWAY (edit in Solid view %s, then switch back to Rendered):"
        % ('immediately' if not wait else 'after waiting %.1f s' % wait))
    res = []
    for label, fn in (('move one interior vertex', mv), ('vertex paint', paint), ('UV edit', uv)):
        space.shading.type = 'SOLID'; draw1(); draw1()
        if wait:
            time.sleep(wait)
        fn(); draw1(); draw1()
        rec = getattr(E, '_EDITED_WHILE_AWAY', None)
        if rec is not None:
            log("  (handler recorded before re-entry: %s)" % sorted(rec)[:6])
        space.shading.type = 'RENDERED'
        n, dt, settled = settle(max_frames=60)
        for nm in ('EditObj', 'EditDup'):
            ok, note = compare(nm); res.append(ok)
            log("  %-26s %-8s %s  (%d frames, %.2f s)  %s" % (label, nm, 'PASS' if ok else 'FAIL', n, dt, note))
    status['checks']['edit_while_away_%.1f' % wait] = '%d/%d pass' % (sum(res), len(res))
    log("  => %d/%d re-entry checks pass" % (sum(res), len(res)))


def inst_away_test(wait=2.5):
    """Edit an instanced mesh while in Solid view, then switch back to Rendered."""
    win, area, region, rv3d = bench._find_view3d(); space = area.spaces.active
    src = bpy.data.objects['VLR_T_ScatObj_011']; m = src.data; key = 'i:' + m.name
    space.shading.type = 'SOLID'; draw1(); draw1()
    time.sleep(wait)
    m.vertices[interior(len(m.vertices), 1)[0]].co.z += 0.5; m.update(); draw1(); draw1()
    rec = getattr(E, '_EDITED_WHILE_AWAY', None)
    space.shading.type = 'RENDERED'
    n, dt, settled = settle(max_frames=60)
    ok, note = compare(src.name, key=key, mesh=m)
    status['checks']['instance_edit_while_away'] = ok
    log("")
    log("INSTANCED MESH EDIT WHILE AWAY (Solid, after %.1f s; handler recorded %s): %s  (%d frames)  %s"
        % (wait, sorted(rec)[:6] if rec is not None else None, 'PASS' if ok else 'FAIL', n, note))


def inst_edit_test():
    """Edit the mesh of one instanced source object while in Rendered view."""
    src = bpy.data.objects['VLR_T_ScatObj_007']; m = src.data; key = 'i:' + m.name
    k = interior(len(m.vertices), 1)[0]
    m.vertices[k].co.z += 0.5; m.update()
    n, dt, settled = settle(max_frames=60)
    ok, note = compare(src.name, key=key, mesh=m)
    status['checks']['instance_edit'] = ok
    log("")
    log("INSTANCED MESH EDIT (move one vertex of %s, used by the collection instance): %s  (%d frames, %.2f s)  %s"
        % (m.name, 'PASS' if ok else 'FAIL', n, dt, note))


def run():
    global bench
    try:
        if bpy.app.background:
            raise RuntimeError('--background has no GPU drawing')
        spec = importlib.util.spec_from_file_location('benchmark_splats', BENCH)
        bench = importlib.util.module_from_spec(spec); spec.loader.exec_module(bench)
        import addon_utils
        addon_utils.enable('vertex_lit_renderer', default_set=False)
        instrument()
        ver = next((m.bl_info.get('version') for m in addon_utils.modules() if m.__name__ == 'vertex_lit_renderer'), None)
        scene = bpy.context.scene
        log("v0.16.1 AUDIT-FIX VALIDATION: addon %s | Blender %s | %s | _geo_sig: %s"
            % (ver, bpy.app.version_string, bench.detect_caps()['gpu'],
               'OLD v0.16.0 3-vertex signature (NEGATIVE CONTROL)' if OLDSIG else 'as installed'))
        me = build_scene(scene)
        scene.render.engine = 'VERTEX_LIT'
        win, area, region, rv3d = bench._find_view3d()
        area.spaces.active.shading.type = 'RENDERED'
        n, dt, ok = settle(max_frames=200)
        log("entered Rendered: %d frames, %.2f s, %s; %d objects cached" % (n, dt, 'settled' if ok else 'NOT settled',
                                                                          len(CAP['engine']._batch_dict)))
        edit_tests(scene, me)
        away_tests(me)
        away_tests(me, wait=2.5)
        click_cost('no instances')
        instance_test(scene)
        click_cost('%d instance meshes cached' % N_INST)
        inst_edit_test()
        inst_away_test()
        f12_test(scene)
        status['ok'] = True
    except Exception:
        status['error'] = traceback.format_exc()
        log("!! FAILED:\n" + status['error'])
    with open(STATUS, 'w') as f:
        json.dump(status, f, indent=2)
    print('[v0161] done -> exiting without saving'); sys.stdout.flush()
    os._exit(0)


bpy.app.timers.register(run, first_interval=3.0)
