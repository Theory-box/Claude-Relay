"""
Phase 1a — Upload benchmark v2  (Instance B, task B-1)

Goal: settle whether Blender 4.4's `gpu` module can upload raw BGRA bytes to an
INTEGER texture (RGBA8UI) and normalize in a custom shader (usampler2D, /255), thereby
avoiding both (a) the 4x byte inflation and (b) the per-frame CPU uint8->float32
normalize that the v1 benchmark (architecture.md §15) was forced into when
GPUTexture(format='RGBA8', data=Buffer) rejected UBYTE.

What this script does (per B-1 a..e):
  (a) separates CPU-conversion time from the GPU-bound time,
  (b) preallocates all buffers — no per-frame numpy/Buffer allocation in the hot loop,
  (c) prints the EXACT exception when an RGBA8 (unorm) texture is fed a UBYTE Buffer,
  (d) benchmarks the RGBA8UI + usampler2D path head-to-head against the FLOAT path,
  (e) tests realistic panel sizes: 1280x720, 1600x900, 1920x1080, 2560x1440.

HOW TO RUN
  Run from inside Blender (Scripting workspace -> Run Script) on the SAME build/backend
  used for v1 (Blender 4.4.3, OpenGL). A real GPU context is required, so do NOT run
  with --background unless your build provides an offscreen GL context. Results print
  to the system console (Window > Toggle System Console on Windows).

NOTES ON METHOD
  - GL is asynchronous, so a pure "upload-only" vs "draw-only" split is not perfectly
    clean. We isolate what we CAN isolate exactly: t_convert (pure CPU numpy) and
    t_buffer (building the gpu.Buffer). The remaining GPU work (texture create + draw)
    is forced to complete with a 1-pixel framebuffer readback, reported as t_gpu.
  - The texture is recreated each frame on purpose: GPUTexture has no write()/subimage
    method in the Python API (full re-upload is the only path — architecture.md §9.8).
"""

import time
import numpy as np
import gpu
from gpu_extras.batch import batch_for_shader

SIZES = [(1280, 720), (1600, 900), (1920, 1080), (2560, 1440)]
WARMUP = 8
ITERS = 60

# ---- Shaders ---------------------------------------------------------------------
# Vertex shader shared by both paths: fullscreen quad in NDC.
VERT = """
in vec2 pos;
in vec2 uv;
out vec2 uv_interp;
void main() {
    uv_interp = uv;
    gl_Position = vec4(pos, 0.0, 1.0);
}
"""

# FLOAT path: normalized sampler2D. Texture already holds 0..1 unorm. Swap BGRA->RGBA.
FRAG_FLOAT = """
uniform sampler2D image;
in vec2 uv_interp;
out vec4 fragColor;
void main() {
    vec4 c = texture(image, uv_interp);
    fragColor = vec4(c.b, c.g, c.r, c.a);
}
"""

# UINT path: usampler2D returns uvec4 of raw bytes. Normalize + BGRA->RGBA in-shader.
FRAG_UINT = """
uniform usampler2D image;
in vec2 uv_interp;
out vec4 fragColor;
void main() {
    uvec4 c = texture(image, uv_interp);
    fragColor = vec4(float(c.b), float(c.g), float(c.r), float(c.a)) / 255.0;
}
"""

QUAD_POS = ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0))
QUAD_UV = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


def make_shader(frag):
    shader = gpu.types.GPUShader(VERT, frag)
    batch = batch_for_shader(
        shader, 'TRI_FAN', {"pos": QUAD_POS, "uv": QUAD_UV}
    )
    return shader, batch


def median_ms(samples):
    return sorted(samples)[len(samples) // 2] * 1000.0


def probe_ubyte_rejection(w, h):
    """B-1(c): show the EXACT exception when an RGBA8 (unorm) texture is fed UBYTE."""
    n = w * h * 4
    src = np.zeros(n, dtype=np.uint8)
    try:
        buf = gpu.types.Buffer('UBYTE', n, src)
        gpu.types.GPUTexture((w, h), format='RGBA8', data=buf)
        return "ACCEPTED (RGBA8 took a UBYTE buffer — v1's premise may not hold here)"
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def bench_float(w, h, offscreen, shader, batch):
    """FLOAT path: CPU normalize uint8->float32, upload as RGBA8."""
    n = w * h * 4
    src = (np.random.rand(n) * 255).astype(np.uint8)          # synthetic BGRA frame
    dst = np.empty(n, dtype=np.float32)                       # preallocated normalize target
    t_conv, t_buf, t_gpu = [], [], []
    for i in range(WARMUP + ITERS):
        t0 = time.perf_counter()
        np.multiply(src, np.float32(1.0 / 255.0), out=dst)    # convert (the FLOAT tax)
        t1 = time.perf_counter()
        buf = gpu.types.Buffer('FLOAT', n, dst)               # build gpu buffer
        t2 = time.perf_counter()
        tex = gpu.types.GPUTexture((w, h), format='RGBA8', data=buf)
        with offscreen.bind():
            shader.bind()
            shader.uniform_sampler("image", tex)
            batch.draw(shader)
            fb = gpu.state.active_framebuffer_get()
            _ = fb.read_color(0, 0, 1, 1, 4, 0, 'UBYTE').to_list()  # force GPU sync
        t3 = time.perf_counter()
        if i >= WARMUP:
            t_conv.append(t1 - t0); t_buf.append(t2 - t1); t_gpu.append(t3 - t2)
    return median_ms(t_conv), median_ms(t_buf), median_ms(t_gpu)


def bench_uint(w, h, offscreen, shader, batch):
    """UINT path: upload raw bytes to RGBA8UI, normalize in shader. No CPU convert."""
    n = w * h * 4
    src = (np.random.rand(n) * 255).astype(np.uint8)
    t_conv, t_buf, t_gpu = [], [], []
    for i in range(WARMUP + ITERS):
        t0 = time.perf_counter()
        # no conversion step at all
        t1 = time.perf_counter()
        buf = gpu.types.Buffer('UBYTE', n, src)
        t2 = time.perf_counter()
        tex = gpu.types.GPUTexture((w, h), format='RGBA8UI', data=buf)
        with offscreen.bind():
            shader.bind()
            shader.uniform_sampler("image", tex)
            batch.draw(shader)
            fb = gpu.state.active_framebuffer_get()
            _ = fb.read_color(0, 0, 1, 1, 4, 0, 'UBYTE').to_list()
        t3 = time.perf_counter()
        if i >= WARMUP:
            t_conv.append(t1 - t0); t_buf.append(t2 - t1); t_gpu.append(t3 - t2)
    return median_ms(t_conv), median_ms(t_buf), median_ms(t_gpu)


def run():
    print("=" * 78)
    print("Phase 1a benchmark v2 — FLOAT vs RGBA8UI integer-texture upload")
    print("backend:", gpu.platform.backend_type_get(),
          "| renderer:", gpu.platform.renderer_get())
    print("=" * 78)

    # B-1(c): does RGBA8 reject UBYTE on this build? (the whole reason for the v2 path)
    print("\n[probe] RGBA8 (unorm) fed a UBYTE buffer at 256x256:")
    print("   ->", probe_ubyte_rejection(256, 256))

    # Build shaders once. If RGBA8UI/usampler2D won't even compile, report and bail.
    sh_float, ba_float = make_shader(FRAG_FLOAT)
    try:
        sh_uint, ba_uint = make_shader(FRAG_UINT)
        uint_ok = True
    except Exception as e:
        uint_ok = False
        print(f"\n[FATAL for UINT path] usampler2D shader failed to build: "
              f"{type(e).__name__}: {e}")

    hdr = f"\n{'size':>10} | {'path':>6} | {'convert':>8} | {'buffer':>7} | {'gpu':>8} | {'total':>8} | {'fps':>6}"
    print(hdr); print("-" * len(hdr))
    for (w, h) in SIZES:
        offscreen = gpu.types.GPUOffScreen(w, h)
        try:
            for label, fn, ok, sh, ba in (
                ("FLOAT", bench_float, True, sh_float, ba_float),
                ("UINT", bench_uint, uint_ok, sh_uint if uint_ok else None,
                 ba_uint if uint_ok else None),
            ):
                if not ok:
                    print(f"{w}x{h:>5} | {label:>6} |  (skipped — shader/format unavailable)")
                    continue
                try:
                    c, b, g = fn(w, h, offscreen, sh, ba)
                    total = c + b + g
                    fps = 1000.0 / total if total > 0 else float('inf')
                    print(f"{w}x{h:>5} | {label:>6} | {c:8.2f} | {b:7.2f} | {g:8.2f} | "
                          f"{total:8.2f} | {fps:6.1f}")
                except Exception as e:
                    print(f"{w}x{h:>5} | {label:>6} |  EXCEPTION: {type(e).__name__}: {e}")
        finally:
            offscreen.free()

    print("\nInterpretation:")
    print("  - 'convert' is the FLOAT path's recurring CPU tax; UINT should show ~0.")
    print("  - If UINT 'total' beats FLOAT and RGBA8UI was accepted, the ~1440p soft")
    print("    cap (architecture.md §15) can likely be raised. If RGBA8UI is rejected,")
    print("    see the fallback ladder in instance-b-followup.md (B-1).")


run()
