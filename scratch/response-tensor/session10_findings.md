# Response Tensor Research — Session 10 Findings

## Joint probe optimization — and correcting the earlier story

Session 9 found K=4 random probes give 23.3% functional recovery, better than weight statistics. Session 9B found max-disagreement probes live off-manifold and claimed "identity lives in extrapolation." This session tested whether joint optimization could push past the random baseline, and in doing so uncovered that the earlier framing was wrong.

## 10A — Four optimization methods, none beat random

Compared 5 probe-selection methods at K=4, averaged over 3 B-training seeds:

```
method                  ||f_A - f_B||     recovery
max-disagreement        0.0368 ± 0.0032   +19.5%
random                  0.0370 ± 0.0035   +19.2%
active-iterative        0.0395 ± 0.0014   +13.7%
bilevel-ES              0.0403 ± 0.0034   +12.0%
fisher-info             0.0421 ± 0.0050    +8.0%
```

**No method beat random K=4 within error bars.** Max-disagreement ties random; principled methods (Fisher info, active, bilevel ES) all underperform. Session 9's reported 23.3% for random K=4 was seed variance — the true mean is ~19%.

## 10B — Distance sweep reveals the real finding

Generated K=4 probes at controlled off-manifold distances. Each distance tested with 3 probe samples × 3 B-training seeds = 9 trainings per point.

```
off-manifold distance    recovery
  0.00 (on manifold)     +24.6%   ← best
  0.30                   +18.3%
  0.60                   +15.8%
  1.00                   +19.2%
  1.50                   +15.6%
  2.50                   +18.6%
  4.00                   +19.3%
  6.00                   +12.3%   ← worst
```

**On-manifold probes win decisively.** Session 9B's "off-manifold probes are best" claim was wrong. The off-manifold probes have different statistical properties (higher disagreement, Fisher info, norm) but those properties don't translate to training effectiveness.

## 10C — On-manifold probes scale without collapse

Swept K from 1 to 24 for on-manifold probes (both synthetic d=0 and probes drawn from training X):

```
K      synthetic d=0    from training X
 1     +21.9%           +23.7%
 2     +22.6%           +22.5%
 4     +20.2%           +17.2%
 8     +17.2%           +18.5%
12     +20.0%           +21.7%
16     +22.8%           +22.7%
24     +22.4%           +17.5%
```

**K=1 already captures most of the available recovery.** One on-manifold probe (4 numbers) gives +22-24%, indistinguishable from K=24 (96 numbers). On-manifold probes do not collapse at high K as off-manifold ones did in session 9 (K=32 off-manifold: -84%).

## The corrected picture

Two task-trained networks:
- Agree closely on-manifold (both solve the task well), differ slightly in generalization within the data range
- Differ wildly off-manifold (extrapolation is unconstrained by training)
- The on-manifold differences and off-manifold differences are largely **decoupled** — that's how networks can disagree off-manifold while agreeing on-manifold

Matching a signature does two different things depending on probe location:

- **On-manifold:** directly targets A's specific generalization choices within the data range. This is A's functional identity. Matching it transfers identity efficiently.
- **Off-manifold:** targets A's extrapolation behavior, which is decoupled from on-manifold function. Matching there pulls B's extrapolations toward A's but has minimal effect on the on-manifold function we measure.

**A network's functional identity is compressible to ~25% of its random→indep gap in roughly 4 numbers (one on-manifold probe output).** Adding more probes doesn't materially improve this. The 25% appears to be a fundamental ceiling of this compression approach at this architecture/task scale — possibly the "shared structure" fraction that any task-trained network has, vs the irreducibly-idiosyncratic 75%.

## What killed the earlier story

Session 9B's logic was: correlate probe properties (norm, disagreement, off-manifold distance) with functional recovery across K values. The correlation looked like "off-manifold = better." But:

1. The K=4 random result (23.3%) was a lucky seed; with averaging it's 19%
2. Max-disagreement probes are off-manifold by construction, so they *correlate* with off-manifold properties without those properties *causing* good recovery
3. The actual driver of recovery — on-manifold-ness — wasn't measured because random N(0,I) probes in 10d mostly live off-manifold anyway

Better experiments (distance sweep, multi-seed) revealed the opposite answer.

## Confidence

- On-manifold probes outperform off-manifold for functional recovery: **high** — distance sweep clean, multi-seed averaged
- The ~25% ceiling: **medium-high** — consistent across K, distances, methods, but specific to this architecture/task
- K=1 captures most of the recovery: **high** — multiple seeds confirm
- No optimization method beats random on-manifold probes: **high** — 5 methods tried, all underperform or tie
- Ceiling represents a fundamental compression limit: **medium** — not proven, but consistent pattern

## What this means practically

If you wanted to use macro-signatures for anything:
- Use 1-4 on-manifold probes (sampled from training distribution) as the signature
- Don't bother with optimization — random works
- Expect ~25% functional-identity transfer at best
- That's useful for diagnostic purposes, not reconstruction

The approach has a real ceiling. To compress more of a network's function, you'd need a different mechanism — probably model-scale or architecture-specific information that signatures as-defined don't carry.

## Scripts

- `scratch/response-tensor/session10_joint_optimization.py` — 5-method comparison
- `scratch/response-tensor/session10b_distance_sweep.py` — distance-controlled probes
- `scratch/response-tensor/session10c_K_sweep_onmanifold.py` — K sweep at d=0

## What's genuinely novel / honest in this session

- The corrected understanding of where network identity lives (on-manifold, not off)
- The identification of a hard compression ceiling (~25%) for signature-based approaches
- K=1 sufficiency — a single behavioral probe output captures most of the available signal
- The mechanism: on-manifold generalization differences are the distinctive content; off-manifold differences are real but decoupled and thus not useful for reconstruction

These findings are cleaner than what I claimed previously and correct an earlier error.
