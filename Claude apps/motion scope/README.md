# Motion Scope

Real-time motion magnification in the browser. Reads a webcam or a
DSLR-as-webcam feed and exaggerates subtle motion live, so small movements — a
swaying branch, a pulse, machine vibration, insect wingbeats — become visible.

Single self-contained HTML file. No build step, no dependencies.

## Requirements

- A modern browser with camera access (`getUserMedia`).
- Served over `https://` or opened as an artifact. `file://` blocks the camera
  in Chrome — use a local server (`python -m http.server`) if opening directly.
- A tripod. The method assumes a fixed camera; any shake is amplified too.

## Run

1. Open `motion_scope.html` in a browser (or as an artifact).
2. Pick a source, press **Start**, grant camera permission (retry once if the
   first attempt is blocked while the prompt is still up).

## Methods

- **Linear** (default) — amplifies per-pixel brightness change. Simple and
  responsive, but amplifies brightness noise along with the motion.
- **Phase (beta)** — a single-scale Riesz-pyramid method that amplifies local
  *displacement* rather than brightness, so brightness noise is largely left
  alone. Includes amplitude-weighted smoothing, which only shifts pixels sitting
  on real structure and ignores flat/noisy regions. Heavier than Linear; drop
  **Detail** if the frame rate falls. Single-scale, so it favours fine-detail
  motion — still experimental and may need tuning.

## Controls

| Control | Meaning |
| --- | --- |
| **Method** | Linear (brightness) or Phase (displacement, beta) |
| **Amplified / Motion only** | Overlay boosted motion on the image, or show just the motion field |
| **Amplification** | Gain applied to the motion signal |
| **Low / High cutoff** | Temporal band (Hz) that gets amplified — sway ≈ low, wingbeats ≈ high |
| **Temporal denoise** | Motion-adaptive recursive averaging on the feed *before* magnifying: de-noises static regions, passes moving ones through |
| **Spatial scale** | Amplifies a coarser pyramid level (block size 2^level). Higher = less fine noise, only larger motion |
| **Smoothing** | Fine spatial blur of the motion signal (also the amplitude-blur radius in Phase mode) |
| **Color** | Linear only: 0% drives motion from brightness (no colour speckle), 100% amplifies each RGB channel |
| **Detail** | Processing resolution. Lower = smoother, less noise, faster |
| **Reset baseline** | Re-seed the temporal filters after the scene settles |

## Noise handling

The three noise controls attack different sources:

- **Temporal denoise** is the biggest win for a tripod scene. It keeps a running
  per-pixel estimate of the "true" value and averages toward it where the pixel
  is still, but hands the raw value straight through where motion exceeds a
  threshold — so the static background de-noises without smearing the movers.
  The denoised frame feeds both the base image and the magnifier.
- **Spatial scale** amplifies coarse spatial detail, where signal-to-noise is
  higher; fine-grained sensor noise lives at the finest scale and is dropped.
- **Color** removes the coloured confetti in Linear mode by driving motion from
  luminance so channels move together.
- **Phase mode** is itself a noise strategy: amplifying displacement instead of
  brightness means brightness noise isn't amplified linearly.

Most remaining noise originates in the camera's live feed (lower-res, compressed,
reduced in-camera NR, high ISO in dim scenes). Lower ISO / more light beats any
in-app fix.

## Status

Linear + temporal denoise + spatial scale: working, syntax-checked.
Phase mode: beta, single-scale, needs live tuning.
