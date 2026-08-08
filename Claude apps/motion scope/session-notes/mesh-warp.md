# Mesh warp (branch feature/mesh-warp)

GPU warp remap (WGSL_WR) now blends per-pixel flow with a coarse-grid (mesh)
interpolation of the same flow. Grid centers spaced meshCell px; flow sampled at
the 4 surrounding centers, bilinear-interpolated -> coherent rubber-sheet flow;
du = mix(perPixel, mesh, meshAmt). _UW +meshAmt,meshCell (17 f32, uwBuf 80).
Controls (Warp field): "Mesh warp" 0-100% (meshAmt), "Mesh grid size" 16-96px
(meshCell). Default meshAmt=0 == current warp (safe). GPU-only.
Note: grid centers point-sample the already-smoothed flow (post FSH/FSV), so it's
coherent. If blocky at large cells, could add bicubic or cell-averaging later.
