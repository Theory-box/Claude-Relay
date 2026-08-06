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

## Noise reduction pass (added)

User reported heavy noise, especially coloured confetti, on an a6500 in remote/
webcam mode. Diagnosis: most noise is real and enters via the camera's live feed
(downscaled, compressed, reduced in-camera NR, likely high ISO in a shaded
scene). Our linear/intensity EVM then amplifies in-band temporal noise with the
same gain as signal — expected, not a bug.

Two standard, low-risk controls added (both slider-controlled, non-destructive):

- **Color (chroma) slider, default 20%.** Motion signal blended toward luma
  (`0.299R+0.587G+0.114B`); at 0% all channels share one brightness-driven motion
  term, so no hue shifts → coloured confetti gone. 100% = old per-channel
  behaviour. Kept 3-channel filter state so full-colour is still available.
- **Smoothing (spatial denoise) slider, default 1 px.** Separable edge-clamped
  box blur applied to the amplified-motion buffer only, before recombining, so
  the static base image stays sharp. Radius 0–4.

Implementation: processFrame refactored into three passes (bandpass→mBuf,
optional blur, recombine). Added mBuf/mTmp Float32 buffers in allocBuffers.
Energy meter now computed on luma. JS syntax-checked clean.

Deliberately did NOT add heavier edge-preserving denoise (bilateral/NLM) — user
wants nothing that looks artificial, and these two cover the reported symptoms.

## Open interaction to remember

Lifting the processing-resolution cap will *increase* noise as things stand,
because downscaling is currently an implicit denoiser. Add/relies-on spatial
smoothing first, then raising resolution is safer. Camera→Mac output resolution
is being handled in a separate conversation.

## Possible next steps

- Optional spatial blur / pyramid level to cut amplified sensor noise further.
- Frequency presets (buttons) for sway / wingbeat / vibration.
- Record or snapshot the amplified output.
- Region-of-interest mask so only a selected patch is amplified (isolate one
  branch or one insect, ignore background wind).
