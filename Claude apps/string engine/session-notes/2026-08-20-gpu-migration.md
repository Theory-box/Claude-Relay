# GPU migration — status & findings

Goal: move the engine to the GPU. Agreed order: (2) instanced render -> (1) SoA -> (4) Morton -> (5) GPU physics. Skip (3) sleeping islands.

## ✅ DONE — GPU render (on MAIN, ff5d64e)
Instanced-capsule renderer, toggleable standard view ("GPU renderer (beta)", Render tab, default off).
All strands in ONE drawArraysInstanced call from a flat instance buffer. Over/under via depth buffer (real per-seg h).
Reuses microscope canvas overlay -> grab/cut/select still work. Standalone proto: instanced-strand-renderer.html.

## ✅ DONE — SoA foundation (branch feature/gpu, d51728c)
Node positions x/y/h/px/py/ph live in flat Float32Arrays NX,NY,NH,NPX,NPY,NPH, indexed the SAME as G.nodes
(NX[s.a] = node s.a's x) -> directly GPU-uploadable. Node objects keep metadata + index `i`; positions are
accessors on NodeProto. mkNode() replaces the 3 push sites; compactNodes() compacts arrays in lockstep;
integrate() converted to direct array access.
- VERIFIED: invariant NX[i]===G.nodes[i].x holds through 120 frames incl. compaction; no NaN; tabs/micro/
  gpu-render/depth/grab all work; zero errors.
- COST: ~10% CPU (getters on the still-unconverted hot loops constraints/collide/closest). RECOVERABLE by
  converting those to direct NX[s.a] access (closest() takes node OBJECTS -> needs an index-based rewrite +
  call-site changes in collide). That's the pending perf pass.

## ✅✅ GPU PHYSICS — VALIDATED ON REAL HARDWARE (user confirmed "works great")
Proto: protos/gpu-physics-poc.html. Texture-GPGPU cloth: pos+prev packed in ping-pong RGBA32F textures;
1 integrate (Verlet+gravity) + 12 Jacobi distance-constraint passes in fragment shaders, neighbours via
texelFetch; instanced links render straight from the position texture. **Positions never leave the GPU.**
5,400 nodes drape from 7 sparse top pins into catenary curves. Runs at full framerate on real GPU.

### ROOT-CAUSE of the long debug (IMPORTANT / landmine for integration)
The render did `gl.enable(gl.BLEND)` and never disabled it, so the NEXT frame's COMPUTE passes ran with
blending ON — each physics result got alpha-blended into the texture with the node's own coord as the blend
weight -> corrupts to NaN. **SwiftShader (sandbox software WebGL) IGNORES blend on float FBOs, so it worked
in software and exploded only on real GPUs.**  FIX: `gl.disable(gl.BLEND)` before every compute drawArrays.
Also added: velocity/position clamps + isnan/isinf guards in shaders (insurance); fixed camera framing the
full drape (a WORKING cloth hangs to ~y1000, below the old camera -> also looked blank); readback made
informational only (some GPUs can't readPixels RGBA32F).

### CORRECTION to earlier notes
The earlier claim "SwiftShader executes GPGPU arithmetic incorrectly" was a MISDIAGNOSIS caused by the blend
bug + messy tests. A clean rig (protos/gpu-iso.html style) showed SwiftShader runs the integrate+constraint
arithmetic EXACTLY right ([150,151] etc). => the sandbox IS a valid GPU-physics test bed **as long as blend
is disabled during compute passes.** Both software and real hardware now agree.

### Mechanism proven end-to-end (all working, both SW + real GPU):
float-texture storage, texelFetch neighbour reads, ping-pong, Verlet integrate, Jacobi distance constraints,
pinning, instanced render-from-position-texture with zero CPU readback.

## ▶ NEXT STEPS (ready to resume)
1. **Integrate GPU physics into the engine** on the SoA buffers, behind a toggle with CPU fallback.
   Design notes for the port (the engine is richer than the cloth POC):
   - Upload NX..NPH into a position texture each activation; run integrate + distance constraints on GPU.
   - Engine constraints are per-SEGMENT on ARBITRARY topology (not a regular grid). GPU can't scatter, so use
     PER-NODE GATHER: upload a neighbour-list texture from G.nbrs (each node's connected node indices + rest
     lengths). Each node reads its neighbours and applies distance corrections (Jacobi). This mirrors the
     cloth POC's per-node gather but with a neighbour-list texture instead of fixed offsets.
   - Stage it: GPU integrate + length/bend constraints first; keep collision/bonds/affinity/growth on CPU
     with a per-frame sync (readback -> NX..NPH -> objects) until they're ported too. Or render straight from
     the GPU texture (adapt the instanced GPU renderer to read the physics texture) to avoid readback.
   - **MUST disable blend during all compute passes** (see landmine above).
   - h/depth is the 3rd coord -> can pack pos.xyz+prev into 2 RGBA32F textures, or xy+h across channels.
2. **Recover SoA ~10%**: convert constraints/collide/closest to direct array access (index-based closest).
3. **Morton-order the collision grid** (folds into GPU physics).
4. Merge feature/gpu -> main only on explicit user permission.

## FILE MAP
- App (SoA build): "Claude apps/string engine/string-engine.html" (this branch).
- POC (validated): "Claude apps/string engine/protos/gpu-physics-poc.html".
- Outputs mirror: /mnt/user-data/outputs/{string-engine.html, gpu-physics-poc.html, instanced-strand-renderer.html}.

## ✅✅✅ WebGPU POC VALIDATED on real hardware (user: "works!", 100 fps)
Decision: engine goes WebGPU (compute/atomics needed for the real prize — collision, ~48-73% of frame).
Proto: protos/gpu-physics-webgpu-poc.html. 5,400-node cloth, all physics in WGSL compute:
- storage buffers pos (ping-pong A/B) + prev; Verlet integrate; 12 Jacobi length passes; render reads
  positions straight from the GPU buffer (draw(4,numEdges), endpoints via @builtin(instance_index)).
- **CSR adjacency, not grid offsets** — built from an EXPLICIT edge list (nodeRange[start,count] + edgeNbr +
  edgeRest). This is the arbitrary-topology solver the engine needs; cloth is just the test graph.
- Robust harness: navigator.gpu check, adapter/device, device.lost, validation error scope,
  getCompilationInfo() surfaced to on-screen red text.
Landmines hit & fixed (real-hardware only, parser didn't catch): **`meta` is a WGSL reserved keyword** ->
renamed `nmeta`. (Lesson: scan WGSL identifiers against the reserved list; wgsl_reflect parses but doesn't
enforce reserved words / full type checks.)
Tooling: wgsl_reflect (node ESM at node_modules/wgsl_reflect/wgsl_reflect.module.js) parses WGSL + reports
bind groups — good pre-flight, NOT a substitute for real-GPU compile. Sandbox has NO WebGPU (navigator.gpu
false) so the USER is the runtime test bed; every shipped file must self-surface compile errors.

### Approach for the engine integration (layer-by-layer, prove each before stacking)
Isolated `GpuPhysics` WebGPU subsystem behind its OWN experimental toggle (do NOT overload the GPU-renderer
toggle). CPU engine stays default + untouched + the fallback/reference. NO guarding of a shared flag against
the app's own handlers (that was ChatGPT's smell) — instead make the interaction/edit handlers GPU-aware.
Ownership: one authoritative copy. GPU mode uploads once from SoA (NX..NPH) + CSR from G.segs/G.nbrs; single
readback on disable/save/topology-edit. Stage order:
  1. GPU-resident core: integrate + length + degree-2 bend, pins, bounds, h/depth; render from GPU buffer.
     Route unsupported scenes/features (collision, affinity, bonding, tearing, draw/cut, topology edits)
     back to CPU for now.
  2. Interaction w/o per-frame readback: GPU grab (uniform), integer picking target for clicks.
  3. Collision: WGSL spatial-hash compute (atomics) — the real speedup.
  4. Chemistry/topology events as compact GPU event buffers; CPU keeps graph-mutation authority initially.
