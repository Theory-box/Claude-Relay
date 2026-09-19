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

## Found while re-testing: the sorted path is off where trees overlap
With 4 trees overlapping in view, I built an exact reference: all 4 copies merged into one cloud and drawn with a single sort (correct by construction). Results against that reference:
- Stochastic, drawing the 4 trees as separate instances: 36.2 dB. That equals stochastic vs sorted when both draw the merged cloud, i.e. the normal gap between the two methods.
- Sorted, with Unified Sort across the 4 instances: 26.9 dB. Unified Sort off was also about 30 dB vs stochastic.

Each tree on its own matches at 39–44 dB. So the older sorted multi-instance path has an ordering error where trees overlap, and stochastic does not. The sorted path is not fixed here (stochastic is now the default).
