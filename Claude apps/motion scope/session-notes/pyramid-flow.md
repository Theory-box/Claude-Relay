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

## Session 2 — de-noise the flow (mosaic/shimmer fix)
Three fixes to the flow BEFORE it's applied (effect strength untouched):
1. Warp-field spatial smoothing: two box passes (blurGray x2) on R2/gTmp2, radius
   2+denoiseR -> ~Gaussian, removes box-blur mosaic grid; wires the Smoothing slider.
2. Deadband: if band displacement |d|<0.25px -> 0, so stationary regions don't warp
   (kills accumulated-noise shimmer on still areas). Applied post-bandpass.
3. Accumulator leak 0.99/frame -> bounds random-walk drift from integrated flow noise.
Tunables if needed: dead (0.25), leak (0.99), fr base (2), LK iters/level (3).

## Session 3 — keep BOTH (Fast/Deep toggle)
Restored the original single-scale warp as the default; pyramidal flow is now behind
a Warp-field "Fast / Deep · big motion" toggle (deepFlow). warpFrame branches: Deep =
pyramidal+accumulate+bandpass+deadband+leak+field-smooth; Fast = original single-scale
LK on the temporal band (crisp). Suppress works in both (k). gpuSupportedFor: warp on
GPU only when !deepFlow (Deep is CPU-only). So user can turn GPU off + raise Detail to
preview Deep at full res, to judge whether low-res was the artifact source before GPU port.
Next: if full-res Deep looks good -> port pyramidal to GPU (~40 passes, its own build).
