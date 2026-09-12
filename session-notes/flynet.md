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
