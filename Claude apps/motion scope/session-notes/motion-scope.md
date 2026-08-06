# Session notes — Motion Scope

**Branch:** `main` (user granted direct-to-main for the initial drop)
**Folder:** `Claude apps/motion scope/`

## Goal

Real-time Eulerian Video Magnification the user can run against a DSLR-as-webcam
feed, to sit on a back porch and watch amplified motion of trees, birds, and
insects. Curiosity / play project.

## Decisions made

- **Algorithm: linear (amplitude-based) Eulerian, two-EMA temporal bandpass.**
  Per pixel, two exponential lowpass filters (slow + fast); amplified output is
  `x + gain*(fast - slow)`. Chosen over a full complex-steerable-pyramid
  phase-based EVM because it runs comfortably at frame rate in plain JS and
  matches the user's mental model (offset frames, overlay, amplify). No spatial
  pyramid — downscaling provides the spatial smoothing / noise reduction instead.
- **Cutoffs exposed as Hz**, converted to IIR alpha per frame from live fps:
  `alpha = 1 - exp(-2*pi*fc/fps)`. Lets the user tune to motion frequency
  (sway vs wingbeat) rather than abstract smoothing constants.
- **Processing at reduced resolution** (192–640p, default 384p) into Float32
  state buffers, upscaled to the display canvas. Keeps it real-time and doubles
  as denoise.
- **Two views:** Amplified (boost over real image) and Motion-only
  (`128 + gain*band` on grey).
- **Delivery: single self-contained HTML**, both as a Claude artifact and as a
  repo file. Standalone `file://` won't get camera in Chrome — documented the
  https / local-server requirement in the README.

## Open questions (unanswered by user)

- Shooting distance / focal length for the tree setup — affects how much detail
  vs smoothing to default to.
- Priority: slow sway vs fast wingbeat/vibration — would change default cutoffs.
  Current ship default: low 0.5 Hz, high 6 Hz, gain 18.

## Verified

- **Camera works inside the Claude artifact sandbox.** Earlier concern (~60%)
  that the sandbox iframe might block `getUserMedia` did not hold — user
  confirmed live use. First call may need one retry after the permission prompt.

## Possible next steps

- Optional spatial blur / pyramid level to cut amplified sensor noise further.
- Frequency presets (buttons) for sway / wingbeat / vibration.
- Record or snapshot the amplified output.
- Region-of-interest mask so only a selected patch is amplified (isolate one
  branch or one insect, ignore background wind).
