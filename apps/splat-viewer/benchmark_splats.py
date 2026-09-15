"""
benchmark_splats.py — drop-in benchmark for the Vertex-Lit splat renderer, built to the agreed spec.

RUN IT INSIDE BLENDER (Scripting workspace -> Open -> Run), on a scene that already has:
  - the Vertex-Lit engine active (render engine = "Vertex-Lit / VERTEX_LIT"),
  - at least one splat cloud (an "..._Splat" Empty from Convert-to-Splats),
  - a 3D viewport visible (the benchmark drives that viewport).

Honesty rules baked in (do not remove):
  * Capabilities are DETECTED, never assumed. GPU timer queries are used only if verified to work;
    otherwise every number is labelled "wall-clock (submission + draw, readback-synced)" — NOT GPU time.
  * Whole-frame THROUGHPUT is measured via wm.redraw_timer (it actually redraws, so GPU work counts),
    warmed up, repeated, with variability (mean +/- stdev) reported.
  * Feature toggles are reported as WHOLE-PIPELINE deltas, not isolated per-stage GPU timings.
  * The sentinel test is DRAW-ONLY with prepared buffers (increasing dead capacity must not add sort or
    projection work) and verifies the visible image is unchanged.
  * Cross-cloud unified sorting is NOT implemented yet -> reported as PENDING, not measured.
"""
import bpy, gpu, time, statistics, math
import numpy as np
from mathutils import Vector, Matrix


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


def time_redraws(iterations=30, repeats=5):
    """Return (mean_ms_per_frame, stdev_ms) using wm.redraw_timer. Whole-frame, GPU work included
    (it genuinely redraws). Warmed up + repeated. This is wall-clock, not isolated GPU time."""
    v = _find_view3d()
    if v is None:
        return None, None
    win, area, region, rv3d = v
    with bpy.context.temp_override(window=win, area=area, region=region):
        # warm-up (shader compile, cache fill) — discarded
        bpy.ops.wm.redraw_timer(type='DRAW', iterations=5)
        samples = []
        for _ in range(repeats):
            t = time.perf_counter()
            bpy.ops.wm.redraw_timer(type='DRAW', iterations=iterations)
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


# ───────────────────────── main ─────────────────────────
def main():
    caps = detect_caps()
    print("\n" + "="*74)
    print("SPLAT RENDERER BENCHMARK")
    print("="*74)
    print("Blender %s | backend %s | GPU %s (%s)" % (caps['blender'], caps['backend'], caps['gpu'], caps['vendor']))
    print("GPU timer queries: %s" % caps['gpu_timer_note'])
    print("Timings below = wall-clock ms/frame (submission + draw, readback-synced) unless stated.\n")

    s = bpy.context.scene.vertex_lit
    base_m, base_sd = time_redraws()
    if base_m is None:
        print("!! No 3D viewport found — open one and re-run (the benchmark drives the viewport).")
        return
    print("Baseline (current settings): %.2f ± %.2f ms/frame\n" % (base_m, base_sd))

    print("A/B whole-pipeline deltas (feature ON vs OFF):")
    ab_rows = []
    ab("Splats present",   'splat_gpu_sort', on=getattr(s,'splat_gpu_sort',False), off=getattr(s,'splat_gpu_sort',False), results=ab_rows)  # placeholder replaced below
    ab_rows.clear()
    ab("GPU sort",         'splat_gpu_sort', True,  False, ab_rows)
    ab("Backface cull",    'splat_backface', True,  False, ab_rows)
    ab("Ambient occlusion",'use_ao',         True,  False, ab_rows)
    ab("Cavity",           'use_cavity',     True,  False, ab_rows)
    ab("Compute pre-pass", 'splat_compute',  True,  False, ab_rows)
    print("  %-18s %-16s %-16s %s" % ("feature","ON","OFF","delta"))
    for r in ab_rows: print("  %-18s %-16s %-16s %s" % r)

    print("\nScaling (duplicate the tree):")
    for name, val in scaling_test(): print("  %-16s %s" % (name, val))

    print("\nSentinel isolation (fixed visible image, growing DEAD draw capacity, DRAW-ONLY):")
    srows, sok = sentinel_microbench()
    for r in srows:
        print("  " + "  ".join(str(x) for x in r))
    if sok is not None:
        print("  -> visible image unchanged as dead capacity grows: %s" % ("PASS" if sok else "FAIL (image changed!)"))
        print("  -> the time growth across rows IS the per-dead-instance (bounded-capacity) overhead.")

    print("\nCross-cloud unified sort: PENDING — not implemented yet, so not measured here.")
    print("  (Currently each cloud sorts + composites separately; unified ordering is a design item.)")

    print("\nDiagnostic note: 'vertex-bound' vs 'fragment-bound' is an INFERENCE from the sentinel")
    print("curve (dead-instance cost = vertex/reject path) vs feature deltas — NOT a profiled fact")
    print("unless real GPU timer queries were available above.")
    print("="*74 + "\n")


if __name__ == "__main__":
    main()
