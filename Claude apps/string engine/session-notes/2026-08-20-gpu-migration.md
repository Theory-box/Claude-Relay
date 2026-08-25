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

## ✅ LAYER 1 SHIPPED + user-confirmed working ("seems to work", green badge, no errors)
WebGPU physics integrated into the engine as an isolated `GpuPhysics` subsystem (3rd <script> block,
same cross-script-globals pattern the WebGL glM module already uses). CPU engine byte-identical + default.
- Toggle: Sim tab → "GPU physics (experimental)". Own canvas #cwgpu (CSS bg = .screen gradient so it
  covers the stale 2D #c). Green "● GPU PHYSICS" badge.
- WGSL (validated parse + reserved-clean, bindings 5/7/4): INTEGRATE = engine-accurate (Verlet + temp
  jitter via GPU hash rnd() + per-object damping + energy-aware fr + depth slab, **NO gravity**);
  CONSTRAIN = mass-weighted Jacobi length over CSR; REN = per-segment coloured capsules.
- Data: buildScene() packs pos/prev/meta(invMass,objDamp,solid) from NX..NPH + G.nodes; CSR from G.segs
  (skip dead/bond); render seg+style(rgb+radius) buffers. Ownership: single authoritative copy; one
  readback (mapAsync) on toggle-off/edit; discard (no readback) on clearGraph/resetSim.
- Frame hooks gate on S.gpuPhysics (sim + render). stepFrame hook. Interaction routing: while active,
  move=pan-only, edit tools=DropToCPU(readback). GP_PASSES=8, GP_RELAX=0.6.
- Fixed: cwgpu transparent-bg showed stale 2D through → gave #cwgpu the .screen gradient CSS bg.

## ✅ DEV TAB + telemetry (Claude debug tooling) — user asked for a log they export for me
New always-visible "Dev" vertical tab. Live readout (solver CPU/GPU, nodes/segs, fps, pos span x×y,
y range, NaN count). "Export log for Claude" → downloads JSON: build tag, adapter info, config
(temp/damp/depth/speed/quality/GP_PASSES/GP_RELAX), view, scene counts, gpuPhysicsDiagnostics(),
last WGSL messages, cpuStatsNow, gpuStatsLast, and 240× 1Hz telemetry samples (rolling ~4min:
fps, pos min/max/span, NaN). GPU stats via a cheap 1/sec async readback (guarded by telemBusy).
BUILD tag bumped per build so I know which version's log I'm reading. Export = .json file (user uploads).

## KNOWN LAYER-1 LIMITS (by design, not bugs)
No collision (layer 3, the prize). No bend/curl (length only). Editing paused while on (toggle off to
edit). Simpler render (no depth over/under sort, heat, selection, microscope). Jacobi≠Gauss-Seidel so
motion is statistically similar not identical.

## NEXT
1. Read first dev-log export → confirm positions stable (spans steady, NaN=0) on user HW.
2. Bend/curl constraints (degree-2) in WGSL.
3. Collision = WGSL spatial-hash compute w/ atomics (the real speedup). Consider asking ChatGPT (via user
   relay) to (a) check if its env has WebGPU or can install naga-cli for pre-flight WGSL validation, and
   (b) research fastest WebGPU spatial-hash-with-atomics for ~10k particles. Keep integration single-author.

## ✅ FIRST HARDWARE DIAGNOSTIC (Dev-tab one-press export) — layer 1 VALIDATED on real GPU
HW: NVIDIA Lovelace (RTX 40-series), Chrome 151, Win64. Shaders compile clean (0 WGSL errors).
Limits worth noting for collision design: maxStorageBuffersPerShaderStage=8, maxBindGroups=4,
maxComputeWorkgroupSizeX=256, maxStorageBufferBindingSize=128MB, maxBufferSize=256MB.
Scene: 2483 nodes / 1961 segs / 3922 directed. 120-step GPU run vs 120-step CPU (integrate+constraints)
from identical state:
- CORRECTNESS ✅: GPU NaN=0, edgeError mean 0.042 / max 0.25 / p95 0.138 — TIGHTER than CPU
  (mean 0.045 / max 0.56). edgeErrRatio 0.93. spanRatioX 0.99. Trajectory spans stable 1197→1202→1193,
  no explosion/drift/collapse. gpuStable=true, pinsHeld=true. => integrate (temp+damp+depth slab, no
  gravity) + mass-weighted Jacobi length constraints are numerically correct on real hardware.
- PERF ⚠️ (honest no): GPU 0.923 ms/step vs CPU 0.478 ms/step => speedup 0.52× (GPU ~2x SLOWER).
  Cause: 2.5k nodes is tiny => overhead-bound (9 compute passes/step, fixed per-pass cost dominates
  trivial compute). Also diagnostic stalls GPU 5x for trajectory readbacks (inflates GPU ms somewhat).
  CONCLUSION: GPU physics does NOT win on cheap physics at small scale. Payoff is entirely (a) COLLISION
  (48-73% of CPU frame; the reason we picked WebGPU) and (b) SCALE (10k-100k nodes). Bend would add
  fidelity but not change perf. => go to collision next.
Log saved: diag-logs/2026-08-21_layer1_first-hardware-run.json
Minor polish TODO: buildLog webgpu.adapter serializes {} (raw GPUAdapterInfo getters non-enumerable) —
use adapterCaps() extraction there too. Diagnostic perf: add a clean run (no checkpoint stalls) + a
scaling sweep (clone scene x2/x4/x8… time GPU vs CPU) to find the crossover node-count.

## NEXT (revised priority from data)
1. Diagnostic v2: clean perf timing + scaling sweep (find GPU>CPU crossover) — small, informs scale push.
2. COLLISION on GPU = WGSL spatial-hash compute w/ atomics (uniform grid; build cell counts via
   atomicAdd, prefix-sum offsets, scatter node indices, then per-node gather neighbours in 3x3 cells,
   push apart on overlap). The real prize. Good candidate for ChatGPT research relay (fastest WebGPU
   spatial-hash-with-atomics for ~10k-100k particles; single-author the integration).
3. (optional) bend/curl constraints for fidelity.

## ✅ naga in the loop + warm-run perf correction + collision design locked
### Tooling win: naga-wasi-cli installed (npm/WASI, no Rust) — REAL semantic WGSL validator now local.
Run: node tools/naga_validate.mjs <string-engine.html> /home/claude/.wgsl-tools/node_modules/.bin/naga
Catches reserved words + type/validation errors wgsl_reflect misses (the `meta` class). v2 shaders
(bounds fix + extended 48B Params) PASS naga: WGSL_INT(36) WGSL_CON(27) WGSL_REN(23). New loop:
wgsl_reflect (bindings) → naga (semantic) → user GPU (runtime).
### Perf CORRECTION (warm run): earlier 0.52x "GPU slower" was COLD-START contamination.
Warm run (GPU physics active, canvas full-size, warmed pipelines): speedup 1.51× (GPU FASTER) at the
same 2483 nodes — GPU 0.288 ms/step vs CPU 0.434. NaN=0, edgeErr 0.043≈CPU 0.042, spans stable. So GPU
is already ahead at 2.5k when warm; cold first-use + snapshot-stalls inflated the first measurement.
(v2 scaling-sweep build still unrun by user; not blocking collision.)
### v2 shipped: bounds fix (integrate clamps x/y to [pad,W-pad], matches CPU) + diagnostic v2
(scaling sweep x1..x16 clean-timed via onSubmittedWorkDone + crossover; adapter-info extraction).

## COLLISION ENGINE MODEL (from CPU collide()) — SEGMENT-based, not particle
Broad: each SEGMENT inserted into ALL grid cells its AABB (expanded by reach=maxR+maxPad) overlaps;
cell=2*reach. Pair list deduped + filtered (excl set = same-strand-too-close, shared node, bonds,
self-pass-through when obj.selfSolid=false). Narrow: S.iters passes; closest(a0,a1,b0,b1,use3) =
segment-segment closest point (params s,t); if dist<tgt(=rA+rB+pad) push apart, distribute to 4
endpoint nodes weighted by (1-s),s,(1-t),t and inverse mass; optional XPBD velocity cancel (S.xpbd).
3D uses h when depth>0 & neither solid.

## COLLISION GPU DESIGN (research-informed, segment-adapted) — layer 3
Research (ChatGPT handoff, archived research/webgpu-collision-handoff/): count→exclusive-scan→scatter
uniform grid + per-particle Jacobi 3x3 gather; Jacobi gather writes only self => NO float atomics
(atomics only integer, in count/scatter). 8 storage buffers/stage => split grid-build vs gather
pipelines. Segment caveat: bin by AABB into every overlapped cell (not midpoint).
ADAPTATION for our segment model: parallelize narrow phase PER-NODE (not per-pair) — each node gathers
segments near its incident segments, recomputes each pair's closest deterministically, takes only its
OWN share (by barycentric weight+mass), writes only itself. Adjacent segments share nodes, so per-node
Jacobi avoids the shared-node write race WITHOUT atomics (pairs evaluated ~4x — the WebGPU-preferred
trade). Need node→incident-segment CSR (build from G.segs). Prototype grid = fixed-capacity atomic bins
(+overflow counter) to skip the scan first; upgrade to count/scan/scatter if occupancy overflows.
Plan: 3a grid POC (segment AABB → fixed-cap bins, validate occupancy/overflow on real HW) → 3b per-node
gather (closest() WGSL + own-share accumulate) → 3c integrate after constraints in step().

## ✅ COLLISION BROAD + NARROW PHASE validated in isolation (protos)
### Broad phase (protos/gpu-spatial-grid-poc.html): GPU spatial grid, atomic bins, multi-cell segment
AABB insertion. Validated EXACT per-cell vs CPU (5074 cells, insertions+overflow+maxOcc all match), 1ms
for 16.7k segs. Fix: f32-mirror CPU ref + 1.5px conservativeness MARGIN (f32 rounding must never drop a
boundary cell = anti-tunneling). naga-valid.
### Narrow phase (protos/gpu-narrow-phase-poc.html): closest()+push-apart ported to WGSL (Ericson
ClosestPtSegmentSegment), naga-valid. Fixes from research: relative parallel threshold den<=1e-6*a*e
(absolute 1e-9 was dimensionally wrong — length^4; caused a 14.9px phantom push on near-parallel long
segments) + per-pair penetration clamp min(pen,0.25*tgt).
### KEY diagnosis (sandbox diverge.mjs): f32-mirror vs f64 closest DIST = 0.00px divergence over 200k
adversarial pairs => distance/detection is CORRECT. The residual per-endpoint displacement divergence
(~3.3px on ~18% of ADVERSARIAL long-segment pairs) is BARYCENTRIC-SPLIT AMBIGUITY on near-parallel
contacts (WGSL FMA picks a different s than f64; both valid closest points along the parallel overlap).
NET push per segment is s-INVARIANT (dA0+dA1 = u*cA regardless of s) => segments still separate
correctly in the right direction by the right amount; only rotational split between a segment's 2
endpoints differs, which averages out. POC now reports NET-push error (physical, ~0) as the pass metric.
Research (segment-narrowphase-findings.md) confirms: validate physical invariants + f32 tolerance, NOT
bit-parity; parallel contact-point choice is a known refinable ambiguity (midpoint-of-overlap = future).
Real strand segments are SHORT (~12px) => far fewer ill-conditioned pairs than this adversarial test.

## LAYER 3c DESIGN (from segment-jacobi-filters-grid-findings.md)
- Per-node kernel == pair-once Jacobi (algebraically identical when (node,pair) incidence is unique &
  frozen X). NOT equal to sequential CPU (Gauss-Seidel) — validate vs a Jacobi oracle, f32 tolerance.
- Two incident segments of one node both hitting partner B = TWO DISTINCT constraints (include both).
- Shared-endpoint pairs REJECTED (as CPU). Dedup multi-cell duplicates by canonical pair id.
- Exclusions: upload topological excl as sorted CSR (strand-index rule can't capture graph-distance excl
  in general). Filter pairs ONCE before node->pair adjacency.
- Grid reuse across K Jacobi iters with Verlet skin: inflate seg AABB by max endpoint displacement d.
- Accumulation: per-pair pen clamp -> sum slot deltas -> divide by active-contact-count -> omega(SOR,
  start 1.0) -> final per-node magnitude clamp -> write frozenPos+delta.
- Planned impl: per-node gather with a small local "seen" list to dedup candidates (self-contained, no
  separate pair-list pass); accept ~4x pair re-eval (WebGPU-preferred trade). POC vs CPU collide() before
  wiring live. naga every shader.

## ✅✅ LAYER 3c COLLISION GATHER VALIDATED (protos/gpu-collision-gather-poc.html)
Full assembled GPU collision pipeline vs faithful CPU JACOBI mirror: 832 nodes, 800 segs, 32 strands,
bin overflow 0, nodes pushed GPU 576 = CPU 576, max per-node displacement error 1.056e-4 px (f32 noise).
Deep dense overlaps (maxDisp hit the 6px clamp) matched too — the deterministic fallback normal for
dist<0.25 neutralized the n/dist sensitivity that made the isolated narrow POC diverge. All 3 GPU-collision
primitives now proven: broad (grid), narrow (closest+push), integrated gather (home-cell dedup + filters +
exclusion + accumulate/average/omega/clamp). Shader: /home/claude/collide_shader.mjs (COLLIDE).
Buffer layout: pos vec4(xyz+invMass), posOut, nodeRange vec2u(start,count), nodeList u32(seg ids),
segI vec4u(a,b,strand,packed=bond|solid<<1|selfSolid<<2|obj<<3), segF vec4f(effR,pad,along,skipK),
segCell vec4u(xMin,xMax,yMin,yMax), cellBins u32(cap ids, 0xffffffff sentinel), U uniform(48B).

## FINAL DESIGN REVIEW (layer3c-final-design-review.md) — 4 integration decisions:
1. Ring exclusion needs CIRCULAR along-distance (abs is chains-only) -> gate strand rule on topology class.
2. Pinned nodes: discarding their slot under-applies pair response; I DISCARD to match CPU restore (parity).
3. Fallback normal needs 2D vs 3D branch + canonical-ID sign fallback (POC was 2D/depth=0; add 3D for use3).
4. Verlet skin must cover ALL position changes in reuse window -> rebuild grid AFTER constraints, just
   before the K collision iters, so skin spans only collision displacement.

## GPU GRID-REBUILD PIPELINE built + naga-valid (for integration): grid_shaders.mjs
- CLEARGRID: per cell, zero cellCount + fill cellBins with 0xffffffff sentinel.
- GRIDBUILD: per seg, compute+store clamped segCell bounds (AABB+reach, reach incl anti-tunnel margin),
  atomicAdd slot into cellCount, write id to cellBins, atomicAdd overflow if >cap.
- Per substep: clearGrid -> gridBuild -> collide xK (ping-pong pos). overflow[0]!=0 = hard fail (dev-log).

## NEXT: wire into engine (GpuPhysics): buildScene() adds node->seg CSR (nodeRange,nodeList) + segI/segF
(static per topology) + allocate segCell/cellBins/cellCount/overflow; step runs clear->build->collide xK
after constraints; grid params from wall-box bounds + reach=maxEffR+maxPad(+margin); behind gpuPhysics
toggle; dev-log measures overflow/NaN/tunneling/penetration. Then tune omega/K; then bend/curl on GPU.

## 🔧 LAYER 3c COLLISION WIRED INTO ENGINE (string-engine.html) — Stage A, awaiting live test
Full GPU collision integrated into GpuPhysics. Changes (all naga+JS validated, blind — no sandbox WebGPU):
- requestDevice requests maxStorageBuffersPerShaderStage up to 10 (collide needs 9 storage bufs); graceful
  fallback: if <9, GP.collSupported=false -> collision auto-disabled, physics still runs.
- WGSL_CLEARGRID/WGSL_GRIDBUILD/WGSL_COLLIDE added; pipelines built in ensureDevice (try/catch guarded).
- packCollision(): builds node->seg CSR (nsRange/nsList), strand id from G.piece, along-index via chain-walk
  from degree-1 endpoints (rings/branches -> along=0 = over-excluded but SAFE), skipK per seg, segI/segF,
  allocates segCell/cellBins/cellCount/overflow + 3 uniforms, grid params (reach=maxR+maxPad+1.5 margin,
  cell=max(10,2*(maxR+maxPad)), bounds from wall box or node bounds). Wrapped try/catch -> GP.collReady.
- step(): after constraint loop, if collReady && K>0 (K=S.gpuCollIters??4): per iter clear->gridBuild(reads
  curBuf)->collide(ping-pong). Grid REBUILT EACH iter (no Verlet skin needed; reuse window=1 iter). Collision
  LAST in substep (ends on nonpenetration) — matches AI Stage-A recommendation.
- disposeBuffers extended with 11 collision buffers.
- invMass read from nmeta buffer (binding 8) NOT pos.w (int/con write pos.w=0, clobbering it).
Toggle: S.gpuCollIters (default 4; set 0 to disable). No UI slider yet (console-settable) — add after validated.

## STEP-LOOP FINDINGS (layer3c-step-loop-integration-findings.md): validate in STAGES.
Stage A = structural block -> grid build -> collision block, collision LAST (what I shipped). Confirm no
state-transfer/pipeline bugs. Stage B = interleave structural+collision groups per outer iter (block
Gauss-Seidel across groups; couples length+contact better). Stage C = tune group counts/SOR/substeps.
Collision should be last (residual length error > ending penetrated). Walls are contact-like -> place with
collision. Ref: Flex/Unified Particle Physics §4.3.

## KNOWN RISKS (blind integration): 3D fallback normal still 2D-only (POC depth=0); pinned-node path
untested (POC all inv=1); grid fixed-bounds (escaping nodes clamp->edge cells->possible overflow, monitored);
runtime bind-group/param bugs only surface on user GPU (on-screen reportShader + status + console.warn =
diagnostic channel). Next: user live test -> if clean, add slider + dev-log overflow/tunneling, then Stage B.

## 🐛 FIX: collision blowup was REBUILD-GRID-EACH-ITER (over-aggression -> Verlet energy injection)
Live test: collision WORKS (strands stop passing through) but scene eventually explodes (no NaN, just
runaway tangling). Root cause: my step rebuilt the grid + re-discovered contacts EVERY collide iter, so
each of K iters did a fresh full push instead of converging. CPU builds its pair list ONCE per frame and
resolves that FIXED set over passes (Gauss-Seidel, converging -> overlaps shrink). Verlet turns position
pushes into velocity (v=pos-prev); GPU integrate REDUCES friction at high speed -> injected energy cascades.
Note: contactDamp & xpbd both DEFAULT 0, so CPU also injects collision velocity yet is stable -> difference
is MAGNITUDE (converging vs re-aggressing), not velocity cancellation.
FIX: build grid ONCE per substep (clear+gridBuild before the K-loop), K Jacobi iters converge on the fixed
contact set. Matches CPU pair-list-per-frame + review's build-time stored bounds + AI Stage A. Shipped.
NEXT LEVER if still lively: add velocity cancellation (prev update, CPU line 776) via a separate pass
(preColl copy) to avoid a 10th storage buffer. Also: 3D fallback normal still 2D-only (depth=25 live).

## BEND/CURL FINDINGS ARRIVED (gpu-bend-curl-jacobi-findings.md) — for the NEXT layer after collision.

## POLISH PASS 1 (collision working well per live test; explosions are settings-tunable, not a hard bug)
- Dev export now includes collision diagnostics: gpuPhysics.collision {supported,ready,maxStorageBuf,iters,
  lastOverflow,grid{gx,gy,cell,numCells,cap,reach},omega,penFrac,maxDisp}; config adds gpuCollIters/
  collLastOverflow/contactDamp/xpbd; telemetry samples collOverflow. Added collOverflowReadback() (reads
  bufOverflow each 1s). GP.lastOverflow field. -> I can now see overflow/grid/iters in any export.
- QUALITY slider (S.iters) now drives GPU collision iters K (K=S.gpuCollIters ?? S.iters). Was hardcoded 4.

## SETTINGS AUDIT — what's LIVE on the GPU path vs inert (user wants inert ones tied-in OR hidden in GPU mode):
LIVE on GPU: temp, damp, depth, speed, wallPad (integrate+walls); quality->collision iters; rest lengths.
NOT wired (inert in GPU mode, silently do nothing): contactDamp, xpbd (GPU collide has no velocity
  cancellation); attract/repel/tol/affinity (no GPU attract pass); bonding + all bond* (no GPU bonding);
  gCurl/gStiff (no GPU bend solver yet); gThick/gGrow need scene rebuild to affect GPU radii. Render look
  sliders (strandFill/gloss/shadow/outline/shadeSmooth) are CPU-canvas only; GPU renderer has its own capsule
  look. GPU constraint passes still fixed GP_PASSES=8 (not quality-tied like collision now is).
PLAN: (1) UI-gate inert sliders when GPU active (grey/hide + note), (2) progressively port physics to GPU
  (bend/curl next -> findings ready; then affinity, then bonding), (3) grab/select in GPU mode (see below).

## GRAB/SELECT IN GPU MODE — real gap (user switches to CPU just to select/grab).
Mechanism: global `grab` idx set on pointerdown by picking nearest node (uses G.nodes[i].x/y = CPU-side,
STALE in GPU mode since readbacks:0). CPU loop does dragApply()+constraints()+collide(). GPU step ignores
grab. The integrate shader ALREADY has a plumbed-but-unused grab:i32 uniform + free pad/pad2 slots for a
target xy. PLAN: (a) on pointerdown in GPU mode, one readback to refresh G.nodes for picking; (b) pass
grab idx + grabX/grabY in params; (c) integrate shader pins node==grab to target (np.xy=target, prev=target
=no velocity). Selection (S.selected) uses same pick -> works once (a) lands. Deferred to its own careful turn.

## FOUNDATION: gpuRefreshProps() — property edits now take effect LIVE in GPU mode (no sim reset)
Problem: GPU snapshots scene at buildScene; editing object props did nothing (design was edit-on-CPU/run-on-
GPU). Naive buildScene rebuild would reset positions (NX/NY stale in GPU mode, readbacks:0).
Fix: gpuRefreshProps() rewrites ONLY property-derived buffers (meta invMass/damp/solid, segF effR/pad/skipK,
style color/radius) via writeBuffer — positions/prev/grid untouched, running sim preserved. Cached GP._segList
(seg objs) + GP._segF (array). Hooked into bindPair.apply so ANY per-object slider triggers it when GP.active.
NOW LIVE in GPU mode: thickness (collision radius + render + mass), per-object damp, solid, color.
Refreshes but no visible effect until solver lands: stiff, curl (no GPU bend pass yet).
Still needs topology rebuild (not covered): grow, bonding, cut. Global sliders (gThick/gStiff/gCurl/gGrow)
not yet hooked (separate handlers) — TODO.

## DIFFICULTY MAP (told user): infra done (collision proved it). Remaining tiers: live-scalars DONE;
static per-obj props = refresh hook (DONE for thickness/mass); per-frame forces (bend/curl, affinity) = 1
compute pass each (medium, bend findings ready); topology forces (grow/bond/cut) = hybrid (CPU event -> GPU
re-upload, harder tier but known pattern). Not a research problem, a finite list. Next natural: GPU bend/curl.

## ✅ GPU BEND/CURL PASS (stiff + curl now live on GPU) — WGSL_BEND, naga-valid
Ported the CPU's center-node BOW formulation (parity, not the findings' signed-angle PBD - chose parity since
scenes are tuned for CPU look). Per degree-2 movable node: target = chordMid + tangent*bT + normal*(bN +
curl*r*3); pull center toward target by effStiff*0.5. Reuses the constraint CSR (nodeRange/edgeNbr) for the
2 neighbors - NO new adjacency buffer. 6 storage + 1 uniform. bendData vec4(bT,bN,stiff*0.5,curl*r*3) per node
(bT/bN = rest bow from computeRestBend, read ||0; stiff/curl slider-live). packBend() builds it (skips if no
degree-2 nodes). Step loop INTERLEAVES bend after each length pass (matches CPU length-then-bend order).
gpuRefreshProps() now also refreshes bendData factors -> stiff+curl sliders live in GPU mode. Guarded
(bendSupported/bendReady). All 7 shaders naga-valid. Bounds/render z untouched (2D bend like CPU).
NOW LIVE in GPU mode: thickness, mass, damp, solid, color, STIFFNESS, CURL. Forces still CPU-only: affinity
(next port - reuses collision grid), grow/bonding/cut (topology tier - hybrid CPU-event + GPU re-upload).

## FIX: live settings in GPU mode were only firing for bindPair per-object sliders (user: "nothing updates
live, have to switch cpu->gpu"). Now CATCH-ALL: document-level input/change listeners set GP.propsDirty when
GP.active; GPU render() calls gpuRefreshProps() once next frame if dirty. Covers ALL property controls
(thickness, stiff, curl, mass, damp, solid, fixed, color, global gThick/gStiff/gCurl/gGrow) with no per-handler
hooking. gpuRefreshProps refreshes meta+style+segF+bendData (positions untouched). STILL needs cpu->gpu
round-trip: topology changes (grow adds material, bonding, cut) - not property refreshes. Those wait for the
hybrid topology-rebuild path.

## ROOT CAUSE of "object settings dont update in GPU mode": line 1243 pointerdown DROPPED TO CPU on any
edit-intent click (GPU was run-only by design). So you could NOT select an object in GPU mode -> per-object
sliders (bindPair bails if nothing selected) had no target -> did nothing. Not a gpuRefreshProps bug.
## FIX: GPU-mode SELECTION via readback pick. G.nodes[i].x is a getter for NX[i]; readbackToCPU() writes NX[]
-> after readback the existing pick logic sees live positions. New window.gpuPick(mx,my): readbackToCPU().then
-> nearest node (or nearestSeg) -> selectObject + showTab('objects'). Move-tool click in GPU mode now selects
(stays in GPU); middle-mouse pans; non-move tools (draw/cut/erase = topology) still drop to CPU.
NOW: in GPU mode, click an object with Move tool -> selects -> per-object sliders (thickness/curl/stiff/pad)
apply LIVE via gpuRefreshProps. GRAB/DRAG (moving nodes with mouse) still TODO - needs the integrate grab
uniform for continuous drag (readback gives pick; drag needs per-frame pin). Instrumentation (refreshN/
refreshErr) retained for diagnostics.

## ✅ FIXED: live object-property updates in GPU mode (IIFE scope bug — confirmed by diag refreshN=0)
ROOT CAUSE: GPU subsystem (3rd <script>) is an IIFE; GP + gpuRefreshProps are PRIVATE to it. The two refresh
triggers live in block 1 (bindPair.apply hook + catch-all input listener) and referenced those IIFE-private
symbols via `typeof GP!=='undefined'` guards -> always undefined out there -> silently no-op (no error). So
gpuRefreshProps was NEVER called (diag: refreshN=0, propsDirty=false); global scalars worked only because
packParams reads S live INSIDE the IIFE each frame; diag button "fixed" thickness because runDiagnostics
rebuilds buffers inside the IIFE.
FIX (3 lines): expose window.gpuRefreshProps=gpuRefreshProps inside the IIFE; bindPair hook + input listener
now call window.gpuRefreshProps() (self-guards on GP.active, safe anytime). Also bufStyle +COPY_SRC so the
style probe can read back. Diag also confirmed GPU health: 2.32x speedup, 0 NaN, overflow 0, maxStorageBuf=16.
Lesson: defensive typeof guards HID a real wiring failure — cross-IIFE access must go through window.*.

## GROW wired to GPU: effGrow scales constraint rest length (rest*(1+grow)) -> strand expands. GPU constraint
used static rest -> grow was inert. Fix: buildScene now stores GP._baseRest + GP._edgeObj (obj per directed
edge); initial bufRest = base*(1+effGrow); gpuRefreshProps refreshes bufRest = base*(1+effGrow) live. Grow
slider now expands/shrinks on GPU. (Auto-spacing/relaxSpacing o.autoSpace is a separate CPU-only per-frame
ramp - still CPU; manual grow slider works.)
LIVE on GPU now: thickness, mass, damp, solid, color, stiffness, curl, GROW, + global scalars. Remaining
CPU-only: affinity (attract/repel - needs GPU force pass, medium), bonding (topology, hard tier), cut/draw/
erase (edit -> drop to CPU, fine), auto-spacing ramp.

## AFFINITY (attract/repel) — GPU port STARTED. Draft gather shader naga-valid: protos/affinity_shader.mjs
Ported from CPU attract(): per-node Jacobi gather over a SECOND coarser grid (cell~affRange, reuses CLEARGRID/
GRIDBUILD). Bindings (10 storage + 1 uniform; device max=16): pos, posOut, nodeRange, nodeList (reuse coll CSR),
segI (obj in >>3), affF (effR,pad,affRange,tagged), segCellA + cellBinsA (affinity grid), nmeta (invMass),
vmat (nObj*nObj interaction matrix), U. Force: va=vmat[objX*nObj+objY]; closest(X,Y); gate=clamp((dist-tgt)/10)
(attraction fades inside contact, repulsion doesn't); fallA=1-clamp((dist-tgt)/(arX-tgt)); mA=va*BASE*fallA*g;
node i force = -u*mA*w*invI (w=barycentric slot, -u pulls X toward Y for va>0). BASE=0.18.
HELD wiring pending research (relay sent): Q affinity runs once-per-FRAME on CPU (not per substep) - GPU should
match (run affinity pass once per step() call, not in the substep loop); Q needs clamp for Jacobi stability?;
Q stability alongside collision. vmat build (CPU, like attract's precompute) + affF + affinity grid params +
packAffinity + step wiring = NEXT once research lands. Disciplined: not wiring unvalidated design (collision
blowup lesson). Also drafted: bonding = hybrid (GPU proximity detect -> CPU form+reupload).

## GPU AFFINITY wired (attract/repel) — awaiting live test
Two-AI research (research/webgpu-collision-handoff/gpu-affinity-design-findings.md) confirmed + refined the design.
- SECOND coarser tagged-only grid (cell~affRange~140, ~6x collision's). New shaders: WGSL_GRIDBUILDT (tagged-only
  insert; stores AABB for all, inserts bins only if affF.w tagged) + WGSL_AFFINITY (per-node Jacobi gather).
- Reuses collision infra: bufNSR/bufNSL (node->seg CSR), bufSegI (a,b,obj), bufMeta (invMass), bufA/bufB. Requires
  collReady (affinity off if collision off — documented).
- vmat (nO*nO) precomputed CPU-side via interVal (a's pull toward b via a.inter keyed by b.ids). NON-RECIPROCAL:
  X endpoints use vmat[objX*nO+objY], Y endpoints use vmat[objY*nO+objX] = CPU parity (COM drift intentional).
- Force: barycentric slots (1-s,s,1-t,t), equal/opposite pair force x own invMass, SUM (not contact-averaged —
  affinity is additive many-body). Per-node magnitude clamp GP_AFF_MAXDISP=8 (research: mandatory). GP_AFF_BASE=0.18.
- Runs ONCE per frame before the substep loop (attract() is a per-step DISPLACEMENT not h^2 force — matches CPU
  cadence). clear affinity grid -> gridBuildT -> affinity gather (own encoder+submit), ping-pong curBuf once.
- gpuRefreshProps refreshes affF + vmat live. Guarded (affSupported/affReady). All 9 shaders naga-valid, JS valid.
- TODO refinements (research): smoothstep gate+cutoff (used CPU-parity linear clamp), zero-dist fallback normal for
  repulsion, clamp-activation telemetry counter, direct all-pairs path for tiny tagged sets.
BONDING (hybrid) findings also in hand (gpu-bonding-hybrid-design-findings.md) — confirms CPU topology authority +
GPU proximity discovery (atomic append, overflow fatal, double-buffered readback). Next build after affinity verified.

## FIXED: affinity (and any catch-all-driven control) didn't update live — capture-vs-bubble ordering bug
Diag confirmed affinity healthy (ready, overflow 0, refreshN=185 so refresh WAS firing) but values only took
after a rebuild. ROOT CAUSE: the catch-all refresh listener (line 1306) was registered in CAPTURE phase (true),
so it fired on the way DOWN to the control, BEFORE the control's own 'input' handler wrote the model. So
gpuRefreshProps recomputed vmat/affF from the OLD value; only a later unrelated event caught up. The per-object
sliders worked only because bindPair ALSO calls gpuRefreshProps directly after its setter. The affinity matrix
(interRow -> o.interSelf / o.inter[id]) relies solely on the catch-all -> stale.
FIX (1 char): capture true -> bubble false. Bubble fires AFTER target-phase handlers write the model, so the
refresh reads fresh values. Fixes affinity live-update AND the whole class (any control relying on the catch-all).
Verified the lone stopPropagation is on a click handler (material delete), not input/change, so bubble misses nothing.
LESSON: a global capture-phase refresh listener races ahead of the very handlers whose writes it needs to read.

## REAL FIX: affinity enabled-from-zero didn't init live (affReady latched at build) — the capture/bubble guess was wrong
Diag: affinity.ready=true, overflow=0, refreshN=185, refreshErr=null — affinity was HEALTHY, refresh WAS firing.
Symptom persisted: set an affinity value -> no effect until mode-switch/diag. ROOT CAUSE: affReady is decided ONCE
at build time by packAffinity (anyAff = any nonzero interSelf/inter). Default scene has affinity TAGS but zero
VALUES -> affReady=false at build. gpuRefreshProps's affinity block AND step()'s whole affinity pass are both gated
on affReady, so setting a value from zero refreshed nothing and never ran the pass; only a rebuild (switch/diag)
re-ran packAffinity, saw the nonzero value, and flipped affReady=true. (The earlier capture->bubble change was a
wrong guess — timing was never the issue since bindPair/other controls kept refreshN climbing.)
FIX: stash buffer helpers (GP._helpers={mk,bg,B,ST,CD,CS,UN,device}) at build; add rebuildAffinityLive() (dispose
aff buffers + re-run packAffinity) + affinityEnabled(); in gpuRefreshProps detect off->on (anyAff && !affReady ->
rebuildAffinityLive) and on->off (affReady=false). So enabling affinity from zero now builds its buffers live and
the pass starts next frame; disabling stops it. Uses the same packAffinity that already works on rebuild.
LESSON: a subsystem gated on a build-time-latched ready flag can't self-enable from a zero start — the enable
transition must (re)initialize it. (Collision/bend don't hit this: they're active from build in normal scenes.)

## GRAB-TO-DRAG wired in GPU mode. Audit also corrected two audit-time assumptions.
- Collision is NOT enable-latched (packCollision builds whenever segments exist + wantColl; not gated on solids).
  The collide shader's bit-0 check is BOND not solid; solid (bit1) only toggles 2D vs 3D depth. So the "collision-
  solid latch" flagged in the audit isn't real. Minor remaining: toggling an object's solid doesn't refresh bufSegI
  live (segI built once) so the 2D/3D-depth choice for that seg is stale until rebuild — low priority.
- Grab was half-plumbed: WGSL_INT struct had grab:i32 but main() never used it, packParams hard-coded grab=-1, and
  there was no target position. FIX: renamed the two P-struct pad slots -> grabX/grabY (same offsets; WGSL_CON
  ignores them); WGSL_INT now pins node[grab] to (grabX,grabY,z) with zero velocity at top of main. All grab state
  on GP (grabNode/grabX/grabY) via window.gpuGrabMove/Clear/Active. gpuPick sets grabNode=picked node + grabX/Y.
  pointerdown(move,GPU) setPointerCapture; pointermove updates target via gpuGrabMove; pointerup/cancel clear.
  CPU grab var untouched (separate path); no conflict since GP.active gates the GPU branch. WGSL_INT+CON naga-valid.
Remaining GPU-mode gaps: BONDING (formation+breaking+holding existing bonds — next, hybrid), auto-spacing
(relaxSpacing CPU-only), advanceCDRamp (minor), solid->segI live refresh (minor 3D-depth nuance).

## BONDING stage 1: hold + render existing bonds on GPU (prerequisite)
CPU treats bonds as ordinary length-constraint segments (constraints() length loop iterates ALL segs incl s.bond;
formation is in endpointForces line 889 which pushes a bond:true seg on proximity). buildScene was skipping bonds
(if(sg.dead||sg.bond)continue) so bonded structures fell apart on GPU. FIX (1 line): skip only dead, not bond.
Now bonds are in segList -> held (constraint CSR/adj), drawn (bufSeg/style), collision-skipped (segI bond bit set
-> collide line 52 `(w&1)` continues), affinity-skipped (bonds ids=[] -> affF.w=0). Branch nodes at bonds hit the
collider's safe along-index over-exclude path. Grow applies to bonds too (obj=endpoint's obj) = CPU parity.
Bonds are FROZEN on GPU for now (no formation/breaking/hardening yet) but held + visible = structures survive.
NEXT (stage 2): formation + breaking. Plan = pragmatic hybrid first (throttled readback -> run existing CPU bond
logic endpointForces/flag*Breaks/maintainBonds/removeDead -> rebuild GPU buffers on topology change; reuses ALL
CPU bond code, bounded cost via throttle), then stage 3 = move free-endpoint proximity DETECTION to a GPU pass
(research design: atomic-append candidate buffer, overflow fatal, double-buffered readback) to kill the CPU hotspot.

## BONDING stage 2A: pragmatic hybrid (formation + breaking) — the oracle for stage B
gpuBondTick() (async, in step(), throttled GP.bondEvery=3 frames, _bondBusy guard): readbackToCPU -> read REAL
prev buffer into NPX/NPY/NPH (readback alone sets prev=cur=zero velocity; restoring real prev preserves velocity
across rebuild) -> run the EXACT CPU bond pipeline (endpointForces formation+pull, flagBond/Strain/BendBreaks,
maintainBonds, removeDead — these self-maintain nbrs/ends/piece via buildNbrs) -> if seg/node count changed,
buildScene() (disposes+recreates all buffers; reads NX/NY + real prev so velocity survives). Formation + breaking
now WORK in GPU mode, reusing all CPU bond code = exact behavior parity. This is the ORACLE for stage B.
Costs (accepted for A, fixed by B): a readback + CPU bond work + full rebuild per bond-event, ~1-2 frame position
rewind from readback latency. Throttle + rebuild-only-on-change bound it. endpointForces pull is applied only on
rebuild frames (discarded otherwise) = proximity-formation with deferred pull (user OK with pull "after").
Telemetry: diag.bonding {on,every,ticks,events,busy}. Gated on S.bonding (inert until bonding configured).
NEXT (stage B): move free-endpoint proximity DETECTION to a GPU pass (atomic-append candidates, overflow fatal,
double-buffered readback) -> CPU only arbitrates/mutates/rebuilds. Validate B's candidate set vs this A pipeline.

## Bonding stage 2A stutter reduction (diag: 2294 bond events + readback every 3 frames x2 maps @ 4355 nodes)
Continuous stutter was dominated by the per-3-frame readback doing TWO map operations (current + prev = 2 sync
points, ~66/sec). Fixes: (1) ONE combined readback (copy cur + bufPrev into a 2N staging buffer, single mapAsync);
(2) bondEvery 3 -> 6 (halve frequency); (3) skip the whole tick (no readback) when no object has bondOn. Net ~4x
fewer GPU sync points. Periodic hitches remain from full buildScene rebuild per bond-event (~3-4/sec here) — this
is FUNDAMENTAL to topology change and persists even in stage B (research keeps rebuild on CPU). The real smoothness
fix is a cheaper/incremental rebuild (reuse same-size buffers via writeBuffer instead of destroy+recreate) — a
distinct optimization from stage B's GPU detection. Order TBD with user after they test the readback fix.

## CHEAP REBUILD: buffer reuse + capacity headroom (kills the per-bond-event rebuild hitch)
Root of the hitch: buildScene called disposeBuffers() at its start (destroy ALL ~20 GPU buffers) then recreated
them every bond event (~3-4/sec) — GPU buffer allocation is the expensive op. disposeBuffers was ONLY ever called
from buildScene (deactivate/discard just flip active), so:
- Added mkR(key,data,usage,hr) / bufR(key,size,usage,hr): reuse-or-realloc with per-buffer capacity tracking
  (GP._cap) + 1.4x headroom. mkR writeBuffers into the existing buffer when capacity fits; bufR (grids, contents
  rewritten each frame) just ensures capacity. Realloc (destroy+create at 1.4x) only when the count exceeds capacity.
- buildScene no longer disposes; it resets ready flags and repacks via mkR/bufR (buffers persist + reused). Bind
  groups still recreated each rebuild (cheap vs allocation; cache later if needed).
- Converted ALL size-varying allocations (pos/prev/meta/CSR/seg/style/segI/segF/bend/affF/vmat + collision &
  affinity grids + uniforms) to mkR/bufR.
- Real teardown (disposeBuffers, which now also clears GP._cap) moved to gpuPhysicsDiscard (scene replace) so memory
  is freed when topology is truly abandoned; also on device-level teardown.
Effect: a bond event = CPU repack + writeBuffer into existing buffers (no GPU allocation) as long as counts stay
within 1.4x headroom -> the hitch should largely disappear. Memory ~1.4x (fine). Benefits stage A now + stage B later.

## HOTFIX: black scene on GPU switch after cheap-rebuild — buffer size alignment
mkR/bufR computed alloc = ceil(need*1.4), which is NOT a multiple of 4/16 for small buffers (16-byte overflow/
uniforms -> 23 bytes; 32-byte grid uniforms -> 45). WebGPU rejects unaligned storage/uniform buffer sizes ->
bind group / pipeline validation fails -> render blanks (black). FIX: alloc = ceil(need*1.4/16)*16 (round up to
16-byte vec4 alignment) in both mkR and bufR. Uniforms grow slightly (48->80 etc., harmless; shader reads struct
size). All sizes now %16==0.

## BONDING stage B (GPU detection) STARTED — detection shaders validated: protos/bonddetect_shaders.mjs
Formation rules extracted from endpointForces: free endpoints = G.ends (degree-1 + object bondOn); capture radius
ER=maxR+10 (maxR from bond profiles' wRange/sRange/snap*bondRest); dedup n2>n1; non-adjacent; then FINE checks
(endProf compatibility, dist<snapR*bondRest, hysteresis sepFrom/sepUntil) + bond params. The deferred pull drops
out (was discarded in stage A anyway). Split: GPU broad-phase (grid+scan -> candidate pairs), CPU fine checks +
formation (reuse exact CPU logic).
Two shaders naga-valid:
- WGSL_ENDGRID: insert each free endpoint into its home cell (6 bindings). Reuses CLEARGRID to reset.
- WGSL_BONDDETECT: per endpoint scan 3x3 cells, emit candidate pairs (n1<n2) within ER^2 to atomic-append buffer
  (7 storage + 1 uniform). candCount atomic, cand=array<vec2u>(n1,n2), candOver overflow (fatal).
NEXT (B1b wiring, validation-first): packBondDetect in buildScene (endList from G.ends, endpoint grid params,
cand buffers, pipelines guarded); run clear->endgrid->detect in gpuBondTick BEFORE the position readback; readback
candidate COUNT + a small candidate list; report vs CPU oracle (endpointForces newBonds) in dev-export. Confirm GPU
candidate set == CPU broad-phase pairs on frozen positions. THEN (B1c) switch formation to consume GPU candidates
(CPU does only fine checks + create bond), dropping the CPU broad-phase scan = the hotspot kill. Overflow fatal ->
fall back to CPU broad-phase that batch. Buffers via mkR/bufR (cheap-rebuild) so per-event cost stays low.

## Bonding stage B1b: GPU detection VALIDATION PROBE wired (does NOT change formation)
packBondDetect (buildScene): builds endList from G.ends, endpoint grid (cell=ER=maxR+10, cap 32), cand buffer
(candCap=max(64,nE*4), vec2u pairs), atomic counters+overflow, uniforms — all via mkR/bufR (16-aligned), guarded
on bondDetectSupported+S.bonding+eligible objects. Pipelines endGridPipe/bondDetectPipe (guarded). Bind orders
verified vs shaders (ENDGRID pos/endList/cellCount/cellBins/overflow/U; DETECT pos/endList/cellBins/cellCount/
candCount/cand/candOver/U; clear reuses CLEARGRID). Fixed: packBondDetect defines its own ST/CD/CS/UN (were
buildScene-local -> would've silently failed).
gpuBondDetectProbe() (every 30 frames, in step(), guarded, _bdBusy): clear->endgrid->detect on GPU positions,
readback candCount/candOver/endOver + sample pairs, validate each (n1<n2, both in G.ends, dist<=ER^2*1.15), and
compare to cpuCandidateCount() (CPU broad-phase oracle on NX/NY). Reports diag.bonding.detect =
{ends,gpuCand,valid,invalid,candOver,endOver,cpuPairs,cell}. Formation still stage A. Restore point tag:
stable-20260824-pre-bondingB (+ outputs/string-engine-STABLE-preBondingB.html).
VALIDATION TARGET: invalid≈0, candOver=0, endOver=0, gpuCand≈cpuPairs (small margin from ~6-frame position
staleness). If so -> B1c: switch formation to consume GPU candidates, drop CPU broad-phase = hotspot kill.

## B1b probe result + snap-filter fix
First probe (1497 ends): gpuCand 23126 vs cpuPairs 23192 (0.3% apart), invalid 2/5986 -> DETECTION LOGIC CORRECT.
But candOver 17138 (candCap 5988 too small) + endOver 4 (cell cap 32). Key insight: at ER=130 w/ dense ends the
BROAD phase = ~23k pairs = same as CPU broad-phase -> emitting all wouldn't save CPU work. FIX = snap-distance
pre-filter ON GPU: upload per-endpoint endMeta (effR, maxSnap); emit only pairs with d < max(snap)*(effR1+effR2)*
MARGIN(1.2) -> collapses 23k broad pairs to the few near-bond ones. Grid stays cell=ER (covers max), emit filters
to snap. cell cap 32->128 (endOver), candCap now max(1024,nE*6) for the few near-bond pairs. Detect shader now
9 bindings (added endMeta @7, U @8) - naga-valid. Oracle cpuCandidateCount(cell,margin) updated to snap-based to
match. Expect next probe: candOver 0, endOver 0, gpuCand≈cpuPairs (small), invalid 0. Then B1c consume candidates.

## DEV TEST SCENE added (persistent, repurposable) — scene picker button "dev test" (data-s="dev")
Two swappable functions before seedWeavy: buildDevScene(W,H,cx,cy) (geometry) + configureDevBonding() (bonding
setup, called from build() tail after assignDefaultIds). build('dev') branch + tail hook `if(scene==='dev')
configureDevBonding()`. Current target = BONDING stage B: 48 short strands (4-7 nodes), loose ends, all given
shared type ids=['dev'] + snappy same-type endType {sStr:0.8,sRange:45,snap:2.5,brk:3.5,...}, bondOn=true,
S.bonding=true, S.temp>=0.35. On play, ends jitter+pull together and bond -> stresses the detection probe.
WORKFLOW: Claude rewrites buildDevScene/configureDevBonding for whatever is under test; user clicks "dev test",
plays, exports diag. (Note: emoji in source truncates the file via Python surrogate-encoding on write — keep dev
labels plain ASCII.)

## B1b probe #2 result + fixes (dev scene converged on CPU before GPU; probe ran post-formation)
Diag: peakEnds 2, peakGpuCand 0 — the 140 dense strands bonded into ONE blob (ends 96->2), and it converged
during the CPU frames (telemetry t1-8 cpu) BEFORE the GPU switch, so GPU detection inherited a settled blob. Also
the probe ran in step() AFTER gpuBondTick formation each cycle, so formation consumed candidates before the probe
looked. Detection wiring itself was clean (41 runs, 0 errors/overflow). Two fixes:
1. Moved detection measurement INTO gpuBondTick, right after the position readback and BEFORE endpointForces, on
   the SAME cur-buffer positions as the CPU oracle (cpuCandidateCount on NX/NY). This is exactly the B1c data flow
   (detect -> compare -> form) and catches candidates before formation eats them. Removed the old step() probe.
2. Dev scene: SPACED 11x13 grid (strands start separate) + gentle pull (sStr 0.5) so convergence happens GRADUALLY
   in GPU mode -> sustained candidates over seconds. USAGE: switch to GPU before/right as you play so convergence
   is captured on GPU not CPU. detectPeak accumulator catches the bursts.

## ✅ STAGE B DETECTION VALIDATED (user's real scene, GPU mode, 227 bond events)
detect: ends 1149, gpuCand 362 vs cpuPairs 364 -> absDiff 2 (near-exact match). candOver 0, endOver 0.
detectPeak: peakGpuCand 494 vs peakCpuPairs 489, maxCandOver/maxEndOver 0. The snap-filter collapsed the broad
~23k pairs to ~360-490 near-bond pairs (~50x reduction) = the efficiency that makes Stage B worth it.
Also unit-tested cpuCandidateCount headlessly (1/2/0 close-pair cases pass). Detection logic confirmed correct.
(JSDOM full-engine harness hung on the init loop — abandoned; pure-logic test + real-scene diag suffice.)
Dev scene's detection didn't init earlier (detect idle) — a dev-scene-specific quirk; the new auto-flow captures
bondDetectWhy so the next dev run will explain it. Not blocking (real scene works).

## DEV TEST AUTO-FLOW: clicking "dev test" now runs the whole test unattended
runDevTest(): build('dev') -> 300ms settle -> check gpuPhysicsToggle + setGpuPhysicsMode(true) -> poll
gpuPhysicsActive up to 6s -> gpuResetProbe() (fresh accumulators) -> 10s GPU churn (status counts down) ->
runAndExport() (opens save/download). window.gpuResetProbe exposed from IIFE. Dev button wired to runDevTest.
NEXT: B1c — swap formation to consume the GPU candidates (drop the CPU broad-phase), with CPU re-validation +
overflow->CPU fallback. Detection is the validated input.

## ✅ B1c: formation now consumes GPU candidates — CPU broad-phase scan DROPPED (the hotspot kill)
Refactor: extracted applyNewBonds(newBonds) (arbitration + creation, VERBATIM from endpointForces; endpointForces
now calls it = one source of truth) and evalBondPair(n1,n2,newBonds) (per-pair fine checks: compatibility,
hysteresis, snap -> newBonds; mirrors the scan-loop body, no pull). formBondsFromCandidates(pairs) = loop
evalBondPair + applyNewBonds. Unit-tested evalBondPair (close+compat->1, far->0, bondOn=false->0, adjacent->0 all pass).
gpuBondTick: after the pre-formation detection, if candOver==0 && endOver==0 it reads back the actual candidate
PAIRS (bufCand, nR*2 u32 node ids) and calls formBondsFromCandidates(pairs) -> GPU path (CPU broad-phase skipped).
On overflow / detection error -> falls back to endpointForces() (CPU broad-phase). Telemetry: bonding.path
('gpu'|'cpu-fallback') + bonding.fallbacks. Pull stays deferred (proximity bonding; ends meet via physics).
The CPU still does fine checks on the few candidates + arbitration + topology mutation + rebuild (cheap via
buffer-reuse). This removes the O(ends x 9cells) CPU bucketing+scan = the bonding hotspot the user flagged.
TEST: real bonding scene, GPU, play, export -> expect bonding.path='gpu', low/zero fallbacks, bonds form/break
as before, detectPeak still matching.

## AUDIT ROUND 1 — dead code + resource hygiene
- REMOVED gpuBondDetectProbe() (36 lines): dead since detection moved into gpuBondTick (pre-formation); no callers.
- Readback staging buffers: all 9 MAP_READ createBuffer sites have a matching .destroy() within 4 lines — no leaks.
- All size-varying GPU buffers go through mkR/bufR (16-byte-aligned reuse); only transient readbacks + diag-local
  mk() allocate directly, and those are freed. No per-frame allocation leaks.
- NOTED (left for user's call — pre-existing CPU-side, not GPU work, possible unwired API): objInv, pieceNodesOf,
  refreshAutoSpace, sampleJSON, setObjAffinity are defined-but-never-called; thermalBreaks() is an intentional
  documented retired no-op stub. buildScene's `const mk` is now unused (all converted to mkR) but harmlessly passed
  to pack fns that ignore it. None removed (cosmetic, non-zero risk, out of migration scope).

## AUDIT ROUND 2 — stability
- NaN guards: added final `if(any(nd!=nd)){nd=p;}` to WGSL_COLLIDE + WGSL_AFFINITY position writes. NaN guards are
  now uniform across all 5 position-mutating shaders (INT/CON/BEND already had them). Note: affinity's maxDisp clamp
  did NOT catch NaN (NaN>maxDisp is false), so a NaN accum could have slipped through — now guarded. naga-valid.
- Grid memory bound: added a coarsening clamp (GP_MAXCELLS=1<<19) to the collision, affinity, and endpoint grids.
  numCells was driven purely by the scene bounding box with NO cap -> a walls-off, far-drifting scene could request
  a multi-GB cellBins buffer and fail (black screen). Now, if numCells exceeds the budget, the cell size is coarsened
  (sqrt scale) so the grid buffer stays <=~128MB. Verified headlessly: no-op for normal scenes (even 8000x8000
  untouched), and capped at ~525k cells / 128MB for scenes up to 2,000,000 px across. GP.gridCoarsened counts events.
- Confirmed clean: div-zero guards on all divides; overflow (coll/aff/bond/endpoint grids) degrades gracefully
  (drops from cell, counts overflow, monitored via lastOverflow/lastAffOverflow/candOver->CPU fallback); buffer-reuse
  recreates bind groups after any mkR/bufR realloc (no stale buffer refs); all readback staging buffers destroyed.
