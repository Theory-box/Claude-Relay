# GPU affinity design for the String Engine

Context: `Theory-box/Claude-Relay`, branch `feature/gpu`. This report addresses the long-range tagged-segment interaction described for `attract()`. It is a design review only; it contains no engine code.

## Executive recommendation

Use a **second, affinity-specific uniform grid containing only affinity-tagged segments**. Keep it independent of the collision grid because the interaction radius is roughly six times larger and the useful population is sparse. Reuse the existing clear/build/per-node-gather architecture and the deterministic home-cell rule, but size and capacity this grid from affinity occupancy rather than collision occupancy.

Do not assume the grid always wins. Retain a direct all-pairs path as a benchmark/reference for very small tagged populations. The crossover depends on the browser, adapter, tag count, and spatial distribution; it should be measured rather than inferred from total engine segment count.

Treat affinity as a smooth external positional force, not as another collision constraint. Compute each segment-pair interaction from one frozen position buffer, distribute equal-and-opposite pair force to the four endpoints with closest-point barycentric weights, multiply each endpoint by its own inverse mass, then accumulate per node. Preserve neighbor-count scaling for CPU compatibility; control instability with timestep scaling and explicit pair/node clamps rather than silently averaging the force away.

## Q1 — broad phase

### Why the collision grid should not be reused

With collision cells near 22 px and affinity reach near 140 px, a query would cover roughly a 13×13 cell neighborhood before accounting for segment extent. That increases loop overhead and exposes the gather to many duplicate discoveries. Enlarging the existing grid instead would make collision bins much denser and weaken collision culling.

A separate grid lets the two workloads use different:

- populations: all collidable segments versus only tagged segments;
- cell widths and world bounds;
- fixed-bin capacities and overflow telemetry;
- rebuild cadences;
- shaders and bind groups.

This follows the normal cutoff-neighbor pattern: spatial subdivision is useful when interactions are bounded by a radius, but performance is controlled by population per cell and can still degrade toward quadratic in dense cells. See [GPU Gems 3, Chapter 32](https://developer.nvidia.com/gpugems/gpugems3/part-v-physics-simulation/chapter-32-broad-phase-collision-detection-cuda) and the more recent cutoff-interaction study [Efficient GPU Implementation of Particle Interactions with Cutoff Radius and Few Particles per Cell](https://arxiv.org/abs/2406.16091).

### Recommended representation

Compact the tagged segments into an affinity-only index list. Build grid entries from their segment AABBs, expanded conservatively so every pair within the largest possible affinity reach shares at least one cell.

For a symmetric maximum cutoff `Rmax`, expanding each segment AABB by `Rmax/2` is sufficient for the two expanded boxes to overlap whenever the unexpanded boxes are separated by at most `Rmax`. Storing the actual inserted integer cell rectangle then makes the existing rule usable:

> A pair is owned by the lowest cell in the intersection of its two stored cell rectangles.

That gives deterministic multi-cell dedup without an invocation-local seen array. Exact segment distance and the pair-specific range still decide whether the broad-phase candidate is active.

Important qualifications:

- Derive `Rmax` from the exact CPU pair-range rule. If `affRange` is asymmetric, first define whether a pair uses A's value, B's value, minimum, maximum, or another combination, and mirror that rule everywhere.
- Include segment thickness in the conservative bound if CPU distance is surface-to-surface rather than centerline-to-centerline.
- A very long tagged segment may cover many coarse cells. Track total insertions as well as maximum bin occupancy.
- A fixed-capacity atomic grid is correct only when overflow is a hard failure. Never continue with a silently truncated affinity grid.

An alternative is one centroid cell per segment plus neighboring-cell queries. That reduces insertion replication, but its safe query radius must include both segment half-extents as well as affinity range. For the current short-segment engine the AABB/home-cell design is easier to prove and aligns with the validated collision path.

### Grid size and sparse-set crossover

Start with cell width near `Rmax`, then profile neighboring work and bin occupancy. There is no universal optimum:

- Smaller cells reduce candidates per cell but increase insertion replication or neighbor cells.
- Larger cells reduce build overhead but move work into the quadratic inner loop.
- If only a few dozen tagged segments are active, a direct triangular all-pairs pass can be cheaper than clear/build/gather dispatches.
- If tags are numerous but clustered into one attraction range, no uniform grid can avoid the true dense interaction count. A sort-based compact cell list removes fixed-cap overflow risk, but it does not remove the quadratic number of real neighbors.

Recommended dispatch policy: benchmark direct all-pairs against the second grid at representative tagged counts and distributions, then choose a conservative crossover. Count only tagged segments, not all segments.

### Rebuild cadence

One build per substep is the simple safe default. Reuse across multiple substeps only with a neighbor-list skin that covers relative movement: if each segment endpoint can move at most `d` since build, the broad-phase expansion needs at least `2d` of additional pair separation allowance before the next rebuild. Track displacement from the positions used to build the grid, not merely displacement during the latest substep.

Because affinity is long-range and smooth, a skinned list may tolerate less frequent rebuilds better than collision. Correctness still requires rebuilding before accumulated motion consumes the skin.

## Q2 — per-node Jacobi accumulation

### Pair geometry and endpoint slots

For closest parameters `s` on segment A and `t` on segment B, use the same shape weights as the collision narrow phase:

- A0: `1-s`
- A1: `s`
- B0: `1-t`
- B1: `t`

Let the pair force vector on A be **F** and the vector on B be `-F`. The endpoint forces are the corresponding barycentric fraction of those two resultants. This preserves equal-and-opposite resultant force at the segment-pair level before fixed particles and inverse masses are applied.

Each node invocation processes every tagged incident segment for which it owns an endpoint slot. It recomputes the pair from frozen positions and takes only that slot, exactly as the collision gather does. A complete node-to-tagged-segment CSR is therefore required. Shared endpoints and any CPU exclusions must be filtered identically.

### Inverse mass and timestep semantics

For a true force, an endpoint's positional contribution over a Verlet substep is proportional to

`h² × inverseMass(endpoint) × endpointForce`.

That differs from a PBD distance projection, whose correction divides by a common effective-mass denominator. Adding that denominator would turn affinity into a constraint-like correction and change its mass and strength semantics. The compatibility-first port should mirror whatever `attract()` currently means:

- If its value is a force, retain `h²` scaling.
- If it is already a per-step displacement, preserve that definition initially and document that it is timestep dependent.
- If CPU code deliberately uses segment-average mobility rather than endpoint inverse mass, mirror it for parity before changing the model.

The standard PBD loop accumulates external forces before predicting positions and projects constraints afterward; see the original [Position Based Dynamics paper](https://doi.org/10.1016/j.jvcir.2007.01.005). That ordering is a good fit here: affinity influences the predicted position, while length, bend, bounds, and collision get the final authority to restore valid geometry.

### Do not automatically contact-average affinity

Collision contact averaging is a numerical guard for simultaneous inequality corrections. Affinity is an additive many-body effect: twice as many attractive neighbors normally means more attraction. Dividing by active pair count changes the physical/visual behavior, especially in clusters.

For CPU compatibility, use an unnormalized sum and stabilize it with:

1. a per-pair displacement/force clamp;
2. an aggregate per-node vector-magnitude clamp;
3. correct substep scaling;
4. optional strength retuning after the GPU and CPU trajectories are compared.

If density-independent affinity is actually desired, normalize by a deliberate smooth weight sum, not raw pair count, and treat that as a model change. Keep its normalization separate from collision and bend counts.

### Symmetry of the object-pair matrix

The pair must select one scalar value deterministically. If `vmat[A][B] != vmat[B][A]`, two per-node invocations must not independently use their own row: that would destroy equal-and-opposite pair force and create center-of-mass drift.

Canonicalize the segment pair and reproduce the CPU's exact matrix lookup/symmetrization rule once conceptually. Every endpoint recomputation must derive the same signed scalar regardless of which incident segment discovered the pair. If directional/asymmetric affinity is intentional, document that it is an active non-reciprocal force and accept the resulting momentum injection explicitly.

## Q3 — nonlinear falloff and stability

### Recommended scalar shape

The broad phase should be conservative; the gather should apply the exact scalar law. A stable shape has three parts:

1. exact segment distance and closest points;
2. a near-contact gate that fades affinity out before collision must separate the pair;
3. a cutoff falloff that reaches exactly zero at the pair range.

A hard gate produces chatter when collision moves a pair back and forth across the threshold. Prefer a short `smoothstep`-style transition, ideally with zero slope at both ends. The same applies at the outer cutoff if visible popping occurs.

For near-zero closest distance, `normal = delta/dist` is ill-conditioned. Attraction should already be suppressed by the near gate. Repulsion still needs the same deterministic fallback-normal policy used by collision; otherwise f32 noise can rotate a large clamped response.

### Solver ordering

Recommended substep order:

1. integrate external acceleration and affinity into predicted positions;
2. solve length and bend/curl;
3. solve collision and bounds last, or at least finish with collision/bounds;
4. update velocity/previous-position state consistently with the engine's Verlet scheme.

Do not repeatedly apply the full affinity force in every constraint iteration. That makes strength scale with iteration count. One affinity evaluation per substep is the clean default; if reevaluation is needed for strongly nonlinear behavior, divide or reformulate it so total strength remains invariant.

### Specific traps

- **Collision fighting attraction:** fade attraction to zero at or just outside the collision target; let collision win the final projection.
- **Repulsion plus collision double counting:** decide whether near-range repulsion supplements collision or hands off to it. A smooth partition is more stable than two full-strength responses.
- **Discontinuous sign or matrix lookup:** all four endpoint invocations must choose identical pair sign and range.
- **Changing closest features:** closest parameters can jump between endpoint and interior regions. Smooth scalar falloff and aggregate clamps bound the resulting direction change.
- **Large neighbor count:** an individually weak pair can still create a large sum. The final node clamp is mandatory telemetry, not merely a last-resort branch; count how often it activates.
- **Timestep dependence:** force-like displacement scales with `h²`. Retune from that invariant when substep count changes. Work on small substeps is generally more stable than spending the same work on many iterations of a large step; see [Small Steps in Physics Simulation](https://doi.org/10.1145/3309486.3340247).
- **NaN propagation:** reject non-finite matrix values, ranges, distances, and accumulated vectors, and expose a diagnostic counter.

At omega near 1, begin with conservative clamps rather than lowering the shared collision/constraint omega. Affinity should have its own strength and aggregate cap because it is a force pass with different scaling.

## Validation checklist

- GPU candidate set contains every brute-force tagged pair inside its exact pair range.
- Each active segment pair contributes exactly once to each participating endpoint slot.
- Home-cell ownership is computed from the exact stored insertion rectangles.
- Affinity bin overflow and insertion overflow are both zero; otherwise the pass is rejected.
- Swapping canonical discovery side does not change pair sign, range, matrix value, or endpoint result.
- For symmetric `vmat` and all nodes movable, the mass-unscaled four endpoint forces sum approximately to zero.
- Fixed endpoints receive zero displacement while movable endpoints still respond according to the CPU rule.
- Strength remains comparable when substep count changes after applying the intended `h²` scaling.
- Attraction fades before collision contact and does not produce gate chatter.
- Cluster tests record candidate count, active-pair count, maximum node sum, and pair/node clamp counts.
- Direct all-pairs and grid paths agree within f32 tolerance on the same frozen snapshot.

## Final answers

### Q1

Use a second, tagged-only coarse uniform grid. Reuse AABB insertion, stored cell rectangles, hard overflow checks, and home-cell dedup. Keep a direct tagged all-pairs path for small sets and choose the crossover by benchmark.

### Q2

Use closest-point barycentric endpoint slots `(1-s, s, 1-t, t)`, equal-and-opposite segment forces, and each endpoint's own inverse mass. In a force interpretation scale by substep `h²`. Sum neighbors for compatibility; use per-pair and final per-node clamps rather than collision-style contact averaging.

### Q3

Evaluate affinity once per substep before structural/contact projection. Smooth both the near-contact handoff and outer cutoff, use a deterministic zero-distance normal, make matrix/range selection canonical, and prevent collision/repulsion double application. Track clamp activation and timestep scaling explicitly.

## Sources

- Matthias Müller et al., [Position Based Dynamics](https://doi.org/10.1016/j.jvcir.2007.01.005).
- Miles Macklin et al., [Small Steps in Physics Simulation](https://doi.org/10.1145/3309486.3340247).
- Scott Le Grand, [GPU Gems 3, Chapter 32: Broad-Phase Collision Detection with CUDA](https://developer.nvidia.com/gpugems/gpugems3/part-v-physics-simulation/chapter-32-broad-phase-collision-detection-cuda).
- David Algis et al., [Efficient GPU Implementation of Particle Interactions with Cutoff Radius and Few Particles per Cell](https://arxiv.org/abs/2406.16091).
- W3C GPU for the Web Community Group, [WebGPU Shading Language specification](https://www.w3.org/TR/WGSL/).
- Project context: [`Claude apps/string engine/string-engine.html` on `feature/gpu`](https://github.com/Theory-box/Claude-Relay/blob/feature/gpu/Claude%20apps/string%20engine/string-engine.html). The repository page was not needed as a source for the general GPU/PBD claims above; exact CPU range and matrix semantics should still be checked directly during integration.
