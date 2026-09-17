"""
auto_bench_tree.py — unattended splat battery on a tree .blend. Launch a LIVE Blender on a THROWAWAY COPY:

  blender.exe <copy>.blend --python auto_bench_tree.py -- <out_dir> <benchmark_splats.py> [counts] [main_count]

  counts      comma list of per-tree splat counts to sweep (default 250000,500000,1000000)
  main_count  per-tree count for the standard benchmark_splats.main() battery (default 500000)

Per count: converts the biggest mesh (the tree) to splats, lays out 6 trees (the source anchor + 5 copies,
5 m grid), and at ONE fixed camera measures 1 tree vs 6 separate clouds vs 6 trees merged into ONE unified
cloud (one sort): splats hidden, still + orbiting, GPU sort + CPU sort, exact overdraw counts, and isolated
per-sort cost. Also measures how much of the leaf surface is transparent in the leaf alpha texture (splats
the current alpha-blind conversion places on empty leaf-card area). Writes tree_results.txt,
tree_benchmark_battery.txt and auto_status.json to <out_dir>, saves the COPY, quits.
"""
import bpy, sys, os, json, time, math, statistics, traceback, importlib.util
import numpy as np
from mathutils import Euler, Quaternion, Vector

ARGS = sys.argv[sys.argv.index('--') + 1:]
OUT_DIR, BENCH = ARGS[0], ARGS[1]
COUNTS = [int(x) for x in (ARGS[2] if len(ARGS) > 2 else '250000,500000,1000000').split(',')]
MAIN_COUNT = int(ARGS[3]) if len(ARGS) > 3 else 500000
RESULTS = os.path.join(OUT_DIR, 'tree_results.txt')
BATTERY = os.path.join(OUT_DIR, 'tree_benchmark_battery.txt')
STATUS = os.path.join(OUT_DIR, 'auto_status.json')
GRID = [(ix * 5.0, iy * 5.0) for iy in range(2) for ix in range(3)]   # 6 trees, 5 m apart (tree ~3.8 m wide)
ORBIT_FRAMES, ORBIT_STEP = 24, 3.0
status = {'steps': [], 'ok': False}
L = []
bench = None


def log(s=''):
    print('[tree]', s)
    L.append(str(s))


def flush():
    with open(RESULTS, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')


def _load_bench():
    spec = importlib.util.spec_from_file_location('benchmark_splats', BENCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mod(suffix):
    m = next((m for n, m in list(sys.modules.items()) if n.endswith(suffix)), None)
    if m is None:                                  # addon submodules are imported lazily by its operators
        try:
            m = importlib.import_module('vertex_lit_renderer.' + suffix)
        except Exception:
            m = None
    return m


def _view():
    return bench._find_view3d()


def draws(n):
    win, area, region, rv3d = _view()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.redraw_timer(type='DRAW', iterations=n)
    bench._gpu_sync()


def orbit_ms():
    """Mean ms/frame while orbiting ORBIT_STEP deg/frame (forces a re-sort every frame), GPU-synced."""
    win, area, region, rv3d = _view()
    base = rv3d.view_rotation.copy(); ts = []
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.redraw_timer(type='DRAW', iterations=3); bench._gpu_sync()
        for i in range(ORBIT_FRAMES):
            rv3d.view_rotation = Quaternion((0.0, 0.0, 1.0), math.radians(ORBIT_STEP * (i + 1))) @ base
            t = time.perf_counter()
            bpy.ops.wm.redraw_timer(type='DRAW', iterations=1)
            bench._gpu_sync()
            ts.append((time.perf_counter() - t) * 1000.0)
        rv3d.view_rotation = base
        bpy.ops.wm.redraw_timer(type='DRAW', iterations=1)   # refresh rv3d.view_matrix (read by overdraw_counts)
    bench._gpu_sync()
    return statistics.mean(ts)


def sort_ms(cloud, gpu_sort, reps=10):
    """Isolated cost of ONE depth sort of this cloud from the current camera (GPU-synced)."""
    win, area, region, rv3d = _view()
    vm = rv3d.view_matrix; vp = rv3d.window_matrix @ vm
    cam = np.array(vm.inverted().translation, 'f4'); fwd = np.array(-Vector(vm[2][:3]), 'f4')
    cloud.ensure_gpu(); prev = getattr(cloud, '_gpu_sort', False); cloud._gpu_sort = gpu_sort

    def once():
        if not gpu_sort:
            cloud._sortcache = {}          # defeat the throttle cache -> a real CPU re-sort + upload
        else:
            getattr(cloud, '_gcache', {}).pop('__iso__', None)   # v0.14+: GPU sort is throttled too
        cloud._sorted_index(cam, fwd, vp, False, '__iso__')
    once(); bench._gpu_sync()
    t = time.perf_counter()
    for _ in range(reps):
        once()
    bench._gpu_sync()
    ms = (time.perf_counter() - t) / reps * 1000.0
    cloud._gpu_sort = prev
    if not gpu_sort and hasattr(cloud, '_sortcache'):
        cloud._sortcache.pop('__iso__', None)
    return ms


def measure(anchors):
    """Frame costs for exactly these visible anchors at the current camera."""
    vls = bpy.context.scene.vertex_lit
    win, area, region, rv3d = _view()
    r = {}
    r['hidden'] = bench.timed_hidden(anchors)[0]
    for gs in (True, False):
        vls.splat_gpu_sort = gs
        tag = 'gpu' if gs else 'cpu'
        r['still_' + tag] = bench.time_redraws(iterations=15, repeats=3)[0]
        r['move_' + tag] = orbit_ms()
    vls.splat_gpu_sort = True
    r['od'] = bench.overdraw_counts(region, rv3d, anchors)
    return r


def frame_on(anchors, factor):
    win, area, region, rv3d = _view()
    space = area.spaces.active
    lo, hi = bench.splat_bounds(anchors)
    d = bench.fill_distance(rv3d, lo, hi)
    rv3d.view_location = (lo + hi) * 0.5; rv3d.view_distance = d * factor
    space.clip_end = max(space.clip_end, d * 50.0)
    draws(5)
    return d


# ─────────────────────────────── alpha analysis ───────────────────────────────
def _alpha_source(mat):
    """(image, channel, how) for whatever drives the material's transparency, else (None, None, why)."""
    if mat is None or not mat.use_nodes:
        return None, None, 'no node material'
    nt = mat.node_tree

    def trace(sock):
        if not sock.is_linked:
            return None, None
        lk = sock.links[0]; stack = [(lk.from_node, lk.from_socket.name)]; seen = set()
        while stack:
            nd, sname = stack.pop()
            if nd.as_pointer() in seen:
                continue
            seen.add(nd.as_pointer())
            if nd.type == 'TEX_IMAGE' and nd.image is not None:
                return nd.image, (3 if sname == 'Alpha' else 0)
            for inp in nd.inputs:
                if inp.is_linked:
                    stack.append((inp.links[0].from_node, inp.links[0].from_socket.name))
        return None, None
    bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is not None and bsdf.inputs.get('Alpha') is not None:
        img, ch = trace(bsdf.inputs['Alpha'])
        if img is not None:
            return img, ch, "Principled Alpha <- '%s' %s" % (img.name, 'alpha' if ch == 3 else 'colour(R)')
    for n in nt.nodes:
        if n.type == 'MIX_SHADER':
            img, ch = trace(n.inputs[0])
            if img is not None:
                return img, ch, "Mix Shader Fac <- '%s' %s" % (img.name, 'alpha' if ch == 3 else 'colour(R)')
    for n in nt.nodes:
        if n.type == 'TEX_IMAGE' and n.image is not None and n.outputs['Alpha'].is_linked:
            return n.image, 3, "image '%s' alpha output (linked somewhere)" % n.image.name
    return None, None, 'no alpha-driving texture found'


def alpha_analysis(obj, n=400000, seed=0):
    sg = _mod('splat_gen')
    deps = bpy.context.evaluated_depsgraph_get(); ev = obj.evaluated_get(deps); me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
        nv = len(me.vertices); verts = np.empty(nv * 3, np.float32); me.vertices.foreach_get('co', verts)
        verts = verts.reshape(-1, 3)
        nt = len(me.loop_triangles)
        tv = np.empty(nt * 3, np.int32); me.loop_triangles.foreach_get('vertices', tv); tv = tv.reshape(-1, 3)
        tl = np.empty(nt * 3, np.int32); me.loop_triangles.foreach_get('loops', tl); tl = tl.reshape(-1, 3)
        tmat = np.empty(nt, np.int32); me.loop_triangles.foreach_get('material_index', tmat)
        nl = len(me.loops); uvf = np.empty(nl * 2, np.float32); me.uv_layers.active.data.foreach_get('uv', uvf)
        loop_uv = uvf.reshape(-1, 2)
        mw = np.array(obj.matrix_world, np.float32); vw = verts @ mw[:3, :3].T + mw[:3, 3]
        idx, bary, _ = sg._sample_triangles(vw[tv], n, seed)
        uv = (bary[:, :, None] * loop_uv[tl][idx]).sum(1); smi = tmat[idx]
    finally:
        ev.to_mesh_clear()
    rows = []
    for si, slot in enumerate(obj.material_slots):
        mask = smi == si; share = float(mask.mean())
        img, ch, how = _alpha_source(slot.material)
        if img is None or not mask.any():
            rows.append((slot.material.name if slot.material else None, share, None, how))
            continue
        w, h = img.size
        px = np.empty(w * h * 4, np.float32); img.pixels.foreach_get(px); px = px.reshape(h, w, 4)
        u = np.clip(((uv[mask, 0] % 1.0) * w).astype(int), 0, w - 1)
        v = np.clip(((uv[mask, 1] % 1.0) * h).astype(int), 0, h - 1)
        a = px[v, u, ch]
        rows.append((slot.material.name, share, float((a < 0.5).mean()), how))
    return rows


# ─────────────────────────────── test-only radix patch ───────────────────────────────
def patch_radix():
    """IN-MEMORY ONLY (never touches the addon files): v0.14.1's RadixSorter.build() first compiles the
    keygen with mk() — without its sampler/camera declarations — which fails (C1503 undefined uData/uCam/
    uFwd/uViewProj) and aborts the whole build, so every sort silently falls back to bitonic. Rebuild
    build() from its own source minus that one stray statement, so the radix path can be measured."""
    import inspect, textwrap, re
    m = _mod('splat_radix')
    if m is None:
        return "splat_radix module not found"
    msgs = []
    # v0.14.1: stray keygen mk() call before the real keygen setup
    src = textwrap.dedent(inspect.getsource(m.RadixSorter.build))
    new = re.sub(r"\n\s*self\.sh_key = mk\(_KEYGEN.*?\]\)\n", "\n", src, count=1, flags=re.S)
    if new != src:
        ns = {}
        exec(compile(new, m.__file__ + ' [benchmark in-memory patch]', 'exec'), m.__dict__, ns)
        m.RadixSorter.build = ns['build']
        msgs.append("removed stray self.sh_key = mk(_KEYGEN, ...) from RadixSorter.build")
    # v0.14.2: 'active' is a reserved word in GLSL -> the parallel scatter fails to compile (C0000)
    scat = getattr(m, '_SCATTER', '')
    if re.search(r'\bactive\b', scat):
        m._SCATTER = re.sub(r'\bactive\b', 'is_act', scat)
        msgs.append("renamed reserved GLSL identifier 'active' -> 'is_act' in _SCATTER")
    # v0.14.2: the chunked Hillis-Steele scan reads sdata[i-off] in a later sub-pass after an earlier
    # sub-pass of the SAME step already updated it (256 threads x 4 sub-passes over 1024 entries) ->
    # over-counted offsets. Double-buffer each step through registers: read all, barrier, write all.
    scan = getattr(m, '_SCAN', '')
    hazard = re.compile(r"for\(int i=lid;i<SCAN_CHUNK;i\+=SCAN_THREADS\)\{\s*uint v = \(i>=off\) \? sdata\[i-off\] : 0u;"
                        r"\s*barrier\(\);\s*sdata\[i\]\+=v;\s*barrier\(\);\s*\}")
    if os.environ.get('VLR_PATCH_SCAN') == '1' and hazard.search(scan):
        fixed = ("uint tmp[SCAN_CHUNK/SCAN_THREADS]; int j=0;\n"
                 "    for(int i=lid;i<SCAN_CHUNK;i+=SCAN_THREADS){ tmp[j] = (i>=off) ? sdata[i-off] : 0u; j++; }\n"
                 "    barrier();\n"
                 "    j=0;\n"
                 "    for(int i=lid;i<SCAN_CHUNK;i+=SCAN_THREADS){ sdata[i] += tmp[j]; j++; }\n"
                 "    barrier();")
        m._SCAN = hazard.sub(lambda _m: fixed, scan, count=1)
        msgs.append("double-buffered the Hillis-Steele scan step (read-all / barrier / write-all) in _SCAN")
    return ("patched in memory: " + "; ".join(msgs)) if msgs else "nothing to patch"


# ─────────────────────────────── per-count battery ───────────────────────────────
def clear_splats():
    sr = _mod('splat_render')
    for o in [o for o in bpy.data.objects if o.get('vlr_splat_id') is not None]:
        bpy.data.objects.remove(o, do_unlink=True)
    if sr:
        for c in sr.SPLAT_CLOUDS.values():
            try: c.free()
            except Exception: pass
        sr.SPLAT_CLOUDS.clear()


def convert(tree, count):
    scene = bpy.context.scene; vls = scene.vertex_lit
    win, area, region, rv3d = _view()
    vls.splat_method = 'SURFEL'; vls.splat_count = int(count); vls.splat_color = 'TEXTURE'
    vls.splat_lit = True; vls.splat_hide_src = True; vls.splat_gpu_sort = True
    vls.splat_compute = False; vls.splat_tile = False; vls.splat_backface = False
    tree.hide_set(False)
    for o in bpy.context.view_layer.objects:
        if o.select_get(): o.select_set(False)
    tree.select_set(True); bpy.context.view_layer.objects.active = tree
    t = time.perf_counter()
    with bpy.context.temp_override(window=win, area=area, region=region,
                                   active_object=tree, object=tree, selected_objects=[tree]):
        res = bpy.ops.vertex_lit.generate_splats()
    dt = time.perf_counter() - t
    anchor = bpy.context.view_layer.objects.active
    sr = _mod('splat_render')
    cloud = sr.SPLAT_CLOUDS[int(anchor['vlr_splat_id'])]
    return anchor, cloud, dt, res


def unified_cloud(cloud):
    """The 6-tree layout merged into ONE cloud (same splats, same world positions) -> one sort per frame."""
    d = cloud.d
    U = {k: np.concatenate([d[k]] * len(GRID)).astype(d[k].dtype) for k in ('color', 'opacity', 'scale', 'quat')}
    U['xyz'] = np.concatenate([d['xyz'] + np.array([dx, dy, 0.0], np.float32) for dx, dy in GRID]).astype('f4')
    U['count'] = int(d['count']) * len(GRID)
    return U


def with_sort(clouds, fn, radix):
    """Run fn() with the Radix Sort scene toggle forced on (radix) or off (bitonic). The engine copies the
    toggle to each cloud every draw; sorters + caches are dropped on both sides so no earlier sorter is
    reused (v0.14.2 kept a per-anchor sorter regardless of the toggle; v0.14.4 rebuilds on change)."""
    vls = bpy.context.scene.vertex_lit
    prev = bool(getattr(vls, 'splat_radix', False))

    def reset():
        for c in clouds:
            c._gsorts = {}; c._gcache = {}
    vls.splat_radix = bool(radix); reset()
    try:
        return fn()
    finally:
        vls.splat_radix = prev; reset()


def verify_sort(anchor, cloud, radix):
    """Read the GPU-sorted index texture back and check it against a CPU recomputation from the same
    camera: far->near order, no duplicates, same visible set, culled sentinels at the end."""
    win, area, region, rv3d = _view()
    vm = rv3d.view_matrix; pm = rv3d.window_matrix
    model = anchor.matrix_world.copy(); minv = model.inverted()
    cam = vm.inverted().translation; fwd = -Vector(vm[2][:3])
    cam_l = np.array(minv @ cam, 'f4'); fwd_l = np.array((minv.to_3x3() @ fwd).normalized(), 'f4')
    vp = pm @ vm @ model
    prev = (getattr(cloud, '_radix', True), getattr(cloud, '_gpu_sort', False), getattr(cloud, '_radix_pref', False))
    cloud._radix = radix; cloud._radix_pref = radix; cloud._gpu_sort = True   # v0.14.2 reads _radix_pref
    key = '__verify_%s' % ('radix' if radix else 'bitonic')
    getattr(cloud, '_gsorts', {}).pop(key, None); getattr(cloud, '_gcache', {}).pop(key, None)
    try:
        tex = cloud._sorted_index(cam_l, fwd_l, vp, False, key)
        bench._gpu_sync()
        kind = type(cloud._gsorts.get(key)).__name__
        import gpu
        tw, th = tex.width, tex.height          # read through a framebuffer (same path the engine uses)
        fb = gpu.types.GPUFrameBuffer(color_slots=(tex,))
        with fb.bind():
            buf = fb.read_color(0, 0, tw, th, 1, 0, 'FLOAT')
        try:
            arr = np.frombuffer(buf, dtype=np.float32).ravel().copy()
        except Exception:
            buf.dimensions = tw * th
            arr = np.array(buf, dtype=np.float32).ravel()
        log("    [verify %s] index tex %dx%d, %d floats, first ids %s" % (kind, tw, th, arr.size,
                                                                        [int(x) for x in arr[:6]]))
    finally:
        cloud._radix, cloud._gpu_sort, cloud._radix_pref = prev
        cloud._gsorts.pop(key, None); cloud._gcache.pop(key, None)
    N = int(cloud.d['count']); ids = np.rint(arr[:N]).astype(np.int64)
    nvis = int(np.argmax(ids >= N)) if (ids >= N).any() else N
    vis_ids = ids[:nvis]
    xyz = cloud.d['xyz']; depth = (xyz - cam_l) @ fwd_l
    hc = np.column_stack([xyz, np.ones(N, 'f4')]) @ np.array(vp, 'f4').T
    w = hc[:, 3]; safe = np.where(np.abs(w) > 1e-6, w, 1e-6)
    vis = (depth > 0) & (w > 1e-4) & (np.abs(hc[:, 0] / safe) < 1.3) & (np.abs(hc[:, 1] / safe) < 1.3)
    d = depth[vis_ids] if len(vis_ids) else np.zeros(0)
    inc = np.diff(d); tol = 1e-5 * max(float(np.abs(d).max()) if len(d) else 1.0, 1.0)
    return dict(kind=kind, nvis=len(vis_ids), cpu_vis=int(vis.sum()),
                viol=int((inc > tol).sum()), worst=float(inc.max()) if len(inc) else 0.0,
                dup=len(vis_ids) - len(np.unique(vis_ids)),
                tail_ok=bool((ids[nvis:] >= N).all()),
                set_diff=int(len(np.setxor1d(vis_ids, np.nonzero(vis)[0]))))


def fmt(r):
    s = ("hidden %6.2f | still GPU %6.2f  CPU %6.2f | moving GPU %7.2f (%4.0f fps)  CPU %7.2f (%4.0f fps)"
         % (r['hidden'], r['still_gpu'], r['still_cpu'], r['move_gpu'], 1000 / r['move_gpu'],
            r['move_cpu'], 1000 / r['move_cpu']))
    if 'move_rad' in r:
        s += " | moving RADIX %7.2f (%4.0f fps)" % (r['move_rad'], 1000 / r['move_rad'])
    if 'move_bit' in r:
        s += " | moving BITONIC %7.2f (%4.0f fps)" % (r['move_bit'], 1000 / r['move_bit'])
    return s


def battery_for(tree, count, summary):
    sr = _mod('splat_render')
    clear_splats()
    anchor, cloud, gen_s, res = convert(tree, count)
    N = int(cloud.d['count'])
    log("")
    log("=" * 100)
    log("PER-TREE COUNT %d  ->  %d splats per tree after conversion (generate %s in %.1fs)" % (count, N, set(res), gen_s))
    log("=" * 100)
    copies = []
    coll = anchor.users_collection[0]
    for dx, dy in GRID[1:]:
        c = anchor.copy(); c.location = anchor.location + Vector((dx, dy, 0.0)); coll.objects.link(c); copies.append(c)
    six = [(anchor, cloud)] + [(c, cloud) for c in copies]
    frame_on(six, 1.1)                       # one fixed camera framing the 6-tree layout
    win, area, region, rv3d = _view()
    log("camera: framed on the 6-tree layout (%.1f m), viewport %dx%d" % (rv3d.view_distance, region.width, region.height))

    # 6 separate clouds
    r6 = measure(six)
    r6['move_rad'] = with_sort([cloud], orbit_ms, True); r6['move_bit'] = with_sort([cloud], orbit_ms, False)
    ver = [verify_sort(anchor, cloud, True), verify_sort(anchor, cloud, False)]
    flush()
    # 1 tree, same camera
    for c in copies: c.hide_set(True)
    r1 = measure([(anchor, cloud)])
    r1['move_rad'] = with_sort([cloud], orbit_ms, True); r1['move_bit'] = with_sort([cloud], orbit_ms, False); flush()
    # 6 trees merged into one unified cloud (one sort), same camera
    anchor.hide_set(True)
    sid_u = sr.register_cloud(unified_cloud(cloud), sigma=cloud.sigma)
    ua = bpy.data.objects.new('UnifiedSix_Splat', None); ua.location = anchor.location; ua['vlr_splat_id'] = sid_u
    coll.objects.link(ua)
    ucloud = sr.SPLAT_CLOUDS[sid_u]
    draws(3)
    ru = measure([(ua, ucloud)])
    ru['move_rad'] = with_sort([ucloud], orbit_ms, True); ru['move_bit'] = with_sort([ucloud], orbit_ms, False); flush()
    # isolated sort costs
    iso = dict(gpu_N=sort_ms(cloud, True), gpu_6N=sort_ms(ucloud, True),
               cpu_N=sort_ms(cloud, False), cpu_6N=sort_ms(ucloud, False))
    # close view on 1 tree (fills frame)
    bpy.data.objects.remove(ua, do_unlink=True); ucloud.free(); sr.SPLAT_CLOUDS.pop(sid_u, None)
    anchor.hide_set(False)
    frame_on([(anchor, cloud)], 1.0)
    rc = measure([(anchor, cloud)])
    for c in copies: bpy.data.objects.remove(c, do_unlink=True)

    log("Frame ms (GPU-synced wall clock). 'moving' = orbit %g deg/frame, re-sort every frame." % ORBIT_STEP)
    log("  1 tree            %s" % fmt(r1))
    log("  6 trees separate  %s" % fmt(r6))
    log("  6 trees UNIFIED   %s" % fmt(ru))
    log("  1 tree close-up   %s" % fmt(rc))
    for v in ver:
        log("GPU sort correctness (%s, readback vs CPU): %d visible (CPU %d, set diff %d), order violations %d "
            "(worst %.2g m), duplicates %d, culled-at-end %s"
            % (v['kind'], v['nvis'], v['cpu_vis'], v['set_diff'], v['viol'], v['worst'], v['dup'], v['tail_ok']))
    log("Isolated single sort (timer context, indicative only): GPU %d %.2f ms | GPU %d (unified 6x) %.2f ms"
        % (N, iso['gpu_N'], 6 * N, iso['gpu_6N']))
    log("                      CPU %d splats %.2f ms | CPU %d (unified 6x) %.2f ms  vs 6 x %.2f = %.2f ms separate"
        % (N, iso['cpu_N'], 6 * N, iso['cpu_6N'], iso['cpu_N'], 6 * iso['cpu_N']))
    log("Overdraw (exact counts, real foliage):")
    for lab, r in (("1 tree", r1), ("6 trees separate", r6), ("6 trees unified", ru), ("1 tree close-up", rc)):
        log("  %-17s %s" % (lab, bench._fmt_overdraw(r['od'])))
    # where the heavy frame goes: 6 separate trees, moving, GPU sort
    base = r6['hidden']
    draw_fill = max(r6['still_cpu'] - base, 0.0)     # still + CPU sort = cached order: pure draw/fill
    log("Heavy-frame breakdown (6 trees, moving, default GPU sort = %.2f ms; in-frame deltas):" % r6['move_gpu'])
    log("  scene/engine without splats  %.2f ms" % base)
    log("  splat draw + blend (fill)    %.2f ms   (still frame with cached order - hidden)" % draw_fill)
    log("  re-sorting 6 clouds          radix %.2f ms | bitonic %.2f ms | default %.2f ms   (moving - still cached)"
        % (r6['move_rad'] - r6['still_cpu'], r6['move_bit'] - r6['still_cpu'], r6['move_gpu'] - r6['still_cpu']))
    log("  still frame with GPU sort    %.2f ms   (cached order reused)" % r6['still_gpu'])
    summary.append(dict(count=N, r1=r1, r6=r6, ru=ru, rc=rc, iso=iso))
    flush()


def run():
    global bench
    try:
        if bpy.app.background:
            raise RuntimeError('--background has no GPU drawing')
        if not bpy.data.filepath or 'claude' not in bpy.data.filepath.lower():
            raise RuntimeError('refusing to run on a non-scratch file: %r' % bpy.data.filepath)
        bench = _load_bench()
        scene = bpy.context.scene
        scene.render.engine = 'VERTEX_LIT'
        if os.environ.get('VLR_PATCH_RADIX') == '1':
            msg = patch_radix()
            status['steps'].append('radix: ' + msg)
            log("TEST-ONLY RADIX PATCH: %s" % msg)
        stale = [o.name for o in scene.objects if o.get('vlr_splat_id') is not None]
        clear_splats()
        status['steps'].append('removed stale anchors %s' % stale)
        tree = max((o for o in scene.objects if o.type == 'MESH'), key=lambda o: len(o.data.polygons))
        win, area, region, rv3d = _view()
        with bpy.context.temp_override(window=win, area=area, region=region):
            if bpy.context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
        space = area.spaces.active
        space.shading.type = 'RENDERED'; rv3d.view_perspective = 'PERSP'
        rv3d.view_rotation = Euler((math.radians(75), 0.0, math.radians(20))).to_quaternion()

        log("TREE SPLAT BATTERY — %s" % bpy.data.filepath)
        log("Blender %s | %s | viewport %dx%d" % (bpy.app.version_string, bench.detect_caps()['gpu'],
                                                  region.width, region.height))
        log("Source mesh '%s': %d verts, %d faces, dims %s m, materials %s" % (
            tree.name, len(tree.data.vertices), len(tree.data.polygons),
            tuple(round(d, 2) for d in tree.dimensions), [s.material.name for s in tree.material_slots if s.material]))
        log("Conversion: Surfel, Texture colour, Scene Lighting on, source mesh hidden. Removed stale anchor(s) %s." % stale)
        log("")
        log("Leaf alpha check (area-weighted surface samples; splats get constant opacity, alpha is NOT used):")
        try:
            for name, share, frac, how in alpha_analysis(tree):
                log("  %-38s %5.1f%% of surface | %s | %s" % (
                    name, 100 * share, ("%.1f%% of it transparent (alpha<0.5)" % (100 * frac)) if frac is not None else "-", how))
        except Exception:
            log("  !! alpha analysis failed (continuing):\n" + traceback.format_exc())
        flush()

        summary = []
        for count in COUNTS:
            battery_for(tree, count, summary)

        log("")
        log("SUMMARY (ms/frame, same camera; 'mov' = orbiting)")
        log("  GPU sort; 'bit' = Radix Sort toggle OFF (bitonic), 'rad' = toggle ON (radix); both orbiting")
        log("  %-11s | %-28s | %-28s | %-28s" % ("splats/tree", "1 tree  still / bit / rad", "6 separate  still / bit / rad",
                                                "6 UNIFIED  still / bit / rad"))
        for s in summary:
            log("  %-11d | %7.2f / %7.2f / %7.2f  | %7.2f / %7.2f / %7.2f  | %7.2f / %7.2f / %7.2f"
                % (s['count'], s['r1']['still_gpu'], s['r1']['move_bit'], s['r1']['move_rad'],
                   s['r6']['still_gpu'], s['r6']['move_bit'], s['r6']['move_rad'],
                   s['ru']['still_gpu'], s['ru']['move_bit'], s['ru']['move_rad']))
        flush()

        # standard battery on a single tree
        clear_splats()
        anchor, cloud, gen_s, _ = convert(tree, MAIN_COUNT)
        frame_on([(anchor, cloud)], 1.6)
        with bpy.context.temp_override(window=win, area=area, region=region):
            bench.main(BATTERY)
        status['steps'].append('battery -> %s' % BATTERY)
        status['ok'] = True
    except Exception:
        status['error'] = traceback.format_exc()
        log("!! FAILED:\n" + status['error'])
    try:
        flush()
    except Exception:
        pass
    with open(STATUS, 'w') as f:
        json.dump(status, f, indent=2)
    try:
        bpy.ops.wm.save_mainfile()     # the throwaway copy; clears dirty flag so quit won't prompt
    except Exception as e:
        print('[tree] save copy failed:', e)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=5.0)
