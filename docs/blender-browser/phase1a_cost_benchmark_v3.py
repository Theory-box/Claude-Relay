"""
Phase 1a v3 — STEADY-STATE cost benchmark (answers "will my computer work hard?").

v1/v2 measured PEAK throughput (flat-out). This measures the per-frame cost at realistic
panel sizes, then projects it into the load you'd actually see at a CAPPED frame rate
(30/60 fps), and states the idle cost explicitly. No CEF / no helper needed — synthetic
frames, runs in Blender alone.

RUN: Scripting workspace -> Text Editor -> Run Script (NOT --background). Output in the
system console. (Windows: Window > Toggle System Console.)

WHAT IT REPORTS, per panel size:
  convert ms : CPU cost to turn one raw BGRA frame into the FLOAT buffer 4.4 requires
  gpu ms     : cost to upload that buffer to a GPUTexture + draw it (mostly driver on a
               fast GPU; real utilization is lower than the wall time)
  Then projected steady load at 30 and 60 fps:
  cpu/core % : convert_ms * fps / 10   (approx % of ONE CPU core spent on the convert)
  these are WORST CASE: a full-frame change every single frame. Real scrolling/video
  changes less, and a STATIC page changes nothing -> ~0 cost (printed as the idle line).
"""
import time, gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

SIZES = [("720p", 1280, 720), ("900p", 1600, 900),
         ("1080p", 1920, 1080), ("1440p", 2560, 1440)]
ITERS, WARMUP = 120, 20


def bench(w, h):
    n = w * h * 4
    src = np.random.randint(0, 256, size=n, dtype=np.uint8)
    fdst = np.empty(n, dtype=np.float32)            # preallocated convert target

    # --- CPU convert cost (uint8 BGRA -> float32 normalized), isolated ---
    for i in range(WARMUP):
        src[i % n] = i & 255
        np.divide(src, 255.0, out=fdst)
    t0 = time.perf_counter()
    for i in range(ITERS):
        src[i % n] = i & 255
        np.divide(src, 255.0, out=fdst)
    convert_ms = (time.perf_counter() - t0) * 1000.0 / ITERS

    # --- GPU upload+draw cost, isolated (reuse the converted buffer) ---
    offs = gpu.types.GPUOffScreen(w, h)
    shader = gpu.shader.from_builtin('IMAGE')
    batch = batch_for_shader(shader, 'TRI_FAN',
                             {"pos": [(-1, -1), (1, -1), (1, 1), (-1, 1)],
                              "texCoord": [(0, 0), (1, 0), (1, 1), (0, 1)]})
    for _ in range(WARMUP):
        fb = gpu.types.Buffer('FLOAT', n, fdst)
        tex = gpu.types.GPUTexture((w, h), format='RGBA8', data=fb)
        with offs.bind():
            shader.bind(); shader.uniform_sampler("image", tex); batch.draw(shader)
    t0 = time.perf_counter()
    for _ in range(ITERS):
        fb = gpu.types.Buffer('FLOAT', n, fdst)
        tex = gpu.types.GPUTexture((w, h), format='RGBA8', data=fb)
        with offs.bind():
            shader.bind(); shader.uniform_sampler("image", tex); batch.draw(shader)
    try:
        offs.texture_color.read()    # force GPU completion for honest timing
    except Exception:
        pass
    gpu_ms = (time.perf_counter() - t0) * 1000.0 / ITERS
    offs.free()
    return convert_ms, gpu_ms


def run():
    import bpy
    try:
        backend = gpu.platform.backend_type_get()
    except Exception:
        backend = "unknown"
    print("\n" + "=" * 70)
    print("Phase 1a v3 — STEADY-STATE cost (per-frame cost -> projected capped load)")
    print(f"Blender {bpy.app.version_string} | backend {backend}")
    print("Idle (static page, no new frames): ~0% CPU / ~0% GPU — nothing uploads or")
    print("draws when nothing on the page changes. Cost is paid ONLY per changed frame.")
    print("-" * 70)
    print(f"{'panel':6} {'convert':>8} {'gpu':>7} | {'CPU@30fps':>9} {'CPU@60fps':>9}  (% of one core, worst case)")
    for label, w, h in SIZES:
        try:
            c, g = bench(w, h)
            cpu30 = c * 30 / 10.0
            cpu60 = c * 60 / 10.0
            print(f"{label:6} {c:7.2f}m {g:6.2f}m | {cpu30:8.1f}% {cpu60:8.1f}%")
        except Exception as e:
            print(f"{label:6} FAILED: {e}")
    print("-" * 70)
    print("How to read it:")
    print(" - 'CPU@30fps' is the convert tax if the WHOLE panel changes 30x/sec (e.g. full-")
    print("   screen 30fps video). Scrolling text or a mostly-static page costs far less.")
    print(" - The GPU upload time is mostly driver/sync on a fast card; real GPU load is low.")
    print(" - Plan: cap the browser at 30fps, render at panel size, suspend when hidden.")
    print(" - The browser ENGINE's own cost (JS, video decode) is the same as Chrome/Brave")
    print("   and is NOT included here — this is only OUR added pixel-path overhead.")
    print("=" * 70 + "\n")
    return None


import bpy  # noqa: E402
bpy.app.timers.register(run, first_interval=0.0)
print("[v3] steady-state cost benchmark scheduled — results in the system console.")
