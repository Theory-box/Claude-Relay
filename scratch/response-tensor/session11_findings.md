# Response Tensor Research — Session 11 Findings

## Push point

Session 10 concluded with a claimed ~25% "ceiling" on signature-based functional recovery. This session tested two things the user proposed:

1. Different compression targets (not just f_A, but Jacobians, hidden activations, combinations)
2. Whether findings generalize to a different task (char-level Shakespeare)

Both produced results that reshape the earlier story substantially.

## 11A — Richer targets with ES gradient: NO improvement

Compared output / hidden / Jacobian / combined at K=1 and K=4 using ES-style signature gradients (same optimization as sessions 9-10):

```
type         K    sig dim    recovery
output       1          4    +21.7%
output       4         16    +21.1%
hidden       1         20    +18.8%
hidden       4         80    +17.8%
jacobian     1         40    +19.6%
jacobian     4        160    +20.7%
combined     1         64    +21.5%
combined     4        256    +19.5%

full-dataset distillation (exact gradient, K=600, dim=2400): +37.3%
```

Richer targets don't break the ~22% ES ceiling. But the full-dataset baseline (+37.3%, exact gradient) indicates the ceiling may be optimization-limited, not information-limited.

## 11B — Exact gradient breaks the ceiling

Replaced ES-estimated signature gradient with exact backprop (treat probes+targets as extra mini-batch):

```
K     exact gradient    ES gradient    Δ
1     -118.1%           +23.0%         -141%   ← K=1 exact catastrophically overfits
4     +24.7%            +22.5%            +2%
16    +31.2%            +17.0%           +14%
64    +42.3%            —                 —
600   +34.2%            —                 —
```

**K=64 exact = +42.3%, well past the "25% ceiling."** 

Two surprises:
- **K=1 exact is catastrophic.** Concentrated exact gradient on one probe warps the whole network. The reason K=1 appeared to work in session 10 was ES gradient noise acting as implicit regularization — it prevented effective matching, which coincidentally prevented overfit.
- **K=64 (+42.3%) beats K=600 full-dataset (+34.2%).** Sparse probes with appropriate weighting outperform standard full-distillation.

## 11C — Exact + combined + tuned: push to ~52%

Tested richer targets WITH exact gradient, then swept K and λ:

```
At K=64:
  output-match alone:              +42.3%
  hidden-match alone:              +6.6%    (doesn't constrain Wo)
  combined (α_h=0.3):              +50.5%   ← best combined
  combined (α_h=1.0):              +11.7%
  combined (α_h=3.0):              -209.8%  (instability)

K sweep, output-match, exact gradient, per-K λ tuning:
  K=4    +22.5%
  K=16   +30.1%
  K=64   +42.3%
  K=128  +45.8%   ← K peak
  K=200  +43.7%
  K=300  +41.9%
  K=400  +38.5%
  K=600  +34.2%   ← full

λ sweep at K=128:
  λ=0.5  +28.7%
  λ=1.0  +34.4%
  λ=3.0  +44.1%
  λ=5.0  +47.9%
  λ=8.0  +52.4%   ← best
  λ=15.0 -249.9%  (instability)
```

**Peak recovery: +52.4% at K=128, λ=8.** Over 2× the session-10 "ceiling."

Combined hidden+output gives an additional 8 points at K=64 (42% → 50%). Hidden alone is weak because it only constrains W1/b1 (Wo/bo are untouched). Combining targets constrains more of the parameter space.

Sparse K=128 beats K=600 because at K=600 the per-probe weight dilutes; at K=128 with high λ each probe is well-matched.

## 11D — Shakespeare test

Char-level next-char prediction on a chunk of Hamlet (public domain). Vocab=26, context=4, tiny architecture (4218 params).

```
K          recovery
4          +2.6%
16         +4.6%
64         +6.7%
256        +31.6%
532 (full) +33.3%
```

**Qualitatively different pattern from teacher task:**

```
                  teacher       Shakespeare
K=4               +22-25%       +2.6%
K=16              +30%          +4.6%
K=64              +42%          +6.7%
K=256             —             +31.6%
K=full            +34%          +33.3%

sparse vs full    sparse wins   sparse ≈ full
```

Low-K signatures work poorly on Shakespeare. Only when K approaches full-dataset does recovery kick in. And sparse doesn't beat full.

**This reveals what signature compression is actually doing.** On smooth, structured tasks (teacher regression), a function's behavior across inputs is correlated — a few probes pin down the rest. On high-entropy tasks (language modeling, especially with heavy overfit), the function is essentially memorized per-training-point content, so compression requires many probes. The compression ratio is a measure of the trained function's *intrinsic dimensionality*.

Caveat: the Shakespeare anchor barely trains (test CE 3.09 vs uniform 3.26), and heavily overfits (train CE 1.21). A better-trained language model might compress differently. But at least for this setting, the pattern is clear.

## Two corrections to my earlier claims

1. **Session 9B's "identity lives off-manifold":** wrong. Session 10 showed on-manifold probes win (distance sweep); session 11 confirms this.

2. **Session 10's "K=1 captures 22% of identity":** misleading. With exact gradient, K=1 is catastrophic. The apparent success was ES-gradient noise acting as implicit regularization. The real compression curve is monotonically increasing in K (up to ~128, then diluted), not flat-from-K=1.

## The corrected picture, start to finish

- Signature = A's behavior on a small set of probes
- Recovery = how much matching that signature pulls B toward A's function
- With **exact gradients, proper λ tuning, and combined targets**, signature compression at K=128 gives ~52% recovery on teacher regression — much better than I previously reported
- On **high-entropy/overfit tasks** like char-LM, the compression is much weaker at low K and eventually matches full-dataset distillation at high K
- The compression ratio **measures intrinsic task structure** — smooth task = high compression, memorization task = low compression

## Confidence

- Exact gradient beats ES gradient for signature matching: **high** (direct comparison at same K)
- K=128 at λ=8 achieves ~52% recovery on teacher task: **high** (multiple seeds, consistent)
- Sparse K=128 beats full K=600: **high** (with appropriate λ tuning)
- Signature compression is task-dependent with Shakespeare being much weaker at low K: **medium-high** (one alternate task tested, Shakespeare model was small and overfit)
- Previous K=1 result was an ES-gradient artifact: **high** (reproduced K=1 catastrophe with exact gradient)

## What's genuinely new in this session

- The recognition that the previous "ceiling" was optimization-limited, not information-limited
- Combined (output + hidden) matching with correct α_h weighting adds ~8 points over output alone
- Sparse probes at high λ can outperform full-dataset distillation
- Task-dependence of signature compression ratio as a diagnostic of intrinsic task structure
- The ES-gradient acted as implicit regularization at K=1 — this is a specific observation about the interaction between gradient-estimator noise and probe-concentration

## Scripts

- `scratch/response-tensor/session11a_rich_targets.py` — ES gradient with richer targets (no improvement)
- `scratch/response-tensor/session11b_exact_gradient.py` — exact vs ES at same K
- `scratch/response-tensor/session11c_exact_richer.py` — combined targets + K and λ sweeps
- `scratch/response-tensor/session11d_shakespeare_fast.py` — Shakespeare character-LM test

## Where this could go if we keep pushing

1. Run combined (output + hidden) at K=128, λ=8 with tuned α_h — might push past 52%
2. Test intermediate-complexity tasks (beyond teacher, short of natural language) to characterize the compression-ratio vs task-complexity relationship
3. Better-train a Shakespeare-capable model (bigger net, more text) — see if a properly-fit LM compresses more like teacher or remains memorization-heavy
4. Theoretical bound on maximum compression given task complexity
5. Full synthesis doc for the 11-session arc
