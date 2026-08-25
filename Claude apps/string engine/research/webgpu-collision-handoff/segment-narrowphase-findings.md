# Segment narrow-phase findings for Claude

Context checked against `Theory-box/Claude-Relay`, `feature/gpu`, commit `0179580410aff2cbdf2fc062b1e4d0ccf5c8a80e`. Findings only; no engine changes.

## Bottom line

Per-node independent recomputation is mathematically equivalent to a **pair-centric Jacobi** evaluation when every invocation reads the same frozen positions and each physical node receives exactly the endpoint-slot contributions belonging to it. It is **not frame-for-frame equivalent to the current CPU solver**, because that solver is Gauss–Seidel-like: it updates all four endpoints immediately, and later pairs recompute `closest()` from already-modified positions.

The recommended GPU design is still sound. Define parity against a reference Jacobi step, not against the order-dependent CPU loop. Keep a single canonical candidate-pair set, recompute closest geometry from the frozen input for every node, accumulate only the current node's contribution, average/relax the accumulated constraints, clamp, and write once.

## Q1 — equivalence and the actual traps

For pair `A=(a0,a1)` and `B=(b0,b1)`, let:

```text
pa = lerp(a0, a1, s)
pb = lerp(b0, b1, t)
n  = normalize(pa - pb)       // points B → A
penetration = target - distance
```

A pair-centric Jacobi pass computes four deltas from the same frozen state:

```text
Δa0 = +responseA0 * (1-s) * n
Δa1 = +responseA1 * s     * n
Δb0 = -responseB0 * (1-t) * n
Δb1 = -responseB1 * t     * n
```

A per-node pass that independently reconstructs the same `s`, `t`, `n`, penetration, mobility denominator, and response coefficient produces the same vector for every node, apart from ordinary f32 evaluation-order differences. Recomputing the pair four times is intentional; it does not multiply the global response by four because each invocation writes a different node.

### Conditions required for equivalence

1. Every invocation reads the same frozen position buffer for the entire iteration.
2. Candidate pair identity is canonical, normally `min(segA,segB), max(segA,segB)`.
3. Each node processes a canonical pair **once**, even if multi-cell AABB insertion emitted it through several cells or several incident-list paths.
4. Pair filtering is identical: exclusions, bonds, self-pass-through, 2D/3D choice, pad, radius, and topology filters.
5. The response denominator and clamping are pair-defined, not dependent on which endpoint invocation is evaluating it.
6. Output is `frozenPosition[node] + accumulatedNodeDelta`, not a read/modify/write of positions during the dispatch.

### Shared-node case

At the examined commit, CPU `collide()` explicitly rejects segment pairs sharing any endpoint:

```text
if (sa.a===sb.a || sa.a===sb.b || sa.b===sb.a || sa.b===sb.b) continue
```

Exact behavioral parity therefore means rejecting them on GPU too. In that configuration, the proposed “same node is on both segments” collision case never reaches narrow phase.

If shared-node pairs are deliberately enabled later, a node that occupies slots on both segments must receive the **sum of all its slot contributions from one pair evaluation**. For example, if `a0` and `b1` are the same physical node:

```text
Δshared = Δa0 + Δb1
        = response * ((1-s) - t) * n     // schematic; retain each slot's mass factor
```

Do not discover the pair through A and B and then apply that combined result twice. The safe rule is: canonicalize the pair, evaluate it once per node, and sum contributions for every endpoint slot whose node ID equals the current node ID.

There is a subtler issue for a textbook PBD/XPBD denominator. With distinct endpoint nodes, for

```text
C = length(pa - pb) - target
```

the gradients are:

```text
ga0 = +(1-s)n   ga1 = +s n
gb0 = -(1-t)n   gb1 = -t n
```

and the hard-contact denominator is:

```text
D = wa0(1-s)² + wa1 s² + wb0(1-t)² + wb1 t²
```

If the same physical node occupies multiple slots, first add that node's slot gradients and then square the combined gradient in `D`. Treating repeated slots as independent degrees of freedom gives the wrong effective mass. This is another reason to retain the current shared-node exclusion unless there is a clear need to collide adjacent topology.

### Existing CPU weighting is not textbook endpoint PBD

At `0179580`, the CPU code uses segment-average mobility:

```text
mobA = (a0.inv + a1.inv) * 0.5
mobB = (b0.inv + b1.inv) * 0.5
cA = penetration * mobA / (mobA + mobB)
cB = penetration * mobB / (mobA + mobB)
```

It then applies barycentric factors, but does not multiply each endpoint correction by that endpoint's own inverse mass or use the squared-gradient denominator above. If the current branch has not changed this, a “more correct” endpoint-inverse-mass GPU response will intentionally differ from CPU. Decide whether the validation target is exact legacy behavior or a principled PBD constraint and make the CPU reference use the same rule.

### XPBD/velocity caveat

- True XPBD compliance has pair-owned multiplier state `lambda`. Four node invocations must not independently evolve four lambdas. Store/update lambda per canonical pair in a separate pair pass, or keep collision compliance stateless.
- The examined `xpbd` control is a final normal-velocity cancellation, not the full compliant XPBD multiplier formulation. A per-node final velocity pass can reproduce a **Jacobi** version by reading frozen current/previous positions and writing only its own previous position.
- It will not exactly reproduce sequential pair-by-pair velocity cancellation when a node has multiple contacts. Average/relax and clamp the node's accumulated velocity correction just as for position deltas.

## Q2 — robust closest points in WGSL

Ericson's `ClosestPtSegmentSegment` is appropriate and is already essentially what the CPU `closest()` implements. The same vector algorithm works in 2D and 3D; use `vec2<f32>` or `vec3<f32>` consistently.

Given endpoints `p1,q1,p2,q2`:

```text
d1 = q1 - p1
d2 = q2 - p2
r  = p1 - p2
a  = dot(d1,d1)
e  = dot(d2,d2)
f  = dot(d2,r)
```

Then use these regions:

```text
if a <= lenEps2 and e <= lenEps2:
    s = 0; t = 0                         // point–point
else if a <= lenEps2:
    s = 0; t = clamp(f/e, 0, 1)          // point–segment
else:
    c = dot(d1,r)
    if e <= lenEps2:
        t = 0; s = clamp(-c/a, 0, 1)     // segment–point
    else:
        b = dot(d1,d2)
        denom = a*e - b*b
        if denom > parallelThreshold:
            s = clamp((b*f - c*e)/denom, 0, 1)
        else:
            s = 0                        // parallel provisional choice
        t = (b*s + f)/e
        if t < 0:
            t = 0; s = clamp(-c/a, 0, 1)
        else if t > 1:
            t = 1; s = clamp((b-c)/a, 0, 1)

cp1 = p1 + d1*s
cp2 = p2 + d2*t
delta = cp1 - cp2
dist2 = dot(delta,delta)
```

### Thresholds and f32 pitfalls

- Do not use one dimensionless absolute epsilon for both `a/e` and `denom`. `a` and `e` have units of length²; `denom` has units of length⁴.
- Define `lenEps` in engine/world units, tied to the smallest meaningful segment length, and compare `a/e <= lenEps²`.
- Use a relative parallel test such as `denom <= relParallelEps * a * e`, after confirming `a` and `e` are nondegenerate. Start with `relParallelEps` around `1e-6` for f32 and test at the engine's coordinate scale; this is a tuning seed, not a universal constant.
- Rounding can make `a*e-b*b` slightly negative. Branch on the threshold; never divide merely because `denom != 0`.
- Compare `dist2` against `target²` and take `sqrt` only for an actual contact. Before normalization require `dist2 > normalEps²`.
- WGSL permits reassociation/fusion differences, unspecified rounding direction in some circumstances, and subnormal flush-to-zero. Expect CPU-double versus GPU-f32 boundary differences. For exact validation, run the CPU oracle in `Math.fround`-style f32 or allow a narrow tolerance band around thresholds.
- Keep world coordinates reasonably local. Subtracting large nearly equal absolute coordinates destroys low bits before the closest calculation. Origin rebasing or object-local positions helps.
- Validate inputs and outputs as finite. WGSL's finite-math assumptions mean `min/max/clamp` are not a reliable NaN sanitizer.

### Zero-distance normal

`closest()` can be perfectly valid while returning zero distance, where `normalize(delta)` is undefined. Do not skip these deepest contacts as the current CPU does with `dist > 1e-6`; choose a deterministic fallback normal:

- Prefer a cached previous contact normal if stable pair state exists.
- Otherwise use relative closest-point velocity projected onto the plane normal to the segment direction.
- In 2D, use the perpendicular of the longer nondegenerate segment, with sign chosen from midpoint separation, relative velocity, or finally canonical pair ID.
- In 3D nonparallel cases, normalized `cross(d1,d2)` is perpendicular to both; orient it using prior normal/relative motion. For parallel segments, project midpoint separation perpendicular to the longer direction; if that is also zero, choose the least-aligned coordinate axis and cross it with the direction, then choose sign from canonical pair ID.
- For two degenerate points at the same location, previous normal or an ID-derived unit direction is required.

Ericson's parallel branch returns a correct minimum distance, but can choose an arbitrary point within a continuum of equally close points. Ericson's companion-site discussion notes that this may be undesirable for parallel overlapping capsules. A midpoint-of-overlap refinement can improve contact-position continuity, although it does not change the separation distance.

## Q3 — clamps and crowd normalization

There is no scale-independent magic clamp. Express limits in terms of the pair target thickness `T = rA+rB+pad`, and collect diagnostics before tuning.

Recommended conservative starting point for 2–8 Jacobi iterations:

1. Compute the unclamped pair correction using the chosen legacy or PBD effective-mass rule.
2. Clamp penetration used by one pair to `0.25*T` per iteration. A reasonable benchmark range is `0.15*T`–`0.5*T`.
3. Accumulate all active pair deltas for the node.
4. Apply constraint averaging: divide the sum by `max(1, activeContactCount)`; a pair counts once even if the node occupies two slots.
5. Start global relaxation `omega = 1.0` after averaging. Benchmark roughly `0.7`–`1.5`; lower values are safer for dense self-contact, while values above one may restore convergence lost to averaging.
6. Clamp the final node displacement magnitude to `0.25*Tnode` per iteration; benchmark up to `0.5*Tnode`. Choose `Tnode` conservatively from incident segment radii/pads, not from whichever pair happened to execute last.

These are stability defaults, not physical constants. Macklin et al.'s parallel PBD solver accumulates all constraint deltas per particle and divides by the number of affecting constraints; it then exposes an SOR factor `omega`. Their reported general range is `1–2` after averaging, but collision-heavy segment graphs and only 2–8 iterations justify starting at 1.0 and widening through measurement.

### Why use both clamps

- Per-pair clamping prevents one deep or newly teleported overlap from dominating the node.
- Contact-count averaging prevents many individually reasonable corrections from adding into an explosive displacement.
- Final magnitude clamping bounds the residual worst case when normals align or candidate duplication slips through.

Deep penetration is better handled by smaller substeps, swept/continuous detection, or a limited recovery phase than by allowing one huge projection. Clamping alone can leave objects interpenetrating; measure maximum and p95 penetration after the final iteration.

### Alternatives if averaging is too soft

- Divide by `sqrt(activeContactCount)` instead of count for faster but less robust convergence.
- Divide by a weighted count based on the node's barycentric influence, e.g. accumulate `abs(slotWeight)` alongside delta. This avoids a barely involved endpoint damping a strong contact as much as a full endpoint.
- Use `omega > 1` with strict final clamping.
- Separate contact constraints from length/bend constraints and apply the accumulated group between passes; this propagates corrections faster.
- If piles remain too soft, graph-colored pair-centric Gauss–Seidel is the next quality option, at the cost of more dispatches and coloring complexity.

Track at least: candidate duplicates rejected, active contacts/node, maximum contacts/node, raw accumulated-delta magnitude, averaged magnitude, clamp-hit count, maximum penetration, NaNs, and zero-normal fallbacks. These counters will distinguish density instability from closest-point or broad-phase errors.

## WebGPU-specific flags

- Per-node ownership is a good fit because core WGSL has only `atomic<i32>`/`atomic<u32>`, not portable float atomic add.
- A dispatch boundary is the global barrier between frozen input and output. Workgroup barriers cannot synchronize different workgroups.
- Do not rely on invocation order, subgroup width, or bit-identical CPU/GPU f32 behavior.
- Guard all runtime storage-buffer indices even if broad-phase counts were previously validated; an out-of-range dynamic reference is invalid and robustness behavior is not a substitute for correctness.
- Keep the output buffer distinct from every position buffer read by the iteration.

## Primary references

- Christer Ericson, *Real-Time Collision Detection*, §5.1.9, companion site: https://realtimecollisiondetection.net/
- Ericson companion discussion of the parallel-segment contact-point choice: https://realtimecollisiondetection.net/blog/?p=41
- Macklin et al., *Unified Particle Physics for Real-Time Applications*, parallel projected Jacobi, constraint averaging, and SOR: https://matthias-research.github.io/pages/publications/flex.pdf
- Fratarcangeli and Pellacini, *Scalable Partitioning for Parallel Position Based Dynamics*, comparison with averaged Jacobi: https://mfratarcangeli.github.io/pdf/eg15_ppbd.pdf
- W3C WGSL specification, floating-point evaluation and accuracy: https://www.w3.org/TR/WGSL/

