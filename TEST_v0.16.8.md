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

# v0.16.9: defaults
- **Stochastic Splats** and **GPU Sort** now default to on. **Radix Sort** was already on by default.
- Checked on a new scene: stochastic, GPU sort, radix and unified are all True.
- A scene where these were set by hand keeps its values; files that never changed them pick up the new defaults.

## Correction (v0.16.10): there is no sorted-path ordering bug
v0.16.9 claimed that the sorted path is 26.9 dB off where trees overlap. That was wrong. There were two separate causes:
1. **The stochastic path drew more splats than the sorted path.** Every sorted path (CPU, bitonic, radix, unified) skips a splat whose **centre** lies outside 1.3x the view. The stochastic path did not. Fixed in v0.16.10.
2. **The merged-reference experiment disturbed the sorted draw.** Registering the extra (hidden) merged cloud changes the sorted multi-tree image in that run: 26 dB with it, 45.7 dB without. Not investigated further.

# v0.16.10: close-ups
- **Stochastic now uses the sorted paths' 1.3x centre cull.** In close-ups, that cull removes the giant near-camera splats, which sorted never drew. At 16 trees, close-up (1/4 distance):
  - points: 753M -> 235M per frame;
  - frame time: 16.5 -> 11.6 ms;
  - image vs sorted: 7 dB (a full-screen orange wash) -> 45 dB.
- **Off-screen point skipping ("thinning") is built in, always on, with no toggle.** It is exact: on vs off differs by 70 dB, while off vs off with other random seeds differs by 42 dB. Once the cull is in place it saves only about 1%, so a toggle would be clutter.

| Viewport, orbiting, whole frame | Sorted | Stochastic | Refined vs sorted |
|---|---|---|---|
| 1 tree, normal | 2.48 ms | 2.31 ms (1.07x) | 41.4 dB |
| 4 trees, normal | 5.52 ms | 4.50 ms (1.23x) | 45.7 dB |
| 16 trees, normal | 26.4 ms | 10.5 ms (2.52x) | 41.2 dB |
| 1 tree, close-up | 2.95 ms | 4.83 ms (0.61x) | 36.3 dB |
| 4 trees, close-up | 5.45 ms | 4.55 ms (1.20x) | 51.9 dB |
| 16 trees, close-up | 24.4 ms | 11.6 ms (2.10x) | 45.1 dB |

Still open: a single tree in close-up is slower than sorted. Its big on-screen splats need many points. The fix would be drawing large splats per pixel instead of as points.
