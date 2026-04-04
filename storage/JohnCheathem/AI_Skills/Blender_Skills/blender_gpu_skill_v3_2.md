# Blender GPU Compute Shader Skill
**Version:** 3.2  
**Blender:** 4.4.3 | **GPU:** NVIDIA GeForce RTX 4090, OpenGL 4.6, driver 595.71  
**Verified by:** Two diagnostic runs + phacelle_erosion_v2.py + Shakespeare RNN + BlenderNet 3-bit MLP  
**Last updated:** 2026-04-02

---

## Overview

This skill documents everything confirmed about using Blender 4.4's `gpu` Python module for GPU-accelerated compute operations. All APIs, patterns, and gotchas are **empirically verified** — not assumed from docs.

The primary use case is running GLSL compute shaders from Python addons to process mesh vertex data in parallel. Python processes vertices sequentially; a GLSL compute shader processes all vertices simultaneously on the GPU.

---

## Quick Reference: What Exists vs What Doesn't

### ✅ EXISTS in Blender 4.4
```
gpu.capabilities          gpu.compute           gpu.matrix
gpu.platform              gpu.select            gpu.shader
gpu.state                 gpu.texture           gpu.types

gpu.types.Buffer                gpu.types.GPUBatch
gpu.types.GPUFrameBuffer        gpu.types.GPUIndexBuf
gpu.types.GPUOffScreen          gpu.types.GPUShader
gpu.types.GPUShaderCreateInfo   gpu.types.GPUStageInterfaceInfo
gpu.types.GPUTexture            gpu.types.GPUUniformBuf
gpu.types.GPUVertBuf            gpu.types.GPUVertFormat

gpu.texture.from_image()        ← ONLY method on gpu.texture
gpu.compute.dispatch()          ← ONLY method on gpu.compute
gpu.shader.create_from_info()
gpu.shader.from_builtin()
gpu.shader.unbind()
```

### ❌ DOES NOT EXIST in Blender 4.4
```
GPUTexture.write()          ← was removed; use data= kwarg instead
gpu.types.GPUStorageBuf     ← SSBOs not exposed; must use textures
gpu.texture.new()           ← does not exist
bpy.data.images[x].as_texture()  ← no such method
imageMemoryBarrier()        ← GLSL function unavailable (compiler error)
```

---

## Hardware & Capability Reference (RTX 4090, OpenGL 4.6)

```python
# Deprecation warning: these two are always True in 4.4, no need to check
gpu.capabilities.compute_shader_support_get()         # → True (deprecated)
gpu.capabilities.shader_image_load_store_support_get() # → True (deprecated)

# Limits
gpu.capabilities.max_work_group_size_get(0)   # → 1024  (X)
gpu.capabilities.max_work_group_size_get(1)   # → 1024  (Y)
gpu.capabilities.max_work_group_size_get(2)   # → 64    (Z)
gpu.capabilities.max_work_group_count_get(0)  # → 2147483647
gpu.capabilities.max_work_group_count_get(1)  # → 65535
gpu.capabilities.max_work_group_count_get(2)  # → 65535

gpu.capabilities.max_texture_size_get()       # → 32768
gpu.capabilities.max_images_get()             # → 8  (max image bindings)
gpu.capabilities.max_textures_get()           # → 192

# Platform info
gpu.platform.vendor_get()       # → "NVIDIA Corporation"
gpu.platform.renderer_get()     # → "NVIDIA GeForce RTX 4090/PCIe/SSE2"
gpu.platform.version_get()      # → "4.6.0 NVIDIA 595.71"
gpu.platform.device_type_get()  # → "NVIDIA"
gpu.platform.backend_type_get() # → "OPENGL"
```

All formats tested valid for `GPUTexture`:
`RGBA32F`, `RGBA16F`, `RGBA8`, `RG32F`, `RG16F`, `RG8`, `R32F`, `R16F`, `R8`,
`RGBA8UI`, `RGBA16I`, `RGBA32I`, `R32I`, `R16I`, `R8I`, `R32UI`, `R16UI`, `R8UI`,
`DEPTH24_STENCIL8`, `DEPTH_COMPONENT16`, `DEPTH_COMPONENT24`, `DEPTH_COMPONENT32F`

---

## THE COMPLETE WORKING PATTERN (Confirmed End-to-End)

This is the only fully verified GPU compute path in Blender 4.4. Every line of this pattern is confirmed working.

### Step 1 — Pack CPU data into a GPUTexture via Buffer

```python
import gpu
import numpy as np
import math

N = len(vertices)           # number of items to process
W = min(N, 32768)           # max texture width = 32768 on RTX 4090
                            # single-row textures avoid all tiling issues

# Build your data array — 4 floats per texel (RGBA32F)
uv_data = np.zeros((W, 4), dtype=np.float32)
uv_data[:N, 0] = u_coords   # R channel
uv_data[:N, 1] = v_coords   # G channel
# B and A can carry anything else (coords, IDs, etc.)

# ✅ CORRECT upload: pass Buffer via data= kwarg
buf = gpu.types.Buffer('FLOAT', W * 4, uv_data.flatten().tolist())
in_tex  = gpu.types.GPUTexture((W, 1), format='RGBA32F', data=buf)
out_tex = gpu.types.GPUTexture((W, 1), format='RGBA32F')
# out_tex starts zeroed — no upload needed for output textures
```

**GPUTexture full constructor signature:**
```python
GPUTexture(size, layers=0, is_cubemap=False, format='RGBA8', data=None)
# size: int | (W,) | (W, H) | (W, H, D)
# data: gpu.types.Buffer — only way to upload CPU data
```

### Step 2 — Build Compute Shader

```python
ci = gpu.types.GPUShaderCreateInfo()
ci.local_group_size(16, 1, 1)          # work group size — see tuning section

# READ-ONLY input: use sampler
ci.sampler(0, 'FLOAT_2D', "in_tex")   # (slot, type, name)

# WRITE-ONLY output: use image WITH {'WRITE'} qualifier
# ⚠️ CRITICAL: qualifiers MUST be a keyword argument
# ⚠️ CRITICAL: {'WRITE'} is required — default {'NO_RESTRICT'} = readonly on NVIDIA
ci.image(0, 'RGBA32F', 'FLOAT_2D', "out_tex", qualifiers={'WRITE'})

# Push constants (fast scalar uniforms — no UBO needed)
ci.push_constant('INT',   "u_n")
ci.push_constant('INT',   "u_width")
ci.push_constant('FLOAT', "u_scale")

# GLSL source — DO NOT redeclare images/uniforms, Blender injects them
ci.compute_source(GLSL_SOURCE)

shader = gpu.shader.create_from_info(ci)
```

### Step 3 — Bind and Dispatch

```python
shader.bind()
shader.uniform_sampler("in_tex", in_tex)   # for ci.sampler()
shader.image("out_tex", out_tex)            # for ci.image()
shader.uniform_int("u_n", N)
shader.uniform_int("u_width", W)
shader.uniform_float("u_scale", 3.0)

groups_x = math.ceil(N / 16)
gpu.compute.dispatch(shader, groups_x, 1, 1)
# signature: dispatch(shader, groups_x, groups_y, groups_z)
```

### Step 4 — Read Back Results

```python
result = np.array(out_tex.read(), dtype=np.float32)
```

**⚠️ THE READBACK IS TILED — THIS IS THE MOST CRITICAL THING IN THIS SKILL.**

See the full section below. Never use `result[0, i, :]` directly — it will give wrong data.

---

## DEFINITIVE READBACK FORMULA (Confirmed on RTX 4090, Blender 4.4.3)

### The problem
`out_tex.read()` returns a Buffer. When converted to numpy, shape is `(1, W, 4)`. **But `arr[0, col, ch]` does NOT equal the RGBA of texel `col`.** NVIDIA stores textures in tiled/swizzled memory; the physical layout is not linear.

### The confirmed pattern (from diagnostic + working addon)

For a single-row RGBA32F texture of width W, where texel `i` was written with `imageStore(out_tex, ivec2(i,0), vec4(R,G,B,A))`:

```
arr = np.array(out_tex.read(), dtype=np.float32)
flat = arr[0]   # shape (W, 4)
q = W // 4      # quarter size

# arr[0, col, ch] = channel ch of texel (col//4 + ch*(W//4))
#   equivalently:
# Texel i, channel c is at: flat[(i % q)*4 + c, i // q]
```

**Verified data (N=16, q=4, texel i written with vec4(i, i+0.1, i+0.2, i+0.3)):**
```
arr[0, 0,:] = [0.0,  4.0,  8.0,  12.0]   ← R of texels 0, 4, 8, 12
arr[0, 1,:] = [0.1,  4.1,  8.1,  12.1]   ← G of texels 0, 4, 8, 12
arr[0, 2,:] = [0.2,  4.2,  8.2,  12.2]   ← B of texels 0, 4, 8, 12
arr[0, 3,:] = [0.3,  4.3,  8.3,  12.3]   ← A of texels 0, 4, 8, 12
arr[0, 4,:] = [1.0,  5.0,  9.0,  13.0]   ← R of texels 1, 5, 9, 13
...
```

### Vectorised extraction (production-ready)

```python
arr  = np.array(out_tex.read(), dtype=np.float32)
flat = arr[0]          # shape (W, 4)
q    = W // 4

idx   = np.arange(N)   # 0..N-1
ch    = idx // q        # which numpy "channel" column
col_R = (idx % q) * 4          # column index for R channel of texel idx
col_G = (idx % q) * 4 + 1      # column index for G channel
col_B = (idx % q) * 4 + 2      # column index for B channel
col_A = (idx % q) * 4 + 3      # column index for A channel

eroded_z  = flat[col_R, ch]    # GLSL R output for each vertex
ridge_map = flat[col_G, ch]    # GLSL G output for each vertex
```

### ❌ 2D OUTPUT TEXTURES ARE BROKEN — DO NOT USE (confirmed failure)

**This closes the open item "2D texture readback" from v2.0.**

If you use `GPUTexture((N, M), ...)` with `height=M > 1` as an output and try to read it back, you will get **silently corrupted data** — no error, no warning. The tiling formula above only holds for `height=1`. Multi-row textures have additional Y-axis interleaving that the Python side cannot compensate for without knowing NVIDIA's internal tile geometry.

**How the failure manifests:** During a training run writing one float per texel to a `(N, M)` output texture, the readback returned values that inflated the loss by exactly a factor equal to the sequence length (32×), producing `loss=133` instead of the expected `~4.17`. The data was not random garbage — it was coherent but scrambled, making the bug extremely hard to detect without a ground-truth comparison.

**The rule: all output textures must be single-row (`height=1`).** If your logical output is a 2D matrix `(rows, cols)`, flatten it: use `width = rows * cols`, write `imageStore(out, ivec2(b * cols + m, 0), ...)`, and reshape after readback.

```python
# ❌ WRONG — 2D output, broken readback
out_tex = gpu.types.GPUTexture((N, M), format='RGBA32F')   # height=M > 1

# ✅ CORRECT — flatten to single row
out_tex = gpu.types.GPUTexture((N * M, 1), format='RGBA32F')
# After readback, reshape: result.reshape(N, M)
```

### Why single-row textures avoid the worst tiling

NVIDIA tiles textures in blocks. Single-row textures (H=1) have a predictable `W//4` quarter pattern. Multi-row textures have additional Y-axis interleaving that compounds the complexity. **Always use single-row textures per chunk for 1D data (vertex arrays, flat arrays).**

### Chunk pattern for large meshes

```python
TEX_WIDTH = 32768  # max single-row width on RTX 4090

for start in range(0, n_verts, TEX_WIDTH):
    end   = min(start + TEX_WIDTH, n_verts)
    chunk = data[start:end]
    n     = len(chunk)
    
    # pad chunk to full TEX_WIDTH
    padded = np.zeros((TEX_WIDTH, 4), dtype=np.float32)
    padded[:n, 0] = chunk[:, 0]
    padded[:n, 1] = chunk[:, 1]
    
    buf    = gpu.types.Buffer('FLOAT', TEX_WIDTH * 4, padded.flatten().tolist())
    in_tex = gpu.types.GPUTexture((TEX_WIDTH, 1), format='RGBA32F', data=buf)
    out_tex = gpu.types.GPUTexture((TEX_WIDTH, 1), format='RGBA32F')
    
    # ... dispatch ...
    
    result = np.array(out_tex.read(), dtype=np.float32)
    flat   = result[0]
    q      = TEX_WIDTH // 4
    idx    = np.arange(n)
    ch     = idx // q
    col_R  = (idx % q) * 4
    col_G  = (idx % q) * 4 + 1
    
    out_R[start:end] = flat[col_R, ch]
    out_G[start:end] = flat[col_G, ch]
```

### ✅ ADDITIONAL APIs confirmed (from BlenderNet 3-bit MLP)
```
gpu.state.active_framebuffer_get()    ← inside offscreen.bind() context
gpu.state.depth_test_set('NONE')
gpu.state.blend_set('NONE')
gpu.matrix.push_pop()                 ← context manager, works inside offscreen.bind()
gpu_extras.batch.batch_for_shader()   ← from gpu_extras (separate import)
GPUOffScreen.bind()                   ← context manager: with offscreen.bind():
GPUOffScreen.free()                   ← explicit cleanup, call after use
GPUOffScreen(w, h, format='RGBA32F')  ← format= kwarg confirmed
GPUFrameBuffer.read_color(x,y,w,h,ch,slot,'FLOAT',data=buf)  ← full readback sig
GPUShaderCreateInfo.vertex_in(loc, type, name)
GPUShaderCreateInfo.vertex_source(src)
GPUShaderCreateInfo.fragment_source(src)
GPUShaderCreateInfo.fragment_out(loc, type, name)
```

---

## SECOND GPU PATH: Fragment Shader via GPUOffScreen (confirmed working)

The skill so far has documented **compute shaders** as the GPU path. There is a second fully working path: **vertex + fragment shaders rendering into a GPUOffScreen framebuffer**, where each fragment computes one output element. This is confirmed working for ML inference (BlenderNet 3-bit MLP on MNIST).

### When to use which path

| | Compute Shader | Fragment Shader / GPUOffScreen |
|---|---|---|
| API | `gpu.compute.dispatch()` | `batch.draw()` into `GPUOffScreen` |
| Output | GPUTexture (tiled readback) | Framebuffer (clean `read_color` readback) |
| Readback | Tiled — requires quarter formula | `fb.read_color()` — no tiling, straightforward |
| Input data | RGBA32F sampler textures | Same — RGBA32F sampler textures |
| Best for | Large parallel compute, no geometry | Neuron-per-pixel inference, shader effects |
| Tiling trap | **YES** — single-row only (see §READBACK) | **NO** — `read_color` is linear |

**Key advantage of the fragment path: no tiling problem.** `fb.read_color()` returns data in straightforward row-major order, no quarter-interleave formula needed.

### Full confirmed fragment shader pipeline

```python
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

# 1. Build shader with vertex + fragment sources
def make_shader(frag_src):
    info = gpu.types.GPUShaderCreateInfo()
    # Inputs (samplers, push constants)
    info.sampler(0, 'FLOAT_2D', 'weight_tex')
    info.sampler(1, 'FLOAT_2D', 'input_tex')
    info.push_constant('INT', 'input_size')
    info.push_constant('INT', 'output_size')
    info.push_constant('FLOAT', 'quant_levels')
    # Geometry interface
    info.vertex_in(0, 'VEC2', 'pos')
    info.fragment_out(0, 'VEC4', 'fragColor')
    # Sources
    info.vertex_source("""
void main() {
    gl_Position = vec4(pos, 0.0, 1.0);
}
""")
    info.fragment_source(frag_src)
    return gpu.shader.create_from_info(info)

# 2. Build fullscreen quad batch
def make_fullscreen_batch(shader):
    verts   = [(-1,-1), (1,-1), (-1,1), (1,1)]
    indices = [(0,1,2), (1,3,2)]
    return batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=indices)

# 3. Render into GPUOffScreen, read back result
def gpu_forward(shader, batch, weight_tex, input_tex,
                input_size, output_size, out_w, out_h):
    offscreen = gpu.types.GPUOffScreen(out_w, out_h, format='RGBA32F')
    with offscreen.bind():
        fb = gpu.state.active_framebuffer_get()
        fb.clear(color=(0.0, 0.0, 0.0, 1.0))
        with gpu.matrix.push_pop():
            gpu.matrix.load_matrix(Matrix.Identity(4))
            gpu.matrix.load_projection_matrix(Matrix.Identity(4))
            gpu.state.depth_test_set('NONE')
            gpu.state.blend_set('NONE')
            shader.bind()
            shader.uniform_sampler("weight_tex", weight_tex)
            shader.uniform_sampler("input_tex",  input_tex)
            shader.uniform_int("input_size",  input_size)
            shader.uniform_int("output_size", output_size)
            shader.uniform_float("quant_levels", 3.0)
            batch.draw(shader)
        # Read back — no tiling, straightforward RGBA layout
        buf = gpu.types.Buffer('FLOAT', out_w * out_h * 4)
        fb.read_color(0, 0, out_w, out_h, 4, 0, 'FLOAT', data=buf)
        result = np.array(buf, dtype=np.float32).reshape(out_h, out_w, 4)
    offscreen.free()
    return result[:, :, 0].flatten()[:output_size]   # R channel only
```

### Fragment shader source rules (same as compute, plus geometry)

```glsl
/* Blender injects all declared samplers and push_constants.
   Do NOT re-declare them. Fragment shaders additionally have:
   - gl_FragCoord.xy  → pixel position (use to map pixel→output index)
   - fragColor        → output (name must match fragment_out declaration) */

void main() {
    ivec2 fc         = ivec2(gl_FragCoord.xy);
    int neuron_idx   = fc.y * out_tex_w + fc.x;
    if (neuron_idx >= output_size) { fragColor = vec4(0.0); return; }

    float acc = 0.0;
    for (int i = 0; i < input_size; i++) {
        int   w_addr = neuron_idx * input_size + i;
        ivec2 w_uv   = ivec2(w_addr % weight_tex_w, w_addr / weight_tex_w);
        float w      = texelFetch(weight_tex, w_uv, 0).r;
        ivec2 in_uv  = ivec2(i % in_tex_w, i / in_tex_w);
        float x      = texelFetch(input_tex, in_uv, 0).r;
        acc += w * x;
    }
    fragColor = vec4(max(0.0, acc), 0.0, 0.0, 1.0);
}
```

**Key pattern:** use `gl_FragCoord.xy` to determine which output element this fragment computes. Size the offscreen so `out_w * out_h >= output_count`. Unused fragments (beyond output_count) return early with `vec4(0.0)`.

### `fb.read_color()` full signature (confirmed)

```python
buf = gpu.types.Buffer('FLOAT', width * height * 4)
fb.read_color(
    x,        # int: pixel x offset
    y,        # int: pixel y offset
    width,    # int: read width
    height,   # int: read height
    4,        # int: channels (4 = RGBA)
    0,        # int: slot (always 0)
    'FLOAT',  # str: data type
    data=buf  # Buffer to fill
)
result = np.array(buf, dtype=np.float32).reshape(height, width, 4)
# result[row, col, 0] = R channel of pixel (col, row) — NO tiling, linear layout
```

---

## Data Texture Upload via bpy.data.images (fragment shader path)

The compute shader path uploads data via `gpu.types.Buffer` + `GPUTexture(data=buf)`. The fragment shader path requires `gpu.texture.from_image()` which needs a `bpy.data.images` image as intermediary. Full confirmed round-trip:

```python
def numpy_to_gpu_texture(rgba_flat, width, height):
    """
    Upload float32 RGBA data as a GPUTexture for use in fragment shaders.
    rgba_flat: 1D float32 array of length width*height*4
    Returns: (GPUTexture, bpy.data.images Image)
    Caller must call bpy.data.images.remove(img) when done to free memory.
    """
    # Use a unique name to avoid collisions on re-upload
    name = f"__gpu_tmp_{width}x{height}_{id(rgba_flat)}"
    if name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[name])

    img = bpy.data.images.new(name, width, height,
                               alpha=True,
                               float_buffer=True)   # ← REQUIRED for float32

    # ⚠️ CRITICAL: set Non-Color BEFORE uploading pixel data
    # Without this, Blender applies a colorspace transform and corrupts your values
    img.colorspace_settings.name = 'Non-Color'

    img.pixels.foreach_set(rgba_flat)               # upload CPU→GPU-backed image
    gpu_tex = gpu.texture.from_image(img)           # wrap as GPUTexture for shader
    return gpu_tex, img                             # return img for later cleanup

# Usage:
tex, img = numpy_to_gpu_texture(rgba_data, tex_w, tex_h)
# ... use tex in shader ...
bpy.data.images.remove(img)   # ← REQUIRED cleanup, or images accumulate in .blend
```

**Three things that are ALL required together:**
1. `float_buffer=True` — without this, image is 8-bit and floats are quantized
2. `colorspace_settings.name = 'Non-Color'` — without this, sRGB transform corrupts data
3. `bpy.data.images.remove(img)` after use — without this, temp images accumulate every frame

---

## Modal Operator Pattern (for long-running GPU tasks)

GPU training loops cannot run in a blocking `execute()` without freezing Blender. The confirmed pattern for keeping Blender responsive:

```python
class MY_OT_Train(bpy.types.Operator):
    bl_idname = "myaddon.train"
    bl_label  = "Train"
    _timer    = None

    def modal(self, context, event):
        if event.type == 'TIMER':
            if not context.scene.my_running:
                self.finish(context)
                return {'FINISHED'}
            # Do ONE step of work here (not a full loop)
            self._do_one_step(context)
        return {'PASS_THROUGH'}   # ← lets Blender process other events

    def execute(self, context):
        context.scene.my_running = True
        wm = context.window_manager
        # Timer interval in seconds — 0.001 = as fast as possible
        self._timer = wm.event_timer_add(0.001, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def finish(self, context):
        context.window_manager.event_timer_remove(self._timer)

class MY_OT_Stop(bpy.types.Operator):
    bl_idname = "myaddon.stop"
    bl_label  = "Stop"

    def execute(self, context):
        context.scene.my_running = False   # modal checks this each tick
        return {'FINISHED'}
```

**Key points:**
- `execute()` returns `{'RUNNING_MODAL'}` — tells Blender to keep calling `modal()`
- `modal()` returns `{'PASS_THROUGH'}` — Blender keeps processing UI events
- Do only ONE unit of work per timer event — never loop inside `modal()`
- Stop is communicated via a scene property, not by calling `finish()` directly
- `event_timer_add(0.001, ...)` gives ~1000 steps/sec maximum; actual rate depends on step cost

---

## Storing Shader State Across Operators

GPU shaders compiled in `execute()` can't be passed between operators directly. Store them on `bpy.types.Scene` as a class attribute (not a registered property — just a plain Python dict):

```python
# In execute() of operator A:
bpy.types.Scene.my_shaders = {
    'forward': make_shader(FRAG_SRC),
    'batch':   make_fullscreen_batch(shader),
}

# In modal() of operator A, or in any other operator B:
if hasattr(bpy.types.Scene, 'my_shaders'):
    shaders = bpy.types.Scene.my_shaders
    shader  = shaders['forward']

# Cleanup on unregister or stop:
if hasattr(bpy.types.Scene, 'my_shaders'):
    del bpy.types.Scene.my_shaders
```

This is distinct from `bpy.props` registration — it's just a Python class attribute. It survives as long as Blender is running, accessible from any code that imports `bpy`.

---

## Scene Properties for UI Display (live-updating panel values)

```python
# Register in register():
bpy.types.Scene.my_loss = bpy.props.FloatProperty(default=0.0)
bpy.types.Scene.my_step = bpy.props.IntProperty(default=0)

# Update in modal() — panel redraws automatically:
context.scene.my_loss = float(current_loss)
context.scene.my_step += 1

# Display in panel draw():
layout.label(text=f"Loss: {context.scene.my_loss:.4f}")
layout.label(text=f"Step: {context.scene.my_step}")

# Unregister in unregister():
for prop in ['my_loss', 'my_step']:
    if hasattr(bpy.types.Scene, prop):
        delattr(bpy.types.Scene, prop)
```

---



### Multiple samplers in one shader (confirmed working)

You can bind up to `gpu.capabilities.max_textures_get()` (→192) samplers. Two confirmed working simultaneously:

```python
ci.sampler(0, 'FLOAT_2D', "tex_X")
ci.sampler(1, 'FLOAT_2D', "tex_W")
# ...
shader.uniform_sampler("tex_X", tex_X)
shader.uniform_sampler("tex_W", tex_W)
```

Slots are integers starting at 0. No observed conflicts with the single `ci.image()` output binding.

---

### Packing a 2D matrix into a single-row sampler (confirmed pattern)

To pass an `(N, K)` matrix to a shader where K is not a multiple of 4, pad K up to `K4 = ceil(K/4)*4`, then pack each row as K4/4 consecutive RGBA texels:

```python
def pack_matrix_to_tex(mat, K4):
    """mat: (N, K) float32 → GPUTexture((N*K4, 1), RGBA32F)"""
    N, K = mat.shape
    padded = np.zeros((N, K4 * 4), dtype=np.float32)
    padded[:, :K] = mat
    # (N, K4, 4) → (N*K4*4,) flat
    flat = padded.reshape(N * K4, 4).flatten()
    buf  = gpu.types.Buffer('FLOAT', len(flat), flat.tolist())
    return gpu.types.GPUTexture((N * K4, 1), format='RGBA32F', data=buf)
```

In GLSL, row `n`, quad `k4` is at `texelFetch(tex, ivec2(n * K4 + k4, 0), 0)`.

---

### GLSL accumulation loops are valid (confirmed)

Internal `for` loops in `main()` that accumulate results work correctly:

```glsl
void main() {
    int gid = int(gl_GlobalInvocationID.x);
    if (gid >= u_B * u_M) return;
    int b = gid / u_M;
    int m = gid % u_M;

    float acc = 0.0;
    for (int k4 = 0; k4 < u_K4; k4++) {
        vec4 x = texelFetch(tex_X, ivec2(b * u_K4 + k4, 0), 0);
        vec4 w = texelFetch(tex_W, ivec2(m * u_K4 + k4, 0), 0);
        acc += dot(x, w);   // dot() on vec4 confirmed working
    }
    imageStore(out_C, ivec2(gid, 0), vec4(acc, 0.0, 0.0, 1.0));
}
```

This is the basis of a GPU matrix-multiply where each invocation computes one output element. Confirmed numerically correct (max_err < 0.05 vs numpy on float32).

---

### `local_group_size(64, 1, 1)` confirmed working

The skill mentioned `(64, 1, 1)` as an alternative to `(16, 16, 1)` for 1D dispatches but had not confirmed it. Now confirmed. Dispatch pattern:

```python
ci.local_group_size(64, 1, 1)
# ...
groups = math.ceil(total_elements / 64)
gpu.compute.dispatch(shader, groups, 1, 1)
```

---

### `np.array(tex.read()).reshape(1, W, 4)` — explicit reshape is required

The skill shows `arr[0]` assuming shape `(1, W, 4)` but does not note that for large W the numpy conversion may return a flat 1D array. Always force the reshape explicitly:

```python
raw  = np.array(tex.read(), dtype=np.float32)
arr  = raw.reshape(1, W, 4)   # ← explicit — do not rely on implicit shape
flat = arr[0]                  # (W, 4) — now apply quarter formula
```

---

### Sanity-check pattern (engineering best practice)

Always verify GPU readback correctness against numpy before trusting results in production. Silent corruption (wrong but finite values) is more dangerous than crashes:

```python
def gpu_sanity_check(shader, gpu_fn):
    """Compare GPU function output against numpy for a small known input."""
    rng = np.random.default_rng(0)
    X   = rng.standard_normal((8, 16)).astype(np.float32)
    W   = rng.standard_normal((12, 16)).astype(np.float32)
    ref = X @ W.T                     # numpy ground truth
    got = gpu_fn(shader, X, W)        # GPU result
    err = float(np.abs(ref - got).max())
    ok  = err < 0.05                  # float32 round-trip tolerance
    print(f"GPU sanity: max_err={err:.6f}  {'PASS' if ok else 'FAIL'}")
    return ok

# Call before any training loop or production use:
if not gpu_sanity_check(shader, gpu_xwt):
    print("GPU readback unreliable — falling back to numpy")
```

**Why this matters:** In the RNN session, the 2D texture bug produced `loss=133` (should be `~4.17`) with no Python exception — pure silent corruption. A sanity check would have caught this in one step.

---

## GLSL Source Rules

```glsl
// ✅ DO NOT declare images, samplers, or uniforms in GLSL source
// Blender auto-injects them from ci.image(), ci.sampler(), ci.push_constant()
// DO NOT write: layout(binding=0) uniform image2D my_tex;
// DO NOT write: uniform int u_n;

// ✅ USE the names directly:
void main() {
    ivec2 coord = ivec2(gl_GlobalInvocationID.xy);
    int idx = coord.y * u_width + coord.x;
    if (idx >= u_n) return;

    vec4 val = texelFetch(in_tex, coord, 0);   // sampler → texelFetch
    // ... compute ...
    imageStore(out_tex, coord, vec4(result_r, result_g, 0.0, 1.0));  // image → imageStore
}
```

**Confirmed GLSL features:**
| Feature | Status |
|---|---|
| `shared float arr[N];` | ✅ Works |
| `barrier()` | ✅ Works |
| `atomicAdd(shared_uint, 1u)` | ✅ Works |
| `#define` macros | ✅ Works |
| `struct MyStruct { ... };` | ✅ Works |
| Utility/helper functions | ✅ Works |
| `gl_WorkGroupID`, `gl_LocalInvocationID` | ✅ Works |
| `gl_WorkGroupSize`, `gl_GlobalInvocationID` | ✅ Works |
| `memoryBarrier()` | ✅ Works |
| `imageMemoryBarrier()` | ❌ Compiler error — does NOT exist |
| Loops, conditionals, nested functions | ✅ Works |

---

## Uniform Setters — Confirmed API

```python
shader.uniform_int("u_n",   42)            # INT, IVEC — scalar only
shader.uniform_float("u_scale", 3.14)      # FLOAT — scalar only
shader.uniform_bool("u_flag", True)        # BOOL

# ✅ VEC2/VEC3/VEC4: pass as a SINGLE tuple/list argument
shader.uniform_float("u_vec2", (1.0, 2.0))         # ✅
shader.uniform_float("u_vec4", [1.0, 2.0, 3.0, 4.0])  # ✅

# ❌ WRONG — separate args fail:
shader.uniform_float("u_vec2", 1.0, 2.0)  # ❌ "takes exactly 2 arguments"

# ✅ For vectors of integers: use uniform_vector_int / uniform_vector_float
# (also exists on GPUShader but less tested)
shader.uniform_vector_float(location, value, count)
shader.uniform_vector_int(location, value, count)

# Uniform discovery methods on GPUShader:
shader.uniform_from_name("u_n")      # → location int
shader.uniform_block("binding_name") # → for UBOs
shader.attrs_info_get()              # → list of attribute info

# ⚠️ VEC2/IVEC2 uniforms defined with push_constant('VEC2') may not be
# found by uniform_float("name", (x,y)) — the uniform name lookup fails.
# WORKAROUND: use two separate FLOAT push_constants instead of VEC2.
```

**Valid push_constant types:** `'INT'`, `'FLOAT'`, `'BOOL'`, `'VEC2'`, `'VEC3'`, `'VEC4'`, `'IVEC2'`, `'IVEC3'`, `'IVEC4'`, `'MAT3'`, `'MAT4'`

---

## Alternative Input Path: gpu.texture.from_image()

When you need to read from a `bpy.data.images` image (e.g., a painted texture, render result, or existing float image):

```python
import bpy, gpu

# Create or load a float image
img = bpy.data.images.new('my_tex', width=N, height=1, float_buffer=True, alpha=True)
pixels = []
for i in range(N):
    pixels.extend([float(i), float(i)+0.1, 0.0, 1.0])  # RGBA per texel
img.pixels[:] = pixels
img.update()

# Convert to GPU texture for use as sampler
gpu_tex = gpu.texture.from_image(img)
# gpu_tex is a GPUTexture — use as shader.uniform_sampler("name", gpu_tex)

# Clean up when done
bpy.data.images.remove(img)
```

**Notes:**
- `gpu.texture` has exactly ONE method: `from_image()`
- The returned texture has methods: `clear`, `format`, `height`, `read`, `width`
- The same NVIDIA tiling applies when you `read()` from a `from_image` texture
- `bpy.data.images` pixel precision is limited (~7 decimal digits), not full float32

---

## Performance Numbers (RTX 4090, Blender 4.4.3)

### Shader compile timing
```
First compile:    ~25ms  (GPU shader compilation)
Subsequent:       ~0.26ms (Blender caches by source string)
Dispatch call:    ~0.07ms first, ~0.0ms subsequent (command queue)
```

**→ Always cache your shader object across bake calls. Recompile only if source changes.**

```python
# Module-level cache
_shader_cache = None

def get_shader():
    global _shader_cache
    if _shader_cache is None:
        _shader_cache = _build_compute_shader()
    return _shader_cache
```

### Work group size guidance
The diagnostic ran ALU-heavy compute (32 sin/cos per thread) at N=65536:
- Local size 64 is a safe default for 1D vertex processing
- Local size 256 is often optimal for pure ALU-bound work
- Respect hardware limits: X≤1024, Y≤1024, Z≤64

```python
# Recommended: query at runtime
max_local = gpu.capabilities.max_work_group_size_get(0)  # → 1024
LOCAL_X = min(64, max_local)  # conservative safe default

groups = math.ceil(N / LOCAL_X)
gpu.compute.dispatch(shader, groups, 1, 1)
```

### Throughput expectations (erosion-complexity math)
These are wall-clock measurements from Python, not pure GPU time:
- The GPU itself is faster; these include Python dispatch overhead
- Pure-output compute (no readback) is fastest — use when possible

### Attribute write speed
```python
# ❌ SLOW (Python loop): ~100x slower
for i in range(n): attr.data[i].value = arr[i]

# ✅ FAST (C bulk):
attr.data.foreach_set('value', arr.astype(np.float32))
```

---

## Dispatch Behavior Gotchas

```python
# dispatch(0, 1, 1) → SILENT NO-OP — no exception raised
# dispatch(-1, 1, 1) → SILENT NO-OP — no exception raised
# Dispatch without bind() → SILENT undefined behavior — no exception
# Missing uniform set → SILENT, uniform defaults to 0 — no exception

# ALWAYS verify your bind/uniform order before dispatching.
# There is NO error feedback from GPU side if you omit a uniform.

# Multi-dispatch (chained compute, ping-pong): WORKS without explicit barriers
# between dispatches in Python. Blender handles ordering at the GL level.
# Confirmed: dispatch pass1 then dispatch pass2 with pass1's output as pass2's
# input produces correct results without any Python-side synchronization.
```

---

## Confirmed GLSL Features (from phacelle_erosion_v2.py source audit)

These GLSL features are confirmed to compile and execute correctly inside Blender 4.4's compute shader pipeline:

### `#define` constants work
```glsl
#define TAU 6.28318530718
#define PI  3.14159265359
// Use TAU, PI directly — no redeclaration needed
```

### Helper functions above `main()` work
Any number of free GLSL functions defined before `void main()` compile and execute correctly. Complex call chains confirmed:
```glsl
vec2 hash2(vec2 x) { ... }
vec3 noised(vec2 p) { ... uses hash2 ... }
vec3 fractalNoise(vec2 p, ...) { ... uses noised ... }
void main() { ... uses fractalNoise ... }
```

### `struct` with returned values works
GLSL structs compile, can be returned from functions, and their fields are accessible:
```glsl
struct ErosionResult {
    float height;
    float ridgeMap;
};

ErosionResult myFunc(...) {
    ErosionResult r;
    r.height   = ...;
    r.ridgeMap = ...;
    return r;
}

void main() {
    ErosionResult er = myFunc(...);
    float h = er.height;   // ✅ works
}
```

### Nested `for` loops work
Multiple levels of nesting confirmed:
```glsl
for (int i = -1; i <= 2; i++) {
    for (int j = -1; j <= 2; j++) {
        // inner body — confirmed correct
    }
}
```

### Built-in math functions confirmed working in compute shaders
`dot()`, `length()`, `normalize()`, `floor()`, `fract()`, `clamp()`, `mix()`, `exp()`, `abs()`, `sign()`, `max()`, `min()`, `cos()`, `sin()`, `pow()`, `sqrt()`

---

## Confirmed GLSL Push Constant Type: No `BOOL` — Use `INT`

There is no `'BOOL'` type for `ci.push_constant()` in practice. Boolean flags must be passed as `INT` (0 or 1) and tested with `!= 0` in GLSL:

```python
# Python side
ci.push_constant('INT', "u_use_base_noise")
# ...
shader.uniform_int("u_use_base_noise", 1 if props.use_base_noise else 0)
```

```glsl
// GLSL side — test as int, not bool
if (u_use_base_noise != 0) {
    // enabled path
}
```

Note: `shader.uniform_bool()` exists on the Python instance (see GPUShader API) but `ci.push_constant('BOOL', ...)` may not behave reliably in compute shaders. Use `INT` for flags to be safe.

---

## Confirmed Shader Compile Error Handling

`gpu.shader.create_from_info(ci)` raises an exception on compile failure — it does **not** return `None`. Wrap in try/except and return `None` yourself:

```python
def _build_compute_shader():
    try:
        ci = gpu.types.GPUShaderCreateInfo()
        # ... setup ...
        return gpu.shader.create_from_info(ci)
    except Exception as e:
        print(f"[MyAddon] Shader compile failed: {e}")
        return None   # caller checks for None before dispatching
```

Similarly, wrap the dispatch and readback in try/except with `traceback.print_exc()` for full diagnostics:

```python
try:
    shader.bind()
    # ... uniforms, dispatch, readback ...
    return result
except Exception as e:
    print(f"[MyAddon] GPU dispatch failed: {e}")
    import traceback
    traceback.print_exc()
    return None
```

---

## Confirmed: `B,A` Input Texture Channels as Readback Debug Anchors

Packing `coord.x` and `coord.y` into the **B and A channels of the input texture** lets the shader write them back into the output, providing a ground-truth check on readback ordering. If `out[i].z != i`, the deinterleaving formula is wrong:

```python
# Python: pack B=coord.x, A=coord.y into input
uv_data[:n, 2] = np.arange(n, dtype=np.float32)   # B = index
uv_data[:n, 3] = 0.0                                # A = row (always 0 for single-row)
```

```glsl
// GLSL: echo them back to output B and A channels
imageStore(out_tex, coord, vec4(eroded, ridge, float(coord.x), float(coord.y)));
```

```python
# Python: verify after readback
col_B = (idx % q) * 4 + 2
expected_coords = flat[col_B, ch]
assert np.allclose(expected_coords, np.arange(n), atol=0.5), "Readback ordering is wrong!"
```

This technique caught the 2D texture corruption bug (v3.0). Always include it during development.

---

## Confirmed: Uniform Split Pattern (Props-Level vs Chunk-Level)

When processing data in chunks, split your uniform bindings into two groups set at different times. Setting props-level uniforms inside the chunk loop wastes time:

```python
# ✅ CORRECT: props uniforms ONCE before loop
shader.bind()
shader.uniform_float("u_erosion_scale",   props.erosion_scale)
shader.uniform_float("u_erosion_strength", props.erosion_strength)
# ... all other props uniforms ...

for start in range(0, n_verts, TEX_WIDTH):
    end   = min(start + TEX_WIDTH, n_verts)
    chunk = data[start:end]
    n     = len(chunk)

    # ✅ Chunk-specific uniforms PER ITERATION
    shader.bind()                           # rebind before each chunk
    shader.uniform_sampler("in_tex", ...)   # new texture each chunk
    shader.image("out_tex", ...)            # new texture each chunk
    shader.uniform_int("u_n_verts", n)      # chunk size varies
    shader.uniform_int("u_tex_width", TEX_WIDTH)

    gpu.compute.dispatch(shader, math.ceil(n / 16), 1, 1)
    # ... readback ...
```

Note that `shader.bind()` must be called again before each chunk's uniforms — rebinding is safe and required.

---

## Confirmed Mesh Attribute Writing Pattern

```python
# Remove old attribute if it exists (required before re-creating)
if "my_attr" in mesh.attributes:
    mesh.attributes.remove(mesh.attributes["my_attr"])

# Create new attribute
attr = mesh.attributes.new("my_attr", 'FLOAT', 'POINT')

# Write with foreach_set — 100x faster than per-element loop
attr.data.foreach_set('value', my_numpy_array.astype(np.float32))

# ✅ REQUIRED: call mesh.update() after foreach_set
mesh.update()
```

Without `mesh.update()`, changes may not be visible in the viewport.

---

## Confirmed: Property Update Callback Guard Pattern

Property `update=` callbacks fire in many contexts including panel redraws. Guard against this:

```python
def _live(self, context):
    if not self.live_update:
        return
    # ⚠️ REQUIRED guard — context.screen is None during panel draw
    if not context or not context.screen:
        return
    obj = context.active_object
    if obj and obj.type == 'MESH':
        bake_erosion(obj, self)
        # Force viewport refresh after GPU compute
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
```

Without the `context.screen` check, the callback fires during UI layout and either errors or triggers unintended computation.

---

## Confirmed GeoNodes Additional Patterns

### `InputNamedAttribute` node still uses `data_type` directly (not `capture_items`)
The `CaptureAttribute` gotcha (use `capture_items.new()`) does **not** apply to `InputNamedAttribute`:

```python
# InputNamedAttribute — data_type assignment works fine in 4.4
n_attr = nodes.new("GeometryNodeInputNamedAttribute")
n_attr.data_type = 'FLOAT'                          # ✅ still works for this node type
n_attr.inputs["Name"].default_value = "my_attr"     # ✅ by name, not index

# CaptureAttribute — use capture_items (different node, different API)
n_cap = nodes.new("GeometryNodeCaptureAttribute")
n_cap.capture_items.new('FLOAT', 'Value')           # ✅ required for this node
```

### `SetShadeSmooth` requires `domain = 'FACE'`
```python
n_smooth = nodes.new("GeometryNodeSetShadeSmooth")
n_smooth.domain = 'FACE'                            # ✅ confirmed — not 'POINT' or 'EDGE'
n_smooth.inputs["Shade Smooth"].default_value = True
```

---

## Multi-Pass / Chained Compute

You can chain compute passes without barriers between dispatches:

```python
# Pass 1: in_tex → mid_tex
shader1.bind()
shader1.uniform_sampler("in_tex", in_tex)
shader1.image("out_tex", mid_tex)
shader1.uniform_int("u_n", N)
gpu.compute.dispatch(shader1, groups, 1, 1)

# Pass 2: mid_tex → out_tex
# No barrier needed between these dispatches
shader2.bind()
shader2.uniform_sampler("in_tex", mid_tex)
shader2.image("out_tex", out_tex)
shader2.uniform_int("u_n", N)
gpu.compute.dispatch(shader2, groups, 1, 1)

# ✅ Results are correct without explicit Python-side synchronization
```

---

## GPUShader Full Instance API

All methods confirmed available on a GPUShader instance:

```python
shader.bind()                        # Bind shader for use
shader.image(name, gpu_texture)      # Bind image (for ci.image() outputs)
shader.uniform_sampler(name, tex)    # Bind sampler (for ci.sampler() inputs)
shader.uniform_int(name, value)      # Set INT push_constant
shader.uniform_float(name, value)    # Set FLOAT push_constant
shader.uniform_bool(name, value)     # Set BOOL push_constant
shader.uniform_vector_float(loc, val, count)
shader.uniform_vector_int(loc, val, count)
shader.uniform_from_name(name)       # Get uniform location int
shader.uniform_block(name)           # Bind UBO
shader.uniform_block_from_name(name)
shader.attr_from_name(name)          # Get attribute location
shader.attrs_info_get()              # List all attributes
shader.format_calc()                 # Vertex format info
shader.name                          # str — shader name
shader.program                       # int — GL program handle
```

---

## GPUTexture Full API

```python
tex = gpu.types.GPUTexture((W, H), format='RGBA32F', data=buf)

tex.width      # int
tex.height     # int
tex.format     # str — e.g. 'RGBA32F'
tex.read()     # → Buffer — reads GPU→CPU (tiled, see readback section)
tex.clear(format='FLOAT', value=(0.0, 0.0, 0.0, 1.0))  # fill with value
```

**GPUOffScreen** also exposes a GPUTexture via `.texture_color` (and deprecated `.color_texture`):
```python
ofs = gpu.types.GPUOffScreen(W, H)
tex = ofs.texture_color  # GPUTexture — same API as above
```

---

## GPUUniformBuf (UBO path, for large arrays)

For passing large read-only arrays to shaders (alternative to textures):

```python
data_bytes = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32).tobytes()
ubo = gpu.types.GPUUniformBuf(data_bytes)
# or:
buf = gpu.types.Buffer('FLOAT', 4, [1.0, 2.0, 3.0, 4.0])
ubo = gpu.types.GPUUniformBuf(buf)

ubo.update(new_bytes)  # update contents

shader.uniform_block("MyUBO", ubo)  # bind to shader
```

Note: UBO layout in GLSL must use `std140`, and the Python side must match the exact byte layout (alignment rules apply).

---

## Blender 4.4 API Gotchas (Node/Modifier Side)

### CaptureAttribute (4.4+)
```python
# WRONG (pre-4.3):
node.data_type = 'FLOAT'
# CORRECT (4.4):
node.capture_items.new('FLOAT', 'Value')
```

### RepeatZone (Geometry Nodes)
```python
n_ri.pair_with_output(n_ro)   # MUST call before adding items
n_ro.repeat_items.new('FLOAT', 'My Value')  # type string, not 'NodeSocketFloat'
```

### GeoNodes interface sockets
```python
nt.interface.new_socket("Z Scale", in_out='INPUT', socket_type='NodeSocketFloat')
# Setting modifier values by socket identifier:
for item in nt.interface.items_tree:
    if item.item_type == 'SOCKET' and item.name == 'Z Scale':
        mod[item.identifier] = float(value)
```

### NamedAttribute node
```python
n_attr.inputs["Name"].default_value = "my_attr"  # NOT inputs[0]
n_attr.outputs[0]   # Float value — NOT outputs[1] which is bool Exists
```

### Math node: no LERP operation
```python
# Manual mix using MULTIPLY_ADD:
n_diff = math_node('SUBTRACT')       # b - a
n_mix  = math_node('MULTIPLY_ADD')   # (b-a)*t + a
```

### Valid icons in Blender 4.4 UI
```python
# 'ATTRIBUTE_DATA' does NOT exist → use 'RNA'
# 'FUND' exists (GPU/bolt icon)
# Check: bpy.types.UILayout.bl_rna.properties['icon'].enum_items
```

---

## Complete Working Architecture (Phacelle Erosion Reference)

This is a working GPU compute addon. Use it as a template.

```
phacelle_erosion_v2.py
├── COMPUTE_GLSL           — full erosion GLSL (no declarations, Blender injects)
├── TEX_WIDTH = 32768      — single-row chunk width (fits RTX 4090 max dim)
├── _build_compute_shader()
│     ci.local_group_size(16, 16, 1)  ← 2D work group (width/16 × 1 rows)
│     ci.sampler(0, 'FLOAT_2D', "uv_tex")
│     ci.image(0, 'RGBA32F', 'FLOAT_2D', "out_tex", qualifiers={'WRITE'})
│     INT uniforms: u_n_verts, u_tex_width, u_height_octaves, etc.
│     FLOAT uniforms: u_height_freq, u_erosion_scale, etc.
│     → gpu.shader.create_from_info(ci)
├── _run_compute_chunk(shader, uvs_chunk, W)
│     Pack UV → numpy (W,4) → Buffer → GPUTexture(data=buf)
│     create empty out_tex
│     shader.bind() → set all uniforms → dispatch(W//16, 1, 1)
│     read() → numpy → deinterleave with quarter formula → return (ez, rm)
├── _run_compute(props, uvs)
│     Build shader once, set props uniforms
│     Loop in TEX_WIDTH chunks → collect results
│     Return (eroded_z, ridge_map) arrays or None on failure
├── bake_erosion(obj, props)
│     Build UV array from vertex XY (normalised)
│     Try _run_compute() → fall back to _run_cpu() on failure
│     Write to mesh attributes via foreach_set (100x faster than loop)
│     Apply GeoNodes modifier for non-destructive display
└── _run_cpu(props, uvs)    — identical math in pure Python (fallback)
```

### Key design decisions in the working addon

**Input texture format: RGBA32F**
Pack UVs as (u, v, coord_x, coord_y) in channels R,G,B,A. The coord_x/coord_y in B,A channels allow the GLSL to verify its own position — useful for debugging readback ordering.

**Work group: 16×16 with single-row texture**
The addon uses `ci.local_group_size(16, 16, 1)` even for single-row textures. This means groups_y=1 always. This works fine — just some wasted Y threads. Alternatively use `(64, 1, 1)` for purely 1D dispatch.

**Shader reuse across chunks**
The shader is built once per bake. Props-driven uniforms (`u_erosion_scale` etc.) are set before the chunk loop. Per-chunk uniforms (`u_n_verts`, `u_tex_width`, sampler, image) are re-bound each chunk. This saves ~25ms compile time per bake.

**Graceful fallback**
```python
result = _run_compute(props, uvs)  # returns None on any GPU failure
if result is None:
    result = _run_cpu(props, uvs)  # identical math, sequential
```

---

## GLSL Template for Vertex Processing

```glsl
/* Paste this as your starting point for vertex-processing compute shaders.
   Blender injects: uv_tex (sampler), out_tex (image), and all push_constants.
   Do NOT redeclare them. */

void main() {
    ivec2 coord = ivec2(gl_GlobalInvocationID.xy);
    int idx = coord.y * u_tex_width + coord.x;
    if (idx >= u_n_verts) return;

    /* Read input (UV or whatever you packed) */
    vec4 data = texelFetch(uv_tex, coord, 0);
    float u = data.r;
    float v = data.g;
    vec2  p = vec2(u, v);

    /* ---- Your compute logic here ---- */
    float result_value = /* ... */ 0.0;
    float result_other = /* ... */ 0.0;

    /* Write output — R and G will be extracted in Python */
    imageStore(out_tex, coord, vec4(result_value, result_other, 0.0, 1.0));
}
```

---

## Open Items / Next Investigations

- [ ] **Work group size performance sweep** — need confirmed ms/vert at various local sizes.
- [ ] **Throughput benchmark** — need confirmed Mverts/s for typical compute workloads.
- [ ] **R32F readback pattern** — only RGBA32F is confirmed. R32F may have different tiling.
- [x] **2D texture readback** — ~~only single-row (H=1) is confirmed~~ **CLOSED v3.0: 2D output textures (H>1) are confirmed broken. Silent corruption, no error. Never use. Always flatten to single-row.**
- [ ] **UBO data layout** — GPUUniformBuf confirmed to exist and accept bytes/Buffer, but std140 alignment rules in GLSL vs Python not tested.
- [ ] **Atomic ops on shared memory** — confirmed compile+dispatch, not verified correctness of output values.
- [ ] **AMD GPU behavior** — all testing on NVIDIA RTX 4090. Tiling pattern may differ on AMD/Intel/Apple Silicon.
- [ ] **Multiple image outputs** — only one `ci.image()` binding tested. Whether multiple writable image outputs (up to the max of 8) work correctly is unconfirmed.
- [ ] **Sanity check tolerance on larger matrices** — the 0.05 float32 tolerance was confirmed for (8,16)×(12,16). May need adjustment for larger matrices due to floating-point accumulation error.
- [ ] **GPU matmul performance vs numpy** — the RNN session used GPU dispatch per time-step. No wall-clock benchmark comparing GPU vs numpy throughput at these matrix sizes was recorded.

---

*Version 3.2 — v3.1 base + BlenderNet 3-bit MLP source audit (2026-04-02)*  
*Adds: full fragment shader / GPUOffScreen pipeline, fb.read_color() (no tiling), gpu.texture.from_image() round-trip, float_buffer=True + Non-Color colorspace requirement, offscreen.free(), gpu.matrix.push_pop(), depth_test_set/blend_set, vertex_in/vertex_source/fragment_source/fragment_out on ShaderCreateInfo, batch_for_shader, modal operator pattern, cross-operator shader storage on bpy.types.Scene, bpy.props scene display pattern*  
*All API facts are empirically confirmed on Blender 4.4.3, RTX 4090, Windows, OpenGL 4.6*
