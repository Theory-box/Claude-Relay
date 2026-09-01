# Layer 3c step-loop integration findings

Context: `Theory-box/Claude-Relay`, branch `feature/gpu`. GPU integration, structural constraints, and per-node Jacobi collision are available; this reviews ordering, iteration budgets, and grid rebuild cadence. Findings only; no engine code.

## Recommended starting schedule

Use **block-interleaving between constraint groups**, while retaining Jacobi parallelism inside each group:

1. predict/integrate positions for one substep;
2. perform an initial structural projection group if predicted geometry can be highly distorted;
3. build the conservative collision grid from the resulting positions;
4. for each outer solver iteration, apply structural Jacobi corrections, then collision Jacobi corrections;
5. finish with collision so the final substep state prioritizes nonpenetration;
6. update velocity/previous-position state only after the final corrected position is established.

This is a block Gauss–Seidel schedule across groups: collision sees the structural group's newly written positions, while every invocation within one group still reads a frozen buffer. It usually couples length and contact more effectively than completing all length iterations and then all collision iterations.

For the first integration checkpoint, also keep a selectable **CPU-shaped baseline**—all structural iterations followed by all collision iterations. It is useful for isolating regressions and comparing broad behavior, but it should not be assumed to be the best GPU schedule.

## Q1 — separate collision solve or interleave it?

### Full structural solve followed by full collision solve

Advantages:

- Closest high-level match to the existing CPU order.
- Simplest pipeline and easiest phase-by-phase diagnostics.
- Collision receives a shape whose length/bend errors have already been reduced.
- Grid can be built immediately before collision, so its reuse margin only needs to cover collision iterations unless other passes follow.

Disadvantages:

- Collision corrections made after the structural solve can stretch or bend strands, and no structural iteration repairs that error until the next substep.
- Contact response cannot feed back into length/bend during the same substep.
- Dense folds can converge slowly because information passes through all structural iterations and then all collision iterations rather than alternating.
- If the last collision corrections are strongly clamped, structural error can accumulate around contacts.

This schedule is defensible as a compatibility baseline and may be adequate with small substeps. It is not inherently unstable; it simply solves the coupled constraint system in two large blocks.

### Interleaving constraint groups

Advantages:

- Structural corrections that recreate penetration are handled in the same outer iteration.
- Collision corrections that stretch an edge are partially repaired in the next structural group.
- Applying one group's accumulated delta before evaluating the next group propagates information faster than treating all groups as one fully frozen Jacobi iteration.
- It follows the grouping strategy described in §4.3 of [Unified Particle Physics for Real-Time Applications](https://matthias-research.github.io/pages/publications/flex.pdf): constraints of a type are processed in parallel, their accumulated deltas are applied, and then the next group runs.

Disadvantages:

- Grid reuse must cover both structural and collision motion over the complete interleaved window.
- More pipeline transitions/dispatches per substep.
- Group order creates a priority. The last group has the smallest final residual at the expense of possibly worsening the preceding group.
- It diverges further from exact CPU ordering, although both solvers are already algorithmically different because GPU constraints are Jacobi.

### Which group should be last?

For this engine, collision should normally be last. A small residual length error is visually preferable to ending the substep penetrated or allowing strands to cross. The following structural group in the next iteration repairs collision-induced stretch; the final collision group restores separation afterward.

If strand length preservation proves more important for a particular material, measure an optional final structural pass followed by a cheap final collision pass. Do not end with structural projection alone unless tests establish that it cannot recreate visible penetration.

Bounds/walls are contact-like unilateral constraints. Place them with or immediately before collision and ensure the final group cannot push nodes back outside bounds. If bounds are processed separately, a short final bounds/contact sequence may be needed.

### Practical rollout

Validate in stages:

- Stage A: structural block, grid build, collision block. Confirm no state-transfer or pipeline bugs.
- Stage B: interleave structural and collision groups with identical total group counts. Compare residuals and runtime.
- Stage C: tune group counts, SOR, and substeps using integrated metrics.

This preserves a diagnostic baseline without locking the production solver to the CPU's serial schedule.

## Q2 — iteration budgets under Jacobi

There is no reliable fixed conversion such as “two Jacobi iterations equal one Gauss–Seidel iteration.” Convergence depends on graph degree, stiffness, constraint redundancy, contact density, averaging, SOR, and ordering. Jacobi can converge much more slowly than Gauss–Seidel for stiff or ill-conditioned systems; [Macklin et al.](https://matthias-research.github.io/pages/publications/flex.pdf) explicitly discuss nonconvergence/oscillation risks and use constraint averaging plus SOR.

Use residual targets rather than CPU iteration-count parity.

### Reasonable initial budget

For a first integrated WebGPU build with two to eight collision iterations already contemplated:

- structural Jacobi: start around **6–10 group applications per substep**;
- collision Jacobi: start around **4–8 group applications per substep**;
- SOR: start at 1.0 for both unless they have separately validated parameters;
- if block-interleaving, run one structural and one collision group per outer iteration, then add structural-only prepasses or a final collision pass as needed.

These are benchmark seeds, not equivalence claims. If the CPU baseline uses roughly three to four Gauss–Seidel passes, beginning near twice that count for Jacobi is reasonable, but it may be either excessive or insufficient depending on the scene.

### Which family usually needs more?

For sparse cloth-like motion, structural length constraints often need more iterations:

- length error must propagate over many edges;
- a Jacobi iteration moves information only locally through the graph;
- insufficient iterations make the strand globally stretchy.

Collision may need fewer iterations when contacts are sparse and shallow because separation is local. However, dense self-contact, piles, or folded strands reverse that conclusion:

- many contact constraints share nodes;
- contact averaging deliberately weakens each accumulated correction;
- contact information also propagates only locally per Jacobi iteration;
- deep-overlap and final-node clamps require several bounded corrections.

Therefore a useful adaptive *offline tuning rule* is:

- structural-dominated scenes: `Kconstraint ≥ Kcollision`;
- dense-contact stress scenes: raise collision iterations or substeps until penetration residual stops improving.

Avoid runtime CPU readback-driven adaptation initially; fixed GPU budgets are simpler and do not stall the queue.

### Prefer substeps over very large iteration counts

The strongest general result for stiff PBD/XPBD systems is that more smaller substeps can outperform one large step with many solver iterations. [Small Steps in Physics Simulation](https://www.physicsbasedanimation.com/2019/08/01/small-steps-in-physics-simulation/) reports that `n` smaller substeps with one XPBD iteration can yield lower constraint error and damping than one large step with `n` iterations.

For this engine, substeps also refresh predicted positions and collision neighborhoods. If either length or collision needs very high K, benchmark increasing substeps while reducing iterations per substep. The cost is more grid builds, but collision reliability and stiffness may improve enough to win overall.

### Metrics for choosing K

Structural metrics:

- mean, p95, and maximum relative edge-length error;
- bend/rest-shape error where applicable;
- convergence change from iteration K−1 to K;
- visible stretch under load.

Collision metrics:

- active unique contacts and contacts per node;
- mean, p95, and maximum penetration after the final group;
- number of per-pair and final-node clamp hits;
- fallback-normal count;
- strand crossings/tunneling events;
- kinetic-energy or manufactured-velocity spikes;
- bin overflow, which must remain zero.

Integrated metrics:

- total GPU time per substep/frame;
- residual improvement per millisecond, not per iteration;
- NaNs and finite-range bounds;
- pinned-node displacement;
- behavioral stability during drag, pause, and topology changes.

Choose the smallest budgets that meet both structural and collision residual targets across normal and adversarial scenes. If residuals plateau, more iterations are not the right fix; inspect averaging, clamps, group order, grid freshness, or timestep.

## Q3 — once per substep versus once per frame

Once per substep is the safe default. Once per frame is safe only when the neighbor-list skin covers the maximum displacement from the frame's grid-build pose over **all** substeps that reuse it.

Let:

- `Nsub` be the number of substeps sharing the grid;
- `dsub,j` be a proven maximum endpoint displacement during substep j, including integration and every correction group;
- `dframe` be the maximum possible displacement from the grid-build position during the whole reuse lifetime.

A conservative bound is the sum of all substep bounds:

`dframe ≤ dsub,1 + dsub,2 + … + dsub,Nsub`.

If one common bound `dsub` applies, use `dframe ≤ Nsub·dsub`.

To remain conservative:

- inflate each segment's contact-expanded AABB by at least `dframe`; or
- equivalently, use a total pair-list skin of at least `2·dframe`, because two segments can approach by the sum of their displacements.

The familiar half-skin criterion follows directly: a pair list with total skin Δ must be rebuilt before any object moves more than Δ/2 from the build pose. This is the policy described for Verlet lists in the [LAMMPS neighbor-list documentation](https://docs.lammps.org/Developer_par_neigh.html).

### Components of the substep displacement bound

The bound must include:

- predicted motion, approximately bounded by maximum speed times substep duration;
- integration noise/temperature kicks;
- all structural Jacobi corrections;
- all collision corrections;
- wall/bounds projection;
- drag/grab or kinematic target motion;
- pin repositioning;
- 3D depth correction;
- topology-edit relocation, if allowed inside the frame.

If collision's final node clamp is `cCollision` and there are `Kcollision` collision groups, collision contributes at most `Kcollision·cCollision` by triangle inequality. Structural and bounds groups need comparable explicit bounds. The true motion will usually be much smaller, but the skin proof needs the worst case.

### When once per frame is unsafe

It is unsafe whenever an endpoint can move farther from the frame-build pose than the per-segment skin margin. Common triggers are:

- multiple fast substeps despite each individual step being small;
- drag/teleport/kinematic edits;
- deep-contact recovery hitting correction clamps repeatedly;
- structural projection of badly stretched edges;
- moving fixed walls;
- topology changes or changing radius/pad/contact rules;
- an underestimated velocity bound;
- using a margin sized for one substep across several.

The failure is a false-negative broad phase: two segments absent from the original candidate superset can become contacting in a later substep. Exact current-distance narrow phase cannot recover a pair it never discovers.

### Why a large frame skin may lose anyway

A once-per-frame grid can be made conservative by multiplying the skin to cover the whole frame, but that may be slower or less robust than rebuilding:

- expanded AABBs touch more cells;
- bin occupancy rises, threatening the fixed CAP;
- candidate counts and repeated closest evaluations increase;
- the home-cell ranges become larger;
- memory bandwidth grows.

For K solver iterations within one substep, reuse is attractive because motion is tightly clamped and a single build amortizes well. Across several substeps, the required skin grows while a substep build also benefits from fresher, tighter AABBs. Once-per-substep is therefore the recommended default; benchmark once-per-frame only after a proven full-frame displacement bound and CAP/candidate telemetry exist.

### Adaptive rebuild caveat in WebGPU

Tracking maximum displacement on the GPU is easy, but reading it to JavaScript every substep can serialize the queue. Prefer a fixed once-per-substep cadence initially. A future GPU-only strategy can use conservative scheduled rebuild intervals or indirect work, but portable WebGPU does not offer a general conditional command-stream branch that makes this automatically cheap.

## Suggested first integrated configurations

### Diagnostic compatibility baseline

- predict/integrate;
- structural Jacobi block;
- build grid;
- collision Jacobi block;
- update velocity/state;
- rebuild every substep.

Purpose: isolate integration bugs and compare with the CPU's coarse phase order.

### Recommended coupled baseline

- predict/integrate;
- one initial structural group;
- build grid with skin covering the remaining structural and collision groups;
- alternate structural then collision groups;
- end with collision;
- update velocity/state;
- rebuild every substep.

Purpose: better coupled convergence and final nonpenetration.

Compare them at equal total group applications and equal substeps. The coupled schedule should be adopted only if it improves residual per millisecond and does not create energy/pin regressions.

## Final answers

### Q1

Interleave at the **constraint-group level** for the production candidate: structural Jacobi group, apply, collision Jacobi group, apply, repeated; end with collision. Keep the CPU-shaped separate-block schedule as the first diagnostic baseline. Interleaving usually improves coupled convergence, while separate blocks simplify validation and require a smaller grid skin.

### Q2

There is no fixed Jacobi/GS conversion. Start roughly with 6–10 structural and 4–8 collision group applications per substep, then tune to residual-per-millisecond targets. Sparse cloth usually needs at least as much structural work as collision; dense folds may need equal or greater collision work. If counts grow large, prefer more substeps with fewer iterations.

### Q3

Once-per-frame is unsafe unless each segment AABB is inflated by the maximum endpoint displacement from the frame-build pose across all reused substeps—conservatively the sum of per-substep displacement bounds. A total pair skin must be twice that per-segment displacement bound. Once-per-substep is the recommended safe default and usually keeps bins/candidate sets much tighter.

## Sources

- Macklin et al., [Unified Particle Physics for Real-Time Applications](https://matthias-research.github.io/pages/publications/flex.pdf) — projected Jacobi, constraint averaging/SOR, group ordering, and neighbor/contact generation before solver iterations.
- Macklin et al., [Small Steps in Physics Simulation](https://www.physicsbasedanimation.com/2019/08/01/small-steps-in-physics-simulation/) — substeps versus repeated iterations in a large timestep.
- Müller, [Hierarchical Position Based Dynamics](https://matthias-research.github.io/pages/publications/hpbd.pdf) — iteration count, stiffness, and slow propagation in cloth constraints.
- LAMMPS, [Verlet neighbor-list documentation](https://docs.lammps.org/Developer_par_neigh.html) — reusable buffered pair lists and the half-skin rebuild rule.
- Project source, [`string-engine.html` on `feature/gpu`](https://github.com/Theory-box/Claude-Relay/blob/feature/gpu/Claude%20apps/string%20engine/string-engine.html) — CPU phase order and constraint/collision behavior.

