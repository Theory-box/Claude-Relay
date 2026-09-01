# Frequency analysis / FFT readout (branch feature/fft)

New "Frequency analysis" panel: Pick region -> drag a box (amber) over something vibrating ->
live spectrum + dominant frequency; "Set band around peak" snaps loHz/hiHz to peak*0.7..1.4.

Signal: each REAL delivered frame (sampled in the requestVideoFrameCallback tick, so at the true
capture rate -> correct Hz axis), resample probe box to 64x64, take column+row luma profiles,
sub-pixel cross-correlate vs a reference profile (captured on box-set) -> (dx,dy) displacement.
Buffer FFTN=128 samples (~4.3s at 30fps). computeSpectrum: mean-detrend + Hann window, radix-2
fft of dx and dy, sum magnitude spectra. Peak (excluding <~0.3Hz bins) -> peakHz = pk*capFps/FFTN.
Axis 0..capFps/2. drawSpectrum on #fftCanvas; updateSpectrum every 5 render frames.
Validated in node: recovers 1/2.5/6/9.3/13 Hz to ~0.1Hz. Probe draw reuses stageToNorm/normRect;
separate probeLayer + probe-box css. Sampling in vfc = true rate; falls back to loop if no vfc.

TEST: Pick region over a vibrating/oscillating object (needs texture/edges). Wait ~4s (shows
Collecting X/128). Dominant Hz appears; Set band around peak dials the frequency band to it.
Best with clear periodic motion + enough capture fps (Nyquist).

## Session (analysis panel v2) — aliasing + noise confidence (branch feature/alias)
- Aliasing: for a detected apparent peak, list candidate true freqs (k*Fs +/- apparent, <=250Hz).
- Noise confidence: noise floor = median of non-peak spectrum bins; SNR = peak/noiseFloor.
  SNR<3 -> "reads as noise" (region static/too noisy). >=7 High, >=4.5 Moderate, else Low.
  Validated in node: pure noise SNR~2.5 (flagged noise), signal+noise SNR~33 (high). Reuses the
  probe box already in the panel -> user picks a region, gets frequency + trustworthiness.
