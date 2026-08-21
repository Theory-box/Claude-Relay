# Fast WebGPU spatial-hash collision, 10k–100k particles

## Recommendation

Start with a compact uniform grid built as **count → exclusive scan → scatter**, followed by a **per-particle Jacobi 3×3 gather** into a ping-pong position buffer.

This is the best robust default for the requested range because it has bounded storage, contiguous ranges per cell, no fixed bucket overflow, and coherent neighbor reads. The narrow phase needs no atomic correction buffer: invocation `i` reads old positions, accumulates only `i`'s correction, and writes only `newPosition[i]`. Each pair is evaluated twice, but that is usually a better WebGPU trade than contended integer atomics and fixed-point conversion for pair-once response.

Do not claim a universal winner without timing all passes on target browsers. For sparse scenes near 10k, a fixed-capacity atomic bin can win by avoiding scan passes. For very large/reused datasets, radix sorting can win through locality. At 10k–100k, count/scan/scatter is the sensible implementation and benchmark baseline.

## Build and solve passes

1. Clear `cellCounts` and any statistics/overflow flags.
2. Count: one invocation per particle; compute cell and `atomicAdd(&cellCounts[cell], 1u)`.
3. Exclusive scan `cellCounts` into `cellOffsets`; retain a sentinel offset for the final cell end.
4. Clear `cellWriteHeads` (or copy zero counters; using offsets directly as atomics also works if offsets are preserved separately).
5. Scatter: `slot = cellOffsets[cell] + atomicAdd(&cellWriteHeads[cell], 1u)`; write particle ID to `cellEntries[slot]`.
6. Gather: one invocation per particle scans the 3×3 cells, tests exact distance, accumulates its own correction, and writes one ping-pong output position.
7. Swap position buffers. Rebuild before another collision iteration if a correction can move a center across a cell boundary; otherwise a small number of gathers may reuse the grid conservatively.

Suggested buffers (SoA):

```text
positionsIn:    array<vec4<f32>>
positionsOut:   array<vec4<f32>>
cellCounts:     array<atomic<u32>>
cellOffsets:    array<u32>          // numCells + 1
cellWriteHeads: array<atomic<u32>>
cellEntries:    array<u32>          // particleCount
```

The recorded device supports only eight storage buffers per shader stage. Split grid-build and gather bind groups/pipelines instead of trying to expose all existing simulation buffers plus grid buffers to one shader.

## Method comparison

| Method | Build cost | Neighbor locality | Main failure/cost | Best fit |
|---|---:|---|---|---|
| Fixed-capacity bins via `atomicAdd` | 1 clear + 1 build | Acceptable within fixed cell slabs | Wasted memory, overflow/caps, contended/random writes | Fast prototype; sparse and bounded occupancy near 10k |
| Atomic linked lists (`atomicExchange` head + `next[]`) | 1 clear + 1 build | Poor; pointer chasing | Random reads and heavy contention in dense cells | Minimal-pass experiment, not the robust default |
| Count + scan + scatter | 4–5 compute passes | Good; compact contiguous cell ranges | Dispatch/scan overhead | Recommended 10k–100k baseline |
| Cell-key radix sort | Key generation + multiple radix/scan/scatter passes + range detection | Best if particle data is reordered or order is reused | Larger fixed cost and more transient buffers | Benchmark above ~100k or when several systems consume the order |

NVIDIA's particle sample explicitly describes both atomic fixed bins and the variable-size two-pass count/scan/compact approach; it also notes serialization and non-coalesced writes when many particles hit the same cell. Its sorting alternative creates `(cell hash, particle ID)` pairs and radix-sorts them. The WebGPU radix-sort implementation cited below targets large arrays and describes its GPU advantage as applying above 100,000 elements; that is a useful signal, not a guaranteed crossover for this app.

## 3×3 gather correctness

- In 2D, examining 3×3 cells is sufficient only when the maximum interaction distance is no larger than the cell width and particles are assigned by center.
- Use cell width equal to the maximum collision diameter for equal-radius particles. Very different radii need a largest-radius grid (which may overfill cells), radius tiers/multilevel grids, or conservative multi-cell insertion.
- Hashing an infinite/sparse grid needs exact cell-coordinate verification after a hash match; otherwise hash collisions become false spatial neighbors. A bounded dense grid can use a direct linear cell ID.
- Skip `j == i`. If each particle writes only itself, processing both `(i,j)` and `(j,i)` is intentional.
- Avoid `j > i` in the per-particle Jacobi design: that would omit the other particle's response unless a pair-once accumulation pass is added.
- Cap or instrument pathological occupancy, but do not silently drop particles. Record maximum count, mean candidates, exact contacts, and overflow.

## Push-apart design

For equal radii `r`, a typical own-particle correction for overlap is based on:

```text
d = pi - pj
distance = length(d)
penetration = (ri + rj) - distance
correction_i += normal * penetration * wi / (wi + wj)
```

Handle near-zero distance with a stable ID-derived direction. Clamp correction per neighbor or per iteration, and consider averaging/density normalization in highly crowded cells so one particle with many overlaps does not explode outward. Use inverse mass `w`; pinned particles have `w = 0`.

Core WGSL atomics are 32-bit integer atomics, not floating-point atomic add. If a later pair-once solver is required, accumulate quantized `atomic<i32>` x/y corrections plus a count, then apply them in a separate pass. That saves duplicate pair tests but introduces scale selection, overflow risk, extra clearing/apply passes, contention, and order-dependent integer rounding. Benchmark it against the simpler double-evaluated Jacobi gather.

For position-based constraints, favor smaller substeps with fewer solver iterations when stability permits. The “Small Steps” result supports substeps as an important quality/performance axis, although collision-grid rebuild cost must be included in this app's measurement.

## Scan notes for WebGPU

- Use a work-efficient hierarchical exclusive scan: scan blocks in workgroup memory, scan block totals, then add block offsets.
- Workgroup barriers synchronize only a workgroup; cross-workgroup stages require separate dispatches. Do not implement a global spin-wait/lookback scheme that assumes forward progress.
- The hardware log's maximum is 256 invocations/workgroup. Start benchmarking at 128 and 256; do not hardcode an assumed subgroup width.
- The grid-cell count, not particle count, sets scan cost. Bound the active grid tightly or compact active cell IDs if the world is enormous and sparse.
- Encode all build/gather passes into one command encoder and submit once per simulation step to reduce JavaScript/queue overhead.

## String Engine caveat

These findings are for center-based particle collisions. A segment cannot safely be binned only by its midpoint and then searched in 3×3 cells: a long segment crosses distant cells. Segment collision needs conservative AABB/swept-AABB insertion into every overlapped cell, or a separate acceleration strategy. Multi-cell insertion also needs pair deduplication or a home-cell rule.

## Benchmark matrix

Measure total GPU time if timestamp queries are available; otherwise use sufficiently large batches and queue completion only in diagnostics, never the hot loop.

- N: 10k, 25k, 50k, 100k
- Distributions: uniform sparse, clustered, pile/high occupancy, moving coherent cloud
- Methods: fixed atomic bins, count/scan/scatter, radix sort
- Metrics: build time, gather time, candidates/particle, exact contacts, max occupancy, total solver step, memory, overflow, NaNs
- Reuse: one gather per build versus two/four gathers per build

The decision should be based on end-to-end step time, not grid-build time alone.

## Primary references

- NVIDIA CUDA particle sample, uniform grid and atomic versus scan/sort construction: https://turing.une.edu.au/~cosc330/lectures/cuda-samples/Samples/2_Concepts_and_Techniques/particles/doc/particles.pdf
- NVIDIA GPU Gems 3, Chapter 32, parallel spatial-subdivision collision: https://developer.nvidia.com/gpugems/gpugems3/part-v-physics-simulation/chapter-32-broad-phase-collision-detection-cuda
- W3C WGSL specification, atomic/storage and synchronization rules: https://www.w3.org/TR/WGSL/
- WebGPU radix-sort implementation and work-efficient recursive scan: https://github.com/kishimisu/WebGPU-Radix-Sort
- Macklin et al., “Small Steps in Physics Simulation”: https://dl.acm.org/doi/10.1145/3309486.3340247

