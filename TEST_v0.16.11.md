# v0.16.11: screen-space effects, 6x faster (Claude Code)

Cavity World, Cavity Screen and Outline were slow on heavy scenes because of **where** the work was, not the effect maths:

1. **Cavity Screen** needed a view-normal buffer → the engine re-drew **every mesh again**, plus all splats (re-sorting them).
2. **Cavity Screen / Outline** needed an object-id buffer → another full re-draw of every mesh.

So a heavy scene drew its geometry 3x per frame. Both buffers are now written by the **main pass** as extra render targets (`shaders.AUX_CHUNK`), which is free of extra geometry work. Splats, which are not part of that pass, still draw their normals — but only splats, onto the same buffer.

Cavity World (AO) was a different problem: its whole sample kernel ran every frame. It now takes **8 samples per frame** and accumulates them in a history buffer that is **reprojected** with the camera, so moving frames stay smooth. When the view settles the history restarts and re-accumulates from that viewpoint, so the settled image is exactly what the old one-shot pass produced; once converged the pass **stops running entirely**. F12 still takes the full kernel in one shot.

## Measured (RTX 4090, 400 objects x 20k tris = 8.2M tris, 2033x1230, Supersampling 2, Quality 32)

Effects-only cost per frame while orbiting (GPU-synced, median; "effects off" = 0.30 ms is the final blit):

| Configuration | v0.16.10 | v0.16.11 | Faster |
|---|---|---|---|
| Cavity Screen | 3.80 ms | 0.20 ms | 19x |
| Cavity World | 1.80 ms | 0.71 ms | 2.5x |
| Both cavities | 5.67 ms | 0.83 ms | **6.8x** |
| Both + Outline | 5.57 ms | 0.92 ms | **6.1x** |

Whole viewport frame, both cavities: **11.23 ms -> 6.84 ms**. At Supersampling 1, Cavity Screen went from +3.52 ms to +0.22 ms per frame.

## Image: unchanged
Settled frames compared against v0.16.10, same scene and camera:

| Configuration | PSNR | Worst pixel | Pixels differing >2% |
|---|---|---|---|
| Effects off | identical | 0.000 | 0.00% |
| Cavity Screen | 106 dB | 0.002 | 0.00% |
| Cavity World | 85 dB | 0.033 | 0.00% |
| Both cavities | 84 dB | 0.031 | 0.00% |
| Both + Outline | 83 dB | 0.121 | 0.00% |

Two bugs were caught by that comparison and fixed: the aux normals were flipped toward the camera (the old pass did not), and the per-frame AO slices had to cover exactly the taps the old kernel averaged.

While the camera moves, AO now comes from 8 fresh samples blended with reprojected history instead of 32 fresh samples. History is rejected where the reprojected depth disagrees (disocclusions, moved objects), so those pixels fall back to this frame's samples.

Splats are unaffected: `auto_test_stochastic.py` gives identical numbers on v0.16.10 and v0.16.11.

Test: `apps/splat-viewer/auto_test_fx.py` (builds its own heavy scene; `VLR_OBJ`, `VLR_SUB`, `VLR_SS`, `VLR_AOQ`, `VLR_TAG`).

## Possible follow-up
Cavity World's remaining 0.71 ms is two full-resolution passes (AO history + apply), not sample count — dropping to 4 samples/frame changed nothing. Merging the apply into the AO pass would save roughly another 0.3 ms.
