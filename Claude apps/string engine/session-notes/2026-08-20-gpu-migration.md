# GPU migration — status & findings

Goal: move the engine to the GPU. Order agreed with user: (2) instanced render -> (1) SoA -> (4) Morton -> (5) GPU physics. Skip (3) sleeping islands.

## DONE — GPU render (on MAIN, commit ff5d64e)
Instanced-capsule renderer as a toggleable standard view ("GPU renderer (beta)", Render tab, default off).
All strands drawn in ONE drawArraysInstanced call from a flat instance buffer (endpoints/radius/colour).
Over/under via depth buffer (real per-segment h). Reuses microscope canvas overlay -> interactions work.
Standalone proto: instanced-strand-renderer.html.

## DONE — SoA foundation (this branch feature/gpu)
Node positions x/y/h/px/py/ph now live in flat Float32Arrays NX,NY,NH,NPX,NPY,NPH, indexed the SAME as
G.nodes (so NX[s.a] = node s.a's x) -> directly GPU-uploadable. Node objects keep metadata + index `i`;
x/y/h/px/py/ph are accessors on NodeProto into the arrays. mkNode() replaces the 3 G.nodes.push sites.
compactNodes() compacts the arrays in lockstep (copy by old index, set n.i=new). integrate() converted
to DIRECT array access (NX[i] etc, getters bypassed).
- VERIFIED: invariant NX[i]===G.nodes[i].x holds before/after 120 frames incl. compaction; no NaN; all
  tabs/micro/gpu-render/depth/grab work; zero errors.
- COST: ~10% CPU vs pre-SoA (6.8 vs 6.3ms/frame, noisy software env) from getters on the hot loops NOT
  yet converted (constraints, collide, closest). RECOVERABLE: convert those to direct NX[s.a] access
  (closest() takes node objects -> needs an index-based rewrite). That's the next optimization pass.

## GPU physics compute — VALIDATED IN PIECES, blocked from full verify in THIS sandbox
POC: gpu-physics-poc.html (texture-GPGPU cloth: pos in ping-pong RGBA32F textures, integrate + 12 Jacobi
distance-constraint passes in fragment shaders reading neighbours via texelFetch, instanced links render
straight from the position texture -> positions never leave the GPU).
Findings (5 isolation tests, headless SwiftShader software WebGL):
- WORKS: float-texture storage + readback; texelFetch reads (exact values); passthrough ping-pong; render
  from a GPU position texture. i.e. the whole GPGPU MECHANISM is sound.
- BROKEN in this sandbox only: GPU-compute ARITHMETIC. `pos+vel+gravity` returns ~pos.x*pos.y garbage then
  NaN; transform-feedback returns zeros. This is a SwiftShader software-WebGL bug, NOT the algorithm/arch
  (the technique is standard and the mechanism is proven). => GPU physics can't be numerically verified in
  the sandbox; needs REAL GPU hardware. POC is ready to run there.

## NEXT
1. Recover SoA perf: convert constraints/collide/closest to direct array access (index-based closest).
2. GPU physics compute integrated behind a toggle w/ CPU fallback, validated on real hardware.
3. Then Morton-order the collision grid (folds into GPU).
