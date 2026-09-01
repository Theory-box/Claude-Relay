# WebGPU / WGSL validation at `0179580`

## Result

The three WGSL modules embedded in `string-engine.html` pass an independent Naga parser/validator check:

```text
PASS WGSL_INT (35 lines)
PASS WGSL_CON (27 lines)
PASS WGSL_REN (23 lines)
```

Environment used:

- Exact commit: `0179580410aff2cbdf2fc062b1e4d0ccf5c8a80e`
- Node: v24.19.0
- Validator: `naga-wasi-cli` 0.1.0, a third-party WASI packaging of the wgpu/Naga CLI (`ihasq/naga-wasi`)
- This runner has no Chrome/Chromium executable and no exposed GPU, so it cannot independently dispatch WebGPU work.

Install and rerun from the repository root:

```bash
npm install --prefix .wgsl-tools naga-wasi-cli@0.1.0
node validate-string-engine-wgsl.mjs "Claude apps/string engine/string-engine.html" ".wgsl-tools/node_modules/.bin/naga"
```

The script creates temporary extracted `.wgsl` files under the current directory, invokes Naga, and removes the files afterward. With a native `naga` binary on `PATH`, omit the second argument.

## Existing real-hardware evidence in the commit

`diag-logs/2026-08-21_layer1_first-hardware-run.json` is already a stronger end-to-end WebGPU confirmation than an offline compile alone:

- WebGPU supported: `true`
- Adapter: NVIDIA, Lovelace
- Browser: Chrome 151 on Windows
- Shader compilation: `ok: 1`, empty message list
- Scene: 2,483 nodes; 1,961 segments; 3,922 directed constraints
- GPU test: 120 steps, 0 NaNs, 0.923 ms/step
- CPU comparison: 0.478 ms/step; reported speedup 0.52×
- GPU mean edge error: 0.042; CPU: 0.045
- Limits relevant to the next layer: workgroup maximum 256 invocations, eight storage buffers per shader stage, four bind groups

Interpretation: the shaders both compile and execute stably on actual WebGPU/NVIDIA hardware. At this small scene and current pass structure, GPU execution is slower than CPU; that result does not establish the crossover for the planned 10k–100k collision workload.
