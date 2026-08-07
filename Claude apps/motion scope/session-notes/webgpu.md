# Session notes — WebGPU port

**Branch:** `feature/webgpu` (branched from main @ perf commit a392733).
Do NOT merge to main until the user explicitly says so.

## Goal
Move the heavy per-pixel processing to the GPU via WebGPU (user is fine with
WebGPU-only), with WebGL2 and CPU fallbacks. User wants the active backend shown
clearly in the UI so a fall-back is visible.

## Done this session
- Header **ENGINE** badge (mono pill, right side): shows active compute path;
  phosphor when webgpu, amber when webgl2, muted for cpu. Tooltip lists what's
  available and the active path, so a fallback is always visible.
- `detectBackends()`: sets caps.webgpu (navigator.gpu.requestAdapter) and
  caps.webgl2 (canvas webgl2 context) at startup. `backend` var = active path,
  currently forced 'cpu' (compute not ported yet). updateEngineBadge() reflects it.
- Everything still runs on CPU; badge shows CPU. Foundation only.

## Port plan (incremental, behind the badge; verify parity each step)
1. WebGPU device/context setup + a "GPU or bust?" fallback chain
   (requestAdapter -> device; on any failure set backend='webgl2' or 'cpu').
2. Port ONE op first as proof of concept: the **Warp remap** (bilinear resample =
   near-free on GPU) OR a box blur. Flip badge to 'webgpu' only when that path runs.
3. Then port blurs, temporal bandpass, gradients/structure tensor, isolate, overlay.
4. State as ping-pong textures (EMAs, bgModel, flow accumulators, prev-frame).
5. Keep STABILIZE estimate on CPU (block-match/argmin/median = awkward on GPU);
   it runs on the 120px thumbnail already. Counter-shift can be GPU.
6. WebGPU compute shaders (WGSL) handle the reductions later if wanted.

## Caveats / notes
- Can't visually verify GPU output here — port behind a CPU/GPU toggle so the user
  can flip and confirm parity per step.
- Brave/Mac: WebGPU should work (Chromium 113+ default) but Brave gates via
  privacy/farbling; user to confirm `navigator.gpu` returns an object.

## Session 2 — first GPU path landed (Linear amplify)

Implemented WebGPU render pipeline for the Linear (Eulerian) amplify path.
- Second canvas #viewGPU (webgpu context) overlaid in stage; shown when GPU active,
  #view (2d) shown otherwise. Header GPU toggle (enabled only if caps.webgpu).
- WGSL fullscreen pass, 3 render targets (MRT): display (canvas) + slowN + fastN
  (rgba32float). Reads inputTex (video->proc canvas via copyExternalImageToTexture)
  + previous slow/fast state; computes EMA bandpass, luma/chroma blend, gain; writes
  display + new state. Ping-pong slow[2]/fast[2]. seed uniform sets s=f=x on frame 1.
- Uniforms (32B): gain,aSlow,aFast,chroma,amp,seed,w,h. aSlow/aFast from live fps.
- Fallbacks: any init/frame/device-lost error -> gpuFallback() -> useGPU off,
  gpuFailed, button disabled, CPU resumes. CPU path is UNTOUCHED and always safe.
- backend var flips to 'webgpu' only while a GPU frame actually runs; badge + tooltip
  reflect it, so falling back to CPU (e.g. switching to Warp) is visible.

### GPU coverage / parity notes (v1)
GPU path currently = Linear, Amplified/Motion-only, non-Compare ONLY. It does NOT
yet apply: temporal denoise, stabilize, spatial scale, smoothing. So for a fair
CPU-vs-GPU parity check, turn those off. Compare view forces CPU. Energy meter is
stale in GPU mode (cosmetic).

### Next
- Wire temporal denoise + stabilize (pre-pass) into GPU, then scale/smoothing.
- Port Phase, Isolate, Warp (warp remap = near-free on GPU) as further passes.
- Keep stabilize ESTIMATE on CPU (thumbnail); counter-shift on GPU.
- Can't verify GPU output here — needs user test (toggle GPU, use Compare mentally
  by flipping the toggle; watch badge + fps).
