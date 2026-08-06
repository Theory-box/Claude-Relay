# Motion Scope

Real-time **Eulerian Video Magnification** (motion magnification) in the browser.
Reads a webcam or a DSLR-as-webcam feed and exaggerates subtle motion live, so
small movements — a swaying branch, a pulse, machine vibration, insect wingbeats
— become visible to the eye.

Single self-contained HTML file. No build step, no dependencies.

## Requirements

- A modern browser with camera access (`getUserMedia`).
- Served over `https://` or opened as an artifact. `file://` blocks the camera
  in Chrome — use a local server (`python -m http.server`) if opening the file
  directly, or run it as a Claude artifact.
- A tripod. The method assumes a fixed camera; any shake is amplified as much as
  the subject.

## Install / Run

1. Open `motion_scope.html` in a browser (or as an artifact).
2. Pick a source from the **Source** dropdown and press **Start**.
3. Grant camera permission. If the first attempt is blocked, press **Start**
   again once the permission is granted.

## How it works

Per pixel, the app keeps two exponential temporal filters — a slow one and a
fast one — and amplifies the difference between them. That difference is a
**temporal bandpass**: only motion whose rhythm falls between the two cutoff
frequencies gets boosted, everything else is left alone. This is the linear
(amplitude-based) Eulerian approach: no motion tracking, just per-pixel temporal
filtering and gain, recombined with the original frame.

Filter coefficients are derived live from the cutoff sliders and the measured
frame rate: `alpha = 1 - exp(-2*pi*fc/fps)`.

## Controls

| Control | Meaning |
| --- | --- |
| **Amplified / Motion only** | Overlay boosted motion on the real image, or show just the motion field on grey |
| **Amplification** | Gain applied to the bandpassed signal (1–80×) |
| **Low cutoff** | Lower edge of the motion band, in Hz (slow sway ≈ low) |
| **High cutoff** | Upper edge of the motion band, in Hz (wingbeats / vibration ≈ high) |
| **Color** | 0% drives motion from brightness only (removes coloured speckle); 100% amplifies each RGB channel independently (full-colour, noisier) |
| **Smoothing** | Spatial blur radius applied to the amplified motion only. 0 = off. Higher cuts grain, softens fine motion detail |
| **Detail** | Processing resolution. Lower = smoother, less noise, faster |
| **Reset baseline** | Re-seed the temporal filters after the scene or camera settles |

## Noise handling

Two controls target the two kinds of amplified noise:

- **Coloured speckle (confetti)** comes from amplifying each RGB channel
  independently — the per-channel sensor noise mismatches become random hue
  shifts. **Color** blends the motion signal toward luminance, so channels move
  together and the colour speckle disappears, leaving only grey grain.
- **Grey grain** is spatially random, while real motion is spatially coherent.
  **Smoothing** blurs only the amplified motion signal (not the base frame), so
  the noise averages toward zero while the moving edges survive, and the static
  background stays sharp.

Most of the remaining noise originates in the camera's live feed, which is
lower-resolution and less denoised than its recorded video. Better light (lower
ISO) and a cleaner capture path reduce it at the source, upstream of anything the
app does.

## Behaviour notes

- Whole-frame motion (wind moving a plant, camera shake) amplifies too — that is
  correct behaviour, not a bug. A tripod isolates the subject.
- Slow global light changes (clouds) can flicker; the bandpass rejects most
  drift below the low cutoff.
- Very small / distant subjects can sit below the noise floor at low detail —
  raise **Detail** if the frame rate allows.
- Camera device labels only populate after the first permission grant.

## Tuning starting points

- **Branch sway / breathing:** low 0.2 Hz, high 2 Hz, gain 15–25.
- **Wingbeats / fast vibration:** low 3 Hz, high 12 Hz, gain 20–40.

## Status

Working. Confirmed live camera access inside the Claude artifact sandbox (first
`getUserMedia` call may need a retry after the permission prompt).
