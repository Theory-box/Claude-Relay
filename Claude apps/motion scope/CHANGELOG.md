# Changelog — Motion Scope

All notable changes to the app. Newest first.

## 2026-08-12p — Zoom tab (appears when zoomed)

### Added
- A **Zoom tab** appears in the tab strip when you zoom into a region and disappears when you restore
  (hooked into updateTabAvailability, keyed on cropRect; leaving zoom auto-switches off the tab). Holds
  a Restore-full-view button + info; home for zoom settings (process-crop toggle to come).

## 2026-08-12o — Zoom to region (view crop)

### Added
- **Zoom to region**: magnifying-glass icon under the View icons. Click it, drag a box, and the view
  zooms so that region fills the viewport (icon becomes a restore glyph; click to return to full view).
  Implemented as a CSS transform on the view canvases — overlays and marker/coordinate math auto-align
  via getBoundingClientRect. Full-frame processing is unchanged (this is a digital zoom of the output).
  Transform validated (crop maps to fill stage exactly).
- NEXT: 'Process cropped region only' toggle (re-process just the crop for sharper, region-adapted
  results) — needs procW/procH re-derivation + cropped source, deferred to do carefully.

## 2026-08-12n — Vibration map: pre/post-amp source

### Added
- **Pre-amp / Post-amp** toggle for the Vibration map (mutually exclusive). Pre-amp reads the raw video;
  Post-amp reads the magnified output so faint vibrations produce a stronger map. Switching resets the
  demod so it re-locks.

## 2026-08-12m — Vibration map: Frequency mode + auto-detect

### Added
- **Frequency mode** for the Vibration map: a 14-band lock-in filterbank (log-spaced 1–25 Hz) tints each
  area by WHICH frequency dominates it (blue=low → red=high) instead of phase. Validated: filterbank
  resolves a pixel to its nearest band (3→3.4, 12→11.9, 18→19.5).
- **Detect peaks**: scans ~2 s, sums per-band energy across the frame, lists the scene's strongest
  frequencies as clickable chips that jump the Phase map to that frequency.
- Phase/Frequency mode toggle; frequency slider auto-hides in Frequency mode.

## 2026-08-12l — Vibration map (phase filter)

### Added
- **Vibration map** (Analysis subpanel): full-frame lock-in demodulation at a chosen frequency —
  colors every pixel by its vibration PHASE (same hue = in sync, opposite hue = antiphase), brightness
  = vibration strength. Own frequency slider + threshold + intensity. Per-pixel DC removed before
  demod (fixes phase recovery). Validated: in-phase 0deg, antiphase 180deg, off-frequency amp 1.5 vs
  9.7 on-frequency. Runs at reduced res, scaled to display; independent of the magnify pipeline.
- (Frequency-map mode + auto-detect peaks to follow.)

## 2026-08-12k — Real-unit vibrometry + phase relationships

### Added
- **Real-unit vibrometry**: calibrate a scale (Set scale -> drag a line over a known length -> enter it
  in mm/cm/in), and analysis point amplitudes read in real units (mm) instead of pixels. Amplitude
  from the FFT peak lobe (leakage-corrected); validated within ~4%% across frequencies.
- **Phase relationships**: when points share a frequency (within 15%%), each point shows its phase
  vs Point 1 (the phase ref): in-phase / antiphase / +-N deg. Phase from the dominant-axis FFT;
  validated (90deg->89, 180deg->180). Reveals how vibration propagates between points.
- trkDominantHz now also outputs per-point amplitude (t._ampPx) and dominant-axis phase; phaseAtHz(t,hz)
  helper. Amber calibration line drawn on the overlay.

## 2026-08-12j — Analysis graphs

### Added
- **Live analysis graph** in the Analysis tab (per tracked point, colored lines):
  - **Spectrum**: amplitude vs frequency (0–25 Hz), dominant peak marked + labeled in Hz — reads out a
    pulse or vibration frequency directly (the heartbeat-from-head-bob view).
  - **Waveform**: displacement over time along each point's dominant axis, with amplitude scale.
  - trkDominantHz now caches the full FFT spectrum; graph draws every frame when the Analysis tab is
    open. Peak-bin verified (7 Hz signal -> 7.0 Hz peak).

## 2026-08-12i — All three stabilizers orderable

### Changed
- Region is now folded into the same composed-transform path as Points and Auto (in the default Input
  stabilize mode), so **all three have a 1st/2nd/3rd layer-order dropdown** with three-way auto-swap.
  Region's shader shift is used only in View-only (post) mode now. Signs verified to match (shader and
  preFrame both give displayed = raw − acc).

## 2026-08-12h — Stabilizer intensity + layering

### Added
- **Per-stabilizer intensity** (Region / Points / Auto, 0–100%): scales each stabilizer's correction.
  Validated: 100% = unchanged, 0% = no correction, 50% = half.
- **Points + Auto can now both be active**, composed in a chosen **layer order** (1st/2nd/3rd dropdown
  with auto-swap). Region stays the whole-frame outer layer with its own intensity.
- (Full arbitrary region-in-the-middle reordering deferred — needs a deeper per-layer cascade.)

## 2026-08-12g — Analysis: measure on Amplified footage

### Added
- Analysis point tracking measure-on is now 3-way: **Stabilized / Raw / Amplified**. **Amplified**
  tracks the magnified output so tiny sub-pixel vibrations become big enough to lock a clean frequency
  (amplification preserves Hz). Caveats noted in UI: amplitude is gain-inflated; only motion inside the
  Hz band shows. Raw stays default-broadband.

## 2026-08-12f — Corner-detection mask (Auto stabilizer)

### Added
- **Corner mask** (Auto group): draw box(es) to control where Auto detects features. **Exclude** =
  don't detect inside the boxes (mask out a moving subject); **Include** = only detect inside them.
  Draw mask / Clear mask + Exclude/Include toggle; re-detects on change. Reuses the region-draw
  interaction; dashed red (exclude) / green (include) overlay. Validated: exclude 0 inside, include
  0 outside. RANSAC still rejects movers — this is extra fine-tuning control.

## 2026-08-12e — Stabilization analysis: overall + per-mode metrics, master toggle

### Added
- **Master STAB button** (header, green when on): toggles ALL stabilizers (region + points + auto) at
  once for instant A/B comparison.
- **Overall stabilization number** in the top readout: 'stab ↓X%' — green reducing, red adding, OFF
  when master off. Measured on monitor feature-corners under the final applied transform.
- **Per-mode metrics**: Region now shows its own Raw→Stab reduction (auto + points already did).
  Monitor corners auto-tracked whenever any stabilizer is intended.
- NOTE: region/overall assume displayed = raw − acc; if a number moves the wrong way vs the master
  toggle it is a one-line sign flip (verify via A/B).

## 2026-08-12d — Tracker refinement 1a: predictive tracking (coast-through)

### Added
- **Predictive tracking / coast-through** (Analysis tab toggle, default on, all trackers): an alpha-beta
  predict-correct filter with confidence-adaptive gain. Rides through brief occlusion or a noisy frame
  instead of jumping/freezing, and smooths jitter. Stays faithful when confident so it doesn't skew
  frequency. Validated on real trackOne: freq 6.09 vs 6.00Hz (preserved); occluded 18 frames -> bounded
  error 5.5px, not lost, recovered to 0.21px.

## 2026-08-12c — Tracker control + stabilization accuracy readout

### Added
- **Delete individual trackers**: right-click a marker while in placement mode to remove just that one.
- **Placement mode is now obvious**: the Add point button turns green and stays green while active;
  click again to exit.
- **Residual-motion accuracy readout**: live 'Raw X.X → Stab Y.Y px/f (↓Z%)' in the stabilizer status —
  green when stabilization is removing motion, red when it's adding jitter. Measured from tracked
  features frame-to-frame, raw vs stabilized. Validated.
- **Stabilizer smoothing slider (+ deadband)**: averages the stabilizing transform over recent frames
  to kill frame-to-frame jitter (applies to Auto + point stabilizers); deadband snaps to no-warp when
  motion is below the noise floor. Validated: jitter 1.96 → 0.41 px/f as smoothing 0 → 80.

## 2026-08-12b — Auto (feature-based) stabilizer

### Added
- **Auto stabilizer** (Stabilize tab): automatically detects dozens of Shi-Tomasi corners, LK-tracks
  them, and fits a similarity transform with **RANSAC** — steadies translation + rotation + zoom with
  nothing to place, and rejects moving objects as outliers (validated: 45/45 inliers found, 18/18
  moving outliers rejected, transform recovered to 0px). Green dots = trusted, grey = rejected/lost.
  Shares the Input/View mode + the same warp path as the point stabilizer. Third independent option
  alongside Region and Points.

## 2026-08-12 — Pre-stabilization (stabilize before amplify/analyze)

### Added / Changed
- Point stabilization now defaults to **pre-processing**: the input frame is warped by the stab
  transform *before* the magnifier, neural models, and analysis run on it — so everything works on
  steadier footage. Toggle **Input** (pre, default) / **View only** (cosmetic display warp, old).
- Frame-source routing: CPU/neural/analysis read the stabilized canvas; the WebGPU path reads it via
  a VideoFrame wrapper (importExternalTexture can't take a canvas). Falls back to raw video if a
  transform isn't ready. Uses last frame's transform (1-frame lag, negligible).
- Analysis point tracker gets **On stabilized / On raw** toggle: measure the target's own motion
  (shake removed) or absolute motion including camera shake.

## 2026-08-11e — Two independent point trackers

### Changed
- Analysis point tracking and Stabilize-to-points are now **fully separate** trackers with their own
  point sets — you never place a stabilization point with the analysis tool. Analysis points draw as
  circles (with Hz); stabilization points draw as squares and drive the warp. Stabilize tab got its
  own Add point / Clear.

## 2026-08-11d — Tracked-point stabilization

### Added
- **Stabilize view** (Track tab): fits a similarity transform (translation + rotation + scale) from
  your tracked points and warps the picture so they hold still — 1 point cancels shake, 2+ cancel
  rotation and zoom-wobble. Applied as a CSS transform to the view + marker overlay (moves together).
  Similarity fit (Umeyama) validated: recovers a known transform to 0.0000px residual.

## 2026-08-11c — Tracker validation + fixes

### Fixed / improved
- **Confidence metric fixed** — was inverted (noise inflated it; clean tracks flagged "lost").
  Now a contrast-normalized residual with a low-contrast gate. Validated on synthetic ground truth.
- Markers no longer mis-draw in **compare mode** (hidden there — single-video mapping doesn't apply).
- Each live marker now shows its **dominant frequency (Hz)** right on the video.

### Validated (objective, synthetic ground truth via the actual shipped functions)
- Position RMS **0.013 px** on a clean signal; ~0.3–0.7 px under light/moderate noise.
- Frequency accurate within one FFT bin across 2–15 Hz; robust even when position is noisy.
- Confidence now rises for clean tracks and falls with noise; low-contrast features read ~0.

## 2026-08-11b — Point tracking (Lucas-Kanade)

### Added
- **Point tracking** (new Track tab): drop up to 8 markers on the video; each is followed by a
  pyramidal inverse-compositional Lucas-Kanade tracker (sub-pixel). Shows a marker, a motion-trail,
  a velocity **direction arrow**, a per-point **dominant frequency**, and a **confidence** value
  (from LK residual + Shi-Tomasi min-eigenvalue texture). Reuses the existing FFT.
- First step of the tracking/stabilization foundation. Next: Kalman smoothing + phase-fusion +
  frequency-consensus audit, then feature-based (corners+RANSAC) stabilization.

## 2026-08-11 — Neural engine, offline processing, and UI restructure

### Added — Neural / AI magnification
- In-browser learned motion magnification via ONNX Runtime Web (WebGPU), no server.
- Four selectable models: **MagNet** (instant, any resolution), **STB-VMM 128 / 256**
  (Swin Transformer — sharper, less noise), and **theta-Net** (tiny 2025 model, native 1280).
- **Residual "Sharp" mode** — composites the AI's magnified motion onto the full-resolution
  frame so low-res models still look crisp (toggle: Sharp / Upscale).
- Reference-frame workflow with a "Set reference frame" control; Gain drives magnitude.

### Added — Offline processing
- **Process video** — choose a frame range and render the whole clip in any mode (including
  the slow neural modes) offline, then download a correctly-timed WebM to play back in real time.
- **theta-Net frame-packing (2x / 4x)** — packs multiple frames into one fixed-1280 inference
  for 2-4x batch throughput; degrades gracefully (native quality for <=640px sources).

### Changed — Performance & accuracy
- Live neural cost cut from ~2200 ms to ~500 ms (256 model); MagNet resolution cap raised so the
  Detail slider actually drives it.
- GPU acceleration is now **on by default** (auto-initializes when a source starts).

### Changed — UI
- **Tabbed control panel**: Capture / Settings / Process / Analysis / Stabilize / Smoothing.
- **Always-visible method/view rail** on the left with 2-letter labels (LI/PH/RI/AI/WA/IS, A/M)
  and instant tooltips.
- **YouTube-style video bar**: play button + full-width scrubber + time, anchored to the bottom
  of the video (works in compare mode).
- Source buttons now **toggle** (Live video / Share screen / Open file each flip to Stop).
- **Warp and Isolate promoted to full methods**; clearer colored panel headers, bigger labels,
  more spacing between panels.
- **Smart control visibility** — only settings that affect the current method are shown (e.g. the
  frequency band, denoise, color, scale, and velocity/acceleration are hidden under Neural; the
  Stabilize and Smoothing tabs hide for Neural since they don't apply).

### Notes
- Evaluated newer models (GeoMag 2026, diffusion approaches) for browser use and ruled them out —
  Mamba/State-Space and multi-step diffusion don't survive in-browser conversion. STB-VMM / theta-Net
  are the practical ceiling for now.
- Known: the neural path reads the raw frame and does not yet apply stabilization (possible future
  feature).
