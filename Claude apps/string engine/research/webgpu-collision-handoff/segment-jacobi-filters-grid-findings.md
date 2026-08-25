# Segment Jacobi narrow phase: equivalence, filters, and grid reuse

Findings for `Theory-box/Claude-Relay`, branch `feature/gpu`. Source behavior cross-checked at commit `0179580410aff2cbdf2fc062b1e4d0ccf5c8a80e`. No engine code.

## Executive recommendation

- The per-node kernel is algebraically equal to a **pair-once Jacobi** kernel if both compute the same canonical constraint set and the node kernel adds each pair's contribution to that node exactly once. It is not bitwise equal because f32 summation order may differ, and it is not equal to the current sequential CPU loop across multiple pairs because that loop is Gauss–Seidel-like.
- Upload the exact topological exclusions as sorted CSR when topology changes. A strand/order rule is faster and smaller, but exact only for simple chains/rings with a well-defined order. A hybrid rule-plus-exceptions representation is attractive if profiling shows CSR membership is material.
- Filter canonical pairs once, before building node-to-pair adjacency. Do not repeat exclusion searches in four endpoint invocations.
- Build the grid/contact superset once per substep and reuse it for the K Jacobi iterations with a conservative skin. If maximum endpoint displacement from the build pose is `d`, inflate each segment AABB by `d`; equivalently the total pair cutoff needs a `2d` skin.

## Q1 — proof and stress cases

Let `X` be the frozen input position array for one Jacobi iteration, and let `P` be the deduplicated, filtered set of canonical segment pairs. For pair `p`, define `delta(p,slot,X)` as the correction calculated for one of its four endpoint slots from the common closest-point result and common pair-wide denominator.

A pair-centric Jacobi implementation computes:

```text
output[i] = X[i] + Σ(p in P) Σ(slot of p whose nodeId == i) delta(p,slot,X)
```

The per-node implementation computes that same expression directly for each `i`. Therefore the two are algebraically identical. Parallelizing by pairs versus nodes only changes where the sum is formed.

This establishes equality only if all of the following hold:

1. Both use the same frozen `X` throughout the iteration.
2. Pair IDs are canonical and broad-phase multi-cell duplicates are removed.
3. The node-to-pair incidence contains one record per `(node,pair)`, not one per grid occurrence or discovery path.
4. The node invocation reconstructs the same closest result, normal, penetration, inverse-mass denominator, relaxation, and clamps as the pair implementation.
5. A node adds all endpoint-slot contributions it owns, then writes once.
6. Contact-count normalization uses the same definition in both implementations.

### Not bitwise equality

Real-number addition is commutative; f32 addition is not associative. Different pair order in a node's adjacency list can change low bits. For strict diagnostics, sort each node's pair list by canonical pair key and make the CPU Jacobi oracle accumulate in the same order. Otherwise validate within an f32 tolerance and compare physical invariants.

### One node has two incident segments, both colliding with one partner

Suppose node `i` owns endpoint slots on segments `A` and `C`, and both pairs `(A,B)` and `(C,B)` are valid. These are **two distinct constraints**, not a duplicate. Pair-once Jacobi applies both corrections to `i`; per-node Jacobi must also add one `i` contribution from each pair. The endpoints of `B` likewise receive two distinct contributions.

It may look like B is “double pushed,” but CPU pair-once processes both segment pairs too. Removing one would change the model. Stability under many such constraints belongs in contact averaging/clamping, not pair deduplication.

The trap is representation: if the node kernel reaches `(A,B)` through multiple grid cells, or the same incident segment appears twice, that is an accidental duplicate. Deduplicate by canonical segment-pair ID before constructing node adjacency.

### Both partners are in the same node's incident set

That means the two segments share the node. At the examined commit, CPU `collide()` rejects every shared-endpoint pair before narrow phase, so the correct GPU result is to reject it too. The situation should never enter node adjacency.

If shared-endpoint collision is later enabled, the physical node may occupy a slot on both sides of one constraint. Evaluate the canonical pair once for that node and add both signed slot contributions. With `n` pointing from closest point B to closest point A, A's contributions are positive and B's are negative. Do not apply a pre-summed “node result” once through A's incidence and again through B's incidence.

For a principled PBD denominator, repeated endpoint slots are not independent degrees of freedom. Sum the constraint gradients for each unique physical node first, then square that combined gradient in the effective-mass denominator. The usual four independent terms are valid only when all endpoint nodes are distinct.

### Sign checklist

For closest points `pa=lerp(a0,a1,s)`, `pb=lerp(b0,b1,t)`, define `n=(pa-pb)/distance`, pointing B→A. An overlapping pair should produce:

```text
a0: +(1-s) * positiveScale * n
a1: +s     * positiveScale * n
b0: -(1-t) * positiveScale * n
b1: -t     * positiveScale * n
```

Useful invariant tests:

- Equal masses and no pins: the mass-weighted center should not translate from one isolated contact.
- Swap A/B and map `s↔t`: endpoint vectors should be unchanged after relabeling.
- Reverse A's endpoints: `s` becomes `1-s`, but physical-node corrections stay unchanged.
- Reverse B similarly.
- One endpoint at closest point (`s=0/1`): the opposite endpoint's barycentric contribution is zero.

### Current CPU is not the proof target across a whole pass

The existing CPU loop immediately modifies all four endpoints and then evaluates later pairs from modified positions. That is a Gauss–Seidel ordering. A frozen-buffer GPU iteration is Jacobi. The equivalence proof is between two ways of evaluating the same Jacobi sum, not between Jacobi and the existing order-dependent CPU pass.

Also verify the intended mass rule. At `0179580`, CPU collision uses average mobility per segment and then barycentric splitting. That differs from textbook endpoint-wise PBD using squared barycentric gradients. Exact legacy parity and a principled inverse-mass formulation are separate targets.

## Q2 — encoding exclusion filters

The cheap filters should be packed into per-segment/per-object metadata:

- Shared endpoint: compare the four endpoint node IDs.
- Bond: one segment flag bit.
- Same object with `selfSolid == false`: segment object ID plus one packed object flag.
- Topological-near exclusion: CSR or an order rule as discussed below.

Apply these once to canonical candidate pairs. The output should be a filtered pair array; build node→pair CSR from that. Then the four per-node evaluations do not repeat filter work.

### Exact CSR exclusion list

Representation:

```text
exclOffsets[numSegments + 1]
exclSegmentIds[totalExclusions]
```

Sort each row. For short rows, a linear scan is usually better than binary search on GPU; benchmark the crossover. If rows can be long, binary search reduces comparisons but introduces divergent branches and scattered reads.

Advantages:

- Exactly represents the current CPU graph-distance BFS, including loops, imported graphs, branches, cuts, and merges.
- Rebuilt/uploaded only when topology or thickness/rest values that determine the skip radius change.
- Simple to validate row-for-row against CPU exclusion sets.

Costs:

- Two extra storage ranges and irregular reads during filtering.
- Memory is `O(total excluded pairs)`, approximately `O(segments × local topological radius)` for ordinary strands but worse around high-degree graph nodes.
- A per-segment row can be asymmetric if its skip radius differs from the partner's.

The final point matters for exact parity. At `0179580`, exclusions are computed per source segment using a skip derived from that segment's rest length, while collision canonicalizes `A<B` and tests only `A.excl.has(B)`. If rest lengths vary, the relation need not be symmetric. Preserve that directional/lower-ID behavior for exact validation, or deliberately redefine the CPU and GPU filter as symmetric.

### Strand ID + along-strand index

For a simple open chain, exclusion can be `sameStrand && abs(indexA-indexB) <= skip`. For a ring, use circular distance `min(diff, segmentCount-diff)`. This is O(1), coherent, and needs only a few integers per segment.

Advantages:

- Minimal memory and bandwidth.
- No variable-length lookup or divergent loop.
- Easy to evaluate during pair filtering.

Limitations:

- “Along index” is not well-defined at branches or general graph topology.
- Cuts, merges, and dynamic topology require reindexing components.
- Per-segment or nonuniform skip radii need carefully specified directional/symmetric behavior.
- Two segments may be close in graph distance through a junction while far in any arbitrarily chosen linear ordering.

Given the engine's graph-based exclusion construction, a pure order rule is safe only if runtime topology is guaranteed to remain degree≤2 chains/rings.

### Recommended choice

Use sorted CSR first. It preserves semantics and its cost is paid once per candidate pair, not once per endpoint. Topology changes are much less frequent than solver iterations, so CPU construction plus buffer upload is a good trade.

If exclusion filtering becomes significant, use a hybrid:

- O(1) strand/order metadata for components proven to be simple chains/rings.
- CSR exception rows for branched/general components or nonuniform rules.

A dense bit matrix is unattractive beyond small segment counts (`S²/8` bytes). Bloom filters risk false exclusions, which create missed physical contacts; they are unsuitable unless every positive is confirmed against an exact list.

### WebGPU layout notes

- Pack segment endpoints, object ID, and flag bits into aligned `vec4<u32>`-like records where convenient.
- CSR offsets and indices can share one storage buffer at known aligned byte ranges if binding limits are tight.
- The hardware diagnostic at `0179580` reports eight storage buffers per shader stage. Use a dedicated pair-filter pipeline rather than exposing every solver buffer to one monolithic shader.
- Dynamic topology uploads should use newly sized buffers or capacity-managed buffers; never let stale offsets address beyond the uploaded exclusion array.

## Q3 — rebuild every iteration or reuse?

Production-style PBD generally separates **substeps** from **solver iterations**. Neighbor/contact generation is commonly performed once per substep, and the resulting conservative set is reused across the inner constraint iterations. NVIDIA's Unified Particle Physics algorithm finds neighbors and solid contacts before its stabilization and solver-iteration loops. This is a representative GPU PBD design, not a universal rule.

General collision engines use the same principle in other forms: buffered/persistent pair sets, contact offsets, and speculative margins. LAMMPS/GROMACS use Verlet neighbor lists with a skin and rebuild after sufficient motion; PhysX generates contacts before actual overlap using contact offsets and can inflate them based on predicted motion for speculative CCD.

### Exact conservative bound for segments

Let segment A's endpoints move by at most `dA` from the grid-build pose, and B's by at most `dB`. Any point at a fixed barycentric parameter on a segment moves no farther than the maximum of its endpoints' movements. Therefore the distance between the two segments can decrease by at most:

```text
dA + dB
```

For a uniform bound `d` on every endpoint, a pair-list cutoff needs an extra skin of at least `2d`.

There are two equivalent margin conventions; do not mix them:

- **Per-segment AABB inflation:** expand every segment's already radius/pad-expanded AABB by `M >= d`. Two expanded AABBs provide `2M` relative coverage.
- **Single pair-distance/list skin:** use `skin >= 2d` beyond the true contact cutoff.

This is the same factor-of-two logic behind rebuilding a Verlet list when any particle moves more than half the total skin.

If each Jacobi iteration clamps a node's final correction magnitude to `cMax`, then the worst-case endpoint displacement after K iterations is:

```text
d <= K * cMax
```

So a proof-safe choice is per-segment AABB margin:

```text
M >= K * cMax
```

Add any displacement from other operations performed after the build: length/bend constraints, dragging, kinematic edits, integration if the grid was built before prediction, and depth-axis effects if the grid is 3D. Bounds add by triangle inequality. If those moves are not bounded, no fixed margin proves reuse safe.

Use a small numerical guard beyond the theoretical margin for f32 cell-boundary rounding. Conservative floor/ceil cell coverage is required.

### Practical recommendation for this engine

1. Build after integration/prediction and any large kinematic edits.
2. Insert each segment's swept/fat AABB using its contact radius/pad plus `M`.
3. Generate/deduplicate/filter the pair superset once.
4. Build node→pair adjacency once.
5. Reuse both for all K=2–8 collision Jacobi iterations.
6. In each iteration, still run the exact current-distance test; fat-margin pairs are only candidates.

Start with `M=K*cMax` if collision is the only position-changing operation inside the reuse window. This is conservative and easy to validate. Compare its extra candidate count with rebuilding every iteration.

### When rebuilding wins

Rebuild every iteration, or every small batch of iterations, when:

- corrections/teleports are not tightly clamped;
- length/bend/drag passes are interleaved and can move endpoints substantially;
- `K*cMax` makes fat AABBs cover so many cells that narrow-phase recomputation dominates;
- the scene is highly clustered and conservative margins explode pair counts;
- topology changes inside the solve window;
- exact new contacts created by solver motion are more important than grid cost.

A useful middle ground is rebuild every 2 iterations with `M=2*cMax`.

### Adaptive reuse on WebGPU

Track maximum squared endpoint displacement from the build pose on GPU. In a CPU solver, exceeding the threshold triggers immediate rebuild. In WebGPU, reading that flag back each iteration can stall the queue and erase the savings. Prefer a proof-safe fixed margin/cadence, or consume the flag entirely in a later GPU-driven design. WebGPU does not provide a general conditional command-encoder branch, so fixed scheduled rebuilds are simpler and portable.

Validate reuse with an adversarial CPU oracle: after every iteration, rebuild an exact grid/pair set and assert that every currently contacting pair exists in the reused superset. Test opposing maximum corrections, cell-boundary positions, long diagonal segments, clustered folds, pins, and dragged nodes.

## Primary references

- Macklin et al., *Unified Particle Physics for Real-Time Applications*, Algorithm 1: neighbor/contact generation precedes stabilization and solver iteration loops: https://matthias-research.github.io/pages/publications/flex.pdf
- LAMMPS developer documentation, Verlet neighbor-list skin and half-skin rebuild criterion: https://docs.lammps.org/Developer_par_neigh.html
- GROMACS reference manual, buffered pair-list reuse on CPUs/GPUs: https://manual.gromacs.org/current/reference-manual/algorithms/molecular-dynamics.html
- NVIDIA PhysX, contact/rest offsets and speculative collision margin: https://nvidia-omniverse.github.io/PhysX/physx/5.1.2/docs/AdvancedCollisionDetection.html
- W3C WGSL specification: https://www.w3.org/TR/WGSL/

