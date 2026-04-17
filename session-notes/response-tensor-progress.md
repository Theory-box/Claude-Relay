# Response Tensor Research — Session Progress

**Branch:** `research/response-tensor`
**Started:** April 2026
**Status:** Session 06 complete (6 of up to 10). Novel characterization found: dream dynamics = Fisher-metric Brownian motion on weight-space. Preserved macro-invariants define "type" as a level set, not a point.

## Research Question

Weights and activations are conventionally treated as distinct. Backprop shows they are dual — weight-gradients factor as (incoming activation) ⊗ (backprop error). Is there a single underlying object — call it the *response tensor* R — of which weights and activations are two projections? If so:
- What is R?
- Is it a faithful invariant of the function the network computes?
- What structure (low rank? group symmetry?) does it have?
- Would a model with access to a compressed R have qualitatively richer self-access than one fed raw weights+activations?

## Framing

The candidate R proposed: the collection of input-output Jacobians `{J(x) = dy/dx : x ∈ data}`. This lives between weights (which parameterize J for all x) and activations (which parameterize a single forward trace). Moments/spectra of R, and its symmetry-quotient, are the targets.

## Sessions

### Session 01 — foundational probes on tiny MLP
- Setup: two students trained on same nonlinear teacher, `d_in=12, d_hid=64, d_out=6, N=800`.
- Verified activations-as-gradients duality numerically.
- Spectrum of R is sharply low-rank: top-1 captures 90% energy; effective rank ~19/72.
- **Key finding:** R splits into (mean Jacobian, 89.7% energy, function-invariant with cosine 0.9997 across nets) + (residual, 10.3% energy, network-specific).
- Interpretation: the mean Jacobian is a genuine function-invariant — a weak "Maxwell" candidate but too coarse (it discards nonlinearity). The residual is where parameterization still bleeds through, even between networks solving the same task.
- Full writeup: `scratch/response-tensor/session01_findings.md`
- Scripts: `scratch/response-tensor/session01_response_tensor.py`, `session01_meanVSresidual.py`

### Session 02 — the unified object is on-manifold J
- Worked out algebra: both `dy/dx` and `dy/dθ` contract through `M(x) = W2·diag(σ'(W1 x))`. M was the first-guess unified object.
- T5: Hungarian hidden-unit alignment drops weight-space distance but leaves J unchanged to 10^-32 (J is exactly permutation-invariant by algebra). So Session 1 residual disagreement is NOT a symmetry artifact.
- T6: Networks agreeing in first Jacobian moment (cos 0.9997) disagree in second moment (Bures distance 0.29 vs scale 0.48).
- **T7 headline:** on a task where data lives on a 4-dim subspace of 12-dim input, residual J has cosine agreement **0.93 on-manifold** and **0.14 off-manifold**. Networks agree on Jacobians in directions the data actually explores, disagree in directions orthogonal to data.
- T8: M(x) as a unified object is refuted — even after alignment, M_a vs M_b per-unit cosine only 0.40. M is the algebraic ancestor but is not basis-free.
- **Refined unified-object candidate:** the pushforward measure `x → J(x)` over the data distribution, restricted to on-manifold directions. This is function-invariant, parameterization-free, and much smaller than weights.
- Implication for self-modeling: the right object to feed a model as self-knowledge is on-manifold J, not weights or full J.
- Full writeup: `scratch/response-tensor/session02_findings.md`
- Scripts: `scratch/response-tensor/session02_unified_M.py`

### Session 03 — pivot after lit survey; self-modeling with J(x) fails cleanly
- **Lit survey finding:** sessions 1-2 rediscovered established work. EDJM (Wang 2016), on-manifold Jacobian and generalization (Novak 2018), information/nuisance split of Jacobian spectrum (Oymak 2019), Jacobian matching between networks (Srinivas 2018), empirical NTK, Git-Rebasin. The "unified object" framing was mostly a re-presentation of standard algebra.
- **Pivot:** tested whether USING J(x) as a self-modeling input channel produces qualitatively different behavior. Six conditions with proper null controls (pure noise, static noise, shuffled J, x-projection).
- **Headline negative result:** self_access, shuffled_J, pure_noise, and static_noise are statistically indistinguishable on every metric. Off-manifold stability improves dramatically with ANY side pathway (std 0.44 → 0.13), but independent of what flows through it.
- **Why:** J(x) is a deterministic function of x and θ; the network already has both. Formally zero new information. Side-channel usage is ~0.03 RMS, vs 0.52 for a genuine extra-info signal (x_proj).
- **Reframing:** for self-knowledge to matter, the signal must carry information the network cannot compute from its current inputs. Candidates: past states (temporal), perturbation responses (Fisher), external analysis (recursion), held-out behavior.
- Methodological catch: first run had a broken "random control" that was actually informative about x — had to rerun with proper nulls.
- Full writeup: `scratch/response-tensor/session03_findings.md`
- Scripts: `scratch/response-tensor/session03_self_modeling.py`, `session03b_controls.py`

### Session 04 — temporal past-M via active gating; works modestly; "self" is type not identity
- Combined all three: temporal (past_M, not current J), unified object (M not J), active feedback (multiplicative gate).
- Architecture: h_mod = tanh(W1 x + b1) · (1 + tanh(W_g · flatten(M(x; θ_{t-K})) + b_g)). Gate starts at identity, can learn to modulate.
- Why the signal isn't redundant: M(x; θ_{t-K}) depends on past weights that the current network doesn't have. Unlike session 3's J(x; θ_t), which was fully determined by current state.
- **Result:** test loss 0.0027 (no_feedback) → 0.0022 (self_temporal), ~20% improvement, ~1σ. Gate_dev ~0.07 (network actively uses the gate).
- **Surprise:** other_temporal (past from a *different seed*) performs the same as self_temporal (0.0023 vs 0.0022). Shuffled_temporal and random_history don't help. So what matters is *coherent* M(x; θ_past) paired correctly with x — whether θ_past is literally mine or a peer's is irrelevant.
- **Philosophical implication:** if self-knowledge is the local response structure M(x), then "self" is about TYPE (competent network solving this task), not IDENTITY (this specific network). For the recursion question from turn 1: interpretation chains A→B→C might collapse to a shared functional type rather than diverge into genuinely distinct objects.
- Effect size is modest and needs replication with more seeds and real data to be trusted.
- Full writeup: `scratch/response-tensor/session04_findings.md`
- Script: `scratch/response-tensor/session04_temporal_feedback.py`

### Session 05 — write-to-future-self via tied weights; works architecturally, fails optimizationally
Three-part experiment (5A memoryless, 5B drift task, 5C oracle probe).
- Architecture: `z1 = W1 x + b1 + W_m m_prev`, `m_new = W_m^T · mean(h) + b_m`. Tied weights, no BPTT, message is stop-grad on read.
- 5A: On IID task, all conditions tie. Network correctly ignores an irrelevant channel. Expected.
- 5B: Even with drift task that REWARDS memory (optimal no-memory floor at 0.051 due to unresolvable phase), self_write matches no_memory exactly (0.051 vs 0.051). Messages don't oscillate at drift frequency. Network never writes useful content.
- 5C: Oracle [sin(2πt/T), cos(2πt/T)] signal fed through the same memory channel drops loss to 0.015 — 3.3× improvement. Architecture works when given usable signal.
- **Diagnosis:** cold-start / credit-assignment failure. At init m ≈ 0, reading is neutral, gradient on W_m has no pressure toward useful content. Without BPTT or explicit supervision, the write never gets off the ground.
- **Broader implication:** gradient descent on weights IS already a self-modification channel with a working credit-assignment path. Any additional self-modification mechanism needs its own such path. Without one it's dead code. Matches all existing literature on memory-augmented architectures.
- Full writeup: `scratch/response-tensor/session05_findings.md`
- Scripts: 3 files in `scratch/response-tensor/`

### Session 06 — dream dynamics as Fisher-metric Brownian motion (novel characterization)
Committed direction: combined Möbius + dreams. Networks evolve under their own dream-driven weight updates with no external gradient signal. Update rule: sample noise, forward pass, perturb target by ε, gradient step.

- **Math:** δθ = lr · ε · ξ · ∂f/∂θ. Expected δθ = 0 (zero drift). Covariance ∝ (∂f/∂θ)^T (∂f/∂θ) = empirical Fisher. So dream dynamics IS Fisher-metric Brownian motion on weight space.
- **Convergence test:** Networks DIVERGE under dream dynamics. Pairwise function distance +75% over 1000 steps. Refutes my initial "shared attractor" hypothesis.
- **Preservation probe (6B):** 9 macro-properties preserved to <5% drift (W_norm +0.0%, J_eff_rank +0.0%, J_top +0.2%, out_var +1.2%, lipschitz +0.3%, etc.). Test loss degrades +170%. Random-init networks preserve the SAME set of macro-invariants — preservation is a property of the dynamics, not training.
- **Unifying frame:** Fisher-metric Brownian motion preserves Fisher-isotropic quantities and erodes weight-space-directed quantities. Training content is directed (requires specific weight-data alignment); macro-properties are isotropic (functionals that don't care about direction in weight-space).
- **Reframing session 4:** "Type equivalence" is a shared LEVEL SET in weight-space, not a shared point. Networks in the same type share macro-invariants but occupy different points within the level set. The macro-signature is the parameterization-free object — what the "unified object" framing from sessions 1-2 was actually pointing at all along.
- **Novelty:** The framing "dream dynamics = Fisher Brownian motion characterizing networks via preserved invariants" is novel to my literature survey. Pieces exist (SGLD, NTK, empirical Fisher) but not this specific combination or the type=level-set conclusion.
- Full writeup: `scratch/response-tensor/session06_findings.md`
- Scripts: `scratch/response-tensor/session06_dream_attractor.py`, `session06b_macro_invariants.py`

### Session 07 — options
1. Longer-timescale probe: 50k steps, test Brownian-motion prediction formally — does weight distribution asymptote to Fisher-predicted shape?
2. Scale test: 4-layer net + MNIST — do the preserved invariants survive?
3. Enumerate invariants via symmetry group of the Fisher walk (Lie-theoretic framing)
4. Biology connection: REM sleep has drift term (consolidation) that our dynamics lacks. Adding back drift might reveal something.
5. Stop and write final synthesis. Session 6 may be the best place to wrap.

### Sessions 03+ — tentative
- Scale up (larger model, real task) to see if the mean-vs-residual energy partition survives.
- Formalize the path-integral / action-functional framing raised in the earlier conversation.
- Probe the Kronecker structure of per-layer Fisher info (K-FAC style) and relate to R.
- Prototype a "response-native" architecture that parameterizes J directly and see if it trains.
- Write-up a theoretical note on "R as a function invariant modulo weight-space symmetry."

## Files

- `session-notes/response-tensor-progress.md` — this file (tracker)
- `scratch/response-tensor/session01_response_tensor.py` — baseline experiments
- `scratch/response-tensor/session01_meanVSresidual.py` — mean/residual decomposition
- `scratch/response-tensor/session01_findings.md` — session 01 writeup
- `scratch/response-tensor/session02_unified_M.py` — M(x), Hungarian, on/off-manifold
- `scratch/response-tensor/session02_findings.md` — session 02 writeup

## Open questions carried forward

- Does the on-manifold J invariance survive at depth and on real data? (Session 3 primary)
- What is the formal relationship between on-manifold J and the NTK? Are they dual? (Session 3)
- For data that doesn't lie on a clean low-dim subspace (real images, text), how do we operationalize "on-manifold"? Local PCA? Data-tangent space?
- Given the unified object is the on-manifold Jacobian pushforward, what's the right *architecture* for a network that parameterizes it directly?
- Connection to mechanistic interpretability: features learned by SAEs are roughly "directions the network is sensitive to on data" — is this the same thing we're calling on-manifold J, just computed one layer at a time?
