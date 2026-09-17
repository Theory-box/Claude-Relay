"""
auto_bench_unified.py — unattended validation of the v0.15 UNIFIED cross-cloud splat sort. Launch a LIVE
Blender on a THROWAWAY COPY of a tree .blend:

  blender.exe <copy>.blend --python auto_bench_unified.py -- <out_dir> <benchmark_splats.py> [counts]

Per per-tree count (default 500000,1000000):
  1. did the unified path run?  (SORTER.draw is wrapped to RECORD calls + return value; observation only)
  2. is the global order right? read back the R32UI unified index, decode inst<<24|id, check world-space
     far->near order, no duplicate (inst,id), visible set == CPU, culled sentinels at the end
  3. overlap ordering in the actual engine image: screenshots (overlays off) with unified ON / OFF vs a
     REFERENCE = all trees merged into ONE cloud (one sort -> correct order by construction); 6-tree grid
     and 2 trees in line
  4. cost: unified ON vs OFF, still + orbiting, plus the first frame after the texture array is (re)built
Clouds are generated with Splat Softness 2.4 = the unified draw's default sigma, so image diffs isolate ORDER.
Writes unified_results.txt + auto_status.json + PNGs to <out_dir>, saves the COPY, quits.
"""
import bpy, sys, os, json, time, math, statistics, traceback, importlib.util
import numpy as np
from mathutils import Euler, Quaternion, Vector

ARGS = sys.argv[sys.argv.index('--') + 1:]
OUT_DIR, BENCH = ARGS[0], ARGS[1]
COUNTS = [int(x) for x in (ARGS[2] if len(ARGS) > 2 else '500000,1000000').split(',')]
RESULTS = os.path.join(OUT_DIR, 'unified_results.txt')
STATUS = os.path.join(OUT_DIR, 'auto_status.json')
GRID = [(ix * 5.0, iy * 5.0) for iy in range(2) for ix in range(3)]
SIGMA = float(os.environ.get('VLR_TEST_SIGMA', '2.2'))   # 2.2 = addon default; v0.15.0 needed 2.4 to hide its sigma bug
ORBIT_FRAMES, ORBIT_STEP = 24, 3.0
status = {'steps': [], 'ok': False}
L = []
bench = None


def log(s=''):
    print('[unified]', s); L.append(str(s))
    with open(RESULTS, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')


def _mod(suffix):
    m = next((m for n, m in list(sys.modules.items()) if n.endswith(suffix)), None)
    if m is None:
        try: m = importlib.import_module('vertex_lit_renderer.' + suffix)
        except Exception: m = None
    return m


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
            bpy.ops.wm.redraw_timer(type='DRAW', iterations=1)
            bench._gpu_sync()
            ts.append((time.perf_counter() - t) * 1000.0)
        rv3d.view_rotation = base
        bpy.ops.wm.redraw_timer(type='DRAW', iterations=1)
    bench._gpu_sync()
    return statistics.mean(ts)


def frame_on(anchors, factor):
    win, area, region, rv3d = _view()
    lo, hi = bench.splat_bounds(anchors)
    d = bench.fill_distance(rv3d, lo, hi)
    rv3d.view_location = (lo + hi) * 0.5; rv3d.view_distance = d * factor
    area.spaces.active.clip_end = max(area.spaces.active.clip_end, d * 50.0)
    draws(5)


def reset_sorts(clouds):
    for c in clouds:
        c._gsorts = {}; c._gcache = {}; c._sortcache = {}


def clear_splats():
    sr = _mod('splat_render')
    for o in [o for o in bpy.data.objects if o.get('vlr_splat_id') is not None]:
        bpy.data.objects.remove(o, do_unlink=True)
    if sr:
        for c in sr.SPLAT_CLOUDS.values():
            try: c.free()
            except Exception: pass
        sr.SPLAT_CLOUDS.clear()
    SU = _mod('splat_unified')
    if SU is not None:
        SU.SORTER.array = None; SU.SORTER._sig = None


def convert(tree, count):
    vls = bpy.context.scene.vertex_lit
    win, area, region, rv3d = _view()
    vls.splat_method = 'SURFEL'; vls.splat_count = int(count); vls.splat_color = 'TEXTURE'
    vls.splat_lit = True; vls.splat_hide_src = True; vls.splat_sigma = SIGMA
    tree.hide_set(False)
    for o in bpy.context.view_layer.objects:
        if o.select_get(): o.select_set(False)
    tree.select_set(True); bpy.context.view_layer.objects.active = tree
    with bpy.context.temp_override(window=win, area=area, region=region,
                                   active_object=tree, object=tree, selected_objects=[tree]):
        bpy.ops.vertex_lit.generate_splats()
    anchor = bpy.context.view_layer.objects.active
    return anchor, _mod('splat_render').SPLAT_CLOUDS[int(anchor['vlr_splat_id'])]


# ───────────────────────── observation hook (records, never changes behaviour) ─────────────────────────
def install_recorder():
    SU = _mod('splat_unified')
    S = SU.SORTER
    orig = type(S).draw
    S._calls = 0; S._ok = 0; S._rec = None; S._cpu = []

    def recorded(entries, vm, pm, w, h, **kw):
        S._calls += 1
        t = time.perf_counter()
        r = orig(S, entries, vm, pm, w, h, **kw)
        S._cpu.append((time.perf_counter() - t) * 1000.0)   # CPU/submission time of the call itself
        if r: S._ok += 1
        S._rec = dict(entries=[(c, m.copy(), n) for c, m, n in entries], vm=vm.copy(), pm=pm.copy(),
                      ret=bool(r), kw=dict(kw))
        return r
    S.draw = recorded
    return S


def verify_unified(S):
    """Decode the unified R32UI index from the LAST recorded unified draw and check it against the CPU."""
    import gpu
    rec = S._rec
    if not rec or not rec['ret']:
        return dict(ok=False, why='no successful unified draw recorded')
    ents = rec['entries']; counts = [int(c.d['count']) for c, _m, _n in ents]; total = sum(counts)
    tex = S.uIndex; tw, th = tex.width, tex.height
    fb = gpu.types.GPUFrameBuffer(color_slots=(tex,))
    with fb.bind():
        buf = fb.read_color(0, 0, tw, th, 1, 0, 'UINT')
    try:
        arr = np.frombuffer(buf, dtype=np.uint32).ravel().copy()
    except Exception:
        buf.dimensions = tw * th; arr = np.array(buf, dtype=np.uint32).ravel()
    p = arr[:total]
    sent = p == 0xFFFFFFFF
    nvis = int(np.argmax(sent)) if sent.any() else total
    head = p[:nvis]
    inst = (head >> 24).astype(np.int64); sid = (head & 0x00FFFFFF).astype(np.int64)
    vm = rec['vm']; pm = rec['pm']
    cam = np.array(vm.inverted().translation, 'f8'); fwd = -np.array(vm[2][:3], 'f8')
    vp = np.array(pm @ vm, 'f8')
    bad_inst = int(((inst < 0) | (inst >= len(ents))).sum())
    depth = np.empty(nvis, 'f8'); cpu_vis = 0
    for k, (c, m, _n) in enumerate(ents):
        M = np.array(m, 'f8'); xyz = c.d['xyz'].astype('f8')
        W = xyz @ M[:3, :3].T + M[:3, 3]
        dk = (W - cam) @ fwd
        hc = np.column_stack([W, np.ones(len(W))]) @ vp.T
        w = hc[:, 3]; safe = np.where(np.abs(w) > 1e-6, w, 1e-6)
        vis = (dk > 0) & (w > 1e-4) & (np.abs(hc[:, 0] / safe) < 1.3) & (np.abs(hc[:, 1] / safe) < 1.3)
        cpu_vis += int(vis.sum())
        sel = inst == k
        if sel.any():
            ok_sid = sid[sel] < len(xyz)
            dd = np.full(int(sel.sum()), np.nan); dd[ok_sid] = dk[sid[sel][ok_sid]]
            depth[sel] = dd
    key = inst * (1 << 24) + sid
    dup = nvis - len(np.unique(key))
    inc = np.diff(depth)
    tol = 1e-5 * max(float(np.nanmax(np.abs(depth))) if nvis else 1.0, 1.0)
    per_inst = [int((inst == k).sum()) for k in range(len(ents))]
    return dict(ok=True, instances=len(ents), total=total, nvis=nvis, cpu_vis=cpu_vis, bad_inst=bad_inst,
                nan=int(np.isnan(depth).sum()), viol=int((inc > tol).sum()),
                worst=float(np.nanmax(inc)) if len(inc) else 0.0, dup=int(dup),
                tail_ok=bool(sent[nvis:].all()), per_inst=per_inst, sigma=rec['kw'].get('sigma', 'default(2.4)'))


# ───────────────────────── images ─────────────────────────
_GRAB = {'want': False, 'img': None, 'handle': None}


def _grab_cb():
    """POST_PIXEL draw handler: read the region framebuffer right after the engine drew it."""
    if not _GRAB['want']:
        return
    import gpu
    try:
        fb = gpu.state.active_framebuffer_get()
        x, y, w, h = gpu.state.viewport_get()
        buf = fb.read_color(x, y, w, h, 4, 0, 'FLOAT')
        try:
            a = np.frombuffer(buf, dtype=np.float32).copy()
        except Exception:
            buf.dimensions = w * h * 4; a = np.array(buf, dtype=np.float32)
        _GRAB['img'] = a.reshape(h, w, 4)
    except Exception as e:
        print('[unified] grab failed:', e)
    _GRAB['want'] = False


def install_grabber():
    if _GRAB['handle'] is None:
        _GRAB['handle'] = bpy.types.SpaceView3D.draw_handler_add(_grab_cb, (), 'WINDOW', 'POST_PIXEL')


def save_png(img, path):
    h, w, _ = img.shape
    im = bpy.data.images.new('vlr_grab', w, h, alpha=True, float_buffer=True)
    im.pixels.foreach_set(np.ascontiguousarray(img, dtype=np.float32).ravel())
    im.filepath_raw = path; im.file_format = 'PNG'; im.save()
    bpy.data.images.remove(im)


def shot(name):
    """Grab the engine's viewport image (framebuffer readback via a draw handler) and save it as a PNG.
    If handlers don't fire with overlays off, retry with overlays on but grid/cursor/extras hidden."""
    space = _view()[1].spaces.active
    for attempt in (0, 1):
        _GRAB['want'] = True; _GRAB['img'] = None
        draws(2)
        if _GRAB['img'] is not None:
            break
        if attempt == 0 and not space.overlay.show_overlays:
            ov = space.overlay; ov.show_overlays = True
            for a in ('show_floor', 'show_axis_x', 'show_axis_y', 'show_cursor', 'show_object_origins',
                      'show_extras', 'show_relationship_lines', 'show_text', 'show_stats'):
                if hasattr(ov, a): setattr(ov, a, False)
    if _GRAB['img'] is None:
        raise RuntimeError('viewport framebuffer grab failed')
    save_png(_GRAB['img'], os.path.join(OUT_DIR, name))
    return _GRAB['img']


def load_rgb(x):
    return x[..., :3]


def save_mask(a, b, path):
    """Red where the two images differ by more than 2%, grey image elsewhere (for eyeballing)."""
    d = np.abs(a[..., :3] - b[..., :3]).max(axis=2) > 0.02
    out = np.empty(a.shape[:2] + (4,), np.float32); g = a[..., :3].mean(axis=2) * 0.35
    out[..., 0] = np.where(d, 1.0, g); out[..., 1] = np.where(d, 0.0, g); out[..., 2] = np.where(d, 0.0, g)
    out[..., 3] = 1.0
    save_png(out, path)


def diff(a, b):
    d = np.abs(a - b).max(axis=2)
    return "mean |d| %.4f, pixels differing >2%%: %.2f%%, max %.3f" % (float(d.mean()), 100 * float((d > 0.02).mean()),
                                                                      float(d.max()))


def overlap_test(tag, anchors, cloud, anchor):
    """Engine image with unified ON / OFF vs a merged single-cloud reference, same camera."""
    vls = bpy.context.scene.vertex_lit; sr = _mod('splat_render')
    space = _view()[1].spaces.active
    prev_ov = space.overlay.show_overlays; space.overlay.show_overlays = False
    try:
        clouds = [c for _o, c in anchors]
        vls.splat_unified = True; reset_sorts(clouds); draws(3)
        p_on = shot('%s_unified_ON.png' % tag)
        vls.splat_unified = False; reset_sorts(clouds); draws(3)
        p_off = shot('%s_unified_OFF.png' % tag)
        vls.splat_unified = True
        # reference: every visible tree merged into ONE cloud at the source anchor -> one global sort
        offs = [np.array(o.location - anchor.location, 'f4') for o, _c in anchors]
        d = cloud.d
        U = {k: np.concatenate([d[k]] * len(offs)).astype(d[k].dtype) for k in ('color', 'opacity', 'scale', 'quat')}
        U['xyz'] = np.concatenate([d['xyz'] + off for off in offs]).astype('f4'); U['count'] = int(d['count']) * len(offs)
        for o, _c in anchors: o.hide_set(True)
        sid = sr.register_cloud(U, sigma=cloud.sigma)
        ua = bpy.data.objects.new('MergedRef_Splat', None); ua.location = anchor.location; ua['vlr_splat_id'] = sid
        anchor.users_collection[0].objects.link(ua)
        draws(3)
        p_ref = shot('%s_reference_merged.png' % tag)
        bpy.data.objects.remove(ua, do_unlink=True); sr.SPLAT_CLOUDS.pop(sid).free()
        for o, _c in anchors: o.hide_set(False)
        reset_sorts(clouds); draws(3)
        on, off, ref = load_rgb(p_on), load_rgb(p_off), load_rgb(p_ref)
        log("  %s overlap image test (engine screenshots, overlays off):" % tag)
        log("    unified ON  vs merged reference: %s" % diff(on, ref))
        log("    unified OFF vs merged reference: %s" % diff(off, ref))
        log("    unified ON  vs unified OFF     : %s" % diff(on, off))
        save_mask(off, ref, os.path.join(OUT_DIR, '%s_OFF_vs_reference_diff.png' % tag))
        save_mask(on, ref, os.path.join(OUT_DIR, '%s_ON_vs_reference_diff.png' % tag))
    finally:
        space.overlay.show_overlays = prev_ov


# ───────────────────────── draw-order image test (offscreen, splats only) ─────────────────────────
def render_off(fn, w, h):
    """Run fn() inside a cleared RGBA16F offscreen (with depth) and return (image, fn's result)."""
    import gpu
    off = gpu.types.GPUOffScreen(w, h, format='RGBA16F')
    ok = False
    try:
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 0.0), depth=1.0)
            gpu.state.depth_test_set('LESS_EQUAL'); gpu.state.depth_mask_set(True)
            ok = fn()
            buf = fb.read_color(0, 0, w, h, 4, 0, 'FLOAT')
            try:
                a = np.frombuffer(buf, dtype=np.float32).copy()
            except Exception:
                buf.dimensions = w * h * 4; a = np.array(buf, dtype=np.float32)
    finally:
        gpu.state.blend_set('NONE'); gpu.state.depth_test_set('NONE'); gpu.state.depth_mask_set(True)
        off.free()
    return a.reshape(h, w, 4), ok


def order_image_test(tag, anchors, cloud, anchor, S):
    """Same camera, splats only, three ways: PER-CLOUD (each tree sorted+drawn on its own = today's
    behaviour), UNIFIED (SORTER.draw), and REFERENCE (all trees merged into ONE cloud -> one global sort,
    correct by construction). Unified should match the reference; per-cloud should differ where trees overlap."""
    sr = _mod('splat_render')
    win, area, region, rv3d = _view()
    draws(1)
    vm = rv3d.view_matrix.copy(); pm = rv3d.window_matrix.copy(); w, h = region.width, region.height
    for _o, c in anchors:
        c._gpu_sort = True; c._radix_pref = True

    def per_cloud():
        for o, c in anchors:
            c.draw(vm, pm, w, h, write_depth=False, light=None, model=o.matrix_world.copy(), obj_key='__img_' + o.name)
        return True

    def unified():
        ents = [(c, o.matrix_world.copy(), o.name) for o, c in anchors]
        return bool(S.draw(ents, vm, pm, w, h, light=None, sigma=cloud.sigma, write_depth=False))
    img_pc, _ = render_off(per_cloud, w, h)
    img_un, ok_un = render_off(unified, w, h)
    offs = [np.array(o.location - anchor.location, 'f4') for o, _c in anchors]
    d = cloud.d
    U = {k: np.concatenate([d[k]] * len(offs)).astype(d[k].dtype) for k in ('color', 'opacity', 'scale', 'quat')}
    U['xyz'] = np.concatenate([d['xyz'] + off for off in offs]).astype('f4'); U['count'] = int(d['count']) * len(offs)
    sid = sr.register_cloud(U, sigma=cloud.sigma); mc = sr.SPLAT_CLOUDS[sid]
    mc._gpu_sort = True; mc._radix_pref = True

    def ref():
        mc.draw(vm, pm, w, h, write_depth=False, light=None, model=anchor.matrix_world.copy(), obj_key='__img_ref')
        return True
    img_ref, _ = render_off(ref, w, h)
    sr.SPLAT_CLOUDS.pop(sid, None); mc.free()
    for nm, im in (('per_cloud', img_pc), ('unified', img_un), ('reference_merged', img_ref)):
        v = np.clip(im, 0.0, 1.0).copy(); v[..., 3] = 1.0
        save_png(v, os.path.join(OUT_DIR, '%s_%s.png' % (tag, nm)))
    cov = float((img_ref[..., 3] > 0.01).mean())
    log("  %s draw-order image test (offscreen, splats only, %dx%d, splat coverage %.1f%%):" % (tag, w, h, 100 * cov))
    if not ok_un:
        log("    unified draw FAILED (returned False / fell back) -> unified image is empty")
    log("    unified   vs merged reference: %s" % diff(img_un[..., :3], img_ref[..., :3]))
    log("    per-cloud vs merged reference: %s" % diff(img_pc[..., :3], img_ref[..., :3]))
    log("    unified   vs per-cloud       : %s" % diff(img_un[..., :3], img_pc[..., :3]))
    save_mask(img_pc, img_ref, os.path.join(OUT_DIR, '%s_per_cloud_vs_reference_diff.png' % tag))
    save_mask(img_un, img_ref, os.path.join(OUT_DIR, '%s_unified_vs_reference_diff.png' % tag))


# ───────────────────────── multi-angle sweep (incl. rotated / scaled copies) ─────────────────────────
def merged_cloud(anchors, anchor, cloud):
    """Reference: every anchor's copy of `cloud` baked into ONE cloud in the source anchor's local frame
    (position, orientation AND uniform scale applied to the splats) -> one global sort, correct by construction."""
    d = cloud.d; A_inv = anchor.matrix_world.inverted()
    xs, qs, ss = [], [], []
    for o, _c in anchors:
        loc, rot, sca = (A_inv @ o.matrix_world).decompose()
        R = np.array(rot.to_matrix(), 'f8'); s = float(sca.x)
        xs.append((s * (d['xyz'].astype('f8') @ R.T) + np.array(loc, 'f8')).astype('f4'))
        qw, qx, qy, qz = rot.w, rot.x, rot.y, rot.z
        q = d['quat'].astype('f8'); w2, x2, y2, z2 = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
        qs.append(np.stack([qw*w2 - qx*x2 - qy*y2 - qz*z2,
                            qw*x2 + qx*w2 + qy*z2 - qz*y2,
                            qw*y2 - qx*z2 + qy*w2 + qz*x2,
                            qw*z2 + qx*y2 - qy*x2 + qz*w2], 1).astype('f4'))
        ss.append((d['scale'] * s).astype('f4'))
    n = len(anchors)
    return dict(count=int(d['count']) * n, xyz=np.concatenate(xs), quat=np.concatenate(qs),
                scale=np.concatenate(ss), color=np.concatenate([d['color']] * n),
                opacity=np.concatenate([d['opacity']] * n))


def pct_wrong(a, b):
    return 100.0 * float((np.abs(a[..., :3] - b[..., :3]).max(axis=2) > 0.02).mean())


def angle_sweep(tag, anchors, cloud, anchor, S, yaws=(0, 60, 120, 180, 240, 300)):
    """Orbit the camera around the layout. At every angle: did the ENGINE run the unified draw, is the
    engine's global order right (GPU readback vs CPU), and what % of pixels are wrong vs the merged
    reference for the unified draw and for per-cloud drawing."""
    sr = _mod('splat_render')
    win, area, region, rv3d = _view()
    base = rv3d.view_rotation.copy()
    sid = sr.register_cloud(merged_cloud(anchors, anchor, cloud), sigma=cloud.sigma); mc = sr.SPLAT_CLOUDS[sid]
    mc._gpu_sort = True; mc._radix_pref = True
    for _o, c in anchors:
        c._gpu_sort = True; c._radix_pref = True
    log("  %s angle sweep (orbit around the layout; engine order check + offscreen pixels wrong vs merged reference):" % tag)
    worst = (-1.0, None)
    try:
        for yaw in yaws:
            rv3d.view_rotation = Quaternion((0.0, 0.0, 1.0), math.radians(yaw)) @ base
            S._calls = 0; S._ok = 0
            draws(3)
            calls, okc = S._calls, S._ok
            v = verify_unified(S)
            vm = rv3d.view_matrix.copy(); pm = rv3d.window_matrix.copy(); w, h = region.width, region.height

            def per_cloud():
                for o, c in anchors:
                    c.draw(vm, pm, w, h, write_depth=False, light=None, model=o.matrix_world.copy(), obj_key='__sw_' + o.name)
                return True

            def unified():
                return bool(S.draw([(c, o.matrix_world.copy(), o.name) for o, c in anchors], vm, pm, w, h,
                                   light=None, sigma=cloud.sigma, write_depth=False))

            def ref():
                mc.draw(vm, pm, w, h, write_depth=False, light=None, model=anchor.matrix_world.copy(), obj_key='__sw_ref')
                return True
            ipc, _ = render_off(per_cloud, w, h); iun, oku = render_off(unified, w, h); iref, _ = render_off(ref, w, h)
            ppc = pct_wrong(ipc, iref); pun = pct_wrong(iun, iref) if oku else float('nan')
            ordr = ("viol %d dup %d vis %d/%d" % (v['viol'], v['dup'], v['nvis'], v['cpu_vis'])) if v.get('ok') \
                else "NOT RUN (%s)" % v.get('why')
            log("    yaw %3d: engine unified draws %d/%d ok | engine order %s | pixels wrong vs reference: unified %.2f%%  per-cloud %.2f%%"
                % (yaw, okc, calls, ordr, pun, ppc))
            score = pun if oku else 100.0
            if score > worst[0]:
                worst = (score, (yaw, iun, ipc, iref))
    finally:
        rv3d.view_rotation = base
        sr.SPLAT_CLOUDS.pop(sid, None); mc.free()
        draws(1)
    if worst[1] is not None:
        yaw, iun, ipc, iref = worst[1]
        save_mask(iun, iref, os.path.join(OUT_DIR, '%s_worst_yaw%d_unified_vs_reference_diff.png' % (tag, yaw)))
        save_mask(ipc, iref, os.path.join(OUT_DIR, '%s_worst_yaw%d_per_cloud_vs_reference_diff.png' % (tag, yaw)))


# ───────────────────────── test-only in-memory patch (env VLR_PATCH_UNIFIED=1) ─────────────────────────
def patch_unified():
    """IN MEMORY ONLY: v0.15.0 builds the texture array with GPUTexture((w,h,layers), ..., is_layered=True);
    Blender 4.4's signature is GPUTexture(size, layers=0, is_cubemap=False, format, data) -> TypeError ->
    unified falls back every frame. Rebuild ensure_array() with GPUTexture((w,h), layers=layers, ...)."""
    import inspect, textwrap, re
    import gpu as _gpu
    SU = _mod('splat_unified')
    if SU is None:
        return "splat_unified not found"
    msgs = []
    # (1) texture array constructor
    src = textwrap.dedent(inspect.getsource(SU.UnifiedSorter.ensure_array))
    old = "gpu.types.GPUTexture((w, h, layers), format='RGBA32F', data=buf, is_layered=True)"
    if old in src:
        new = src.replace(old, "gpu.types.GPUTexture((w, h), layers=layers, format='RGBA32F', data=buf)")
        ns = {}
        exec(compile(new, SU.__file__ + ' [benchmark in-memory patch]', 'exec'), SU.__dict__, ns)
        SU.UnifiedSorter.ensure_array = ns['ensure_array']
        msgs.append("texture array via GPUTexture((w,h), layers=N) instead of is_layered=True")

    # (0) v0.15.1 engine: _draw_splats computes `sig = ... getattr(vls, 'splat_sigma', ...) if vls else 2.2`,
    # but `vls` is not defined in that method -> NameError -> swallowed by `except Exception` -> the engine
    # never reaches SORTER.draw. Use the clouds' own sigma (also matches the per-cloud path exactly).
    try:
        E = importlib.import_module('vertex_lit_renderer.engine')
        cls = next((v for v in vars(E).values() if isinstance(v, type) and '_draw_splats' in vars(v)), None)
        if cls is not None:
            esrc = textwrap.dedent(inspect.getsource(cls._draw_splats))
            enew, ne = re.subn(r"sig = float\(getattr\(vls, 'splat_sigma', 2\.2\)\) if vls else 2\.2",
                               "sig = float(entries[0][0].sigma) if entries else 2.2", esrc)
            if ne:
                ns = {}
                exec(compile(enew, E.__file__ + ' [benchmark in-memory patch]', 'exec'), E.__dict__, ns)
                cls._draw_splats = ns['_draw_splats']
                msgs.append("engine._draw_splats: sigma from entries[0][0].sigma (undefined `vls` NameError)")
    except Exception as e:
        msgs.append("engine patch skipped: %s" % e)

    # (1b) v0.15.1: one layer per UNIQUE cloud, but planes were still packed per ENTRY ->
    # "array size does not match" -> _failed=True -> unified disabled for the session. Pack per unique cloud.
    src = textwrap.dedent(inspect.getsource(SU.UnifiedSorter.ensure_array))
    new, n0 = re.subn(r"for c, _m, _n in entries:(?:\s*#[^\n]*)*\s*planes\.append\(c\._packed_data\(w, h\)\)",
                      "for c in self._uniq: planes.append(c._packed_data(w, h))", src)
    if n0 and '_uniq' in src:
        ns = {}
        exec(compile(new, SU.__file__ + ' [benchmark in-memory patch]', 'exec'), SU.__dict__, ns)
        SU.UnifiedSorter.ensure_array = ns['ensure_array']
        msgs.append("ensure_array packs one plane per UNIQUE cloud (self._uniq) instead of per entry")

    # (2) uniform ARRAYS: 'uModels[%d]' / 'uCounts[%d]' are not resolvable names -> set the whole array
    def _vlr_set_mat4s(sh, name, mats):
        flat = [float(m[r][c]) for m in mats for c in range(4) for r in range(4)]   # column-major
        sh.uniform_vector_float(sh.uniform_from_name(name), _gpu.types.Buffer('FLOAT', len(flat), flat), 16, len(mats))

    def _vlr_set_ints(sh, name, vals):
        vals = [int(v) for v in vals]
        sh.uniform_vector_int(sh.uniform_from_name(name), _gpu.types.Buffer('INT', len(vals), vals), 1, len(vals))
    SU._vlr_set_mat4s = _vlr_set_mat4s; SU._vlr_set_ints = _vlr_set_ints
    dsrc = textwrap.dedent(inspect.getsource(SU.UnifiedSorter.draw))
    d2, n1 = re.subn(r"for i, m in enumerate\(models\):\s*\n\s*(\w+)\.uniform_float\('uModels\[%d\]' % i, m\)",
                     r"_vlr_set_mat4s(\1, 'uModels', models)", dsrc)
    d2, n2 = re.subn(r"for i, c in enumerate\(counts\):\s*\n\s*(\w+)\.uniform_int\('uCounts\[%d\]' % i, c\)",
                     r"_vlr_set_ints(\1, 'uCounts', counts)", d2)
    # (3) the DRAW shader declares uTotal but never uses it -> optimised out -> uniform_int raises
    d2, n3 = re.subn(r"sh\.uniform_int\('uTotal', total\)", "None", d2)
    # (5) v0.15.1 throttle recomputes every cloud's full xyz bbox on the CPU EVERY frame (min/max over
    # N x 3 per entry) -> O(total splats) Python/numpy work per still frame. The cloud already caches it:
    # SplatCloud.ensure_gpu() sets move_eps = extent * 0.02.
    d2, n5 = re.subn(r"ext = max\(float\(np\.linalg\.norm\(c\.d\['xyz'\]\.max\(0\)-c\.d\['xyz'\]\.min\(0\)\)\) "
                     r"for c, _m, _n in entries\)",
                     "ext = max(float(getattr(c, 'move_eps', 0.02)) / 0.02 for c, _m, _n in entries)", d2)
    if n5:
        msgs.append("throttle uses cached cloud.move_eps instead of a per-frame xyz bbox scan")
    if n1 or n2 or n3 or n5:
        ns = {}
        exec(compile(d2, SU.__file__ + ' [benchmark in-memory patch]', 'exec'), SU.__dict__, ns)
        SU.UnifiedSorter.draw = ns['draw']
        msgs.append("uModels/uCounts set as whole arrays via uniform_vector_float/int (%d mat4 loop(s), %d int loop(s))"
                    % (n1, n2))
        if n3:
            msgs.append("dropped sh.uniform_int('uTotal') on the draw shader (uniform optimised out)")
    # (4) sort_existing: histogram dispatched over ceil(N/256) groups while the scan reads s.groups
    # (the size the shared sorter was BUILT for). When a smaller N reuses a bigger sorter, the undispatched
    # groups keep STALE counts from the previous sort -> wrong offsets -> duplicates / order violations.
    R = _mod('splat_radix')
    if R is not None and hasattr(R, 'sort_existing'):
        rs = textwrap.dedent(inspect.getsource(R.sort_existing))
        rs2, n4 = re.subn(r"\(N \+ _GROUP - 1\)//_GROUP", "s.groups", rs)
        if n4:
            ns = {}
            exec(compile(rs2, R.__file__ + ' [benchmark in-memory patch]', 'exec'), R.__dict__, ns)
            R.sort_existing = ns['sort_existing']
            msgs.append("sort_existing dispatches histogram+scatter over s.groups instead of ceil(N/256) (%d site(s))" % n4)
    return ("patched in memory: " + "; ".join(msgs)) if msgs else "nothing to patch"


# ───────────────────────── timing ─────────────────────────
def timing(anchors, S):
    vls = bpy.context.scene.vertex_lit; clouds = [c for _o, c in anchors]
    r = {'hidden': bench.timed_hidden(anchors)[0]}
    for uni in (True, False):
        vls.splat_unified = uni; reset_sorts(clouds)
        if uni:
            S.array = None; S._sig = None          # force the texture-array (re)build into the first frame
        bench._gpu_sync()
        t = time.perf_counter(); draws(1)
        first = (time.perf_counter() - t) * 1000.0
        tag = 'on' if uni else 'off'
        r['first_' + tag] = first
        r['still_' + tag] = bench.time_redraws(iterations=15, repeats=3)[0]
        r['move_' + tag] = orbit_ms()
    vls.splat_unified = True; reset_sorts(clouds); draws(2)
    return r


def run():
    global bench
    try:
        if bpy.app.background:
            raise RuntimeError('--background has no GPU drawing')
        if not bpy.data.filepath or 'claude' not in bpy.data.filepath.lower():
            raise RuntimeError('refusing to run on a non-scratch file: %r' % bpy.data.filepath)
        spec = importlib.util.spec_from_file_location('benchmark_splats', BENCH)
        bench = importlib.util.module_from_spec(spec); spec.loader.exec_module(bench)
        scene = bpy.context.scene; vls = scene.vertex_lit
        scene.render.engine = 'VERTEX_LIT'
        import addon_utils
        ver = next((m.bl_info.get('version') for m in addon_utils.modules() if m.__name__ == 'vertex_lit_renderer'), None)
        stale = [o.name for o in scene.objects if o.get('vlr_splat_id') is not None]
        clear_splats()
        tree = max((o for o in scene.objects if o.type == 'MESH'), key=lambda o: len(o.data.polygons))
        win, area, region, rv3d = _view()
        with bpy.context.temp_override(window=win, area=area, region=region):
            if bpy.context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
        area.spaces.active.shading.type = 'RENDERED'; rv3d.view_perspective = 'PERSP'
        rv3d.view_rotation = Euler((math.radians(75), 0.0, math.radians(20))).to_quaternion()
        vls.splat_gpu_sort = True
        for p, v in (('splat_radix', True), ('splat_unified', True)):
            if hasattr(vls, p): setattr(vls, p, v)
        if os.environ.get('VLR_PATCH_UNIFIED') == '1':
            msg = patch_unified(); status['steps'].append(msg)
            print('[unified] TEST-ONLY PATCH:', msg)
        else:
            msg = None
        S = install_recorder()
        install_grabber()
        if msg:
            L.append("TEST-ONLY IN-MEMORY PATCH (installed files untouched): %s" % msg)
        log("UNIFIED SORT VALIDATION — addon %s | Blender %s | %s | viewport %dx%d" % (
            ver, bpy.app.version_string, bench.detect_caps()['gpu'], region.width, region.height))
        log("GPU Sort on, Radix on, Unified toggle as noted; clouds generated with Splat Softness %.1f "
            "(= unified draw default) so image diffs isolate ordering. Removed stale anchors %s." % (SIGMA, stale))
        for count in COUNTS:
            clear_splats()
            anchor, cloud = convert(tree, count)
            coll = anchor.users_collection[0]
            copies = []
            for dx, dy in GRID[1:]:
                c = anchor.copy(); c.location = anchor.location + Vector((dx, dy, 0.0)); coll.objects.link(c); copies.append(c)
            six = [(anchor, cloud)] + [(c, cloud) for c in copies]
            frame_on(six, 1.1)
            log("")
            log("=" * 96)
            log("PER-TREE %d splats, 6 trees (5 m grid), camera %.1f m" % (int(cloud.d['count']), rv3d.view_distance))
            log("=" * 96)
            S._calls = 0; S._ok = 0; S._cpu = []
            draws(5)
            log("  unified draw calls in 5 frames: %d, succeeded %d (fell back %d); CPU time per call median %.2f ms"
                % (S._calls, S._ok, S._calls - S._ok, statistics.median(S._cpu) if S._cpu else float('nan')))
            v = verify_unified(S)
            if v.get('ok'):
                log("  unified order check: %d instances, %d entries -> %d visible (CPU %d), bad instance ids %d, "
                    "undecodable %d, order violations %d (worst %.2g m), duplicates %d, culled-at-end %s; "
                    "per-tree visible %s; sigma passed by engine: %s"
                    % (v['instances'], v['total'], v['nvis'], v['cpu_vis'], v['bad_inst'], v['nan'], v['viol'],
                       v['worst'], v['dup'], v['tail_ok'], v['per_inst'], v['sigma']))
            else:
                log("  unified order check: NOT RUN (%s)" % v.get('why'))
            r = timing(six, S)
            log("  cost (ms/frame): splats hidden %.2f" % r['hidden'])
            log("    unified ON : first frame %.1f (array build) | still %.2f | moving %.2f" % (r['first_on'], r['still_on'], r['move_on']))
            log("    unified OFF: first frame %.1f              | still %.2f | moving %.2f" % (r['first_off'], r['still_off'], r['move_off']))
            order_image_test('grid6_%dk' % (count // 1000), six, cloud, anchor, S)
            angle_sweep('grid6_%dk' % (count // 1000), six, cloud, anchor, S)
            # same grid with the copies randomly rotated (Z) and uniformly scaled, as a real scene would be
            import random
            rng = random.Random(7)
            for c in copies:
                c.rotation_euler = (0.0, 0.0, rng.uniform(0.0, 2.0 * math.pi))
                sc = rng.uniform(0.8, 1.25); c.scale = (sc, sc, sc)
            draws(2)
            angle_sweep('grid6rot_%dk' % (count // 1000), six, cloud, anchor, S)
            for c in copies:
                c.rotation_euler = (0.0, 0.0, 0.0); c.scale = (1.0, 1.0, 1.0)
            draws(2)
            # two trees in line: B 7 m farther along the view direction, 1 m to the side
            for c in copies[1:]:
                bpy.data.objects.remove(c, do_unlink=True)
            b = copies[0]
            fwd = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0)); fwd.z = 0.0; fwd.normalize()
            right = rv3d.view_rotation @ Vector((1.0, 0.0, 0.0)); right.z = 0.0; right.normalize()
            b.location = anchor.location + fwd * 7.0 + right * 1.0
            two = [(anchor, cloud), (b, cloud)]
            frame_on(two, 1.0)
            draws(3)
            v2 = verify_unified(S)
            if v2.get('ok'):
                log("  2-in-line order check: %d visible (CPU %d), order violations %d, duplicates %d, culled-at-end %s"
                    % (v2['nvis'], v2['cpu_vis'], v2['viol'], v2['dup'], v2['tail_ok']))
            order_image_test('inline2_%dk' % (count // 1000), two, cloud, anchor, S)
            angle_sweep('inline2_%dk' % (count // 1000), two, cloud, anchor, S)
            bpy.data.objects.remove(b, do_unlink=True)
        status['ok'] = True
    except Exception:
        status['error'] = traceback.format_exc()
        log("!! FAILED:\n" + status['error'])
    with open(STATUS, 'w') as f:
        json.dump(status, f, indent=2)
    try: bpy.ops.wm.save_mainfile()
    except Exception as e: print('[unified] save copy failed:', e)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=5.0)
