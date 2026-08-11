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

## DONE — layout pass 2: panel TABS + polish (pushed to main)
- `.rail` is now flex-row: vertical `.tabstrip` (6 tabs) + `.tabcontent` (#tabcontent) holding the groups.
- Tabs: Capture / Settings / Process / Analysis / Stabilize / Smoothing. `setTab(t)` shows/hides
  `#tabcontent > .group` by `data-tab`. `activeTab` state. Tab buttons wired.
- Split old Capture group into: Source (data-tab=capture), Detail (capture), Processing (record+
  process+pvDialog), Stabilize. Settings holds neuralGroup + Magnification + Warp field. Analysis=
  Frequency. Smoothing=Smoothing. Every `<details class="group">` has a data-tab.
- Neural panel visibility = (activeTab==='settings' && method==='neural') via `updateNeuralGroupVis()`
  (called from setTab, refreshEngineUI, setMethod). Picking Neural auto-switches to Settings tab.
- Polish done: colored header bar on `details.group>summary` (bg var(--panel-2), padding, border,
  radius), bigger/brighter `.group h3` (.76rem, --ink, 700), tabcontent gap 1.5rem.

## POSSIBLE NEXT / REFINE (user to react)
- Tab labels are plain text in a 60px strip; could add small icons per tab (Blender-style).
- Icons in the far-left method/view rail are still first-draft placeholders.
- Verify each tab shows the right controls; Process tab's Record works on live too; Detail slider.
- Consider: does the reset-baseline belong in Capture/Detail or Settings? Currently in Detail(capture).

## (old plan below, now done)
### NEXT — layout pass 2 (was): panel TABS + polish
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

## AUDIT PASS (done, pushed)
- No orphaned refs to removed elements (startBtn/stopBtn/methodGroup/neuralPanel/modeIsolate/
  modeWarp/viewGroup/seekEl/timeVal/playPauseBtn all 0).
- Neural gating: hidden for AI = freq band, color, scale, velocity/accel, temporal denoise, spatial
  denoise. Only Gain + neural picker apply. Also HIDE Stabilize + Smoothing tabs when method==='neural'
  (updateTabAvailability(), auto-switches to Settings if a hidden tab was active). NOTE: neural path
  (grabTensor) uses the RAW frame — does not apply stabilization; could be a future feature.
- velocity/acceleration correctly shown for Linear/Phase/Riesz (accelMode used in GPU rzPhaseUni + CPU
  fc path); not neural/warp/isolate.

## PARKED
- θNet fixed 1280 (frame-packing done for batch). Dynamic-res STB-VMM (1 model any size, 191→~100MB)
  = parked/risky. GeoMag 2026 = Mamba/SSM, won't convert to ORT-Web — advised against.

## WORKFLOW
Repo Theory-box/Claude-Relay; feature branches for active work, main clean. Output: chat for
conversation; the ~191MB single HTML via present_files only (never render in chat). Don't expose
git/token/paths in chat.

## FUTURE IDEAS (user backlog — not started, for whoever picks this up)
- Directional motion marker: let the user drop a point on the scene and show an arrow indicating
  the direction that spot is moving.
- Expand the Analysis tab with real graphs (the current FFT readout is too basic). Goal: select a
  region (e.g. a person's head) and get a proper live frequency graph — e.g. derive heartbeat from
  subtle head-bob motion. (This is the classic "Eulerian video magnification for vital signs" use
  case — pulse from micro-motion/color.)
- User is surveying other motion-magnification apps for more ideas; expect incremental requests.
- Possible: make the neural path use the stabilized frame (currently it uses the raw frame).
- Possible: minor UI polish (tab icons, finalize the placeholder-derived rail labels if desired).

## STATUS: Point tracker v1 built (pyramidal inverse-compositional LK). Track tab: Add point (click
video, up to 8) / Clear. Overlay = marker+trail+velocity arrow on #trackLayer; per-point dominant Hz +
confidence in #trkStatus. Module lives after the region-resize listener; trackTick() hooked into
drawReadout(); trackers cleared on stop(). Sample rate = sampleFps. NOT YET: Kalman smoothing,
phase-fusion, frequency-consensus audit, re-lock. Then feature-based stabilization reuses this LK.

## NEXT BUILD PLAN (agreed): Lucas-Kanade tracking -> point tracker + feature stabilization
Shared core = **pyramidal Lucas-Kanade (KLT)**: solve a 2x2 least-squares from image gradients
(Ix,Iy,It) for a small window's (dx,dy); coarse-to-fine pyramid for larger motion. ~100 lines CPU JS,
runs on the grayscale frame we already compute. No model. Build order (each reuses the last):
1. LK core (pyramidal, per-window (dx,dy) with iteration + confidence).
2. **Point tracker**: user drops marker -> LK follows it sub-pixel -> outputs (a) direction arrow
   from recent velocity, (b) displacement-vs-time -> FFT -> real frequency graph. Wires into the
   Analysis tab + the marker backlog idea. Serves the heartbeat-from-head-bob case.
3. **Feature-based stabilization**: Shi-Tomasi corner detect -> LK-track all corners -> RANSAC-fit a
   global transform (similarity: translation+rotation+scale, or homography) -> warp to cancel.
   Replaces/augments current translation-only grid block-match; handles rotation + zoom-wobble.
   Feeds every method (better input downstream). The tracked points can serve BOTH stabilize + analysis.
Caveats: LK drifts/loses on low-texture/occlusion (add confidence + re-lock); good for small stable
motion (vibration), weaker on erratic motion. Feature-stab warp must avoid artifacts (iterative).
Don't chase heavyweight learned flow (RAFT etc.) — same browser-conversion wall as GeoMag.
