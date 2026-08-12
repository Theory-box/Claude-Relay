# Motion Scope — UI restructure (continuation notes)

## STATE: everything is merged to `main` and pushed. `main` is the live build.

## ===== CURRENT-STATE SNAPSHOT (2026-08-12, after 4 audits) =====
Single-file in-browser motion magnification app. Stable base; 4 audit passes done (bugs fixed early,
now clean). Build/deliver: edit `motion_scope.html` via targeted python string-replaces → validate
`node --check` on the extracted <script> → commit+push main → rebuild the ~191MB single file by
base64-embedding stbvmm_128/256 + tnet into their empty <script> tags → /mnt/user-data/outputs →
present_files. (magnetB64 already embedded in repo; 512 model committed but unused live.)

### Magnification methods (far-left icon rail, 2-letter labels): Linear(LI) Phase(PH) Riesz(RI, real
MIT GPU+CPU) Neural(AI, 4 ONNX models) Warp(WA) Isolate(IS); views Amplified(A)/Motion(M). Smart
per-method control visibility (Neural hides freq/color/scale/denoise/velocity; Stabilize+Smoothing
tabs hidden for Neural). Tabbed panel: Capture/Settings/Process/Analysis/Stabilize/Smoothing.
### Neural: ORT WebGPU→WASM, models MagNet / STB-VMM 128 / STB-VMM 256 / theta-Net; residual "Sharp"
mode; theta-Net frame-packing 2x/4x for offline. Offline "Process video" → WebM (2 paths, both
memory-capped ~600MB).
### TRACKING (validated on synthetic ground-truth in Node): pyramidal inverse-compositional
Lucas-Kanade. TWO independent point trackers, separate sets, no cross-use:
  - Analysis (Analysis tab): circle markers, report frequency (FFT), NEVER warp. Own Add/Clear.
  - Stabilize points (Stabilize tab): square markers, drive the warp only. Own Add/Clear.
  Add point button turns GREEN in placement mode; RIGHT-CLICK a marker deletes it (in placement mode).
### THREE independent stabilizers (each own on/off, combinable):
  1. Region (translation block-match; On=auto whole-frame, draw a box to target; accX/accY).
  2. Stabilize-to-points (sTrackers → fitSimilarity → _stabM; 1pt=translation, 2+=rotation+zoom).
  3. Auto (Shi-Tomasi corners → LK-track → RANSAC similarity → _stabM; rejects moving objects;
     green=trusted grey=rejected dots). Auto takes precedence over points for _stabM.
### Pre-stabilization (DEFAULT): stabilize the input BEFORE amplify/analyze. Toggle Input(pre)/View
(post cosmetic CSS). preFrame() warps raw→procSrcCv using last frame's _stabMApplied (1-frame lag);
GPU reads via VideoFrame (gpuSrc), CPU/neural read procSrcCv (frameSrc), analysis reads analysisSrc
(On stabilized / On raw toggle). Region estimator reads frameSrc.
### Stabilizer smoothing slider + deadband (kills fit-noise jitter; validated). Live accuracy readout:
"Raw X → Stab Y px/f (↓Z%)" green=reducing red=adding — the helping/hurting signal.

## AUDIT RESULTS: P1 fixed metric (was comparing transform to itself). P2 fixed stop() stale
transforms + VideoFrame leak + autoStab toggle desync. P3 removed dead code (blockSadRef,
compositeCompare, fieldAt, rzBiquad, slowX/slowY). P4 clean (concurrency/cleanup/memory all sound).

## IN PROGRESS — Tracker refinement (agreed priority #1): 1a DONE = predictive coast-through
(alpha-beta in trackOne, toggle trkPredict default on; t.kx/ky/kvx/kvy/coast state; faithful when
conf high, coasts when conf<0.15 or oob, lost only after coast>18). NEXT: 1b freq-consensus audit
confidence, 1c auto re-lock; then mask, layering, analysis graphs, batch.

## LAYERING (partial): per-stabilizer intensity (regionInt/pointsInt/autoInt, scaleT) DONE. Points+Auto
compose via buildComposedStabM (scaled, ordered by prPoints/prAuto, composeT). Region = outer shader
layer scaled by regionInt at application (accX*regionInt). TODO: full 3-way reorderable cascade
(region into the middle) needs per-layer intermediate-frame tracking.

## BACKLOG STATUS (updated):
- DONE: tracker refinement 1a (predictive coast-through) + 1b (frequency-consensus/coherence audit);
  corner-detection mask (Auto); analysis measure-on Raw/Amplified/Stabilized (independent); stabilizer
  intensity + full 3-way layer ordering (Region/Points/Auto); analysis graphs (Spectrum + Waveform).
- PARKED (user said hold off for now): BATCH stabilization — apply stabilization + all live settings to
  offline Process-video exports (needs per-seeked-frame track+warp in the batch pipeline).
- POSSIBLE FUTURE: tracker phase-fusion (fuse LK with Riesz phase, the hard one, deferred); full
  per-layer cascade so Points/Auto also build off each other (currently both track raw, composed);
  vibrometry in real units; directional-motion arrows on analysis points.

## (old) BACKLOG (agreed, not started):
  - Corner-detection MASK (paint where Auto looks) — nice extra; RANSAC already rejects movers.
  - Stabilizer LAYERING: choose ORDER (region/points/auto) + per-stabilizer INTENSITY sliders; combine.
  - BATCH stabilization: Process-video should apply stabilization + all live settings offline (needs
    per-seeked-frame track+warp in the batch pipeline).
  - Tracker refinement: Kalman on the STAB transform (not analysis pts), phase-fusion, freq-consensus
    audit for robust confidence + occlusion coast-through.
  - Analysis graphs: real frequency plots (heartbeat-from-head-bob), directional arrows, vibrometry.
  - Minor: tab icons; deadband still builds an identity VideoFrame (harmless).
## ===== END SNAPSHOT =====


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

## AUDIT 3 (2026-08-12): removed dead code (technical debt) — functions blockSadRef, compositeCompare,
fieldAt, rzBiquad (defined, never called; leftovers from earlier implementations) + vestigial slowX/slowY
vars. Verified region-stab + render chains intact. Event listeners (3 pointerdown, 2 pointerup, 2 resize)
all mode-guarded, no conflicts. BACKLOG (agreed): batch Process-video should eventually apply
stabilization + all live settings (needs per-seeked-frame track+warp in the batch pipeline).

## AUDIT (2026-08-12): fixed metric _stabMAppliedPrev ordering (was comparing transform to itself);
fixed stop() to clear stale _stabM/_stabMApplied/_sm and close the _pvf VideoFrame + keep autoStab
consistent (re-detect on new source, no button desync). KNOWN LIMITATION: batch (Process video) reads
raw frames — does NOT pre-stabilize (separate pipeline; would need per-seeked-frame track+warp).
Deadband snaps to identity but still builds an (identity) VideoFrame — harmless minor overhead.

## STATUS: THREE independent stabilizers now — Region (accX/accY translation, whole-frame or drawn
region), Point markers (sTrackers -> fitSimilarity -> _stabM), and Auto (Shi-Tomasi corners +
LK-track autoCorners + RANSAC autoFit -> _stabM). Marker+Auto share the _stabM warp path (preFrame
pre / applyStab post) + stabMode + stabActive(). Auto takes precedence over markers for _stabM.
Pre-stabilization: preFrame() warps input into procSrcCv; GPU reads via VideoFrame (gpuSrc), CPU/
neural read procSrcCv (frameSrc), analysis reads analysisSrc (stab/raw toggle). FUTURE (user asked):
mask for corner detection region; layering ORDER control + per-stabilizer INTENSITY sliders; combine
all three in a chosen order. Also still pending: Kalman + phase + freq-audit tracker refinement.

## STATUS: + tracked-point stabilization built. Track tab has Stabilize off/view. fitSimilarity()
(Umeyama, current->initial, validated 0px residual) + applyStab() warps view/viewGPU/#trackLayer via
CSS matrix (transformOrigin 0,0 for canvases; R.left,R.top for the stage-sized overlay). Toggle=stabView.
This stabilizes the DISPLAYED view (post-process). NEXT could be PRE-stabilization (warp raw frame
before magnify) + auto Shi-Tomasi corners + RANSAC for robustness. Also still pending: Kalman + phase +
freq-audit refinement of the tracker.

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
