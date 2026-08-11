# Motion Scope — UI restructure (continuation notes)

## STATE: everything is merged to `main` and pushed. `main` is the live build.

## App
Single file `Claude apps/motion scope/motion_scope.html`. Real-time + offline motion
magnification in-browser (webcam/screen/video). Engines: Linear, Phase, Riesz (WebGPU+CPU),
Neural (4 ONNX models), Warp, Isolate. FFT analysis, region stabilization, Process-video
offline batch → WebM, θNet frame-packing (2×/4×).

## BUILD & DELIVER (important)
- Repo HTML has EMPTY base64 tags `<script id="stb128B64|stb256B64|tnetB64">` (magnetB64 IS
  embedded, ~5MB). Models in `models/`: magnet.onnx, stbvmm_128/256/512_fp16.onnx, tnet.onnx.
- Deliver = clone, embed base64 of stbvmm_128 + stbvmm_256 + tnet into their tags →
  ~191MB HTML → write /mnt/user-data/outputs/motion-scope.html → present_files. (512 not used live.)
- Validate EVERY edit: awk '/<script>/{f=1;next}/<\/script>/{f=0}f' motion_scope.html > /tmp/x.js && node --check /tmp/x.js
- Container: pip install --break-system-packages ; ~3.9GB RAM.

## DONE — behavior pass
- GPU ON by default (useGPU=true; auto-inits in onSourceReady if navigator.gpu).
- Start/Stop removed → toggling source buttons: liveBtn/screenBtn/openFileBtn each start their
  source and flip to red "Stop" while active. State: `activeSource` (null|'camera'|'screen'|'file')
  + `updateSourceButtons()`. .stop class = red (button.act.stop).
- Warp + Isolate are now METHODS (were View modes). View hides when they're selected.
- "Smoothing & noise" → "Smoothing". Stabilize-strength slider clipping fixed.

## DONE — layout pass 1 (icon rail)
- `.wrap` grid is now `auto 1fr 340px` = [toolrail | stage | panel(.rail)].
- Far-left `.toolrail` / `#toolrail`: 6 method icons (ids mLinear/mPhase/mRiesz/mNeural/mWarp/mIsolate)
  + `#viewIcons` (modeAmp/modeMotion). SVG placeholder glyphs. Active highlights phosphor.
- Instant tooltips: `.tricon::after{content:attr(data-tip)}`; each button has data-tip + aria-label.
- Neural relocated to its own `#neuralGroup` panel (display:none, shown when Neural selected).
- METHOD/VIEW LOGIC IS MODULAR — route everything through these (icon rail is wired to them):
  `pickEngine(e)` , `pickView(v)` , `refreshEngineUI()` (sets button aria-pressed by id,
  toggles #viewIcons for warp/isolate, toggles #neuralGroup for neural). `lastView` tracks amp/motion.

## NEXT — layout pass 2 (NOT started): panel TABS + polish
User wants Blender-style vertical tabs on the panel + clearer separation.
- Tabs to build: Capture / Settings / Processing / Analysis / Stabilize / Smoothing.
  Add a vertical tab rail (panel's left edge or top), tag each `<details class="group">` with a
  data-tab, show/hide by active tab.
- CURRENT panel groups (in `.rail`, order): Capture (~L125: source buttons + resolution +
  STABILIZE controls + fileCtrls[Record + Process-video]); neuralGroup (hidden); Magnification
  (gain/band/per-method sliders); Warp field; Smoothing; Frequency analysis.
- Group→tab mapping (SOME HTML MUST BE SPLIT — Capture currently bundles sources+stabilize+processing):
  Capture = sources + resolution ; Stabilize = the stabilization block (split out of Capture) ;
  Processing = Record + Process-video (split out of Capture's fileCtrls) ; Settings = Magnification
  + Warp field + neuralGroup ; Analysis = Frequency analysis ; Smoothing = Smoothing group.
- POLISH (user complaints): more space between panels; bigger labels WITH padding; a colored
  header row on each group summary (currently `.group h3` = .7rem muted, `details.group>summary`
  plain — give a bg header bar, bigger/brighter label, more padding); ".rail gap" is 1.1rem.
- Palette vars: --bg #0b0f14, --panel #131a22, --panel-2 #1b2430, --line #26313f, --ink #e8eef4,
  --muted #8ea0b2, --phosphor #39e6c4 (accent), --amber #f2a63b, --hot #ff5d73.
- Rail icons are first-draft placeholders (user OK, may refine later).

## PARKED
- θNet fixed 1280 (frame-packing done for batch). Dynamic-res STB-VMM (1 model any size, 191→~100MB)
  = parked/risky. GeoMag 2026 = Mamba/SSM, won't convert to ORT-Web — advised against.

## WORKFLOW
Repo Theory-box/Claude-Relay; feature branches for active work, main clean. Output: chat for
conversation; the ~191MB single HTML via present_files only (never render in chat). Don't expose
git/token/paths in chat.
