# Branch: feature/splat-tile-rasterizer

Goal: top-tier splat speed via a FULL-GPU tile rasterizer (project -> bin -> sort -> blend, all
compute, zero per-frame CPU). Motivation: we are fillrate-bound; fixed-function alpha blending pays
for every splat fragment even behind opaque pixels. A tile rasterizer with front-to-back EARLY
TERMINATION skips that overdraw.

## Validated headless (apps/splat-viewer/)
- tile_raster.py  : conic-based per-pixel blend + early termination. Cactus: 3.42x fewer blend ops
                    (11.4M -> 3.35M), LOSSLESS. Output crisper than billboards (proper EWA eval).
- gpu_sort.py     : GPU bitonic sort (key/value, no CPU, no atomics). Correct to 555k pairs.
- full_gpu.py     : FULL pipeline assembled, all compute, no per-frame CPU:
                    project_emit -> atomic-bin -> bitonic sort -> tile ranges (binary search) ->
                    early-term blend. Matches CPU-binned reference (mean|d|=0.0000). 3.4x win kept.

## Blender feasibility (confirmed)
- gpu.compute.dispatch + create_info(compute) : yes
- image load/store + imageAtomicAdd on R32UI  : yes (our "own SSBO" — no GPUStorageBuf needed)
- CPU tile-bin measured at 96 ms/move-frame (139k) => must be GPU; hybrid rejected.

## Port plan (in progress) -> addons/vertex_lit_renderer/splat_tile.py
Storage = image-backed buffers (linear index -> 2D via at(i,w)=ivec2(i%w,i/w)):
  sdata  RGBA32F (4 texels/splat, reuse data-tex layout)   proj  RGBA32F (3 texels/splat)
  khi/klo/val/ctr/off  R32UI/R32I images                    out   RGBA32F
Passes (create_info compute, push_constants for camera/ints):
  1 project_emit  2 bitonic sort (log^2 dispatches)  3 tile_ranges  4 blend(early-term)
First version: sort fixed MAXP=next_pow2(N*8) (skip the pair-count readback). Opt-in + fallback to
the current billboard renderer. Untestable headless = Blender compute I/O only; algorithm is proven.
Then: mesh compositing (blend reads gbuf depth) + feed AO/cavity.

Latest engine on feature/node-glsl-transpiler: v0.11.34 (culling + compute pre-pass, opt-in).

## OUTCOME (merged to main @ v0.12.6)
The GPU-sort path was the real win — hardware blend + GPU depth sort + GPU frustum/backface culling,
no CPU cost while orbiting ("extremely fast" per user). This is the recommended fast path.
The tile rasterizer works but is a SPECIALIST tool (pathological-overdraw foliage / on-device training);
it loses to hardware blending in normal scenes because it trades overdraw for sort cost. Keep it OFF for
general use; do NOT stack it with GPU Sort (tile mode overrides the draw).

Splat toggles on main (all opt-in, default OFF, auto-fallback):
  GPU Sort (recommended) · Compute Pre-pass · Tile Rasterizer (specialist) · Backface Cull
Default splat path = billboard renderer (stable). Merged commit: "Merge splat pipeline into main (v0.12.6)".
Note: bl_info version bump sed had drifted (stuck at 0.11.31); corrected to 0.12.6 on merge.
