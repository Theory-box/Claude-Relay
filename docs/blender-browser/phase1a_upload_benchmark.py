"""
Phase 1a — GPUTexture upload/draw benchmark (pre-CEF de-risk).

WHY THIS EXISTS
The collaborator review identified the single worst unknown for the in-Blender
browser: whether Blender's Python `gpu` API can push a full BGRA/RGBA frame to a
GPUTexture and draw it fast enough for ~60 fps at high resolution. There is no
partial sub-region update and no PBO path in the current gpu API, so every frame is
a FULL re-upload. This script measures that cost with synthetic frames, BEFORE any
CEF integration. If 4K/60 isn't reachable on the target machine, we adjust the design
(cap render resolution, half-rate video) now instead of after wiring CEF.

WHAT IT MEASURES (per resolution)
  Pass A: upload-only   -> wrap a fresh pixel buffer + create GPUTexture, each frame
  Pass B: upload+draw   -> same, plus draw a fullscreen textured quad into an offscreen
Each pass is flushed once at the end (a texture read forces GPU completion) so the
wall-clock throughput is honest. Per-call timing is intentionally avoided (GPU calls
are async; per-call numbers would be noise).

ALSO REPORTS
  - Blender version + gpu backend (OpenGL on 4.4, Vulkan default on 5.1) — results are
    not comparable across backends, so always note which one produced them.
  - Which Buffer dtype the RGBA8 upload path accepts (UBYTE vs FLOAT). This is a live
    Phase-0 confirmation; the real SHM frame arrives as raw bytes, so UBYTE working is
    the good case.

HOW TO RUN
  Run INTERACTIVELY (not `--background`): a real GPU context is required.
  Scripting workspace -> Text Editor -> open this file -> Run Script.
  Results print to the system console (Window > Toggle System Console on Windows).
  The benchmark runs once via a 0-second timer so it executes inside Blender's main
  loop where a GPU context is live, then unregisters itself.

CAVEATS
  - Synthetic frames only; this isolates the Blender-side cost, which is the point.
  - One byte is mutated per frame to defeat any driver-side dedup.
  - Numbers are throughput estimates for go/no-go, not microbenchmarks.
"""

import time
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

# (label, width, height)
RESOLUTIONS = [
    ("1080p", 1920, 1080),
    ("1440p", 2560, 1440),
    ("4K",    3840, 2160),
]
ITERS = 120      # timed frames per pass
WARMUP = 20      # untimed frames to prime caches/driver


def _make_ubyte_buffer(w, h, src):
    """Wrap a uint8 RGBA numpy array as a gpu.types.Buffer (the realistic SHM-bytes path)."""
    return gpu.types.Buffer('UBYTE', w * h * 4, src)


def _make_float_buffer(w, h, src_u8):
    """Fallback path if RGBA8 upload rejects UBYTE: normalized float buffer (heavier)."""
    f = (src_u8.astype(np.float32) / 255.0)
    return gpu.types.Buffer('FLOAT', w * h * 4, f)


def _detect_dtype(w, h, src):
    """Return ('UBYTE'|'FLOAT', make_fn) for whichever the GPUTexture upload accepts."""
    try:
        buf = _make_ubyte_buffer(w, h, src)
        gpu.types.GPUTexture((w, h), format='RGBA8', data=buf)
        return 'UBYTE', _make_ubyte_buffer
    except Exception as e_u:
        try:
            buf = _make_float_buffer(w, h, src)
            gpu.types.GPUTexture((w, h), format='RGBA8', data=buf)
            return 'FLOAT', _make_float_buffer
        except Exception as e_f:
            raise RuntimeError(f"Neither UBYTE nor FLOAT upload worked: {e_u} / {e_f}")


def _flush(offscreen):
    """Force GPU completion so wall-clock timing reflects real work."""
    try:
        offscreen.texture_color.read()
    except Exception:
        pass


def bench_resolution(label, w, h):
    src = np.random.randint(0, 256, size=w * h * 4, dtype=np.uint8)
    dtype, make_buf = _detect_dtype(w, h, src)

    offscreen = gpu.types.GPUOffScreen(w, h)
    shader = gpu.shader.from_builtin('IMAGE')
    batch = batch_for_shader(
        shader, 'TRI_FAN',
        {"pos": [(-1, -1), (1, -1), (1, 1), (-1, 1)],
         "texCoord": [(0, 0), (1, 0), (1, 1), (0, 1)]},
    )

    # ---- Pass A: upload only ----
    for i in range(WARMUP):
        src[i % src.size] = i & 255
        gpu.types.GPUTexture((w, h), format='RGBA8', data=make_buf(w, h, src))
    t0 = time.perf_counter()
    last_tex = None
    for i in range(ITERS):
        src[i % src.size] = i & 255
        last_tex = gpu.types.GPUTexture((w, h), format='RGBA8', data=make_buf(w, h, src))
    # touch the last texture to force the queue to drain
    with offscreen.bind():
        shader.bind()
        shader.uniform_sampler("image", last_tex)
        batch.draw(shader)
    _flush(offscreen)
    upload_ms = (time.perf_counter() - t0) * 1000.0 / ITERS

    # ---- Pass B: upload + draw ----
    for i in range(WARMUP):
        src[i % src.size] = i & 255
        tex = gpu.types.GPUTexture((w, h), format='RGBA8', data=make_buf(w, h, src))
        with offscreen.bind():
            shader.bind()
            shader.uniform_sampler("image", tex)
            batch.draw(shader)
    t0 = time.perf_counter()
    for i in range(ITERS):
        src[i % src.size] = i & 255
        tex = gpu.types.GPUTexture((w, h), format='RGBA8', data=make_buf(w, h, src))
        with offscreen.bind():
            shader.bind()
            shader.uniform_sampler("image", tex)
            batch.draw(shader)
    _flush(offscreen)
    frame_ms = (time.perf_counter() - t0) * 1000.0 / ITERS

    offscreen.free()
    fps = (1000.0 / frame_ms) if frame_ms > 0 else float('inf')
    return dtype, upload_ms, frame_ms, fps


def run():
    try:
        backend = gpu.platform.backend_type_get()
    except Exception:
        backend = "unknown"
    import bpy
    print("\n" + "=" * 64)
    print("Phase 1a — GPUTexture upload/draw benchmark")
    print(f"Blender {bpy.app.version_string}  |  gpu backend: {backend}")
    print(f"iters/pass={ITERS}  warmup={WARMUP}")
    print("-" * 64)
    print(f"{'res':6} {'dtype':6} {'upload ms':>10} {'frame ms':>10} {'frame fps':>10}")
    for label, w, h in RESOLUTIONS:
        try:
            dtype, up_ms, fr_ms, fps = bench_resolution(label, w, h)
            print(f"{label:6} {dtype:6} {up_ms:10.2f} {fr_ms:10.2f} {fps:10.1f}")
        except Exception as e:
            print(f"{label:6} FAILED: {e}")
    print("=" * 64)
    print("Read: 'frame fps' is the upload+draw ceiling. Need comfortably >60 at the")
    print("resolution you intend to render the browser at (native DPI). If 4K is short,")
    print("cap render res or half-rate video; the SHM/CEF side won't fix a GPU-upload wall.")
    print("=" * 64 + "\n")
    return None  # one-shot timer: returning None unregisters it


# Run inside Blender's main loop (live GPU context) via a one-shot timer.
import bpy  # noqa: E402
bpy.app.timers.register(run, first_interval=0.0)
print("[phase1a] benchmark scheduled — results will print to the system console.")
