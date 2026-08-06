# Session notes — Motion Scope

**Branch:** `main` (user granted direct-to-main for the initial drop)
**Folder:** `Claude apps/motion scope/`

## Goal

Real-time Eulerian Video Magnification the user can run against a DSLR-as-webcam
feed, to sit on a back porch and watch amplified motion of trees, birds, and
insects. Curiosity / play project.

## Decisions made

- **Algorithm: linear (amplitude-based) Eulerian, two-EMA temporal bandpass.**
  Per pixel, two exponential lowpass filters (slow + fast); amplified output is
  `x + gain*(fast - slow)`. Chosen over a full complex-steerable-pyramid
  phase-based EVM because it runs comfortably at frame rate in plain JS and
  matches the user's mental model (offset frames, overlay, amplify). No spatial
  pyramid — downscaling provides the spatial smoothing / noise reduction instead.
- **Cutoffs exposed as Hz**, converted to IIR alpha per frame from live fps:
  `alpha = 1 - exp(-2*pi*fc/fps)`. Lets the user tune to motion frequency
  (sway vs wingbeat) rather than abstract smoothing constants.
- **Processing at reduced resolution** (192–640p, default 384p) into Float32
  state buffers, upscaled to the display canvas. Keeps it real-time and doubles
  as denoise.
- **Two views:** Amplified (boost over real image) and Motion-only
  (`128 + gain*band` on grey).
- **Delivery: single self-contained HTML**, both as a Claude artifact and as a
  repo file. Standalone `file://` won't get camera in Chrome — documented the
  https / local-server requirement in the README.

## Open questions (unanswered by user)

- Shooting distance / focal length for the tree setup — affects how much detail
  vs smoothing to default to.
- Priority: slow sway vs fast wingbeat/vibration — would change default cutoffs.
  Current ship default: low 0.5 Hz, high 6 Hz, gain 18.

## Verified

- **Camera works inside the Claude artifact sandbox.** Earlier concern (~60%)
  that the sandbox iframe might block `getUserMedia` did not hold — user
  confirmed live use. First call may need one retry after the permission prompt.

## Noise reduction pass (added)

User reported heavy noise, especially coloured confetti, on an a6500 in remote/
webcam mode. Diagnosis: most noise is real and enters via the camera's live feed
(downscaled, compressed, reduced in-camera NR, likely high ISO in a shaded
scene). Our linear/intensity EVM then amplifies in-band temporal noise with the
same gain as signal — expected, not a bug.

Two standard, low-risk controls added (both slider-controlled, non-destructive):

- **Color (chroma) slider, default 20%.** Motion signal blended toward luma
  (`0.299R+0.587G+0.114B`); at 0% all channels share one brightness-driven motion
  term, so no hue shifts → coloured confetti gone. 100% = old per-channel
  behaviour. Kept 3-channel filter state so full-colour is still available.
- **Smoothing (spatial denoise) slider, default 1 px.** Separable edge-clamped
  box blur applied to the amplified-motion buffer only, before recombining, so
  the static base image stays sharp. Radius 0–4.

Implementation: processFrame refactored into three passes (bandpass→mBuf,
optional blur, recombine). Added mBuf/mTmp Float32 buffers in allocBuffers.
Energy meter now computed on luma. JS syntax-checked clean.

Deliberately did NOT add heavier edge-preserving denoise (bilateral/NLM) — user
wants nothing that looks artificial, and these two cover the reported symptoms.

## Open interaction to remember

Lifting the processing-resolution cap will *increase* noise as things stand,
because downscaling is currently an implicit denoiser. Add/relies-on spatial
smoothing first, then raising resolution is safer. Camera→Mac output resolution
is being handled in a separate conversation.

## Possible next steps

- Optional spatial blur / pyramid level to cut amplified sensor noise further.
- Frequency presets (buttons) for sway / wingbeat / vibration.
- Record or snapshot the amplified output.
- Region-of-interest mask so only a selected patch is amplified (isolate one
  branch or one insect, ignore background wind).

## Multi-method pass (added)

Added three noise/method options at user request (phase-based, temporal denoise,
spatial pyramid). Neural-net magnification explicitly deferred.

- **Temporal denoise** — motion-adaptive recursive IIR NR on the input, in place
  on the frame before magnifying. `kStatic = 1 - 0.92*strength`; per-channel
  motion weight `w = clamp(|x-state|/thresh)`, `k = kStatic + w*(1-kStatic)`.
  Not true motion-*compensated* (no optical flow) — motion-*adaptive*, which is
  the right fit for a tripod (mostly-static frame). Denoised frame feeds both
  base image and magnifier. High confidence.
- **Spatial scale** — genuine pyramid coarsening via 2^level block-average of the
  motion buffer, then optional Smoothing to de-block. Amplifies coarse scale =
  drops fine sensor noise. High confidence.
- **Phase (beta)** — single-scale Riesz. Y -> lowpass -> band B=Y-Lo -> Riesz
  R1,R2 (3-tap central diff) -> local phase psi=atan2(|Riesz|,B), amplitude A ->
  two-EMA temporal bandpass of psi -> amplitude-weighted spatial smoothing
  (blur(A*band)/blur(A)) -> clamp -> phase-shift reconstruct
  B'=B cos(dPhi) - |Riesz| sin(dPhi) -> add luma delta to all channels.
  Confidence first-try-correct ~50%; can't verify visually here. Labelled BETA
  in UI. Known simplifications: single scale (favours fine motion); psi is
  unsigned [0,pi] so motion-direction sign can be imperfect; brief transient on
  method switch (phase state seeds to 0). Likely needs a tuning round with user.

Buffers added in allocBuffers: tnrState (RGB), Yb/Lo/Bb/R1/R2/Ab/phSlow/phFast/
gTmp/gTmp2 (gray). Color field dims in UI when Phase selected. JS syntax-checked.

## For next session

If Phase looks wrong/janky: first suspects are the psi sign/orientation handling
and the gain->radian scaling (currently reuses the linear gain slider, clamped to
±1.4 rad). A signed phase (project Riesz onto a stable orientation) would fix
direction artifacts. A 2–3 level phase pyramid would add coarse-motion support.
Consider WebGL if plain-JS phase can't hold frame rate at useful resolution.

## Phase method rewrite (bug fix)

First phase attempt was fundamentally wrong: it used intra-frame
psi = atan2(|Riesz|, B), which encodes edge-ness (static), not motion. Symptom
reported by user: mostly grey, faint static outlines, motion (hand wave) barely
visible — i.e. amplified term ~0.

Rewrote using the correct inter-frame quaternion phase difference:
  qRe = B*Bp + R1*R1p + R2*R2p
  qI  = R1*Bp - B*R1p ;  qJ = R2*Bp - B*R2p
  phi = atan2(|(qI,qJ)|, qRe) ; orientation (cx,cy) = (qI,qJ)/|.|
  motion (mx,my) = phi*(cx,cy)
Then per-axis two-EMA temporal bandpass -> amplitude-weighted blur
(blur(A*m)/blur(A)) -> amplified shift (sx,sy), clamp |shift|<=1.2 rad ->
phase-shift band: bNew = B*cos(psi) - (R1*ux+R2*uy)*sin(psi) -> add luma delta.
Keeps previous-frame monogenic in Bprev/R1p/R2p (also reused as blur scratch,
then overwritten with current at end). First frame stores reference, emits none.

Expectation set with user: phase is for SMALL sub-pixel motion (pulse, vibration,
breathing), NOT large motion like hand waves or birds — that's Linear's domain.
Still single-scale, still beta, still blind (not visually verified). If it's still
weak: check gain->radian scaling and whether a 2-3 level pyramid is needed for
coarser motion. Direction now handled via oriented (qI,qJ), so the grey-out bug
should be gone.

## Phase fix #2 — accumulate phase before band-pass

Root cause of "grey / looks like a static high-pass, no visible amplification":
we band-passed the per-frame phase DIFFERENCE (mx,my) directly. That difference
is the temporal derivative of phase, so band-passing it applied an extra d/dt,
attenuating the slow subtle motion the method targets and leaving only faint
high-freq edge noise. Fix: accumulate Pxa+=mx, Pya+=my into a running phase, then
two-EMA band-pass the accumulated phase. Slow-EMA removes accumulator drift, so
no unwrapping needed. Added Pxa/Pya buffers, zeroed on phase init.

Decision point set with user: if a deliberate small vibration (flicked ruler
clamped to desk, table tap, or face-held-still pulse) still shows nothing, we drop
phase — Linear + temporal denoise already covers the actual porch/birds use case.

## Isolate view (added)

Third View option "Isolate": slow per-pixel background EMA (aBg=0.03) learns the
static scene; output = gain*|current - bg| clamped, on black. Reuses spatial
scale + smoothing for denoise, and the Amplification slider for brightness.
Bypasses Linear/Phase when active. bgModel buffer seeded in seed(); re-converges
~1s after switching in. Limitation (told user): lingering smoke slowly bakes into
bg and fades; frame-difference shows presence/edges, not flow direction.

## Stabilize toggle (added)

Global (translation-only) stabilization, runs first in processFrame before seed/
denoise/magnify. Estimates whole-frame shift via SAD block-match on an 80px-wide
gray downsample (search +-8 small px), scales to proc px, accumulates, slow-EMA
(0.08) splits intended pan (low-freq) from shake (high-freq), counter-shifts the
frame by -shake (edge-replicate, clamped to 15% of width). Buffers: curS/prevS
(small gray), shiftBuf (Uint8 n*4). Off by default. Known: translation only (no
rotation/rolling-shutter); slight false-motion rim in Isolate mode after shifting.
