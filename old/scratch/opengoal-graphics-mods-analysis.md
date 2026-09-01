# OpenGOAL Engine — Graphics Modification Feasibility Analysis
*Session: April 2026 | Status: Research/Proposal*

---

## Engine Architecture (What We're Working With)

The OpenGOAL renderer is a **custom OpenGL 4.1 deferred-ish pipeline** that faithfully re-emulates the PS2's GS (Graphics Synthesizer) DMA bucket system. Key facts:

| Component | Detail |
|---|---|
| API | OpenGL 4.1 core |
| Shaders | GLSL, per-bucket (tfrag3, merc2, etie, shrub, etc.) |
| Pipeline | Bucket-based DMA dispatch → FBO → post-processing → blit |
| FBO | `Fbo` struct with optional color tex + depth/stencil RBO |
| Post-processing | Single `post_processing.frag` — currently just color multiply/add |
| Geometry shaders | None (vert + frag only) |
| Depth buffer | Present (`zbuf_stencil_id`) but currently only used for standard depth test |
| Normals | NOT written to a G-buffer — no normal buffer available |

The render pipeline per frame:
```
DMA chain → dispatch_buckets (sky, tfrag, tie, shrub, merc, sprite...) 
         → FBO (color + depth)
         → post_processing.frag (trivial)
         → blit to window
```

---

## SSAO (Screen Space Ambient Occlusion)

### Feasibility: ✅ YES — Achievable, Moderate Difficulty

**What SSAO needs:**
1. Screen-space depth buffer ✅ — already exists in the FBO
2. Screen-space normals ❌ — NOT currently written; would need reconstruction from depth
3. A noise texture + hemisphere sample kernel (CPU-side setup)
4. A blur pass (horizontal + vertical separable)
5. Integration into final composite

**The key problem — normals:**  
The game uses per-vertex colors (vertex lighting pre-baked, PS2 style), not per-pixel normals in a G-buffer. The vertex shaders output `fragment_color` but no normal. You'd need to either:
- **Option A (easier):** Reconstruct screen-space normals from the depth buffer using `dFdx`/`dFdy` — this works reasonably well and requires **zero changes to geometry shaders**
- **Option B (better quality):** Add `out vec3 frag_normal` to each geometry shader (tfrag3.vert, merc2.vert, etc.) and write a normals FBO — significant shader changes across ~15+ shader pairs

**Implementation plan (Option A — depth-reconstructed):**

1. Add a `depth_fbo` that samples the existing depth buffer as a texture (`GL_DEPTH_COMPONENT`)
2. New `ssao.frag` shader — samples depth, reconstructs view-space normals, applies hemisphere kernel
3. New `ssao_blur.frag` — bilateral blur to avoid halos
4. New `ssao_composite.frag` — multiplies SSAO factor into the color buffer
5. Hook into `OpenGLRenderer::render()` after `dispatch_buckets`, before post-processing
6. Expose in `RenderOptions` with `bool enable_ssao`, `float ssao_radius`, `float ssao_strength`

**Expected visual result:** Soft contact shadows in crevices, under ledges, between rocks. Subtly transforms the flat PS2 look into something more grounded. Best visible in cave levels (maincave, robocave, misty).

**Difficulty: 6/10** — no engine restructuring needed, depth buffer already available.

---

## RTX / Ray Tracing

### Feasibility: ❌ No — Not Practical

**Hard blockers:**
- The engine uses **OpenGL 4.1**, not Vulkan or DX12. Ray tracing hardware extensions (`VK_KHR_ray_tracing_pipeline`) are Vulkan-only.
- OpenGL has no standardized ray tracing path.
- The bucket DMA system submits geometry piecemeal — there is **no unified scene BVH** (Bounding Volume Hierarchy) for ray acceleration structures.
- Game geometry is PS2-era (low poly, opaque vertex-lit surfaces) — RTX delivers diminishing returns on assets this simple.

**What "RTX" actually means in practice:**  
If someone says "RTX shadows" or "RTX reflections" for a PS2 game remake, they typically mean **screen-space approximations** (SSAO, SSR, shadow mapping) implemented in a modern engine — NOT actual hardware ray tracing.

**Realistic "RTX-adjacent" effects that ARE achievable:**

| Effect | Feasibility | Difficulty |
|---|---|---|
| SSAO | ✅ Yes | 6/10 |
| Screen Space Reflections (SSR) | ✅ Yes | 7/10 |
| Shadow mapping (directional light) | ✅ Yes | 7/10 |
| Bloom / HDR tone mapping | ✅ Yes | 4/10 |
| FXAA / TAA anti-aliasing | ✅ Yes (MSAA exists) | 3/10 |
| Volumetric fog/light shafts | ⚠️ Hard | 8/10 |
| Hardware ray tracing | ❌ No | Engine rewrite |

---

## Easiest High-Impact Mods (Ranked)

### 1. 🟢 Post-Processing Upgrades (Difficulty: 3/10)
The `post_processing.frag` is literally just a color multiply + add. Upgrading it costs almost nothing.  
Could add: **bloom**, **vignette**, **filmic tonemapping**, **chromatic aberration**, **screen shake distortion**.  
Hook: modify `post_processing.frag` and pass uniforms from `RenderOptions`.

### 2. 🟡 SSAO (Difficulty: 6/10)
As described above. Best bang-for-buck for "modern look" — doesn't require G-buffer if using depth reconstruction.  
Most impactful in: maincave, robocave, misty, sunken.

### 3. 🟡 Shadow Mapping (Difficulty: 7/10)
The game already has `Shadow2` bucket renderers — but these are PS2 stencil-volume shadows.  
Adding a proper **cascaded shadow map** from the main directional light (daytime levels) would dramatically improve outdoor scenes.  
Challenge: need to determine the sun direction from game state, and re-render geometry into a shadow FBO each frame.

### 4. 🟡 Screen Space Reflections (Difficulty: 7/10)
The ocean shader (`ocean_common.frag`) would be a prime target — reflections on water.  
Requires the depth buffer (available) and a copy of the color buffer before water render (doable with a blit).

### 5. 🔴 Volumetric Lighting / God Rays (Difficulty: 8/10)
Jak 1's cave and exterior levels have dramatic directional light setups that would look amazing with ray-marched volumetric light shafts. High difficulty but possible in a post-processing pass.

---

## Recommended Starting Point

**SSAO first**, then post-processing upgrades.  
SSAO is the single change that most shifts the feel from "PS2 emulator" to "modern remaster".  
The depth buffer is already there. The FBO infrastructure is already there. The main work is writing ~3 new shaders and hooking them into the render loop.

---

## Files to Modify

```
game/graphics/opengl_renderer/
├── OpenGLRenderer.h        — add SSAO FBO members, uniforms
├── OpenGLRenderer.cpp      — add SSAO render pass after dispatch_buckets
├── Fbo.h                   — may need depth-only FBO variant
└── shaders/
    ├── ssao.vert/.frag         [NEW]
    ├── ssao_blur.vert/.frag    [NEW]
    ├── post_processing.frag    [UPGRADE — bloom, tonemapping]
    └── tfrag3.vert/.frag       [OPTIONAL — add normal output for better SSAO]

game/graphics/gfx.h
└── RenderOptions struct    — add ssao_enabled, ssao_radius, ssao_strength
```

---
*Confidence: High (85%) on feasibility assessments | SSAO approach based on standard depth-reconstruction techniques well-documented in GL 4.x*
