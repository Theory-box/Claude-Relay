# GPU bend/curl findings for a node-parallel Jacobi strand solver

Context: `Theory-box/Claude-Relay`, branch `feature/gpu`. The engine has node-parallel Jacobi length and collision constraints; the next layer is the degree-2, three-node bend/curl constraint. Findings only; no engine code.

## Recommendation

For a 2D or XY-dominant mass-spring strand, use a **signed three-point turning-angle constraint** as the long-term GPU bend model. It expresses the intended rest angle directly, supports positive and negative curl without mirror ambiguity, is rotation-invariant, and admits a standard mass-weighted PBD projection across all three nodes.

Use the engine's existing **middle-node bow/curvature target** only if matching the current CPU look is the immediate priority. It is cheaper and likely easier to port exactly, but it is not a true angular constraint: its apparent stiffness and preferred curvature vary with edge length, stretching, and sampling density unless carefully normalized.

Run bend as its **own constraint group**, applied after a length group within each outer structural iteration. Give bend its own relaxation/stiffness control. Do not mix length and bend corrections into one shared contact count or one SOR parameter.

For full 3D curl, positions alone do not provide a persistent signed material direction. A robust rod model needs a reference/material frame, transported normal, or extra orientation/ghost degrees of freedom. If the engine's depth coordinate is mainly visual weave, keeping signed curl in the XY plane is substantially simpler and closer to current behavior.

## Q1 — choosing the three-node bend formulation

Let an ordered strand triple be previous node `x0`, interior node `x1`, and next node `x2`. Define forward edges from the strand ordering:

`e0 = x1 - x0` and `e1 = x2 - x1`.

The ordering is important: using two unordered neighbors makes signed curl nondeterministic.

### Signed turning-angle PBD

In 2D, define the signed turn as:

`phi = atan2(cross2D(e0,e1), dot(e0,e1))`.

Straight is zero, left and right turns have opposite signs, and the bend constraint is the wrapped angular error:

`C = wrapToPi(phi - phiTarget)`.

This is preferable to an unsigned `acos` angle:

- `atan2(cross,dot)` preserves curl sign;
- it avoids the explicit `1/sin(phi)` derivative behavior associated with differentiating `acos`;
- it behaves naturally around a straight configuration because straight is centered at zero rather than at the ±π branch;
- its geometry is independent of rigid translation and rotation.

For nondegenerate edges, the 2D gradients can be expressed using each edge's perpendicular divided by its squared length. With `perp(v)` denoting a 90-degree counterclockwise rotation:

- previous-node gradient: `g0 = perp(e0) / |e0|²`;
- next-node gradient: `g2 = perp(e1) / |e1|²`;
- center gradient: `g1 = -(g0 + g2)`.

The gradients sum to zero, so an isolated mass-weighted projection has no artificial translation. The PBD scalar is formed from the pair-wide denominator `w0|g0|² + w1|g1|² + w2|g2|²`, and each node receives only its own inverse-mass-weighted gradient share.

“Symmetric” does not mean equal thirds. For equal masses near a straight configuration, the middle node often has the largest gradient magnitude. Correct symmetry means all three shares come from the same frozen triple, angular error, gradient set, and common effective-mass denominator.

### Node-parallel Jacobi ownership

Each bend constraint is centered at one degree-2 node but affects three physical nodes. A per-node solver therefore needs node→bend-constraint adjacency, not merely a list of constraints centered at that node.

In an open chain, one node may participate in:

- the bend centered on itself;
- the bend centered on its previous neighbor;
- the bend centered on its next neighbor.

The node invocation should recompute every participating triple from the frozen input, map itself to the previous/center/next slot, accumulate only that slot's correction, and write once. If only the center node processes and moves itself, the result is a different center-only bow solver rather than the symmetric three-node PBD constraint.

Node→bend CSR should contain each `(node,bendConstraint)` incidence exactly once and be rebuilt with strand topology. Degree-2 classification must exclude branch nodes unless a junction-specific bend policy exists.

### Degenerate and branch cases

- If either adjacent edge is below a rest/world-scale length threshold, skip or fall back; the angular gradients scale as inverse edge length and become ill-conditioned.
- Do not normalize with an arbitrary tiny denominator and then apply a large correction. Record a degenerate-bend counter.
- At an exact hairpin, the wrapped signed angle lies on the ±π branch. Clamp preferred turns away from that branch or define a persistent orientation rule.
- Open endpoints have no centered bend constraint, although they still participate as outer nodes in their neighbor's bend.
- Rings require a consistent cyclic ordering.
- Degree greater than two requires selecting material branches or separate bend pairs; “the two neighbors” is no longer well-defined.

### Simpler curvature/bow formulation

A cheaper alternative constrains the middle node's displacement from the endpoint midpoint or constrains a discrete second difference such as `x0 - 2x1 + x2` toward a target curvature vector.

Advantages:

- only additions and scalar/vector projection are required;
- it is well-behaved near straight configurations;
- a three-node symmetric projection can use constant linear gradients;
- it closely resembles the examined CPU behavior, which restores the middle node toward a target tangent/normal offset derived from its neighbors and stored rest bow.

Disadvantages:

- a world-space rest curvature vector is not rotation-invariant;
- recomputing a local chord normal restores rotation invariance but makes the constraint nonlinear and introduces a degenerate chord case;
- target offset has length units, so changing segment length or sampling density changes the implied angle/curvature;
- stretch and bend are more tightly coupled;
- a distance-only outer-node constraint cannot distinguish positive from negative curl.

This is a good compatibility POC and may be entirely adequate for a stylized engine. It is not as clean a foundation for resolution-independent signed curl as the turning-angle constraint.

The triangle-bending literature supports inexpensive geometric alternatives to classical angle/dihedral constraints; see Kelager, Niebe, and Erleben, [A Triangle Bending Constraint Model for Position-Based Dynamics](https://iphys.wordpress.com/2010/09/04/a-triangle-bending-constraint-model-for-position-based-dynamics/). That work targets triangle meshes, so it is conceptual support for a cheap curvature formulation rather than a direct three-node chain recipe.

### Dihedral bending is not the right primitive here

A cloth dihedral constraint measures the angle between two adjacent triangle faces and normally involves four vertices. A one-dimensional strand with only positions and two edges has a turning angle, not a surface dihedral. Use a three-point turning/curvature constraint unless the representation is upgraded to a rod with material frames and twist.

For physically richer 3D rods, [Position-Based Elastic Rods](https://www.nobuyuki-umetani.com/publication/2014_sca_positionbasedelasticrod/2014_sca_PositionBasedElasticRod.pdf) introduces additional ghost points to carry material-frame information for bending and twisting. That complexity is unnecessary if curl remains planar.

## Q2 — encoding preferred signed curl

### Store an oriented strand order

At topology build, assign every simple chain/ring a consistent traversal orientation. For each interior node, store or derive an ordered previous/next pair. Compute rest turning angle using the same orientation.

Reversing a strand changes the sign of its measured turn. Therefore either:

- preserve orientation across topology rebuilds; or
- flip stored signed rest/curl targets when orientation reverses.

Without this, a cut, merge, or component reindex can make an unchanged curl control suddenly coil the opposite way.

For rings, choose and retain a deterministic winding/start convention. The start index does not affect local turns, but winding direction changes their signs.

### Rest shape plus spontaneous curvature

A useful target is the stored rest turn plus a signed curl contribution:

`phiTarget = wrapToPi(phiRest + phiCurl)`.

To make curl approximately independent of mesh resolution, interpret the material parameter as preferred curvature `kappa` with units of inverse length and convert it locally using a representative rest arc length:

`phiCurl ≈ kappa · 0.5·(restLength0 + restLength1)`.

If the UI's `effCurl` is dimensionless, choose one documented world-scale conversion to `kappa` or target angle. Avoid adding the same fixed angle at every vertex regardless of segment length: doubling the sampling density would then roughly double total coil angle over the same physical strand.

The target should remain comfortably within `(-pi,pi)`. Large desired curvature is better represented by more, shorter segments than by pushing one vertex toward a 180-degree turn.

### Curl only changes the target, not the correction split

Positive or negative curl changes `C = wrap(phi-phiTarget)`. The same three gradients and effective-mass denominator then distribute the correction automatically:

- all three nodes use the same signed target and canonical triple ordering;
- fixed nodes have zero inverse mass and receive no correction;
- movable nodes take their mass-weighted gradient shares;
- no ad hoc “push center toward curl side” sign rule is needed after the angle is defined consistently.

This preserves local translation invariance and gives the outer nodes counter-corrections rather than forcing the middle node to absorb the entire bend.

### Interaction with length constraints

Angle projection can alter edge lengths, while length projection can alter the angle. They are coupled constraints, so neither should be expected to remain exact immediately after the other group runs. Alternating the groups is the normal iterative solution.

If length is intended to be nearly inextensible, give it higher priority/stiffness and finish the structural solve with a length group. If the visible curl silhouette matters more, finish with bend—but collision later in the overall pipeline may still perturb both.

### 3D sign is not intrinsic

For 3D edges, `dot(e0,e1)` gives an unsigned bend magnitude, but `cross(e0,e1)` is a vector; there is no scalar left/right sign without a reference normal.

Options:

- Keep bend/curl in XY and use global +Z as the sign axis, matching a slab/weave engine.
- Store a rest normal at each bend and transport/update it along the strand.
- Add orientation or ghost points and use a rod formulation capable of twist.

Using a fixed global normal in full 3D causes curl behavior to weaken or flip as the strand rotates out of the reference plane. If depth is modest and curl is deliberately a 2D material effect, state that limitation explicitly rather than treating it as a full 3D rod model.

## Q3 — grouping, ordering, and relaxation

### Bend should be its own group

Run length and bend as separate Jacobi groups with a dispatch/apply boundary between them:

1. evaluate and apply length corrections;
2. evaluate and apply bend corrections;
3. repeat for the structural iteration budget.

This is block Gauss–Seidel between constraint types and Jacobi within each type. It lets bend see the latest edge lengths and lets the next length group repair stretch introduced by bending.

Macklin et al. recommend processing constraint types in groups and applying each group's accumulated delta before the next group, both to express priority and improve propagation; see §4.3 of [Unified Particle Physics for Real-Time Applications](https://matthias-research.github.io/pages/publications/flex.pdf).

Combining length and bend into one frozen group is possible, but usually inferior here:

- both corrections are computed from stale positions relative to each other;
- one shared averaging count mixes constraints with different units, conditioning, and desired stiffness;
- one SOR parameter cannot tune hard length and soft bend independently;
- opposing corrections can partially cancel before either constraint sees the other's result.

### Suggested structural order

For an inextensible strand, a good starting outer sequence is length then bend, repeated, with one final length group before collision. This prioritizes edge length at the structural boundary. If the final length group noticeably erases curl, compare length→bend→length per outer cycle or finish with a lightly relaxed bend group.

Because collision follows or interleaves with structural constraints, integrated residuals matter more than making either bend or length exact in isolation.

### Bend needs separate stiffness and relaxation

Do not reuse length's SOR blindly. Bend is usually intentionally softer, its conditioning varies strongly with edge length, and each node can participate in up to three bend constraints.

Conservative initial tuning:

- keep length at its already validated relaxation;
- start bend relaxation/SOR at or below 1.0;
- for the engine's historically soft bend, begin roughly in the `0.25–0.75` range and increase only if angular residual improves without oscillation;
- measure bend clamp/degenerate counts and energy injection rather than assuming stability from visual smoothness.

This range is only a tuning seed. The correct value depends on whether `effStiff` is interpreted as per-iteration projection strength, per-substep material stiffness, or compliance.

### Iteration-dependent PBD stiffness

Plain PBD stiffness changes when iteration count or substep count changes. If a user-facing bend stiffness `kTotal` is meant to represent the approximate strength over N bend projections, a common per-iteration mapping is:

`kIteration = 1 - (1-kTotal)^(1/N)`.

This mapping is exact only for a simple repeated linear error reduction, but it is a better starting convention than applying the same full stiffness N times.

XPBD compliance offers a more principled timestep/iteration-independent material control. However, XPBD maintains a Lagrange multiplier per bend constraint. A purely per-node kernel cannot have three node invocations independently update the same multiplier without races. Supporting true XPBD bend would require a constraint-owned scalar pass/buffer or another unambiguous lambda ownership scheme. For the current stateless per-node architecture, ordinary PBD plus explicit per-group relaxation is simpler.

See [XPBD: Position-Based Simulation of Compliant Constrained Dynamics](https://dl.acm.org/doi/pdf/10.1145/2994258.2994272) for the compliant formulation.

### Jacobi accumulation

Each node accumulates corrections from all participating bend triples, then applies a bend-specific averaging/relaxation rule. Do not combine bend's active-constraint count with length or collision counts.

Classic averaged Jacobi divides by the number of constraints affecting the particle, but that can overdamp an outer-node contribution whose angle gradient is small relative to another. Start with simple count averaging for robustness and validation; gradient/diagonal-weighted normalization is a later optimization if convergence is too soft.

Pinned nodes should remain unchanged through zero inverse mass, while the common denominator redistributes response among the movable degrees of freedom. Skip a bend whose complete effective-mass denominator is zero.

### Substeps versus many bend iterations

Bending errors propagate locally through a chain and Jacobi is slower than Gauss–Seidel. If high bend counts are needed to hold curls, benchmark additional substeps rather than only adding iterations. Smaller substeps also reduce collision and structural nonlinearity. The general substep result is summarized in [Small Steps in Physics Simulation](https://www.physicsbasedanimation.com/2019/08/01/small-steps-in-physics-simulation/).

## Compatibility path versus principled path

### Compatibility-first layer

- Port the existing rest-bow/middle-offset behavior.
- Initially preserve its target construction and stiffness mapping.
- Optionally distribute the vector constraint symmetrically across the three nodes if behavior change is acceptable.
- Validate CPU/GPU bow residuals and integrated shape.

This minimizes visual regression but inherits resolution/stretch dependence.

### Principled bend/curl layer

- Build ordered three-node bend constraints.
- Use signed turning angle in 2D/XY.
- Store rest turn and preferred curvature-derived target turn.
- Build node→bend CSR with up to three ordinary incidences per chain node.
- Apply mass-weighted three-node PBD correction in a separate bend group.
- Give bend its own relaxation/stiffness mapping.

This is the recommended long-term design.

Do not silently replace the current CPU bow rule with angle PBD and call it a pure port. It is a material-model change and should receive its own visual/regression validation.

## Validation checklist

- Straight three-node chain with zero curl remains straight.
- Positive and negative curl produce mirrored results under a fixed strand orientation.
- Reversing topology order and also transforming the stored signed target leaves world-space behavior unchanged.
- Rigidly translating/rotating the entire 2D triple leaves angular correction behavior unchanged.
- Equal masses produce zero net translational correction for one isolated bend.
- Unequal masses and fixed endpoints follow the common effective-mass denominator.
- Outer nodes receive their shares; center-only motion is detected as a different solver.
- A node participating in three neighboring bend constraints receives each once.
- Edge-length degeneracy triggers a diagnostic and never a large correction/NaN.
- Ring wrap ordering preserves curl sign.
- Changing segment sampling density while holding preferred curvature fixed produces approximately the same total coil.
- Length→bend alternation reduces both residuals rather than oscillating.
- Bend SOR sweep records angular residual per millisecond, not only visual shape.
- Collision stress does not cause curl to inject manufactured velocity or defeat the final displacement clamps.

## Final answers

### Q1

Use a signed three-point turning-angle PBD constraint for the principled GPU model. Every physical node must process every bend triple it participates in and take its own mass-weighted gradient share. A midpoint/second-difference curvature constraint is cheaper and closer to current CPU behavior, but less resolution- and stretch-independent. Cloth dihedral bending is not the appropriate primitive for a one-dimensional chain.

### Q2

Store a consistent strand orientation and target `rest turn + preferred curvature × local rest length`, wrapped to `(-pi,pi)`. Curl changes the scalar target; the symmetric three-node gradient/effective-mass solve distributes the signed correction automatically. In full 3D, signed curl requires a reference/material frame; otherwise keep it explicitly XY-planar.

### Q3

Run bend as its own group after length within each outer structural iteration, normally finishing structural work with length. Give bend its own stiffness/relaxation, starting no higher than 1.0 and likely softer than length. Plain PBD stiffness is iteration-dependent; map it per iteration or adopt XPBD later with constraint-owned multiplier storage.

## Sources

- Müller et al., [Position Based Dynamics](https://blenderartists.org/uploads/short-url/1DZzUq6Sgj29rmcs0YAwnr0UQl7.pdf) — general mass-weighted positional constraint projection.
- Umetani, Schmidt, and Stam, [Position-Based Elastic Rods](https://www.nobuyuki-umetani.com/publication/2014_sca_positionbasedelasticrod/2014_sca_PositionBasedElasticRod.pdf) — 3D rod bending/twist and material frames via ghost points.
- Kelager, Niebe, and Erleben, [A Triangle Bending Constraint Model for Position-Based Dynamics](https://iphys.wordpress.com/2010/09/04/a-triangle-bending-constraint-model-for-position-based-dynamics/) — inexpensive geometric curvature alternatives.
- Macklin et al., [Unified Particle Physics for Real-Time Applications](https://matthias-research.github.io/pages/publications/flex.pdf) — projected Jacobi, constraint averaging/SOR, and type-group ordering.
- Macklin, Müller, and Chentanez, [XPBD: Position-Based Simulation of Compliant Constrained Dynamics](https://dl.acm.org/doi/pdf/10.1145/2994258.2994272) — compliance and per-constraint multipliers.
- Macklin et al., [Small Steps in Physics Simulation](https://www.physicsbasedanimation.com/2019/08/01/small-steps-in-physics-simulation/) — substeps versus repeated iterations.
- Project source, [`string-engine.html` on `feature/gpu`](https://github.com/Theory-box/Claude-Relay/blob/feature/gpu/Claude%20apps/string%20engine/string-engine.html) — current degree-2 rest-bow/curl behavior.

