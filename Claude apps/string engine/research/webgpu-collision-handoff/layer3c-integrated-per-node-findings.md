# Layer 3c findings: per-node pair deduplication, strand exclusions, and accumulation order

Context: `Theory-box/Claude-Relay`, branch `feature/gpu`, integrated per-node Jacobi segment collision. Findings only; no engine code.

## Conclusions

1. Use a **pair home-cell rule**, not duplicate-and-average. Because each segment occupies an integer AABB rectangle of grid cells, the lowest shared cell is computable in constant time from the two stored cell ranges. Accept the pair only while visiting that cell.
2. A strand ID plus along-strand index is an exact replacement for the CPU exclusion sets only for topology known to be simple open chains or rings. For the current CPU construction, an open chain excludes index distance `1…skip`, where `skip = max(1, ceil(2·objectRadius / max(1, segmentRest)) + 1)`. Therefore a strict test `distance < K` requires `K = skip + 1`.
3. The proposed accumulation order is correct: clamp each pair's penetration, form and sum this node's slot corrections, normalize by active contacts, apply SOR, then apply the final vector-magnitude clamp. Do not move the final clamp before SOR.

## Q1 — exactly once per node without a seen set

### Recommended rule: lowest shared occupied cell

For every segment, retain the exact integer cell bounds used when inserting its expanded AABB into the grid. For a pair A/B, intersect those two integer rectangles. If the intersection is nonempty, designate one deterministic cell in it as the pair's owner—for row-major IDs, the cell with the lowest y and then lowest x, equivalent to the lower-left cell of the intersection.

While the node invocation scans an incident segment's occupied cells, it evaluates the pair only when the current cell is that owner cell. Every other shared cell rejects it.

This gives the required property independently for each endpoint node:

- A node on A discovers B while scanning A, but only their shared home cell survives.
- A node on B discovers A while scanning B, and derives the same home cell.
- The pair is intentionally recomputed at the distinct endpoint nodes, but only once at each node.
- Canonical `(minSegment,maxSegment)` ordering still controls filters, closest-point orientation, and deterministic fallback normals.

The owner cell should be derived from the **stored grid-build cell bounds**, not recomputed from positions during later Jacobi iterations. If a fat grid is reused while positions change, deriving ownership from current AABBs could select a cell in which the old grid never stored one partner, causing omission or inconsistent ownership.

For a bounded direct grid, the 2D intersection is:

- minimum shared x = `max(xMinA,xMinB)`;
- maximum shared x = `min(xMaxA,xMaxB)`;
- minimum shared y = `max(yMinA,yMinB)`;
- maximum shared y = `min(yMaxA,yMaxB)`.

The pair has shared cells exactly when both minimums do not exceed their corresponding maximums. The home cell is the shared minimum x/y coordinate under ordinary row-major ordering. The 3D extension adds the corresponding z bounds.

This is related to the home-cell/control-bit strategy used to prevent repeated GPU collision tests in [GPU Gems 3, Chapter 32](https://developer.nvidia.com/gpugems/gpugems3/part-v-physics-simulation/chapter-32-broad-phase-collision-detection-cuda), but the lowest-cell-of-AABB-intersection rule is simpler here because the engine already inserts each complete segment AABB rectangle.

### Do not use `segmentX < segmentY` as the node-local owner rule

Canonical segment ordering alone is insufficient for a per-node gather. If only the lower-index incident segment may process the pair, nodes belonging solely to the higher-index segment will never write their B-side corrections. Canonicalize the pair's math, but allow either incident side to discover it; the shared-cell rule removes only spatial duplicates.

### Why duplicate-and-average is not equivalent

If one isolated constraint is repeated `m` times, summing it `m` times and dividing the contact count by `m` happens to cancel algebraically before nonlinear clamps. That special case is misleading.

In a real node neighborhood, different pairs generally overlap different numbers of cells. One contact might appear once and another six times. Duplicate-and-average therefore weights constraints according to AABB overlap area rather than physics. SOR and the final magnitude clamp make the discrepancy even more nonlinear. It also wastes the most expensive work—filters and robust closest-point evaluation—and atomic-bin insertion order can make its floating-point result nondeterministic.

Reject duplicates exactly. The contact count must count unique active segment-pair constraints, not cell occurrences.

### Additional duplicate traps

- Skip the incident segment itself when it appears in its own bins.
- Multi-cell overflow handling must not make the stored segment bounds disagree with the cells actually inserted. If a segment loses insertions because CAP overflowed, the broad phase is already incomplete; the home rule cannot repair that.
- If the same incident segment ID can occur twice in node CSR, fix the CSR. Do not compensate in narrow phase.
- Pairs between two segments both incident to the current node should be rejected by the shared-endpoint filter before contributing. That is current CPU behavior.

## Q2 — replacing the CPU exclusion sets

### What the CPU construction means

The examined CPU logic constructs segment adjacency through shared endpoint nodes, then performs a breadth-first expansion from each segment. For source segment `i`, it computes:

`skip_i = max(1, ceil(2·objectRadius / max(1, rest_i)) + 1)`.

It expands for `skip_i` graph steps and excludes every same-object segment at graph distance from 1 through `skip_i` inclusive.

For a simple open chain whose segment order follows graph adjacency, graph distance equals absolute along-index difference. Exact equivalence is therefore:

`sameStrand && abs(indexA-indexB) <= skip_source`.

If the GPU test is written with strict less-than, `abs(indexA-indexB) < K_source`, use `K_source = skip_source + 1`. Using `K = skip` with strict less-than is an off-by-one error and permits the CPU's outermost excluded neighbor to collide.

Use the same quantities as the CPU if parity matters: the current builder uses the object's stored radius and the source segment's rest length, including its `max(1,rest)` floor. Do not silently substitute effective/global radius or current stretched length.

### Canonical-source asymmetry

The current CPU first canonicalizes a candidate so A has the lower segment ID, then checks only A's exclusion set. Because `skip_i` can vary with rest length, exclusion is not necessarily symmetric.

For exact parity, the GPU rule must use the canonical lower-ID segment's `skip` value. Using `max(skipA,skipB)` is a reasonable symmetric redesign, but it is not identical to the existing CPU behavior. If symmetry is desired, change the CPU oracle at the same time and revalidate.

### When strand/index is sound

It is sound when every collision-bearing connected component is guaranteed to be:

- an open chain with segment degree at most two and two ends; or
- a simple ring, using circular index distance `min(diff, segmentCount-diff)`.

The strand ID must identify the continuous connected piece, not merely the object/material ID. One object can contain multiple disconnected strands.

Rebuild strand IDs, indices, counts, and per-segment skip values after cuts, merges, or other topology changes. Radius/rest edits that affect `skip` also require refreshing the metadata.

### When it is not sound

A single along index cannot reproduce graph distance at a branch, general imported graph, or component with non-manifold connectivity. Two segments close through a junction may be far apart in an arbitrary linear order. In those cases retain CSR exclusions, store a bounded graph-neighborhood representation, or use a hybrid: O(1) index rules for verified chains/rings and CSR only for exceptional components.

Given the engine's graph-general CPU implementation, the safest integration gate is to classify each component when rebuilding topology. Enable the index rule only for components proven to be chains/rings; fall back otherwise. This avoids silently changing collision behavior on future imported geometry.

## Q3 — accumulation order and normalization

The proposed order is the stable one:

1. Determine actual penetration from the current frozen iteration positions.
2. Clamp penetration per pair to `0.25·target`.
3. Apply the pair-wide inverse-mass denominator and this node's signed barycentric slot weight.
4. Sum the resulting node vectors over unique active pairs.
5. Normalize the sum by the node's active-contact measure.
6. Multiply by SOR `omega`.
7. Clamp the final node vector's magnitude.
8. Write frozen position plus the final delta.

The reasons for this order are:

- The per-pair clamp prevents one deep contact from dominating before mixing.
- Averaging controls the spectral instability of parallel Jacobi when many constraints affect one node.
- SOR restores convergence lost to averaging.
- The last clamp is the absolute safety bound. Placing it before SOR would let `omega > 1` violate that bound.
- The final clamp should be a vector-magnitude clamp, not independent component clamps, so it preserves the accumulated direction.

This matches the structure of the parallel PBD solver described by Macklin et al.: accumulate constraint deltas, divide by the number affecting the particle, then apply an SOR factor. See §4.2–4.3 of [Unified Particle Physics for Real-Time Applications](https://matthias-research.github.io/pages/publications/flex.pdf).

### Define the denominator carefully

Count only pairs that:

- survive all filters;
- produce a valid normal/fallback normal;
- are actually inside the contact target; and
- have a nonzero potential influence on this movable node.

Do not count broad-phase candidates, filtered pairs, cell duplicates, or inactive separated pairs.

There is one segment-specific refinement worth testing. A closest point near the opposite endpoint can give the current node a barycentric slot weight near zero. Counting that as one full contact can overdamp the node's other meaningful contacts. Two defensible choices are:

- **Classic contact count:** divide by unique active constraints affecting the node. This most closely follows averaged Jacobi and is the safest initial implementation.
- **Barycentric-weighted count:** accumulate the absolute slot influence and divide by at least one, e.g. use a normalization measure that never drops below 1. This reduces overdamping from near-zero slot participation without amplifying a solitary tiny contribution.

Start with classic count for validation. Add weighted normalization only as a separately measured behavior change.

If shared-endpoint pairs remain rejected, each valid pair contributes at most one endpoint slot to a given physical node, simplifying both definitions.

### SOR and 2–8 iterations

With contact averaging enabled, start at `omega = 1`. The cited parallel PBD work reports using values from 1 to 2, but dense segment self-contact, nondeterministic f32 sum order, and only a few iterations argue for increasing cautiously. Tune SOR rather than reordering the clamps.

If convergence is too soft:

- raise omega gradually while measuring final-clamp hit rate;
- consider barycentric-weighted normalization;
- use more substeps or iterations;
- separate collision and structural constraint groups so each group's accumulated correction is applied before the next.

If final-clamp hits are common, raising omega is mostly ineffective because the clamp erases it. That indicates the per-node cap, duplicate filtering, crowd normalization, or timestep needs attention.

The final clamp's scale must be node-defined or accumulated deterministically; do not base it on whichever pair happened to be visited last. A fixed per-node collision scale derived from incident segment radii/pads is preferable.

### WebGPU-specific notes

- Atomic insertion makes bucket occupant order nondeterministic. Even with exact home-cell deduplication, different candidate order can alter low f32 bits. Treat tolerance-level variation as expected unless node pair lists are explicitly sorted.
- The home-cell test is invocation-local and needs no atomics or cross-workgroup synchronization.
- Retain integer cell bounds from grid construction in storage accessible to the narrow phase. Recomputing them from corrected positions breaks ownership when reusing the grid.
- Keep CAP overflow a hard diagnostic. A zero overflow counter is a precondition for broad-phase completeness and therefore for the home-cell proof.
- WGSL implementations may reassociate/fuse floating-point expressions within specification allowances; validate physical tolerances rather than requiring JavaScript-double bit identity. See the [WGSL floating-point rules](https://www.w3.org/TR/WGSL/#floating-point-evaluation).

## Recommended validation cases

- Two long diagonal segment AABBs sharing many cells: exactly one active contact per endpoint node.
- One node with two incident segments, both colliding with one external segment: two contacts, each exactly once.
- Shared-endpoint pair occupying many cells: zero contacts after filtering.
- Two contacts with deliberately different shared-cell counts: result unchanged when AABBs are lengthened without changing closest geometry.
- Open-chain exclusion at distances `skip-1`, `skip`, and `skip+1` to catch the strict-less-than off-by-one.
- Ring exclusion across the index wrap.
- Nonuniform rest lengths with canonical segment IDs swapped, to expose the CPU's directional exclusion behavior.
- Cut/merge followed by topology metadata rebuild.
- CAP overflow injection: diagnostic must fail rather than silently trusting an incomplete result.

## Sources

- NVIDIA, [GPU Gems 3, Chapter 32: Broad-Phase Collision Detection with CUDA](https://developer.nvidia.com/gpugems/gpugems3/part-v-physics-simulation/chapter-32-broad-phase-collision-detection-cuda) — multi-cell duplicate collision tests and home-cell ownership.
- Macklin et al., [Unified Particle Physics for Real-Time Applications](https://matthias-research.github.io/pages/publications/flex.pdf) — projected Jacobi, constraint averaging, and SOR.
- W3C, [WebGPU Shading Language specification: floating-point evaluation](https://www.w3.org/TR/WGSL/#floating-point-evaluation) — portable f32 behavior and implementation latitude.
- Project source, [`string-engine.html` on `feature/gpu`](https://github.com/Theory-box/Claude-Relay/blob/feature/gpu/Claude%20apps/string%20engine/string-engine.html) — CPU exclusion-set construction and collision filters.

