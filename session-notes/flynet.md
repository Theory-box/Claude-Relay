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

## UPDATE: direction bank (fly-INSPIRED, not connectome) — all motion types covered
directionbank.py — scene with 4 motion TYPES (H-translate, V-translate, rotation, expansion)
+ strong flicker distractor. Architecture:
  - alpha MAGNITUDE = amplitude-invariant coherence gate (direction-agnostic) -> coverage + flicker rejection
  - 8-direction oriented bank (T4/T5-like) gated by coherence -> per-pixel motion DIRECTION (for selectivity)
Result: single-H detector misses V/rotation and amplifies flicker (6.9) > motion. Coherence gate:
all 4 motion types 0.23-0.63 vs flicker 0.10 -> 100% coverage. Direction map: expansion ring = rainbow.
Outputs: bank_heatmap.png (scene | coherence gate | direction map), bank_channels.png.

## Next
- Selective suppression via the bank: null a chosen direction to reject a known camera-pan/shake axis
  while keeping perpendicular vibration (the real payoff of a bank vs the plain coherence gate).
- Then: real flyvis connectome motion network (needs torch); and/or integrate into the app (needs go-ahead).

## UPDATE: REAL connectome front-end working (fly-ACTUAL, not inspired)
realfront.py — uses flyvis (Lappalainen 2024), the actual connectome-constrained fly visual
network (45,669 neurons, 65 cell types incl. real T4a-d / T5a-d direction detectors).
Install: torch==2.5.1 + torchvision==0.20.1 (cpu index) THEN pip install flyvis. Pretrained
weights via `flyvis download-pretrained` (needs httplib2 CA fix: set httplib2.CA_CERTS to
/etc/ssl/certs/ca-certificates.crt for the sandbox proxy). Model: flow/0000/000.

Validation: rightward bar -> T4b dominant; leftward -> T4a dominant (real direction selectivity).
Vibrating-beam + strong flicker scene through the REAL network:
  T4/T5 in-band motion power  beam=4.9e-2  flicker=4.8e-3  -> 10.1x selectivity.
So the ACTUAL fly brain rejects flicker and selects coherent motion, matching the inspired gate.
Map back-projected via eye.receptor_centers (721 hexals -> 2D). Bright L/R edge bands = hex-field
boundary artifacts, not signal. Output: real_connectome_map.png.

## Status: fly-inspired AND fly-actual both validated.
## Next
- Plug the real T4/T5 map into the full EVM magnify() as the alpha-map (replace inspired gate).
- Higher-res / tiled eye for real video (721 hexals is coarse).
- Head-to-head: real connectome vs inspired gate vs energy on identical scenes.
- App integration -> needs explicit go-ahead.

## UPDATE: 65-cell-type ablation sweep on flyvis vibration task (KEY FINDING)
Task: discriminate vibrating vs non-vibrating (flicker/noise) clips via decoded optic-flow
in-band power. Ablate each cell type via state hook (zero node activity -> propagates downstream).
Metric: perf = log(mean_vib / mean_neg). Intact = 1.480. ablation.py / sweep_driver.py / analysis.py.

RANKING (recovered real biology): top = Mi2, T4c, Tm1, CT1(Lo1), R8, CT1(M10), T4b, Mi9, Mi1,
T4a, C3, TmY15, Mi4, TmY18, R6, Mi12, TmY9, C2 ... i.e. the ON motion pathway + CT1 inhibition
(known critical for direction selectivity) + non-obvious C2/C3 centrifugal + TmY lobula cells.
Validates the discovery approach (found CT1, C2/C3, TmY without being told).

SUFFICIENCY (keep-only-core, delete the rest): top-8=1%, top-12=-2%, top-16=13%, top-20(14420 cells)=21%
of intact. => Motion computation is DISTRIBUTED/REDUNDANT. No small sufficient subcircuit exists.
Structural pruning to a tiny "fly circuit policy" is OFF the table (confirmed the upfront risk).

IMPLICATION: pivot distillation from STRUCTURAL (prune subcircuit) to FUNCTIONAL (train a compact
student to reproduce the teacher's motion output). This is how C. elegans NCPs actually work anyway
(small nets TRAINED to do the task, not pruned from a big one). Caveat: keep-only uses ORIGINAL
weights; a RETRAINED small student is not ruled out. Also single-ablation under-detects redundancy
(L1=0 due to L2-L5 parallel channels).
