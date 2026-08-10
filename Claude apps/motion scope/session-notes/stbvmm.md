# STB-VMM higher-quality neural model (feature/stbvmm) — session notes

## CHUNK 1 (conversion gate): DONE. Result = conversion works, but model is BIG.

### What passed
- STB-VMM (Swin Transformer VMM, Lado-Roige & Perez 2023) = documented higher quality than Oh2018 (less noise/blur/artifacts).
- Official repo: github.com/RLado/STB-VMM (PyTorch). Same TWO-FRAME interface: model(a,b,amp) -> (y_hat,...). Drops into our neural slot.
- Checkpoint: release v1.0.0 `ckpt_e49.pth.tar` (149 MB) -> https://github.com/RLado/STB-VMM/releases/download/v1.0.0/ckpt_e49.pth.tar
- Loaded into STBVMM(img_size=256, manipulator_num_resblk=1) with 0 learned-missing / 0 unexpected AFTER dropping `attn_mask` keys (they are size-dependent recomputed buffers; ckpt trained at 384 -> 36 windows, we build 256 -> 16 windows).
- Exported ONNX (opset 17, dynamo=False) at FIXED 256x256. ONNX == PyTorch to 4.3e-6. FAITHFUL.

### The blocker: SIZE
- fp32 ONNX = 136.6 MB (params 125.3 MB). ~37x the MagNet (3.7MB). CANNOT embed in single HTML (base64 ~180MB).
- Swin needs FIXED input size (attn masks size-dependent). Input must be multiple of 64 (conv_first /8 then window 8). 256 or 384 valid. 384=native/train size (higher quality, slower), 256=faster.

### Delivery options (decide CHUNK 2)
1. fp16 quantize -> ~68 MB. Usually visually lossless. Still big to embed (~90MB HTML). ORT-Web supports fp16.
2. int8 quantize -> ~34 MB. Embeddable-ish (~45MB HTML) but needs calibration, may cut quality (defeats purpose), ORT-Web WebGPU int8 support spotty.
3. Load from URL (repo raw / CDN) instead of embed -> 137MB (or 68MB fp16) download on first use. Breaks single-file wish but keeps app usable. Cache after first load.
- RECOMMENDATION: try fp16 first (chunk 2a) -> if ~68MB and quality holds, offer STB-VMM as a "High quality" neural option that loads-on-demand from URL (not embedded), keeping MagNet as the embedded default fast option. i.e. two neural models: fast(embedded MagNet 3.7MB) + HQ(STB-VMM, on-demand).

### Repro (container, deterministic ~2 min)
- pip install --break-system-packages torch(cpu) onnx onnxruntime timm numpy
- git clone github.com/RLado/STB-VMM ; download ckpt (release v1.0.0)
- STBVMM(img_size=256, manipulator_num_resblk=1); load state_dict dropping 'attn_mask' keys, strict=False
- wrap forward -> return y_hat[0]; inputs a,b [1,3,256,256] f32 in [-1,1]?? VERIFY STB-VMM normalization (check utils/data_loader.py ImageFromFolderTest preprocessing) BEFORE browser wiring — may differ from MagNet's /127.5-1.
- torch.onnx.export(opset 17, dynamo=False), inputs frameA,frameB,amp([1,1,1,1]).

### OPEN QUESTIONS for chunk 2
- Verify input normalization + amp shape/scale (data_loader.py).
- fp16 size + quality.
- ORT-Web perf for a 68-137MB Swin at 256 (likely slow, async so ok).

## CHUNK 2a (fp16 + normalization): DONE
- NORMALIZATION = IDENTICAL to embedded MagNet: in = px/127.5 - 1 ([-1,1], NCHW); out = clip(-1,1); (x+1)*127.5. Browser preproc reusable AS-IS.
- amp input shape = (1,1,1,1) [B,1,1,1] (run.py unsqueezes x3), NOT scalar [] like MagNet. Handle in wiring.
- fp16: 136.6MB -> 72.2MB. fp16 vs fp32 maxdiff 0.0035, mean 0.00045 on [-1,1] -> visually lossless. Embedded HTML ~97MB.
- DECISION (user runs locally, single-user): EMBED fp16 STB-VMM in the single HTML (~97MB ok). fp16 not fp32.

## CHUNK 2b (NEXT): embed + wire
- Regenerate fp16 onnx (recipe above) -> base64 embed like magnetB64 (2nd <script> tag, e.g. id="stbvmmB64").
- Wire as a SECOND neural model option: add a "Quality: Fast / High" toggle in the neural panel. Fast=MagNet(embedded 3.7MB, dynamic res). High=STB-VMM(embedded fp16, FIXED 256x256).
- STB-VMM specifics vs MagNet: (a) FIXED 256x256 input -> resize frame to 256x256 for inference, draw result scaled back (ignore detail slider for HQ, or letterbox-pad to 256). (b) amp tensor shape [1,1,1,1] not []. (c) output name 'out'.
- Perf: Swin at 256 will be much slower than MagNet (maybe 100s of ms - seconds). Async already handles it (UI stays 60fps, neural refreshes slower). Show ms/frame in status.
- IMPROVE base64 decode: current atob+charloop is slow for 97MB. Use fetch('data:application/octet-stream;base64,'+b64).arrayBuffer() for fast native decode, or chunked. Important so load 'runs well'.
