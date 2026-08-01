# Eye tracking — session notes

Branch: `feature/eye-tracking`

## Goal
Build webcam eye tracking that is dramatically smoother than existing open-source
tools (WebGazer et al.), which the user found jittery. Target: match/beat
GazeFollower-class results (sub-cm accuracy, sub-mm precision) with a temporal
model so it *feels* smooth. Not aiming for IR-hardware absolute accuracy.

## Key framing decided
- Split **accuracy** (offset from true gaze) vs **precision** (jitter). User's
  "shaggy/shaky" complaint is mostly precision — highly solvable. GazeFollower
  reports ~0.9 cm accuracy / 0.08 cm precision with personalized fine-tuning on a
  normal webcam, so the jitter is a pipeline gap, not a sensor floor.
- Smoothness should come from a **temporal / video-based model** (looks at a
  window of frames), not a dumb post-hoc smoother. User accepts 1–3 s latency,
  which unlocks **non-causal** (bidirectional / buffered) processing — a big lever.
- Hard ceiling that remains: **absolute anchoring** without IR glint. Mitigations
  in play: rich per-user calibration, screen-as-glint geometry (esp. dark-room
  bright-screen calibration pass), multi-frame fusion.
- Cross-field techniques to draw on: astronomy lucky-imaging / drizzle
  (multi-frame super-res), Digital Image Correlation (sub-pixel displacement),
  Kalman/particle sensor fusion.

## Data capture — the friction problem, solved
- Artifacts + downloaded `file://` pages can't use the webcam (getUserMedia needs
  a **secure context**: https or localhost). Prior native Go wrapper served on
  127.0.0.1 to dodge this (see eye-tracking/README.md) but it's a pain.
- Solution: **hosted capture tool on GitHub Pages** (https = secure context).
  - Source: `eye-tracking/capture.html` (this branch)
  - Deployed: `gh-pages` branch root as `index.html`
  - Live URL: https://theory-box.github.io/Claude-Relay/
  - Pages source config: gh-pages / root
- Tool: one guided ~80s session, spoken + on-screen prompts, in-browser MediaPipe
  FaceLandmarker extracts landmarks so the primary output is a small JSON
  (optional raw video toggle). Phases: fixation, head_rotation, distance,
  camera_pan, pursuit, glint_dark.

## TODO / next
- [ ] User runs a session, uploads `session_*.json` (+ optional `.webm`).
- [ ] Build analysis pipeline against public data (GazeCapture, MPIIGaze) in
      parallel so it's ready for the upload. First measurement: fixation jitter
      floor for the user's specific camera (settles "is the data in the video").
- [ ] **TEARDOWN when done:** user asked to remove the hosted tool afterward.
      Disable Pages (or delete `gh-pages` branch) once capture is finished.

## Session 1 capture — analysis (session_2026-08-01)
Camera 1280x720@30fps, all 6 phases, MediaPipe landmarks present. User held laptop
throughout (not a problem — see below) and glanced away once (didn't register).

Findings:
- **Gaze signal is clearly present.** Uncalibrated corner-normalized iris-x vs target
  during pursuit: r=0.957 horizontal, r=-0.924 vertical. >90% of gaze variance in a
  single raw landmark, no model. "Is the data there" = settled yes.
- **Noise floor low AND smooth.** Fixation jitter ~0.34px iris travel, lag-1
  autocorr 0.99 (MediaPipe pre-smooths). The "shaky" in WebGazer-class tools is white
  per-frame noise those tools have and MediaPipe largely doesn't.
- **Correction to earlier plan:** temporal averaging is NOT the smoothness lever here.
  Residual is drift, not white noise → 1s averaging bought only 1.2x. Head-pose
  compensation (via M matrix) explained only 27% of fixation drift (another 1.2x).
  Remaining wobble is mostly genuine fixational eye motion + detector drift.
- **Holding the laptop was fine:** corner-normalization cut camera_pan motion from
  240px raw to ~4.5px residual (~50x). Those phases are useful head-invariance data.
- Per-frame precision maps to ~1 deg (eye's image-plane travel is only ~7px full range).

Next levers (not filtering): (1) trained *personalized* mapping model over full
landmark+headpose features — the r=0.95 proxy is crude, a model beats it; (2) raw-pixel
sub-pixel iris estimation to probe below MediaPipe's 0.34px floor — REQUIRES video, so
next capture flip "save raw video" ON for fixation+pursuit.

## Stepped capture tool (v2) — thorough data collection
Replaced the auto-run tool with a stepped, per-block version (same URL).
- Per-block "Ready" gating: setup screen per block with live **light meter** (mean
  luminance, intent-aware: bright vs dark blocks) + **face/eyes tracked** lamp;
  Ready enabled only when green, with "record anyway" override + "skip"/"redo".
- Per-block HQ clips at **24 Mbps** (RAR to upload). One combined session JSON with
  landmarks tagged by block id. Filenames NN_blockid_stamp.webm for ordered RAR.
- 12 blocks: fixation_table, fixation_handheld, pursuit, saccades, head_rotation,
  distance, camera_move (slide+tilt+rotate), fixation_bright, fixation_dark,
  color_flash (screen cycles FLASH colors as active illumination; logged per frame),
  eye_extremes (labeled:false — appearance data, gaze != target), eyelid_sweep.
- Design intent: isolate ONE factor per block (light XOR motion XOR color) so labels
  stay clean. Hold vs table specified per block (hold default; table for still baselines).
- Teardown reminder still stands: disable Pages / delete gh-pages when capture done.

## Session 2 capture — analysis (session_2026-08-01T04-17-10, 12 blocks + HQ video)
Data quality: face tracked ~95-100% of frames (head_rotation 90%, color_flash 85% —
expected). Framing horizontally centered (eyeX~0.50) but eyes rode LOW vertically
(eyeY 0.55-0.71, worst on dark block). Usable; add an eyes-in-upper-third framing guide
to the tool for next time. color_flash logged all 7 illumination colors per frame.

### Sub-pixel test (the point of capturing pixels) — partly disconfirms the hope
Ran MediaPipe tasks FaceLandmarker on fixation_table video + a dark-weighted centroid
sub-pixel refinement, still-head clip.
- Corner-normalized eye jitter (head motion removed): u=0.26px, v=0.16px of iris travel;
  **85% is slow drift (real fixational eye motion + residual sway), only ~0.04px is
  white noise.** MediaPipe is already white-noise-free (heavy temporal filtering).
- Naive pixel-centroid matches MediaPipe (traj r=0.994) but does NOT beat it — slightly
  noisier. So there is no big pool of easy sub-pixel detail MediaPipe is discarding for
  iris-CENTER localization. Front-end is already near the floor.
- Caveat keeping the intuition partly alive: MP's filtering could smooth away real fast
  microsaccades (temporal-resolution question, niche for a cursor). Motion-magnification /
  multi-frame super-res would need a fancier method AND wouldn't move the accuracy ceiling
  much, since center noise is already ~0.04px.

### Conclusion / redirect
Bottleneck is NOT sub-pixel detection — it's the MAPPING (clean iris+head signal → screen
coord across pose/distance/light). That's what personalization + calibration fix, and we
now have labeled data across all those conditions. NEXT: build the personalized mapping
model (features: iris + eye-corner + head cues; labels: pursuit/saccade/fixation targets;
test head-invariance using the head/distance/pan blocks; measure deg accuracy).
Tooling now in sandbox: mediapipe tasks API + face_landmarker.task (downloaded).
