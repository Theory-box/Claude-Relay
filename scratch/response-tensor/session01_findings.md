# Response Tensor Research — Session 01 Findings

**Question:** Is there a single underlying object — the "response tensor" R — of which weights and activations are two projections? If so, what does it look like, and what invariants does it have?

## Setup

A tiny MLP `y(x) = W2 · tanh(W1 x + b1) + b2`, trained to fit a fixed nonlinear teacher. Two students A, B trained with different init seeds to near-identical loss on the same data.

- `d_in = 12`, `d_hidden = 64`, `d_out = 6`, `N = 800`
- Per-input Jacobian `J(x) = dy/dx ∈ R^{6×12}`
- Response tensor `R = {J(x_i) : i=1..N} ∈ R^{800 × 6 × 12}` (flattened to `800 × 72` for SVD)

## T1 — Activations-as-gradients duality

Analytic claim: for the output layer `y = W2·h + b2`, we have `dy_i/dW2_ij = h_j` identically.

Numeric finite-diff check on a random entry:
```
h[j]        = 0.384125
dy_i/dW2_ij = 0.384125   (finite-diff)
match: True
```

**Confirmed.** Hidden activations *are* weight-gradients at that layer, up to identity — the split between weights and activations really is a notational convenience for the same underlying gradient structure.

## T2 — Spectrum of R

```
top-10 sing (A): [40.54  5.80  4.96  3.20  2.82  2.75  2.51  2.17  2.09  1.94]
top-10 sing (B): [40.51  5.30  4.49  3.50  3.13  2.85  2.62  2.46  2.26  2.14]
effective rank : A=18.93   B=19.98   of 72
k for 90% energy: 1    |    k for 99% energy: 19    |    ambient: 72
```

One singular value (~40.5) dominates: it captures 90% of R's Frobenius-energy. Effective rank is ~19/72 — R is very low-rank in practice despite its ambient dimension.

Interpretation: the dominant component is the "average behavior" of the network as a linear map. The remaining ~19 meaningful directions encode how the Jacobian varies across inputs (nonlinearity-dependent structure).

## T3 — Subspace overlap between two networks

Principal angles between the top-k row-subspaces of `R_flat` for A vs B:

```
k=  2:  mean cos = 0.5530   min cos = 0.1064
k=  5:  mean cos = 0.7047   min cos = 0.0541
k= 10:  mean cos = 0.5834   min cos = 0.0047
k= 20:  mean cos = 0.5980   min cos = 0.0022
```

Partial overlap at best. The response subspaces of two networks solving the *same task* do not coincide. This is the first evidence that **R (as defined) is not a faithful function invariant** — it still carries parameterization information.

## T4 — The decomposition that clarifies everything

Split `R = (mean Jacobian, broadcast) + (residual)`:

```
Mean Jacobian comparison:
  cosine(J_a_mean, J_b_mean)   = 0.9997
  relative Frobenius distance  = 0.0229

Energy partition (net A):
  mean-part          = 1600.19   (89.7%)
  residual-part      =  183.86   (10.3%)
```

- The **mean Jacobian is essentially function-invariant** — the two networks agree on it to four decimal places in cosine. This is the genuine "functional core" of the response.
- It accounts for **89.7%** of R's total energy.
- The remaining **10.3%** is the input-dependent residual, and *this* is where the networks disagree.

Residual subspace overlap:
```
k=  2:  mean cos = 0.7852   min cos = 0.5914
k=  5:  mean cos = 0.6845   min cos = 0.0093
k= 10:  mean cos = 0.5766   min cos = 0.0101
```

Even in the residual, the top 2 directions agree reasonably well (~0.79), but beyond that the networks' local-sensitivity patterns diverge quickly.

Cross-projection sanity check — how much of A's residual energy lies in B's top-k residual basis:
```
top-10 of B captures  60.72%  of A's residual energy
top-40 of B captures  83.50%  of A's residual energy
top-60 of B captures  94.25%  of A's residual energy
```

Even using a 60-dim basis from B (of 72 ambient), 6% of A's residual is in directions B does not span.

## Summary of the story

R decomposes, empirically, into:
1. A **function-invariant core** — the mean Jacobian. Two networks solving the same task converge on the same average linear map (cosine ≈ 1.0). This carries ~90% of R's energy.
2. A **network-specific fingerprint** — the input-dependent residual. Captures 10% of energy but is where A and B differ substantially.

So the first cut of the Maxwell-moment hypothesis is a partial yes: the *mean Jacobian* is a clean function-invariant object that unifies "how the network responds on average" across both weights and activations. But it's too coarse — it throws away all nonlinear structure.

The actual unified object we're hunting for is probably the **distribution of Jacobians over the data distribution, quotiented by weight-space symmetries** (permutations of hidden units, sign flips under tanh, etc.). The raw distribution differs between A and B; the quotient might not.

## Confidence levels

- T1 duality (numeric + analytic): **very high**
- T2 low-rank structure of R: **high** — consistent with intrinsic-dimension literature
- T3 partial subspace overlap: **medium-high** — caveat that the MLP is small; at scale the story might differ
- T4 mean/residual split: **high** on the mean agreement, **medium** on the interpretation of the residual as "network fingerprint" — could also be that the residual is still function-determined but has hidden symmetries we haven't quotiented out

## What this leaves for Session 2

Three threads in priority order:

1. **Quotient by hidden-unit permutation before comparing residuals.** If the residual agreement improves dramatically after aligning hidden units (via Hungarian matching or optimal transport on the hidden-space representations), that's strong evidence the residual is also function-invariant once weight-space symmetry is divided out.

2. **Compare moments, not subspaces.** Compute the covariance `Cov[J(x)]` over the data. Covariance is symmetry-invariant in ways that "the basis of the row-space" is not. If networks' Jacobian covariances match even when subspaces don't, the unified object is a distributional one.

3. **Formalize the "mean Jacobian" finding theoretically.** For a function `f`, its average linearization `E_x[df/dx]` is well-defined and network-independent. Connect this to neural-tangent-kernel theory — NTK is about `E[df/dθ df/dθ^T]`; our finding is about `df/dx`. These are dual Fisher-like quantities; the relationship between them may be the clearest window into the unified object.
