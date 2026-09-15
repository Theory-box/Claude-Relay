# Splat sort + scene-load performance (branch: feature/unified-sort, v0.16.0)

Measured on the user's RTX 4090 by a Claude Code instance driving real Blender.
Headline: the bottlenecks were NOT the ones we assumed. Measure before building.

## 1. "6 trees at 30fps" -- it was the SORT, not overdraw
Overdraw was never the bottleneck (needs ~4 BILLION blended fragments/frame to cost 33ms; real
scenes are tens of millions, ~1ms). LOD / alpha-aware conversion / a renderer rewrite were all aimed
at the wrong target.
- **v0.14.0 throttle**: the GPU sort re-sorted EVERY frame, even parked -> 15ms of a 17.8ms frame
  (83%). Now cached per object like the CPU path. 6x1M still: 17.59 -> 3.98 ms.
- **v0.14.1-4 radix sort**: replaced bitonic (O(N log^2 N) + power-of-two padding; 1.1M padded to
  2.1M). LSD 4-bit, 8 passes: histogram -> chunked shared-mem scan -> stable scatter (per-digit
  bitmask popcount rank). 6x1M moving: 18.95 -> 7.82 ms (2.4x). Default now; auto-falls back to
  bitonic.

## 2. Overlapping trees blended wrong -- unified sort (v0.15.x)
Each cloud sorted+drew independently, so the LAST drawn won regardless of depth. ANGLE DEPENDENT:
0.00% wrong pixels at 120deg, up to 5.23% at 240deg -- exactly "right from one angle, wrong from
another". Fix: key every splat of every cloud by WORLD depth into one buffer (payload=inst<<24|id),
ONE radix sort, ONE instanced draw; clouds bound as a 2D texture array (one layer per UNIQUE cloud,
so Shift+D copies share a layer), models as MAT4[].
Result: 0.00% wrong pixels at every angle, GPU order check clean, cost within ~0.2-0.9ms of
per-tree. Only affordable because radix landed (bitonic made merging 31% SLOWER).

## 3. Entering Rendered mode -- v0.16.0, 2.7x faster extraction
Azola (394 objects, 18.6M tris): 11.20s -> 5.86s; first frame 4.47s -> 0.60s; reload 7.66 -> 3.54s.
Mesh reading was 72-82% of entry. Five fixes in _extract_mesh_data: per-face material index (not
loop_triangles.foreach_get, 90ms); material split by sort+contiguous slices (not boolean masks,
71ms); vertex normals as fallback only (the GI using them went in v0.10); exact transposed bbox
min/max -- NOT object.bound_box, geometry-node instances make it too large; colour-variance check
only when the attribute exists. Byte-identical on 641 objects / 3 scenes; permanent test at
addons/vertex_lit_renderer/tests/test_extract_identical.py.
Re-entry is 0.05-0.06s -- caches are sound. batch_for_shader is 5-10% of entry and hand-rolling
saves 1-4ms: NOT worth doing.

## Toggles (Splats panel)
GPU Sort | Radix Sort (on) | Unified Sort (on) | Backface Cull | Compute Pre-pass |
Tile Rasterizer (specialist: high-overdraw only, overrides the draw -- don't stack with GPU Sort)

## Known gaps / next
1. Huge single meshes stall one frame (~1.8s for a 6.5M-tri willow): the per-frame budget is checked
   only BETWEEN objects. Needs chunked resumable extraction.  <- biggest remaining
2. Texture uploads ~1.7s inside the first frames: draw untextured, stream textures after.
3. Shader compile waits for ALL geometry (~1.4s serialized): overlap with streaming.
4. Unified path ignores Backface Cull + compute pre-pass.
5. Splats are runtime-only (not saved in the .blend).
6. Brainstormed only: per-cloud LOD (prefer over a global budget -- the budget couples clouds and can
   flicker; build coarse levels as strict SUBSETS to avoid resampling shimmer); frame-skip /
   round-robin sorting; chunk-level occlusion culling (spatial chunking unlocks LOD + occlusion
   together -- measure actual occlusion % first).

## Process lesson
Code reading finds structural bugs, not COST bugs. I called extraction "already optimized" (it held
a 2.9x) and batch_for_shader "very plausible 10x" (it held ~nothing). And when I cannot execute
code, a string-replace is a hypothesis: assert the invariant headlessly first -- the unified packing
bug survived THREE "fixes" because a duplicate loop was never checked.
