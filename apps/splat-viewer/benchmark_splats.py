"""
benchmark_splats.py — drop-in benchmark for the Vertex-Lit splat renderer, built to the agreed spec.

RUN IT INSIDE BLENDER (Scripting workspace -> Open -> Run), on a scene that already has:
  - the Vertex-Lit engine active (render engine = "Vertex-Lit / VERTEX_LIT"),
  - at least one splat cloud (an "..._Splat" Empty from Convert-to-Splats),
  - a 3D viewport visible (the benchmark drives that viewport).
Or drive it unattended with auto_bench_quinn.py (launches Blender, builds the scene, calls main()).

Results are printed to the system console AND written to a text file: main(results_path), else
$VLR_BENCH_OUT, else //splat_benchmark_results.txt next to the .blend, else the temp dir.

Honesty rules baked in (do not remove):
  * Capabilities are DETECTED, never assumed. GPU timer queries are used only if verified to work;
    otherwise every number is labelled "wall-clock (submission + draw, readback-synced)" — NOT GPU time.
  * Whole-frame THROUGHPUT is measured via wm.redraw_timer (it actually redraws, so GPU work counts),
    warmed up, repeated, with variability (mean +/- stdev) reported.
  * Feature toggles are reported as WHOLE-PIPELINE deltas, not isolated per-stage GPU timings.
  * The sentinel test is DRAW-ONLY with prepared buffers (increasing dead capacity must not add sort or
    projection work) and verifies the visible image is unchanged.
  * Overdraw counts come from re-rendering the clouds with the renderer's OWN vertex shader and a
    counting fragment shader (additive float target) — exact fragment counts for this view, not timings.
  * Cross-cloud unified sorting is NOT implemented yet -> reported as PENDING, not measured.
"""
import bpy, gpu, time, statistics, math, os, sys
import numpy as np
from mathutils import Vector, Matrix


# ───────────────────────── output: console + results file ─────────────────────────
_LOG = []

def log(line=""):
    print(line)
    _LOG.append(str(line))


def _default_out_path():
    p = os.environ.get('VLR_BENCH_OUT')
    if p:
        return p
    if bpy.data.filepath:
        return bpy.path.abspath('//splat_benchmark_results.txt')
    import tempfile
    return os.path.join(tempfile.gettempdir(), 'splat_benchmark_results.txt')


# ───────────────────────── capability detection (probe, never assume) ─────────────────────────
def detect_caps():
    caps = {}
    caps['blender'] = bpy.app.version_string
    try: caps['backend'] = gpu.platform.backend_type_get()
    except Exception: caps['backend'] = '?'
    try: caps['gpu'] = gpu.platform.renderer_get()
    except Exception: caps['gpu'] = '?'
    try: caps['vendor'] = gpu.platform.vendor_get()
    except Exception: caps['vendor'] = '?'
    # GPU timer query: only trust it if the type exists AND a trivial query round-trips.
    caps['gpu_timer'] = False
    caps['gpu_timer_note'] = 'not available -> using wall-clock (submission+draw, readback-synced)'
    QT = getattr(gpu.types, 'GPUQuery', None) or getattr(gpu.types, 'GPUTimerQuery', None)
    if QT is not None:
        try:
            q = QT('TIMESTAMP') if 'TIMESTAMP' in str(QT.__init__.__doc__ or '') else QT()
            # if we can't actually read a value back, we do NOT claim GPU timing
            _ = q  # no verified read path in stock API as of writing
            caps['gpu_timer_note'] = 'GPUQuery type exists but no verified timestamp read -> NOT used'
        except Exception:
            pass
    return caps


# ───────────────────────── viewport + honest whole-frame timing ─────────────────────────
def _find_view3d():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                rv3d = area.spaces.active.region_3d
                if region and rv3d:
                    return win, area, region, rv3d
    return None


_sync_off = []

def _gpu_sync():
    """Block until the GPU has executed everything submitted so far: clear + read back one pixel of a
    tiny offscreen (GL executes in order, so the readback waits for all prior viewport draws). Without
    this, redraw_timer only measures CPU submission and GPU-side cost (fill/blend) can hide entirely."""
    try:
        if not _sync_off:
            _sync_off.append(gpu.types.GPUOffScreen(4, 4))
        with _sync_off[0].bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0, 0, 0, 0))
            fb.read_color(0, 0, 1, 1, 4, 0, 'FLOAT')
    except Exception:
        pass


def time_redraws(iterations=30, repeats=5):
    """Return (mean_ms_per_frame, stdev_ms) using wm.redraw_timer. Whole-frame, GPU work included
    (it genuinely redraws, and each timed batch ends with a GPU readback sync so queued GPU work is
    counted). Warmed up + repeated. Wall-clock throughput, not isolated per-stage GPU time."""
    v = _find_view3d()
    if v is None:
        return None, None
    win, area, region, rv3d = v
    with bpy.context.temp_override(window=win, area=area, region=region):
        # warm-up (shader compile, cache fill) — discarded
        bpy.ops.wm.redraw_timer(type='DRAW', iterations=5)
        _gpu_sync()
        samples = []
        for _ in range(repeats):
            t = time.perf_counter()
            bpy.ops.wm.redraw_timer(type='DRAW', iterations=iterations)
            _gpu_sync()
            samples.append((time.perf_counter() - t) / iterations * 1000.0)
    return statistics.mean(samples), (statistics.pstdev(samples) if len(samples) > 1 else 0.0)


# ───────────────────────── A/B whole-pipeline deltas ─────────────────────────
def ab(label, prop, on, off, results):
    """Toggle scene.vertex_lit.<prop> between on/off, measure whole-frame throughput each way,
    report the delta as a WHOLE-PIPELINE effect (not a stage timing)."""
    s = bpy.context.scene.vertex_lit
    if not hasattr(s, prop):
        results.append((label, 'n/a', 'n/a', 'prop missing'))
        return
    prev = getattr(s, prop)
    setattr(s, prop, off); m_off, sd_off = time_redraws()
    setattr(s, prop, on);  m_on,  sd_on  = time_redraws()
    setattr(s, prop, prev)
    if m_off is None:
        results.append((label, '-', '-', 'no viewport'))
        return
    delta = m_on - m_off
    results.append((label, "%.2f±%.2f" % (m_on, sd_on), "%.2f±%.2f" % (m_off, sd_off),
                    "%+.2f ms/frame (whole pipeline)" % delta))


# ───────────────────────── scaling: duplicate the tree ─────────────────────────
def scaling_test():
    anchor = next((o for o in bpy.context.scene.objects if o.get('vlr_splat_id') is not None), None)
    if anchor is None:
        return [("scaling", "no splat anchor found")]
    rows = []
    made = []
    for n in (1, 4, 16, 64):
        while len(made) < n - 1:
            d = anchor.copy()
            d.location = anchor.location + Vector((len(made)*2.5 + 2.5, 0, 0))
            bpy.context.collection.objects.link(d); made.append(d)
        m, sd = time_redraws()
        rows.append(("%d instance(s)" % n, "%.2f±%.2f ms/frame" % (m, sd) if m else "no viewport"))
    for d in made:
        bpy.data.objects.remove(d, do_unlink=True)
    return rows


# ───────────────────────── sentinel micro-benchmark (draw-only, isolated) ─────────────────────────
_SENT_VERT = """
uniform int uVisible;   // instances [0,uVisible) draw a real gaussian; the rest take the reject path
in vec2 corner; out vec2 vC; out float vDead;
void main(){
  int id = gl_InstanceID;
  vC = corner;
  if(id >= uVisible){ vDead = 1.0; gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }   // reject path
  vDead = 0.0;
  // deterministic little grid of visible splats (image must not change as dead capacity grows)
  float gx = float(id % 16) / 16.0 * 2.0 - 0.9;
  float gy = float(id / 16) / 16.0 * 2.0 - 0.9;
  gl_Position = vec4(vec2(gx, gy) + corner * 0.05, 0.0, 1.0);
}"""
_SENT_FRAG = """
in vec2 vC; in float vDead; out vec4 o;
void main(){ if(vDead>0.5) discard; float g=exp(-4.5*dot(vC,vC)); o=vec4(vec3(0.6,0.8,1.0)*g, g); }"""

def sentinel_microbench():
    """Isolate the bounded-capacity overhead: fixed visible image, increasing DEAD draw capacity,
    DRAW-ONLY (no sort/projection). Reports time vs capacity + verifies the image is unchanged."""
    from gpu_extras.batch import batch_for_shader
    try:
        W = H = 512
        off = gpu.types.GPUOffScreen(W, H)
        sh = gpu.types.GPUShader(_SENT_VERT, _SENT_FRAG)
        batch = batch_for_shader(sh, 'TRI_FAN', {"corner": [(-1,-1),(1,-1),(1,1),(-1,1)]})
    except Exception as e:
        return [("sentinel", "unavailable: %s" % e)], None
    VIS = 256
    rows = []; first_img = None
    for cap in (VIS, VIS*8, VIS*64, VIS*256, VIS*1024):   # dead = cap - VIS grows hugely
        with off.bind():
            fb = gpu.state.active_framebuffer_get(); fb.clear(color=(0,0,0,1))
            gpu.state.blend_set('ALPHA_PREMULT')
            sh.bind(); sh.uniform_int('uVisible', VIS)
            # warm + repeat, readback-synced (reading pixels forces GPU completion -> honest wall-clock)
            batch.draw_instanced(sh, instance_count=cap)
            fb.read_color(0,0,1,1,4,0,'FLOAT')
            samples=[]
            for _ in range(8):
                t=time.perf_counter()
                batch.draw_instanced(sh, instance_count=cap)
                px=fb.read_color(0,0,W,H,4,0,'FLOAT')   # readback forces completion
                samples.append((time.perf_counter()-t)*1000.0)
            buf=fb.read_color(0,0,W,H,4,0,'FLOAT'); buf.dimensions=W*H*4
            img=np.array(buf,dtype=np.float32)
        m=statistics.median(samples)
        if first_img is None: first_img=img; diff=0.0
        else: diff=float(np.abs(img-first_img).max())
        rows.append(("cap=%d (dead=%d)"%(cap,cap-VIS), "%.3f ms"%m, "img Δ=%.4f"%diff))
    off.free()
    ok = all(float(r[2].split('=')[1])<1e-4 for r in rows)
    return rows, ok


# ───────────────────────── overdraw diagnostics ─────────────────────────
def _splat_render_module():
    for name, mod in list(sys.modules.items()):
        if name.endswith('splat_render') and hasattr(mod, 'SPLAT_CLOUDS'):
            return mod
    return None


def visible_anchors():
    """[(anchor_object, SplatCloud)] for every non-hidden splat anchor in the scene."""
    sr = _splat_render_module()
    if sr is None:
        return []
    out = []
    for o in bpy.context.scene.objects:
        sid = o.get('vlr_splat_id')
        if sid is None or int(sid) not in sr.SPLAT_CLOUDS:
            continue
        if o.hide_viewport or o.hide_get():
            continue
        out.append((o, sr.SPLAT_CLOUDS[int(sid)]))
    return out


def splat_bounds(anchors):
    """World-space AABB of all given clouds (their local xyz through the anchor transform)."""
    lo = Vector((1e30,)*3); hi = Vector((-1e30,)*3)
    for o, c in anchors:
        mn = c.d['xyz'].min(0); mx = c.d['xyz'].max(0)
        for x in (mn[0], mx[0]):
            for y in (mn[1], mx[1]):
                for z in (mn[2], mx[2]):
                    p = o.matrix_world @ Vector((float(x), float(y), float(z)))
                    lo = Vector(map(min, lo, p)); hi = Vector(map(max, hi, p))
    return lo, hi


def fill_distance(rv3d, lo, hi):
    """view_distance (from the AABB centre) at which the splats just fill the viewport frame."""
    ext = hi - lo; P = rv3d.window_matrix
    horiz = max(ext.x, ext.y)
    return max(ext.z * 0.5 * P[1][1], horiz * 0.5 * P[0][0]) + horiz * 0.5


def timed_hidden(anchors):
    """Whole-frame ms with every splat anchor hidden (everything else unchanged)."""
    for o, _ in anchors:
        o.hide_set(True)
    try:
        return time_redraws()
    finally:
        for o, _ in anchors:
            o.hide_set(False)


_COUNT_FRAG = """
in vec2 vC; in vec3 vCol; in float vOp; out vec4 o;
uniform float uDepthCut;
// R = fragments that survive the colour pass's alpha cut (= blended layers), G = sum of their alpha,
// B = every fragment the rasterizer shaded (incl. the ones the real shader discards).
void main(){ float g=exp(-4.5*dot(vC,vC)); float al=vOp*g; float keep=(al<uDepthCut)?0.0:1.0;
             o=vec4(keep, keep*al, 1.0, 0.0); }"""
_count_state = {}


def _u(sh, fn, name, val):
    try: getattr(sh, fn)(name, val)
    except Exception: pass   # uniform optimised out of the counting program


def overdraw_counts(region, rv3d, anchors):
    """Re-render the visible clouds with the renderer's own EWA vertex shader + a counting fragment
    shader into an additive RGBA32F target at viewport resolution (no depth test; source mesh assumed
    hidden). Returns a dict of per-pixel overdraw statistics for the CURRENT view."""
    from gpu_extras.batch import batch_for_shader
    sr = _splat_render_module()
    W, H = region.width, region.height
    if 'sh' not in _count_state:
        _count_state['sh'] = gpu.types.GPUShader(sr._VERT, _COUNT_FRAG)
        _count_state['batch'] = batch_for_shader(_count_state['sh'], 'TRI_FAN',
                                                 {"corner": [(-1,-1),(1,-1),(1,1),(-1,1)]})
    sh = _count_state['sh']; batch = _count_state['batch']
    vm = rv3d.view_matrix; pm = rv3d.window_matrix
    right = Vector(vm[0][:3]); up = Vector(vm[1][:3]); fwd = -Vector(vm[2][:3])
    cam = vm.inverted().translation
    fx = 0.5*W*pm[0][0]; fy = 0.5*H*pm[1][1]; view_proj = pm @ vm
    backface = bool(getattr(bpy.context.scene.vertex_lit, 'splat_backface', False))
    off = gpu.types.GPUOffScreen(W, H, format='RGBA32F')
    drawn = 0
    with off.bind():
        fb = gpu.state.active_framebuffer_get(); fb.clear(color=(0, 0, 0, 0))
        gpu.state.blend_set('ADDITIVE_PREMULT')      # dst += src (exact integer counts in float32)
        gpu.state.depth_test_set('NONE'); gpu.state.depth_mask_set(False)
        for o, cloud in anchors:
            cloud.ensure_gpu()
            model = o.matrix_world.copy(); minv = model.inverted()
            cam_l = minv @ cam; fwd_l = (minv.to_3x3() @ fwd).normalized()
            idx = cloud._sorted_index(np.array(cam_l, 'f4'), np.array(fwd_l, 'f4'),
                                      view_proj @ model, backface, o.name)
            sh.bind()
            _u(sh, 'uniform_sampler', 'uData', cloud.datatex); _u(sh, 'uniform_sampler', 'uIndex', idx)
            _u(sh, 'uniform_int', 'uTW', sr._TW); _u(sh, 'uniform_int', 'uITW', cloud.itw)
            _u(sh, 'uniform_int', 'uN', int(cloud.d['count'])); _u(sh, 'uniform_int', 'uLit', 0)
            _u(sh, 'uniform_float', 'uRow0', right); _u(sh, 'uniform_float', 'uRow1', up)
            _u(sh, 'uniform_float', 'uRow2', fwd); _u(sh, 'uniform_float', 'uCam', cam)
            _u(sh, 'uniform_float', 'uF', (fx, fy)); _u(sh, 'uniform_float', 'uVP', (float(W), float(H)))
            _u(sh, 'uniform_float', 'uSigma', cloud.sigma); _u(sh, 'uniform_float', 'uViewProj', view_proj)
            _u(sh, 'uniform_float', 'uModel', model); _u(sh, 'uniform_float', 'uDepthCut', 0.004)
            batch.draw_instanced(sh, instance_count=cloud._draw_count)
            drawn += int(cloud._draw_count)
        buf = fb.read_color(0, 0, W, H, 4, 0, 'FLOAT')
        gpu.state.blend_set('NONE'); gpu.state.depth_mask_set(True)
    try:
        img = np.frombuffer(buf, dtype=np.float32).reshape(H, W, 4).copy()
    except Exception:
        buf.dimensions = W*H*4
        img = np.array(buf, dtype=np.float32).reshape(H, W, 4)
    off.free()
    layers = img[..., 0]; asum = img[..., 1]; shaded = img[..., 2]
    cov = layers > 0.5
    n = int(cov.sum())
    st = dict(W=W, H=H, instances=drawn, covered_px=n, coverage=n / float(W*H),
              blended=float(layers.sum()), shaded=float(shaded.sum()))
    if n:
        L = layers[cov]
        st.update(mean=float(L.mean()), median=float(np.median(L)), p95=float(np.percentile(L, 95)),
                  p99=float(np.percentile(L, 99)), max=float(L.max()),
                  alpha_sum=float(asum[cov].mean()))
        # Estimate of layers that actually reach the eye: with mean per-fragment alpha a, front-to-back
        # transmittance falls below 1/255 after k = ln(1/255)/ln(1-a) layers; anything past that is
        # blended but invisible. ESTIMATE (uses mean alpha, not the true per-pixel order).
        a = st['alpha_sum'] / st['mean'] if st['mean'] > 0 else 0.0
        st['mean_alpha'] = a
        if 0.0 < a < 1.0:
            k = math.log(1.0 / 255.0) / math.log(1.0 - a)
            st['visible_layers_est'] = k
            st['wasted_est'] = float(np.maximum(L - k, 0.0).sum() / L.sum())
    return st


def _fmt_overdraw(st):
    if not st.get('covered_px'):
        return "no splat pixels in view"
    s = ("coverage %.1f%% of %dx%d | layers/px mean %.1f  median %.0f  p95 %.0f  p99 %.0f  max %.0f | "
         "%.1fM blended frags, %.1fM shaded (%.0f%% discarded by alpha cut) | mean frag alpha %.2f"
         % (100*st['coverage'], st['W'], st['H'], st['mean'], st['median'], st['p95'], st['p99'], st['max'],
            st['blended']/1e6, st['shaded']/1e6, 100*(1 - st['blended']/max(st['shaded'], 1)), st['mean_alpha']))
    if 'visible_layers_est' in st:
        s += " | est. ~%.1f layers reach the eye -> ~%.0f%% of blended frags invisible (estimate)" % (
            st['visible_layers_est'], 100*st['wasted_est'])
    return s


def overdraw_diagnostics():
    """Splats shown vs hidden (at the current view and at several zooms) + per-pixel overdraw."""
    v = _find_view3d()
    anchors = visible_anchors()
    if v is None or not anchors:
        log("  (skipped: %s)" % ("no viewport" if v is None else "no visible splat anchors"))
        return
    win, area, region, rv3d = v
    space = area.spaces.active
    saved = (rv3d.view_location.copy(), rv3d.view_distance, rv3d.view_rotation.copy(), space.clip_end)
    lo, hi = splat_bounds(anchors)
    centre = (lo + hi) * 0.5
    d_fill = fill_distance(rv3d, lo, hi)
    space.clip_end = max(space.clip_end, d_fill * 50.0)
    n_splats = sum(int(c.d['count']) for _, c in anchors)
    log("  %d visible cloud(s), %d splats total; splat AABB %.2f x %.2f x %.2f"
        % (len(anchors), n_splats, *(hi - lo)))

    views = [("current view", None)]
    views += [("extreme close (0.4x)", d_fill * 0.4), ("zoomed IN (fills frame)", d_fill),
              ("mid (2x farther)", d_fill * 2.0), ("zoomed OUT (4x farther)", d_fill * 4.0)]
    rows = []
    try:
        for label, dist in views:
            if dist is not None:
                rv3d.view_location = centre; rv3d.view_distance = dist
            ms_on, sd_on = time_redraws()
            ms_off, sd_off = timed_hidden(anchors)
            st = overdraw_counts(region, rv3d, anchors)
            rows.append((label, ms_on, sd_on, ms_off, sd_off, st))
    finally:
        rv3d.view_location, rv3d.view_distance, rv3d.view_rotation, space.clip_end = saved

    log("  %-24s %-14s %-14s %-12s %-9s %s" % ("view", "splats SHOWN", "splats HIDDEN", "splat cost",
                                                "coverage", "layers/px mean / p95 / max"))
    for label, a, sa, b, sb, st in rows:
        lay = ("%.1f / %.0f / %.0f" % (st['mean'], st['p95'], st['max'])) if st.get('covered_px') else "-"
        log("  %-24s %-14s %-14s %-12s %-9s %s" % (
            label, "%.2f±%.2f" % (a, sa), "%.2f±%.2f" % (b, sb), "%+.2f ms" % (a - b),
            "%.1f%%" % (100 * st['coverage']), lay))
    log("")
    log("  Overdraw detail (exact fragment counts, re-rendered with the splat vertex shader):")
    for label, *_, st in rows:
        log("   - %s: %s" % (label, _fmt_overdraw(st)))


def overlap_stack_test(ks=(1, 2, 4, 8, 16)):
    """Fill-rate slope: stack k IDENTICAL copies of one cloud at the same transform, so blended
    fragments grow exactly k-fold while everything else stays put. Linear fit of ms/frame vs blended
    fragments gives the marginal cost of splat overdraw on this GPU (ms per 100M blended fragments),
    which extrapolates to any scene once its coverage x layers/px is known."""
    v = _find_view3d()
    anchors = visible_anchors()
    if v is None or not anchors:
        log("  (skipped: %s)" % ("no viewport" if v is None else "no visible splat anchors"))
        return
    win, area, region, rv3d = v
    space = area.spaces.active
    saved = (rv3d.view_location.copy(), rv3d.view_distance, rv3d.view_rotation.copy(), space.clip_end)
    o0, c0 = anchors[0]
    others = [o for o, _ in anchors[1:]]
    for o in others:
        o.hide_set(True)
    lo, hi = splat_bounds([(o0, c0)])
    d_fill = fill_distance(rv3d, lo, hi)
    space.clip_end = max(space.clip_end, d_fill * 50.0)
    coll = o0.users_collection[0] if o0.users_collection else bpy.context.scene.collection
    made = []
    try:
        for label, dist in (("zoomed IN (fills frame)", d_fill), ("extreme close (0.4x)", d_fill * 0.4)):
            rv3d.view_location = (lo + hi) * 0.5; rv3d.view_distance = dist
            ms_hidden, sd_hidden = timed_hidden([(o0, c0)])
            one = overdraw_counts(region, rv3d, [(o0, c0)])
            log("  %s: 1 copy = %.1fM blended frags, coverage %.1f%%, layers/px mean %.1f; splats hidden %.2f±%.2f ms"
                % (label, one['blended'] / 1e6, 100 * one['coverage'], one.get('mean', 0), ms_hidden, sd_hidden))
            pts = []
            for k in ks:
                while len(made) < k - 1:
                    d = o0.copy(); coll.objects.link(d); made.append(d)
                ms, sd = time_redraws()
                pts.append((k, k * one['blended'], ms, sd))
                log("    %2d cop%s  %8.1fM blended frags  %7.2f±%.2f ms/frame  (splat cost %+.2f ms)"
                    % (k, 'y ' if k == 1 else 'ies', k * one['blended'] / 1e6, ms, sd, ms - ms_hidden))
            x = np.array([p[1] for p in pts]); y = np.array([p[2] for p in pts])
            if len(pts) >= 2 and x.max() > x.min():
                slope, icpt = np.polyfit(x, y, 1)
                pred = slope * x + icpt
                r2 = 1 - float(((y - pred) ** 2).sum()) / max(float(((y - y.mean()) ** 2).sum()), 1e-12)
                log("    -> fit: %.2f ms per 100M blended splat fragments (intercept %.2f ms, R^2 %.3f)"
                    % (slope * 1e8, icpt, r2))
            for d in made:
                bpy.data.objects.remove(d, do_unlink=True)
            made.clear()
    finally:
        for d in made:
            bpy.data.objects.remove(d, do_unlink=True)
        for o in others:
            o.hide_set(False)
        rv3d.view_location, rv3d.view_distance, rv3d.view_rotation, space.clip_end = saved


def orbit_test(ks=(1, 4, 16), frames=48, step_deg=3.0):
    """Moving-camera cost. Every static test above reuses the cached depth sort (the CPU sort only
    re-runs after ~2 deg / 2% pan), so it can't see sort cost. Orbiting step_deg per frame forces a
    re-sort EVERY frame -> this is where splat COUNT (sort + upload) shows up, CPU vs GPU sort."""
    from mathutils import Quaternion
    v = _find_view3d()
    anchors = visible_anchors()
    if v is None or not anchors:
        log("  (skipped: %s)" % ("no viewport" if v is None else "no visible splat anchors"))
        return
    win, area, region, rv3d = v
    space = area.spaces.active
    s = bpy.context.scene.vertex_lit
    saved = (rv3d.view_location.copy(), rv3d.view_distance, rv3d.view_rotation.copy(), space.clip_end,
             bool(getattr(s, 'splat_gpu_sort', False)))
    o0, c0 = anchors[0]
    others = [o for o, _ in anchors[1:]]
    for o in others:
        o.hide_set(True)
    lo, hi = splat_bounds([(o0, c0)])
    d_fill = fill_distance(rv3d, lo, hi)
    rv3d.view_location = (lo + hi) * 0.5; rv3d.view_distance = d_fill * 2.0
    space.clip_end = max(space.clip_end, d_fill * 50.0)
    base_rot = rv3d.view_rotation.copy()
    coll = o0.users_collection[0] if o0.users_collection else bpy.context.scene.collection
    made = []

    def orbit():
        ts = []
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.wm.redraw_timer(type='DRAW', iterations=3); _gpu_sync()
            for i in range(frames):
                rv3d.view_rotation = Quaternion((0.0, 0.0, 1.0), math.radians(step_deg * (i + 1))) @ base_rot
                t = time.perf_counter()
                bpy.ops.wm.redraw_timer(type='DRAW', iterations=1)
                _gpu_sync()
                ts.append((time.perf_counter() - t) * 1000.0)
        rv3d.view_rotation = base_rot
        return statistics.mean(ts), statistics.median(ts), max(ts)

    log("  mid view (2x fill distance), orbit %.0f deg/frame x %d frames (re-sort every frame)" % (step_deg, frames))
    log("  %-9s %-9s %-6s %-13s %-28s %s" % ("clouds", "splats", "sort", "static ms", "orbit ms mean/median/max",
                                              "orbit fps"))
    try:
        for k in ks:
            while len(made) < k - 1:
                d = o0.copy(); coll.objects.link(d); made.append(d)
            for gs in (False, True):
                if hasattr(s, 'splat_gpu_sort'):
                    s.splat_gpu_sort = gs
                st, _ = time_redraws(iterations=10, repeats=3)
                om, omed, omax = orbit()
                log("  %-9d %-9s %-6s %-13s %-28s %.0f" % (
                    k, "%.1fM" % (k * c0.d['count'] / 1e6), "GPU" if gs else "CPU", "%.2f" % st,
                    "%.2f / %.2f / %.2f" % (om, omed, omax), 1000.0 / om))
    finally:
        for d in made:
            bpy.data.objects.remove(d, do_unlink=True)
        for o in others:
            o.hide_set(False)
        if hasattr(s, 'splat_gpu_sort'):
            s.splat_gpu_sort = saved[4]
        rv3d.view_location, rv3d.view_distance, rv3d.view_rotation, space.clip_end = saved[:4]


# ───────────────────────── main ─────────────────────────
def main(results_path=None):
    _LOG.clear()
    caps = detect_caps()
    log("\n" + "="*74)
    log("SPLAT RENDERER BENCHMARK")
    log("="*74)
    log("Blender %s | backend %s | GPU %s (%s)" % (caps['blender'], caps['backend'], caps['gpu'], caps['vendor']))
    log("GPU timer queries: %s" % caps['gpu_timer_note'])
    log("Timings below = wall-clock ms/frame (submission + draw, readback-synced) unless stated.\n")

    base_m, base_sd = time_redraws()
    if base_m is None:
        log("!! No 3D viewport found — open one and re-run (the benchmark drives the viewport).")
        return _write(results_path)
    v = _find_view3d()
    log("Viewport region: %dx%d" % (v[2].width, v[2].height))
    log("Baseline (current settings): %.2f ± %.2f ms/frame\n" % (base_m, base_sd))

    log("A/B whole-pipeline deltas (feature ON vs OFF):")
    ab_rows = []
    ab("GPU sort",         'splat_gpu_sort', True,  False, ab_rows)
    ab("Backface cull",    'splat_backface', True,  False, ab_rows)
    ab("Ambient occlusion",'use_ao',         True,  False, ab_rows)
    ab("Cavity",           'use_cavity',     True,  False, ab_rows)
    ab("Compute pre-pass", 'splat_compute',  True,  False, ab_rows)
    ab("Tile rasterizer",  'splat_tile',     True,  False, ab_rows)
    log("  %-18s %-16s %-16s %s" % ("feature","ON","OFF","delta"))
    for r in ab_rows: log("  %-18s %-16s %-16s %s" % r)

    log("\nOverdraw diagnostics (splats shown vs hidden, zoom, blended layers per pixel):")
    try:
        overdraw_diagnostics()
    except Exception:
        import traceback
        log("  !! overdraw diagnostics failed:\n" + traceback.format_exc())

    log("\nOverdraw fill-rate slope (k identical copies stacked in place -> k x the blended fragments):")
    try:
        overlap_stack_test()
    except Exception:
        import traceback
        log("  !! overlap stack test failed:\n" + traceback.format_exc())

    log("\nMoving camera (sort cost vs splat count):")
    try:
        orbit_test()
    except Exception:
        import traceback
        log("  !! orbit test failed:\n" + traceback.format_exc())

    log("\nScaling (duplicate the tree):")
    for name, val in scaling_test(): log("  %-16s %s" % (name, val))

    log("\nSentinel isolation (fixed visible image, growing DEAD draw capacity, DRAW-ONLY):")
    srows, sok = sentinel_microbench()
    for r in srows:
        log("  " + "  ".join(str(x) for x in r))
    if sok is not None:
        log("  -> visible image unchanged as dead capacity grows: %s" % ("PASS" if sok else "FAIL (image changed!)"))
        log("  -> the time growth across rows IS the per-dead-instance (bounded-capacity) overhead.")

    log("\nCross-cloud unified sort: PENDING — not implemented yet, so not measured here.")
    log("  (Currently each cloud sorts + composites separately; unified ordering is a design item.)")

    log("\nDiagnostic note: 'vertex-bound' vs 'fragment-bound' is an INFERENCE from the sentinel")
    log("curve (dead-instance cost = vertex/reject path) vs feature deltas — NOT a profiled fact")
    log("unless real GPU timer queries were available above.")
    log("="*74 + "\n")
    return _write(results_path)


def _write(results_path):
    path = results_path or _default_out_path()
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write("\n".join(_LOG) + "\n")
        print("[benchmark] results written to", path)
    except Exception as e:
        print("[benchmark] could not write results file:", e)
        path = None
    return path


if __name__ == "__main__":
    main()
