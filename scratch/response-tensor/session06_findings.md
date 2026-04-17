# Response Tensor Research — Session 06 Findings

## Committed direction

Combined Möbius + dreams: after training, let networks evolve under their own dream-driven weight updates with no external gradient signal. Use this as a **characterization tool** — measure what drifts and what persists, and see if trained networks on the same task converge to a shared self-consistent state.

## Dream update rule

```
sample noise  N ~ N(0, I)
compute       y = f(N; θ_t)
perturb       y_target = y + ε · unit_gaussian
step          θ_{t+1} = θ_t - lr · ∇_θ ||f(N; θ) - y_target||²
```

The perturbation ε makes the target differ from the current output, giving non-zero gradient. No external data or loss — the network trains on perturbed versions of its own confabulations on noise.

## Phase A — do networks converge?

Initial hypothesis: trained networks on the same task share a self-consistent attractor, and dream dynamics drives them toward it. **Refuted.**

```
step    weight drift    pairwise function dist    test loss
0       0.000           0.030                     0.0008
500     0.023           0.040                     0.0011
1000    0.036           0.053                     0.0017
```

Networks DIVERGE under dream dynamics. Pairwise function distance grows 75% over 1000 steps.

Within-net vs between-net distance at end:
- ||θ_1000^s − θ_0^s|| = 0.036 (self-drift is tiny)
- ||θ_1000^s − θ_1000^s'|| = 9.113 (networks remain very far from each other)

Random-init networks barely move under the same dynamics (pairwise dist 1.01 → 1.02). Trained and random-init networks end up in disjoint regions of weight-space.

## Phase B — but something IS preserved

Ran broader probe of macro-properties across 2000 dream steps.

```
property           t=0        t=2000     % change    verdict
out_var            0.344      0.349      +1.2%       PRESERVED
out_spec_top       0.765      0.794      +3.8%       PRESERVED
J_eff_rank        12.935     12.938      +0.0%       PRESERVED
J_top             17.995     18.029      +0.2%       PRESERVED
J_frob            20.688     20.720      +0.2%       PRESERVED
H_eff_rank        10.885     10.855      -0.3%       PRESERVED
H_sparsity         0.086      0.089      +2.9%       PRESERVED
lipschitz          1.327      1.331      +0.3%       PRESERVED
W_norm            41.727     41.731      +0.0%       PRESERVED
test_loss          0.001      0.002    +169.9%       DRIFTS
```

Eight macro-properties preserved to within 5%. Test loss degrades 170%. Random-init networks show the **same set** of properties preserved, meaning preservation is a property of the dynamics, not the trained state.

## The theoretical frame that unifies these findings

Work through the gradient:

    δθ = -lr · ∇_θ ||f(N; θ) - (f(N; θ) + ε · ξ)||²
       = lr · ε · ξ · ∂f/∂θ                        (where ξ ~ N(0, I))

- E[δθ] = 0 (zero drift — it's a random walk)
- Cov[δθ] ∝ (∂f/∂θ)^T (∂f/∂θ) = **empirical Fisher information matrix**

**Dream dynamics is a zero-drift Brownian motion on weight-space with diffusion tensor equal to the empirical Fisher.**

This is Langevin sampling from a flat prior with Fisher-metric noise. The network walks in weight-space shaped by its own curvature geometry.

## Why this predicts exactly what we observed

- **Isotropic-in-Fisher-metric quantities are preserved:** norms, Jacobian spectrum, output variance, effective ranks, Lipschitz constant. These are functionals that don't change under Fisher-metric random walks.
- **Directed-in-weight-space content is eroded:** task loss requires specific alignment between weights and data structure; a random walk destroys this alignment.
- **Networks diverge, not converge:** different starting points in weight-space walk independently; they don't share a drift-field pulling toward a common target.
- **Random-init preserves the same invariants:** it's the architecture's Fisher geometry that defines the preserved set, not training.

## Reframing session 4's "type equivalence"

Earlier finding: self-temporal ≈ other-temporal — any competent network's past works as self-signal. I interpreted this as "type equivalence means shared functional role."

Session 6 sharpens: **type equivalence is a shared level set in weight-space, not a shared point.** Networks in the same type share macro-invariants (Fisher-preserved quantities) but occupy different points within the level set those invariants define. Training places a network at *some* point in the level set; dream dynamics walks it around within that level set. Multiple trained networks are distinct points in the same level set.

The macro-signature of a network — its collection of Fisher-preserved invariants — is a genuinely parameterization-free object. It's what the "unified object" framing from sessions 1-2 was actually pointing at. Not M(x), not J(x), not the raw response tensor. The macro-signature is:

- Weight-norm spectrum
- Jacobian spectrum (top, Frobenius, effective rank)
- Hidden-space effective rank
- Output variance and covariance spectrum
- Lipschitz bound
- Hidden sparsity

These are what's preserved by Fisher-metric Brownian motion and what characterizes the network's "type."

## What's novel here

To the best of my pre-session literature survey:

- **Framing dream dynamics as pure self-reference and characterizing it as Fisher Brownian motion**: I haven't seen this specific derivation in prior work, though SGLD, NTK, and empirical Fisher are all well-studied separately.
- **The "preserved macro-invariants define type" characterization**: this bridges session 4's type-equivalence finding with the statistical mechanics of neural networks. Novel framing; not obviously a re-derivation.
- **Test-loss erosion vs macro-preservation contrast**: shows that a network can maintain all its statistical properties while losing its trained competence, which is a specific falsifiable prediction about what Fisher-driven dynamics does to a network.

## Confidence

- Dream dynamics preserves macro-invariants: **very high** — clean quantitative result, replicated across 5 trained networks and 5 random-init networks
- Theoretical derivation as Fisher Brownian motion: **high** — math is straightforward; the covariance calculation is routine
- "Type = level set of preserved invariants" as a useful framing: **medium-high** — consistent with all observations; would benefit from verification at larger scale, different architectures, and real tasks
- The specific macro-invariant list is complete: **low-medium** — I measured 10 quantities; there may be others. The list is "ones I thought to measure," not "all invariants of Fisher dynamics." A proper mathematical derivation would enumerate them.

## Scripts

- `scratch/response-tensor/session06_dream_attractor.py` — convergence/divergence test
- `scratch/response-tensor/session06b_macro_invariants.py` — macro-property probe

## What session 7 could do

1. **Prove the Brownian-motion characterization more formally.** Run much longer (50,000 steps). Measure whether weights asymptote to a specific distribution and whether that distribution matches Fisher-metric predictions.

2. **Test at scale.** Deeper network (4 layers), real task (MNIST). Does the preservation set survive, or are these toy-scale artifacts?

3. **Enumerate the invariants.** Which algebraic combinations of weights are preserved by Fisher dynamics? A Lie-theoretic answer would be clean: find the symmetry group of the Fisher walk. Its invariants are exactly our preserved macro-properties.

4. **Connect to biology.** The analogy between dream dynamics and REM sleep is suggestive. REM produces macro-preserved dynamics (brain stays a brain) while doing something to memory. Networks dreaming without consolidation *lose* their training content. Is consolidation (which real brains have) precisely the drift term missing from our dynamics? This is speculative but testable.

5. **Stop.** Session 6 has produced what I think is the most novel finding in the whole 6-session arc. Stopping here and writing a proper synthesis doc may be more valuable than another session.
