# Response Tensor Research — Session Progress

**Branch:** `research/response-tensor`
**Started:** April 2026
**Status:** Session 01 complete (1 of up to 10)

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

### Session 02 — planned
Three threads, in priority order:
1. **Hidden-symmetry quotient.** Align A and B's hidden units via Hungarian matching on activation correlations, then recompute residual subspace overlap. Test hypothesis that residual is function-invariant once symmetry is divided out.
2. **Moments, not subspaces.** Compute Jacobian covariance `Cov_x[J(x)]` for A and B, compare directly. Covariance is symmetry-invariant.
3. **NTK connection.** Our finding is about `df/dx`; NTK is about `df/dθ`. These are dual. Work out the relationship explicitly for the tiny MLP.

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

## Open questions carried forward

- Does the mean-Jacobian invariance survive when the task is harder (deeper network, real data)?
- Is the 10% residual mostly hidden-symmetry (and therefore function-invariant once quotiented) or genuinely network-dependent?
- What's the correct mathematical object: a distribution over Jacobians? A kernel? An equivalence class of tensors?
- Does NTK theory already give us this for infinite-width networks, and we're just seeing its finite-width shadow?
