# Session notes — pyramidal (coarse-to-fine) flow

**Branch:** `feature/pyramid-flow` (from main @ WebGPU[11]). Do NOT merge until tested.

## Goal
Replace warp's single-scale Lucas-Kanade (small-motion only, ±3px clamp) with a
coarse-to-fine pyramidal LK so large/fast motion is measured accurately. Unlocks
better big-motion amplification AND real suppression (freeze).

## Done (CPU-first; GPU warp untouched = still single-scale)
- buildPyr(): 3-level pyramid (procW×procH, /2, /4), per-level buffers.
- computeFlow(I0,I1): downsample both, coarse->fine; per level upsample flow ×2 then
  3× lkStep. lkStep = warp I1 by flow, gradients of I0, It=I1w-I0, structure tensor,
  blurGray(2), 2x2 solve, residual clamp ±2, add to flow.
- warpFrame now: pyramidal flow between Yprev and current Yb (frame-to-frame velocity)
  -> integrate per-pixel position (Pxa/Pya, reused phase buffers) -> temporal band-pass
  (pxS/pxF/pyS/pyF) -> AC displacement -> field-denoise -> k*(dx,dy) -> warp field.
  k = amplify (g-1) or suppress (1/g-1). Remap/plate/overlay unchanged.
- Suppress toggle re-added (Warp field group). Amplification label shows "N% still".
- Verified numerically offline: recovers ~6.75px of an 8px shift (single-scale ~2-3).

## Test plan (GPU OFF, Warp mode)
- Amplify: large/fast motion should exaggerate more cleanly than before.
- Suppress: sway/jitter should actually settle (not just clean-plate).
- Watch for: accumulated-flow drift/jitter (integrating flow noise); tune with Field
  denoise / Smoothing if noisy. CPU is slow at high Detail — keep Detail low to test.

## Next after validation
- Tune (levels, iterations, reg, residual clamp, flow noise handling).
- Port pyramidal flow to GPU (pyramid via downsample passes; iterative LK passes).
