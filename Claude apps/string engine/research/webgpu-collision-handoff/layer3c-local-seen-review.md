# Layer 3c review: self-contained per-node gather with local seen-array deduplication

Context: `Theory-box/Claude-Relay`, branch `feature/gpu`, commit `75a6d26`. Findings only; no engine code.

## Verdict

The per-node discovery topology is sound, but a small fixed local seen array has no scene-independent safe capacity. Segment length and cell size bound how many cells one segment visits; they do **not** bound how many other segments can occupy those cells. Dense folds can produce arbitrarily many candidates up to the bin CAP and segment count.

The strongest design remains a deterministic shared-cell ownership rule, which removes multi-cell duplicates without per-invocation storage. If the local seen array is retained:

- scope it **per incident segment X**, storing candidate segment IDs Y; or store canonical `(X,Y)` keys if one table spans the whole node invocation;
- never use one node-wide set keyed only by Y, because that incorrectly merges the distinct constraints `(X1,Y)` and `(X2,Y)`;
- treat capacity overflow as a correctness event, not a performance statistic;
- on overflow, continue processing rather than silently dropping candidates, set a diagnostic flag/counter, and accept that the fallback frame may overweight duplicates unless it switches to an exact ownership rule.

## Important qualification on the preceding POC conclusion

The identity

`correctionA0 + correctionA1 = commonSegmentScale · normal`

is independent of closest parameter `s` only when both endpoint corrections use the same segment-side scale and differ solely by `(1-s)` and `s`. That matches the examined CPU formula at the earlier commit, where a segment-average mobility produces one common `cA`.

If layer 3c instead multiplies each endpoint slot by its own inverse mass, the sum is proportional to

`inverseMassA0·(1-s) + inverseMassA1·s`,

which generally depends on `s`. A textbook PBD denominator containing squared barycentric gradients also changes with `s`. Therefore the “same total push” invariant must be checked against the exact mass rule being integrated, not assumed from barycentric weights alone.

Even with a common segment-side scale, a different `s` changes angular/deformation distribution between endpoints. Structural constraints and later collision iterations can turn that into visible trajectory divergence. The near-parallel ambiguity can still be acceptable, and it does not imply incorrect closest distance, but “benign” should mean invariant tests and visual/stability tests pass—not that the two endpoint states are mathematically equivalent.

If exact distribution continuity becomes important, the known refinement is to choose a deterministic midpoint of the overlapping interval for parallel/collinear segments rather than accepting an arbitrary closest point. Christer Ericson's companion discussion describes this ambiguity: [parallel segment closest-point choice](https://realtimecollisiondetection.net/blog/?p=41).

## Q1 — fixed-size local seen-array failure modes

### There is no small safe cap implied by short segments

For one incident segment X, define:

- `cells(X)` as the number of grid cells covered by its inserted AABB;
- `CAP` as the fixed maximum occupants stored per cell;
- `S` as the total segment count.

The number of raw candidate visits for X is bounded by `cells(X)·CAP`. The number of unique candidate segment IDs is bounded by `min(S-1, cells(X)·CAP)`. This is the only simple proof-safe capacity bound available from the stated structure.

If a node-wide table covers all incident segments, with node degree `degree(i)`, its raw bound becomes the sum of `cells(X)·CAP` over all X incident to i. A coarse global bound is `maxDegree·maxCellsPerSegment·CAP`.

These bounds are often far too large for a private WGSL array. For example, even a degree-two node with several cells per expanded segment and a moderate bin CAP can require hundreds of unique IDs in the worst case. “Short strand” reduces `cells(X)` but does not constrain local density: many short segments can fold into the same cell.

Consequently:

- A chosen size such as 32, 64, or 128 may be a useful empirical fast-path capacity.
- None is a correctness-safe cap without an enforced scene occupancy invariant considerably smaller than the grid's bin CAP.
- The grid overflow counter and the local seen overflow counter measure different failures. A bin may remain below CAP while the union of several bins exceeds the seen capacity.

### Silent under-count is the worst fallback

When the seen array fills, rejecting every previously unseen Y creates false negatives: valid collision constraints disappear. This can be directional because the endpoint nodes of X and Y may overflow differently. The result can violate momentum symmetry and let segments pass through each other even though broad phase was complete.

Never silently stop admitting candidates. At minimum, atomically increment a seen-overflow counter and set a frame-level failure bit used by diagnostics.

### Fail-soft duplicate processing

If the table fills, continuing to process additional candidates without recording them avoids missed constraints, but later occurrences of those candidates may be processed repeatedly. This is safer than omission for collision containment, especially with the final per-node displacement clamp, but it is not equivalent to the intended solver:

- contacts with more shared cells receive more weight;
- contact-count averaging does not generally cancel duplicates because different pairs have different multiplicities;
- final clamping and SOR are nonlinear;
- atomic bin order can alter which candidates were successfully recorded before overflow.

This mode should be visibly diagnosed and treated as degraded behavior, not accepted as validated correctness.

### Exact overflow fallback

The best fallback is the same exact mechanism that can replace the seen array entirely: process a pair only in one deterministic cell shared by the two stored insertion AABBs, such as the lowest row-major cell in their integer-cell intersection.

Because this test is constant-time and invocation-local, it has no capacity failure. It is closely related to the home-cell ownership used to prevent repeat collision tests in [GPU Gems 3, Chapter 32](https://developer.nvidia.com/gpugems/gpugems3/part-v-physics-simulation/chapter-32-broad-phase-collision-detection-cuda).

If a hybrid is desired, decide the mode for a whole incident segment X before processing any of its candidates. Switching from seen-array processing to home-cell processing only after overflow can leave earlier pairs processed under different ownership and later pairs under the fallback. Since `cells(X)·CAP` is known before scanning, X can conservatively choose home-cell mode whenever that upper bound exceeds the fast-path capacity. This may choose the fallback unnecessarily but remains correct.

Given that the home-cell check is cheap, using it unconditionally is simpler than maintaining two deduplication paths.

### Private-array performance on WebGPU

A fixed function/private array is per invocation. Large arrays with dynamic indexing may consume many registers or spill into device-backed private memory, reducing occupancy and adding irregular memory traffic. The exact lowering is implementation- and adapter-dependent; WGSL does not promise register placement.

A linear seen scan also has quadratic comparison behavior in the unique candidate count: candidate j compares against all earlier IDs. A small open-addressed private hash table reduces expected comparisons but retains the same hard-cap and overflow problem. Before adding either, compare against the branch/arithmetic cost of the deterministic home-cell test.

Relevant language constraints are defined by the [WGSL specification](https://www.w3.org/TR/WGSL/), but register allocation and spilling remain implementation details.

## Q2 — can per-node discovery miss a node that should move?

No, assuming the node→segment CSR is complete and current.

The segment-segment contact response writes only the four endpoint slots of X and Y. A physical node i owns a nonzero slot only if i is an endpoint of X or Y, which is exactly the definition of being incident to that segment. Therefore every node that the pair-centric response could move will traverse at least one of the pair's segments:

- endpoint nodes of X discover Y while scanning X's occupied cells;
- endpoint nodes of Y discover X while scanning Y's occupied cells.

No node incident to neither segment should receive a direct correction from that pair. Collision effects propagate to other nodes later through structural constraints or subsequent iterations, not through this narrow-phase constraint.

This proof has operational preconditions:

- node CSR contains each live endpoint incidence exactly once;
- CSR is rebuilt after cuts, merges, deletion, or topology compaction;
- X scans the exact cells into which X was inserted;
- both X and Y insertions survived the bin CAP;
- a reused grid uses stored build-time cell ranges for traversal and dedup ownership;
- shared-endpoint pairs are rejected consistently before response;
- canonicalization does not impose a rule such as “only the lower segment may evaluate,” which would prevent nodes on the higher segment from writing their shares.

The CAP case deserves emphasis. A nonzero grid overflow counter invalidates the discovery proof: if Y was not stored in a shared cell, nodes on X may miss it, and the opposite traversal need not fail symmetrically. Treat zero bin overflow as a prerequisite for claiming broad-phase completeness.

Degenerate data also needs a defined policy. If a segment lists the same node as both endpoints, that node owns two slots; ordinary incidence CSR may list the segment once. The node response must then deliberately sum both slot contributions or such segments must be rejected during topology construction.

## Q3 — two incident segments colliding with one partner

Per-node discovery reproduces this correctly **only if deduplication keys include X**.

Let node i be incident to X1 and X2, with valid contacts `(X1,Y)` and `(X2,Y)`. These are two independent segment-pair constraints. The node invocation must:

1. process incident segment X1 and deduplicate repeated occurrences of Y only within X1's scanned cells;
2. process incident segment X2 and independently deduplicate repeated occurrences of Y within X2's scanned cells;
3. add one i-slot correction from each active pair;
4. increment the active-contact normalization measure twice.

The endpoint nodes of Y likewise discover X1 and X2 as two different candidate segment IDs and receive both Y-side contributions.

A node-wide seen set keyed only by Y is wrong: after `(X1,Y)` inserts Y, it suppresses `(X2,Y)`. That turns two physical constraints into one based on incidental incident-segment order.

Safe keying choices are:

- reset a Y-only seen list before each incident X; this has the smallest required capacity and simplest semantics; or
- retain one node-wide table keyed by canonical segment-pair `(min(X,Y),max(X,Y))`.

The first is preferable if the array design is retained. Its proof-safe capacity is based on one X's candidate union rather than the sum across the node's degree.

If Y is also incident to node i, then X and Y share endpoint i and the current shared-endpoint filter rejects the pair. Apply that filter consistently; do not let the two-slot shared-node case enter ordinary contact counting.

## Recommended decision

For correctness and simplicity:

1. Remove the local seen array from the required path.
2. For each X/Y encounter, derive the deterministic lowest shared cell from the stored integer insertion bounds.
3. Continue only in that cell.
4. Canonicalize X/Y for filters and closest-point conventions, while retaining whether node i belongs to canonical A or B for correction sign and barycentric slot selection.
5. Count each unique active `(X,Y)` constraint once per node.

If the local seen array is kept as an optimization experiment, scope it per X, add a hard overflow counter, and compare its total narrow-phase time against unconditional home-cell ownership. Do not call an empirical capacity safe unless the engine enforces and validates the corresponding occupancy bound.

## Validation cases

- One short X whose AABB shares many cells with one Y: one constraint per endpoint node.
- One X spanning several full CAP cells containing disjoint Y sets: force seen-array overflow without bin overflow.
- One node incident to X1/X2, both contacting Y: exactly two active constraints at that node.
- Same geometry with incident-segment order reversed: identical active pair set.
- Candidate order randomized within every bin: pair set unchanged; only tolerance-level f32 sum variation allowed.
- One node on X and one on Y: both sides discover the pair even when canonical X/Y order is reversed.
- Shared endpoint X/Y: zero constraint.
- Stale CSR/topology mutation test: diagnostics must catch generation mismatch.
- Bin CAP overflow: validation must fail rather than interpreting missing contacts as a narrow-phase result.
- Unequal endpoint inverse masses in an adversarial near-parallel overlap: test whether the chosen physical invariant is actually independent of `s`.

## Sources

- NVIDIA, [GPU Gems 3, Chapter 32: Broad-Phase Collision Detection with CUDA](https://developer.nvidia.com/gpugems/gpugems3/part-v-physics-simulation/chapter-32-broad-phase-collision-detection-cuda) — multi-cell duplicate collision tests, home-cell ownership, and Jacobi processing.
- Christer Ericson, [parallel segment closest-point discussion](https://realtimecollisiondetection.net/blog/?p=41) — nonunique contact-point parameters for parallel overlapping segments.
- W3C, [WebGPU Shading Language specification](https://www.w3.org/TR/WGSL/) — private/function storage semantics and portable language behavior.
- Project source, [`string-engine.html` on `feature/gpu`](https://github.com/Theory-box/Claude-Relay/blob/feature/gpu/Claude%20apps/string%20engine/string-engine.html) — CPU closest-point, exclusion, and four-endpoint response behavior.

