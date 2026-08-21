# Layer 3c final design review

Context: `Theory-box/Claude-Relay`, branch `feature/gpu`, commit `75a6d26`. Findings only; no engine code.

## Overall verdict

The owner-cell/per-node design is correct and sufficient to give every endpoint of a valid contact exactly one node-local contribution, provided several invariants listed below are enforced. There is no need for a global pair list or float atomics.

The design has four remaining correctness decisions that should be explicit before implementation:

1. **Ring exclusions need circular distance.** Plain absolute along-index distance is correct only for open chains.
2. **Pinned endpoint semantics conflict with segment-average mobility.** If fixed nodes do not write corrections, simply discarding their barycentric slot under-applies the pair response unless the response rule redistributes or uses endpoint-level effective mass.
3. **The fallback normal must distinguish 2D and 3D and must have a final canonical-ID sign fallback.** “Perpendicular to the longer segment” is unique up to sign in 2D, but not in 3D.
4. **The Verlet displacement bound must include every position-changing operation inside the reuse window**, not only collision corrections.

With those resolved, the assembled design has no structural missed-contact or double-application gap.

## Proof of owner-cell sufficiency

Consider a valid contacting segment pair A/B and one physical endpoint node i belonging to A. The same argument applies symmetrically to B.

- Broad-phase completeness guarantees A and B were both inserted into at least one common cell.
- Their stored integer cell rectangles therefore have a nonempty intersection.
- The lowest cell of that intersection is unique and is visited while i scans A's stored rectangle.
- B is present in that cell's occupant list, assuming zero CAP overflow and complete rectangular insertion.
- The owner-cell predicate accepts A/B in that one cell and rejects every other common cell.
- Canonical pair ordering makes filters, closest geometry, fallback-normal orientation, and response coefficients identical regardless of whether A's or B's endpoint invocation discovered the pair.
- Node i selects its one A endpoint slot, adds it once, and writes only i.

Thus every distinct endpoint node of A/B receives its appropriate contribution exactly once. Recomputing the pair in multiple endpoint invocations is intentional Jacobi evaluation, not double-application to one node.

The proof depends on these invariants:

- Every segment is inserted exactly once in every cell of its stored rectangular bounds.
- Stored bounds describe the build-time insertion, not corrected positions from a later iteration.
- The rectangle is not silently truncated by a maximum-cells-per-segment limit or world-bound clipping.
- Every cell gather clamps its read count to CAP to prevent out-of-bounds access, even though any overflow separately hard-fails validation.
- Bin overflow is zero.
- Node→segment CSR contains every live endpoint incidence exactly once and is current for the topology generation.
- A/B are canonicalized before all pair-wide math, but discovery is not restricted to only the lower-index segment.
- Segment metadata, object flags, radii/pads, and topology metadata remain immutable throughout the K-iteration reuse window.

If any insertion cell is dropped, the stored occupied set is not a complete rectangle, or CAP overflow occurs, the home-cell proof no longer holds. A hard diagnostic is appropriate; do not treat the resulting frame as a narrow-phase failure.

## Deduplication and distinct constraints

The owner-cell rule removes only repeated spatial discoveries of the same segment pair. It does not merge physically distinct pairs.

If node i is incident to X1 and X2 and both contact Y, `(X1,Y)` and `(X2,Y)` have separate rectangle intersections and separate owner cells. The node processes each while scanning its corresponding incident segment and counts two active constraints. Endpoints of Y likewise process both pairs. This matches pair-once Jacobi.

If X and Y are both incident to i, they share an endpoint and are rejected before response. The stated “at most one slot per node” assumption is therefore valid for accepted ordinary segments.

Also reject X==Y before pair filters. Ensure duplicate incident segment IDs cannot enter node CSR. A degenerate segment with the same node ID at both ends violates the one-slot assumption even without a second segment; reject it during topology build or define a two-slot policy explicitly.

## Filter review

### Shared endpoint, bond, and self-pass-through

These are straightforward and GPU-friendly. Perform them before closest-point math. Use canonical A/B metadata consistently so filter outcomes do not depend on which incident side discovered the pair.

Object flags can change without topology changes, so the uploaded `selfSolid` state must be refreshed whenever UI/material state changes. Bond/topology generations need equivalent synchronization.

### Chain exclusion rule

For a simple open chain, the proposed strict rule is correct:

`same component && abs(alongA-alongB) < Kcanonical`, with `Kcanonical = skipcanonical + 1`.

The canonical segment is the lower global segment ID if exact parity with the examined CPU behavior is required, because the CPU canonicalizes the pair and checks only that segment's exclusion set. Since skip can depend on segment rest length, replacing it with `max(skipA,skipB)` would be a deliberate symmetric behavior change.

The strand identifier must mean connected continuous component, not merely object/material ID. Separate strands within one object must have different IDs.

### Ring gap

For a ring of N segments, absolute index difference is not graph distance at the wrap. Use circular distance:

`min(abs(alongA-alongB), N-abs(alongA-alongB))`.

Apply the same strict comparison against K. The topology build must upload the component type and ring segment count.

### General-graph CSR fallback

The fallback must preserve the CPU's potentially directional row semantics if exact parity is still the target. When a pair belongs to a complex component, query the canonical lower-ID segment's sorted CSR row for the other segment.

Be explicit about mixed classification: different connected components cannot be topologically near, so no exclusion lookup is needed. If both segments share a component classified chain/ring, use the O(1) rule; if they share a complex component, use CSR.

Cuts, merges, deletion, compaction, radius changes, and rest-length changes that alter skip require a new topology/exclusion generation before collision runs.

## Response and effective-mass review

### Closest-point robustness

The relative parallel threshold is dimensionally appropriate after both segment-length degeneracy checks. Clamp or branch away from a slightly negative denominator caused by f32 rounding. Continue comparing squared distance against squared target before the square root.

Canonicalize operands before calling closest. Otherwise endpoint nodes that encounter the same pair from opposite incident sides can select different provisional parallel parameters or fallback-normal signs.

### Near-zero fallback normal

The fallback must be a total deterministic function: it must produce the same B→A-oriented unit normal in all endpoint invocations, including coincident midpoints.

For 2D:

- use the perpendicular of the longer nondegenerate segment;
- orient it by midpoint separation when that projection is nonzero;
- otherwise orient by relative closest-point velocity if available;
- finally choose sign from the canonical pair ID.

For 3D:

- for nonparallel directions, the normalized cross product supplies a perpendicular contact axis, with canonical orientation;
- for parallel directions, project midpoint separation onto the plane perpendicular to the longer segment;
- if that projection is also near zero, cross the segment direction with a deterministically chosen least-aligned coordinate axis;
- use canonical pair ID for the final sign.

For two zero-length coincident segments, no geometric normal exists; canonical-ID direction, cached prior normal, or relative velocity is required. The current “perpendicular of longer segment” description is incomplete for that case.

Ericson's companion discussion confirms that parallel overlapping segments can have a continuum of valid closest-point parameters and that choosing an overlap midpoint improves contact-position continuity: [parallel-segment closest-point discussion](https://realtimecollisiondetection.net/blog/?p=41).

### Penetration clamp

Applying `min(penetration, 0.25·target)` before mass distribution is the correct location. It bounds one constraint while preserving pair-wide mass ratios. Handle nonpositive/invalid target explicitly.

The clamp bounds magnitude, not direction sensitivity. The deterministic fallback covers the zero-distance singularity; ordinary small nonzero distances may still rotate substantially under f32 perturbation. The final node clamp and repeated Jacobi iterations bound integrated behavior, but dev telemetry should record how often the near-zero/fallback branch and both clamps activate.

### Segment-average mobility and pins

This is the main effective-mass decision.

The examined CPU collision computes one average mobility for each segment, forms a pair-wide split from the two segment averages, then divides each segment's correction barycentrically. This gives all endpoints on one segment a common segment-side coefficient before `(1-s)`/`s` splitting.

If a fixed endpoint's node invocation writes no correction while its movable partner uses the legacy segment-average coefficient, the fixed endpoint's allocated barycentric share disappears. The remaining movable endpoint does not receive the full segment-side correction. Contacts against partly pinned segments will therefore separate too little and can become dependent on closest parameter.

Choose one explicit policy:

- **Exact legacy response:** reproduce all four CPU slot updates, including whatever later pin-restoration behavior the CPU relies on. This may temporarily move nodes labeled fixed.
- **Pins are immovable:** use a response/effective-mass rule that assigns zero gradient weight to fixed nodes and computes the pair denominator from the movable endpoint degrees of freedom, or deliberately renormalize the legacy segment-side share among movable endpoints.
- **Intentional under-correction:** discard fixed slots and accept weaker collision response. This is simple but should not be called correct effective mass.

The principled PBD formulation uses inverse mass per degree of freedom in the pair-wide gradient denominator, as summarized in §4.1 of [Unified Particle Physics for Real-Time Applications](https://matthias-research.github.io/pages/publications/flex.pdf). Moving from legacy segment-average mobility to that formulation is a behavior change, so validate it separately.

Also skip the response when the pair's total movable effective mass is zero. Do not count that pair as an active contact for an immovable node.

## Accumulation and stability review

The proposed order is correct:

1. clamp pair penetration;
2. calculate this node's signed slot correction;
3. sum unique active-pair contributions;
4. divide by the active-contact normalization measure;
5. multiply by SOR omega;
6. apply the final vector-magnitude clamp;
7. write frozen position plus delta.

Count a contact only when it passes filters, is actually penetrating, has a valid normal, and has a nonzero potential influence on the current movable node. Do not count candidate pairs, filtered pairs, fixed-only responses, or cell occurrences.

Starting omega at 1 is conservative. Constraint averaging followed by SOR matches the parallel PBD structure in [Macklin et al.](https://matthias-research.github.io/pages/publications/flex.pdf). Their analysis also notes that per-particle contact averaging is not guaranteed to conserve momentum when neighboring particles have different constraint counts. That is an accepted Jacobi trade-off, not evidence of duplicate processing.

The final magnitude clamp must use a stable node-defined scale. Do not derive it from the last visited pair, because atomic bin order is nondeterministic. A scale derived from immutable incident-segment metadata or a deterministic reduction such as min/max over active targets is appropriate.

For initial validation, use full active-contact count. Barycentric-weighted normalization may reduce overdamping near an endpoint with tiny slot weight, but it is a later solver-quality change rather than a correctness prerequisite.

## Grid and pair-set reuse

The reuse design is safe only with a complete displacement bound.

If an endpoint can move at most `d` from the grid-build pose during the entire reuse window, inflate each segment's already contact-expanded AABB by at least `d`. This is equivalent to a total pair-list skin of `2d`, because both segments may approach each other. This is the standard factor-of-two reasoning behind rebuilding a Verlet list when any particle moves half the list skin; see the [LAMMPS neighbor-list documentation](https://docs.lammps.org/Developer_par_neigh.html).

If the final collision correction clamp is `cNode` per iteration, collision alone gives the worst-case bound `K·max(cNode)`. Add bounds for every other position-changing operation between grid build and final collision iteration:

- length and bend constraints;
- drag/grab movement;
- pin or kinematic target changes;
- wall projection;
- integration if build occurs before prediction;
- depth motion in 3D;
- any structural pass interleaved between collision iterations.

If any contribution is unbounded, the skin is not proof-safe. Build after large kinematic/prediction motion, clamp all inner-loop correction groups, rebuild more frequently, or use a conservative global bound.

The stored owner rectangles must include the skin and remain unchanged for all K iterations. Each iteration still runs exact current-distance narrow phase, so skin creates extra candidates rather than false contacts.

Large skins can make fixed-cap bins overflow or greatly increase candidate cost. Benchmark build-every-iteration against reuse; reuse is not automatically faster when `K·clamp` covers many cells.

## WebGPU-specific failure handling

- Atomic bin counts may exceed CAP. Gather must read at most CAP entries to remain memory-safe, while the overflow flag makes the physical result invalid.
- A hard fail discovered by asynchronous readback occurs after an inaccurate dispatch may already have run. In development, surface the frame and stop/disable GPU collision; in production, define a recovery policy rather than silently continuing.
- No workgroup barrier is needed for owner-cell deduplication. Dispatch boundaries provide the global phase ordering between grid build and Jacobi iterations.
- Ping-pong position buffers are mandatory: every invocation in one iteration reads one frozen buffer and writes only its node in the other.
- Atomic insertion order can change accumulation order and low f32 bits. Pair-set/cardinality invariants and tolerance-based physical metrics are appropriate; JavaScript-f64 endpoint parity is not.
- Validate all dynamic buffer indices. Robust access behavior is not a substitute for correct cell, CSR, or CAP bounds. See the [WGSL specification](https://www.w3.org/TR/WGSL/).

## Pre-build checklist

- Owner cell derives from stored build-time rectangles.
- Complete rectangular insertion; no silent cell-span truncation.
- Gather count is clamped to CAP; overflow is a hard invalidation.
- Canonical A/B ordering is used for filters, closest, normal, and slot-role mapping.
- Either incident side may discover; no `X<Y` discovery restriction.
- Node CSR incidences are unique and topology-generation checked.
- Self-pairs and degenerate same-node segments have explicit rejection/policy.
- Open chains use absolute distance; rings use circular distance; complex graphs use CSR.
- Canonical lower-segment skip semantics match the CPU oracle.
- Fixed endpoint/effective-mass policy is chosen explicitly.
- 2D, 3D, parallel, and zero-length fallback normals are total and canonical.
- Active-contact count includes only constraints that can affect this node.
- Final clamp scale is independent of candidate visitation order.
- Skin covers collision plus every other correction inside the reuse window.
- Telemetry records bin overflow, fallback-normal count, per-pair clamp hits, final-clamp hits, contacts/node, maximum penetration, and NaNs.

## Final answer to the central question

Yes: **process at the unique owner cell, with either incident side allowed to discover, is fully sufficient for every distinct movable endpoint of a valid pair to receive exactly one correction.** It requires complete rectangular insertion, zero bin overflow, current unique node incidence, canonical pair-wide math, and correct mapping back to the discovering node's endpoint slot.

The owner-cell mechanism itself is not the remaining risk. The substantive remaining risks are ring-distance filtering, fixed endpoint/effective-mass semantics, an incomplete 3D/degenerate fallback normal, and an underestimated grid-reuse displacement bound.

## Sources

- NVIDIA, [GPU Gems 3, Chapter 32: Broad-Phase Collision Detection with CUDA](https://developer.nvidia.com/gpugems/gpugems3/part-v-physics-simulation/chapter-32-broad-phase-collision-detection-cuda) — multi-cell ownership and Jacobi collision processing.
- Macklin et al., [Unified Particle Physics for Real-Time Applications](https://matthias-research.github.io/pages/publications/flex.pdf) — inverse-mass PBD response, projected Jacobi, constraint averaging, and SOR.
- Christer Ericson, [parallel segment closest-point discussion](https://realtimecollisiondetection.net/blog/?p=41) — nonunique closest parameters and overlap-midpoint refinement.
- LAMMPS, [Verlet neighbor-list documentation](https://docs.lammps.org/Developer_par_neigh.html) — skin distance and half-skin rebuild criterion.
- W3C, [WebGPU Shading Language specification](https://www.w3.org/TR/WGSL/) — memory, indexing, synchronization, and floating-point rules.
- Project source, [`string-engine.html` on `feature/gpu`](https://github.com/Theory-box/Claude-Relay/blob/feature/gpu/Claude%20apps/string%20engine/string-engine.html) — CPU filter, mobility, closest-point, and response behavior.

