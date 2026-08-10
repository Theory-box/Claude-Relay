# Neural mode (feature/neural) — session notes

## STATUS: model conversion DONE + validated. Browser integration = next (blind, will iterate).

## Model
- Learned Video Motion Magnification (Oh et al., ECCV 2018) — the real SOTA-lineage learned method.
- Weights: ZhengPeng7/motion_magnification_learning-based, release v1.0 `magnet_epoch12_loss7.28e-02.pth` (3.5MB). Loaded into MagNet with 0 missing / 0 unexpected keys.
- Exported to ONNX: `models/magnet.onnx` (3.7MB, opset 17, legacy exporter dynamo=False).
- Validated: ONNX output == PyTorch to ~1e-6 across sizes (128x128, 256x192, 240x320) and amps (5/10/20). Dynamic H/W confirmed.

## I/O spec (CRITICAL for browser wiring)
- Inputs: `frameA` [b,3,H,W] f32, `frameB` [b,3,H,W] f32, `amp` scalar f32.
- Output: `out` [b,3,H,W] f32.
- Normalize IN:  pixelRGB[0..255] -> v/127.5 - 1  (range [-1,1]); layout NCHW (channel-planar, R plane then G then B).
- Denorm OUT: clip(out,-1,1); pixel = round((out+1)*127.5) [0..255]; CHW -> HWC.
- Inference path = MagNet 'evaluate' mode: encode A, encode B, manipulator(mA,mB,amp)=mB+amp*process(mB-mA), decode(tB, motion_mag).
- Frame pairing: STATIC mode A=first/reference frame; DYNAMIC mode A=previous frame. B=current. amp=gain.

## Browser integration plan (next)
1. Load ONNX Runtime Web from CDN (onnxruntime-web), prefer WebGPU backend, fallback WASM.
2. Deliver model: embed magnet.onnx as base64 in the HTML (keeps single-file) OR fetch from repo. ~3.7MB -> ~5MB base64.
3. Per frame: build NCHW f32 tensors for (A,B) from the video/canvas pixels using the normalization above; run session; postprocess to canvas.
4. Add "Neural (beta)" method/mode toggle. amp = the gain slider.
5. Perf: model may be slow at full res -> downscale proc resolution; run every Nth frame if needed. Static vs Dynamic toggle.
6. BLIND step — needs user testing; expect iteration on normalization/layout/perf.

## Repro (container)
- pip install --break-system-packages torch (cpu) onnx onnxruntime onnxscript numpy
- git clone ZhengPeng7/motion_magnification_learning-based ; download weights (release v1.0) ; load into magnet.MagNet ; wrap encoder->manipulator->decoder ; torch.onnx.export(..., opset 17, dynamo=False, dynamic_axes b/h/w).
