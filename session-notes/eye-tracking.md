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
