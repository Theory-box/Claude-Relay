# session-notes: flynet

BRANCH: feature/flynet

## What this is
Testing the fly connectome as a direction-selective motion-amplification front-end for the
existing amplify app. Do NOT modify the amplify app yet (user instruction). New files only,
under research/flynet/.

## Status (feasibility = POSITIVE)
- Connectome loads + runs as a sparse signed recurrent net (real FlyWire v783).
- Direction-selective (Reichardt/T4-T5-style) alpha-map beats motion-energy decisively.
- Biological front-end degradations IMPROVE noise robustness (AUC 0.84-0.99 vs energy 0.0-0.4).
- Conclusion: worth proceeding to a video demo, then possibly integrate into the app.

## Next steps
1. 2D synthetic video visual: energy-magnified vs fly-gated-magnified, side by side.
   Use a minimal self-contained EVM (Laplacian pyramid + temporal bandpass) — do NOT touch app.
2. Optional: swap modeled front-end for real flyvis connectome motion network (needs torch).
3. If user likes the video -> discuss integration into the amplify app (needs explicit go-ahead).

## Caveats to carry forward
- Advantage is vs non-directional flicker/noise + opposite-direction motion; NOT same-direction shake.
- Benchmarked vs raw temporal-power energy; a tuned phase-based EVM baseline would narrow the margin.

## UPDATE: 2D video demo done (POSITIVE)
videodemo.py — synthetic vibrating cantilever beam + strong flicker patch + sensor noise.
Minimal self-contained EVM (FFT temporal bandpass), two alpha strategies on EQUAL total budget.
Fly gate = temporal band-tuning + wide-field spatial pooling (coherent motion survives spatial
blur; incoherent flicker cancels). Amplitude-invariant spatial-coherence gate.

Result (same budget):
  standard EVM : beam x92.9  flicker x13.1  -> signal/noise 7.08
  fly-gated    : beam x145   flicker x11.8  -> signal/noise 12.27   (1.7x better SNR)
Heatmap (alpha_heatmap.png) shows fly budget concentrated on the beam (cantilever mode shape),
flicker patch left dark. Outputs: beam_sidebyside.gif, alpha_heatmap.png, beam_still.png.

Honest notes: win is on equal budget (concentrates amplification on real motion). Flicker
absolute suppression modest (its coherence ~ background); beam boost is the main gain. The
2D gate is the pooled/coherence form of the direction-selective principle validated in 1D.

## Next options
- Direction bank (multi-orientation) for arbitrary-direction motion.
- Real video clip (needs the amplify app / a real EVM pyramid) — pending user go-ahead.
- Swap coherence gate for actual flyvis connectome motion network (needs torch).
