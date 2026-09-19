# v0.16.8: Stochastic Splats (Claude Code)

New toggle **Render > Splats > Display > Stochastic Splats** (off by default). Each splat is drawn as random pixel-sized points instead of being sorted and blended (the method from JorisAR/gaussian-point-splatting). The tooltip explains the trade-off.

## How it renders
- New module: `splat_stochastic.py`.
- Every point is depth-tested exactly in two passes, and each point is also tested against the mesh depth. A pixel shows only the nearest point.
- While the view is still, the image refines over 32 frames. It restarts on any view change or scene change.
- It uses the addon's exact splat footprint, lighting and backface rule.
- It runs in the viewport only. F12 still uses the sorted path.
- Any failure falls back to the sorted path.

## Tested (RTX 4090, 2033x1230 viewport, `apps/splat-viewer/auto_test_stochastic.py`)

| Scene | Whole viewport frame, orbiting: sorted | Stochastic | Image vs sorted (1 frame / refined) |
|---|---|---|---|
| 1 tree, 1M splats | 2.43 ms | 2.26 ms (1.07x) | 37.9 / 41.4 dB |
| 16 trees, 16M splats | 24.3 ms | 9.9 ms (2.46x) | 34.5 / 41.2 dB |

- The stochastic path ran with no fallback and reached 32/32 refinement frames.
- A mesh cube in front of the trees hides them exactly as in the sorted render.
- Backface Cull runs correctly together with stochastic.

Splats-only timings: 4.2–4.8x at 16M and 6x at 32M. These come from `proto_stochastic.py`; the viewport numbers above also include drawing meshes and effects.

## Known limits
- Grain while the camera moves.
- Stochastic splats do not write depth for AO, and they don't feed cavity normals (cavity still draws sorted normals).
- F12 is unchanged.
- Very close-up views, where splats cover most of the screen, gain less (about 3.5x at 32M).
