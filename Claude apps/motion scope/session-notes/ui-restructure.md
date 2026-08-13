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

## ZOOM: view-crop (zoom-only) DONE — CSS transform on view/viewGPU from cropRect; overlays auto-align via getBoundingClientRect; cropDrawMode + magnifier zoomBtn (🔍/⤢). TODO process-crop mode (re-derive procW/procH from crop aspect + cropped source into procSrcCv/_pvf, compose with stab) = the "ignore everything outside" toggle.

## ACCUMULATE method (branch: feature/accumulate, EXPERIMENTAL — not on main)
New method "Accumulate" (rail AC) — real-time frame stacking to denoise + brighten a STATIC-camera dark/noisy scene. Two sub-tabs planned: Stack (DONE) + Super-res/drizzle (placeholder, next).
- accumulateFrame(): draws raw video->proc, getImageData, sums into Float32 accBuf (RGB), accCount++. Frame-change hash (stride-97 sample) skips duplicate captures so √N count is honest. Auto-stretch: 256-bin luma histogram, 0.5/99.5 percentile lo/hi, per-channel (mean-off)*scale -> brightens dark scenes. Renders via dctx.putImageData. Validated in Node: √N denoise + full-range stretch.
- State: accBuf,accCount,accFrozen,accStretch,accLastHash. Reset on entering method.
- Loop dispatch after holdOrig (so C still compares stacked vs 1 raw frame), before neural; CPU-only (no GPU path reached).
- UI: Stack tab (frames+√N readout #accStatus, Reset/Freeze/Save-PNG, Auto-brighten On/Off). Super-res tab placeholder. updateTabAvailability hides settings/process/analysis/stabilize/smoothing/zoom for accumulate, shows stack/superres (+capture). refreshEngineUI hides viewIcons (A/M + zoom) for accumulate. setMethod switches to Stack tab + resets buffer.
- No alignment/stab (static camera). Known: fixed-pattern noise + hot pixels don't average out (noted in UI).
- Super-res (drizzle) DONE (Super-res tab). superResFrame(): global sub-pixel shift via iterative LK (srEstShift, whole-frame translation, ~0.1-0.2px accurate — validated), reject frames outside [srMinDrift,srMaxDrift] (Goldilocks gate), bilinear drizzle splat onto S× grid (srSplat, +(S-1)/2 centering), normalize acc/wt + percentile stretch (srRenderAndShow), drift meter canvas (drawSRMeter: too still/good/too much + px). Dispatch: activeTab===superres -> superResFrame else accumulateFrame. Validated in Node: drizzle RMSE 9.2 (bilinear) / 6.8 (nearest) vs 17.3 upscale on ALIASED input (box-averaged/anti-aliased input can't be recovered — needs sensor aliasing). Controls: 2x/3x grid, min/max drift sliders, reset/freeze/save-PNG, kept/total readout. Needs TEXTURE for alignment; CPU-heavy (may be <30fps at 3x). FUTURE: nearest-splat sharpness option (+holefill), pixfrac, clean-mean reference.
- FIX (super-res only denoised, no res gain): (1) grab was anti-aliased (imageSmoothingEnabled default true) -> killed the aliasing drizzle needs; now dedicated srCapCv/srCapCx grab with imageSmoothingEnabled=false (point-sample, preserves aliasing). (2) base was procW@targetH384 (linear profile); now decoupled srW/srH = min(videoHeight,SR_MAXH=540)*aspect -> higher base, 2x=1080p out. srSplat uses srW/srH. Readout shows output px + "Save to see full res (on-screen is fit-to-window object-fit:contain)". Display caveat: hi-res canvas fit-to-stage on screen, real res only in Save-PNG or on large display. 3x grid heavy (~4.6M cells).
- Convergence readout (Stack + Super-res): settleUpdate() computes RMS frame-to-frame change of the output luma (only when a frame is actually added), EMA-smoothed (pushSettle); settleText() shows absolute change-per-frame with status improving fast/improving/nearly there/settled + trend arrow. Answers "is it still improving / should I stop". Reset via settleReset() on reset btns / scale change / entering method. NOTE: measures output CHANGE (~1/N) not noise (~1/sqrt(N)); absolute thresholds tuned so "settled" ~ when marginal gain is small. Validated in Node (delta falls 14->0.05 over 400 frames, un-converges on disturbance).
- Finer grid: 2x/3x/4x buttons. Hi-res height capped bh=min(videoHeight,SR_MAXH,floor(1500/srS)) so 3x/4x stay tractable (<=1500 high). Finer grid needs more tap variety to fill (higher ceiling).
- Clean-reference re-alignment: srUpdateReference() box-downsamples the converged SR result (srBuf/srWt normalized luma) to base-res gray -> srRef; called at srAccepted 12,25,then every 40. Future frames align to the cleaned image instead of noisy frame#1. Validated: 61% lower alignment error (0.048->0.019px). Sets up IBP.
- NEXT (user most excited): IBP (iterative back-projection) as an ENHANCE button on the converged/frozen SR image. Simulate LR frames from SR estimate (shift+blur(PSF guess)+downsample), compare to real, back-project error, iterate. Needs rolling buffer of recent aligned frames + PSF (assume small Gaussian) + strength dial. Deconvolves camera blur — real info recovery, NOT unsharp (user explicitly rejected cosmetic sharpening). Do AFTER denoise (noise amplification). Honest ceiling: PSF is guessed.
- GRID ARTIFACT AUDIT: srSplat indexing correct (no bug). Grid = coverage unevenness: 2x weight CV~0.08 (smooth) but 3x/4x CV up to 0.51 with small taps (visible grid) + per-cell noise in dark scenes. FIX: confidence-blend gap fill in srRenderAndShow — cells with wt>=0.8*avg stay sharp (early-out, keeps 2x fast), sparse cells blend toward 3x3 neighborhood-normalized value (blur(acc)/blur(wt)). Validated Node: grid 10->7.3, detail err 10->7.5 (both improve). Added srCoverage = % cells fully resolved -> readout "X% resolved" (tap variedly to raise). Dark scene IS a factor (noisy align + noisy samples). srFillBuf scratch (HN*3).
- REGRESSION FIX: prev gap-fill (3x3 box) spread sparse samples into flat SxS BLOCKS -> "bigger pixels"/more pixelated than raw, esp 3x/4x low-coverage. FIXED: fill sparse cells from a BILINEAR upsample of the low-res base mean (srBaseA/srBaseW downsample of acc/wt), never blocky. Covered cells stay sharp (early-out). Validated Node: bilinear-base RMSE 2.98 vs 3x3-box 11.00 on sparse S=3. So low coverage -> clean smooth upscale (>= raw); high coverage -> real resolve. % resolved tells user to tap more.
- ROOT CAUSE of "super-res worse than source": full-frame super-res of a HIGH-RES source is fundamentally pointless — we downsampled videoHeight->540 base then upscaled 2x, can only recover what we discarded (never beat native). Super-res needs an UNDER-sampled/aliased target. FIX: superResFrame now branches — if cropRect active, grab the crop region at NATIVE pixel density (1:1, imageSmoothingEnabled=false only matters when downsampling; native crop = real pixels), base=crop native (capped maxBase=1500/S); else full-frame smooth downsample (imageSmoothingEnabled=true -> clean denoise, no alias artifacts). So super-res the ZOOMED region (small under-resolved target = plate/sign) = real gain; full-frame = just denoise + hint to zoom. applyStab excludes super-res from CSS crop transform (it re-processes the crop instead). Readout shows Region-mode/native vs full-frame hint. srIsNative state.
- Guidance: A6500 full-frame already well-sampled -> use Stack for denoise; Super-res only for under-resolved crops/low-res sources.
- RESEARCH (Wronski/Google Pixel Super-Res Zoom, IPOL, MFSR-GAN): classical MFSR gain is ~1.5x and comes from RAW/Bayer (skip demosaic) — we have demosaiced RGB video so the main lever is gone; SOTA nice results are NEURAL (hallucinate). Best honest classical = steerable kernel regression + robustness model.
- IMPLEMENTED option #1 (replace bilinear splat): srSplat now = anisotropic kernel regression (structure-tensor steerable Gaussian per base pixel via srUpdateReference: narrow across edges/sharp, wide along/clean, wider on flat/denoise; srKa/srKb/srKc inverse-cov; srExpLUT) + ROBUSTNESS (per-sample weight = exp(-(gray-srRef_aligned)^2/(2*40^2)), rejects misaligned/moving/occluding frames). Validated Node: kernel~=bilinear on perfect-align reconstruction (RGB limit confirmed), but robustness = 3x cleaner (rmse 30.9->10.1) with 30/130 corrupted frames. COLOR-DRIFT FIX: auto-stretch lo/hi now EMA-stabilized (srLo/srHi, 0.04) -> no per-frame contrast/hue drift. Perf: kernel splat R=2 heavier than bilinear (fine for crops, slow full-frame).
- RESOLUTION CAP FIX (full-frame less sharp than zoom-crop): Stack + full-frame super-res were capped at the magnification base (targetH 384 stack / SR_MAXH 540), while zoom-crop grabs native -> that is why cropped regions were sharper. FIX: Stack now grabs at NATIVE (accCapCv/accCapCx, ah=min(videoHeight,ACC_MAXH=1440)) instead of procW/procH 384 -> full-res denoise. Super-res full-frame base cap 540->750 (grid cap 1500/S still bounds). C-compare (hold-C) in accumulate now native too (full frame, or crop region for super-res). Zoom-crop unchanged (already native, best for max region detail). Save = view.toDataURL = canvas internal res (now higher). Note: full-frame super-res still can not ADD res (RGB limit); crop for real gain. Mem: stack accBuf up to ~44MB (4K->1440).
- IBP (iterative back-projection) DONE — Enhance button in Super-res tab. Rolling frame buffer srFrames (last 16, region crops only, base<=SR_IBP_MAXPIX 210k). srEnhanceIBP(): X=srBuf/srWt normalized; per iter (7) forward-simulate each stored frame (gaussian PSF sig=srIbpPsf sample of X at shifted hi-res pos via srExpLUT), error=frame-sim, back-project (same gaussian), X+=beta*err/bpW, clamp. Non-destructive -> srIbpOut + srEnhanced flag; srRenderAndShow shows srIbpOut when enhanced; cleared on resume-accept/reset. Controls: Enhance strength (beta srIbpStrength), Detail (sharpness -> PSF sig=1.25-val/100). Validated Node: rmse 23.1->15.6, sharpness 46.9->54.3 toward GT 64.5; too-sharp PSF over-corrects (18.1) -> Detail slider matters. Honest: modest-to-strong, not neural magic; region crops only; a few sec compute (button shows Enhancing).
- IBP NO-EFFECT BUG: SR_IBP_MAXPIX was 210k but crop base up to 750x750=562k -> most crops stored 0 frames -> Enhance silently did nothing. FIXED: SR_IBP_MAXPIX 210k->620k. Clearer failure message. (Enhance sliders are apply-on-click by design.)
- REAL RESOLUTION METRIC: added srPhase (S x S sub-pixel slot histogram) + srPhaseCov = fraction of slots with >=3 samples, using round-to-nearest-slot binning phx=((round(-dx*S)%S)+S)%S (boundary-safe: still-camera +-noise stays in slot0, not straddling). Readout %resolved now = srPhaseCov (was weight-based srCoverage which read ~50-100% even still). Validated: 2x still 25%/varied 100%, 3x still 11%, 4x still 6%/varied-many 100%. settleText labeled '(noise)' to distinguish noise-convergence from resolution. Addresses user: still camera now reads low % resolved (drift gate also rejects still frames as too-still).
- CONFIRMED crop alignment is crop-only: cropRect is video-normalized (stageToNorm letterbox-aware); super-res grabs only the crop region. Head-wiggle outside crop not aligned on (was noise/lighting).
- PRE-TEST AUDIT: (a) IBP X-init used acc/wt directly -> uncovered cells were BLACK holes -> deconvolution would ring on sparse crops; FIXED: X init now gap-fills holes via base-mean bilinear upsample (matches render). (b) IBP could freeze UI many seconds on huge crops; FIXED: adaptive frame cap nUse=clamp(2.5M/(w*h),6,16) so big crops use fewer frames (~3s max). (c) srCoverage now dead (readout uses srPhaseCov) - harmless. Verified: render restructure braces/scoping correct, whole-script braces/parens/brackets all balance (0/0/0), 17/17 details. Known/acceptable: IBP on max ~620k crop ~250MB transient + few-sec freeze (Enhancing shown); Enhance in full-frame -> informative message (no frames).
- 2ND AUDIT: fixed enhance-transition issues — (i) settle-delta compared enhanced vs last accumulated frame (spurious noise spike) -> srAdded=false before enhance render; (ii) auto-stretch EMA drifted accumulation->enhanced histogram (contrast creep) -> srLo=srHi=-1 on enhance so it re-seeds clean; (iii) Detail slider default 65(sig0.60) mismatched state sig0.55 -> slider 70; (iv) stale srEnhanced on base reinit -> cleared in init branch (was length-guarded). Verified: IBP fwd/back math correct (shift dir, LUT idx, normalization), buffers cleared on reinit (no size mismatch), braces balance, end-to-end IBP NO NaN + rmse 8.72->6.00. Accepted: full-frame kernel path slow (deprioritized), IBP max-crop transient ~few hundred MB.
- FULL-FRAME vs ZOOM-CROP RESOLUTION GAP (user: crop 2-3x sharper): audit confirmed it is (a) full-frame DOWNSAMPLING (4K->1440 stack, 4K->750 SR) = avoidable + (b) the super-res xS grid applied to a native crop region = intended (crop dedicates budget to region). FIX (a): ACC_MAXH 1440->2160 (Stack native to 4K); full-frame SR base decoupled cap ffMax=1800/S + SR_MAXH 750->900 (crop cap stays 1500/S so IBP unaffected). After: 4K 30% region Stack 432->648 native, zoom-crop advantage now 2.0x = pure super-res grid (legit, not a bug). Guidance: Stack for whole scene (now native), zoom-crop for max region detail. Note: 4K stack ~200MB buffers + full-frame SR at 900 base slower (deprioritized). No save bug (toDataURL = canvas internal res).
- USER APPROVED merge. Pending confirm -> then merge feature/accumulate to main.

## IDEA BACKLOG (brainstormed, not started) — added 2026-08-12:
Measurement: operating deflection shapes / mode animation; order tracking (RPM + 1x/2x/3x harmonics);
beat/difference-frequency finder; coherence map (regions correlated with a clicked reference point);
displacement/velocity/acceleration toggle (g-units).
Perception: difference-from-baseline (capture healthy ref, highlight what changed); motion history /
temporal echo trail; selective freeze (freeze all except chosen band).
Instrument: session recording + measurement timeline scrubber; threshold alarms (freq/amplitude limit
alerts); A/B compare view (two states, overlaid spectra); saved calibration profiles.
Input/reach: two-camera / stereo depth; high-speed / phone slow-mo import (raise Nyquist ceiling past
60-120Hz); strobe mode (sample near vibration freq to freeze fast motion).
Playful: vibration spectrogram waterfall (see+hear); guitar/string tuner (pitch from plucked string).
Earlier list (still open): rPPG pulse/respiration vitals; motion vector-field overlay; ghost/trail
extremes; slow-mo synthesis; save/load presets; snapshot/report export; guided modes; region-based
magnification; visual-microphone audio recovery; Riesz->Warp cascade; phase-limit slider; frequency-map
DONE, vibration-map DONE, vibrometry DONE, phase-relationship DONE. BATCH stabilization still parked.

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
