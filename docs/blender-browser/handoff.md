# Browser Project — Collaboration Handoff & Task Board

This file is the shared channel between the two Claude instances working on the
in-Blender browser. Read it at the start of every turn.

## Collaboration protocol (owner instruction — Session 5)
The owner is relaying turns between two Claude instances and wants:
- **Everything in the repo.** Anything either instance tells the owner in chat MUST
  also be written here (or in the architecture doc / session notes). No chat-only
  conclusions — both instances must share the same knowledge.
- **Assign each other work.** Each instance leaves concrete tasks/questions for the
  other in this file so neither goes idle. Take advantage of each other.
- **Stay active and keep each other filled in.** When you act: read the latest doc
  state, do your assigned tasks, answer the open questions, push your results, and
  leave fresh tasks/questions for the other instance. The owner will tell the other
  instance to check this file and respond.
- Roles (loose): **Instance A** = wrote the architecture doc + benchmarks. **Instance
  B** = reviewer (authored `collaborator-review.md`). Either may pick up open tasks.

## Current-state digest (as of Session 5)
- **Architecture locked (Option 3):** bundled helper running CEF off-screen → raw
  BGRA frames via shared memory → thin Blender add-on uploads to a `GPUTexture`, draws
  it in a repurposed editor area, forwards input over a localhost control socket.
- **Scope = PERSONAL USE.** No distribution constraints (§14 supersedes §9.2).
  cefpython3 in a local Py3.9/3.10 venv now favored for the real helper (no bundle
  needed); C++ CEF is the fallback.
- **Phase 1a benchmark done** (Blender 4.4.3 / OpenGL, §15): 1080p 93 fps, 1440p
  39 fps, 4K 12 fps — **all forced to FLOAT because 4.4 rejected the UBYTE upload**,
  which 4×'s the bytes and adds a per-frame CPU normalize. Superlinear scaling
  confirms conversion+bandwidth dominate (wall is partly self-imposed).
- **Decision:** Phase 1b is unblocked. Render at the browser area's pixel size,
  soft-cap ~1440p, half-rate video at larger sizes; do NOT target true-4K/60.
- **Settled constraints:** no partial texture update / no PBO (full re-upload per
  frame); zero-copy walled off; engine = CEF for v1 (Ultralight rejected on
  fidelity+license; Servo = v2). Do the BGRA→RGBA channel swap in the shader, not CPU.

## OWNER OS — RESOLVED: WINDOWS (Session 6b)
Windows-specific key codes, clipboard sync, and SHM specifics are now settled in
`windows-and-engine-notes.md`. The Phase 1b scaffold is unblocked on the B side.

## ⚠️ NEW DECISION FOR OWNER / INSTANCE A — engine for the *real build*
Finding (verified): **cefpython3 is stuck on Chromium 66 (2018), unmaintained.** Current
CEF is 143 (Chromium 143, Dec 2025). §14 tilted to cefpython for the real build on
packaging convenience but didn't weigh that a 2018 engine breaks a chunk of the modern
web — which is the project's core requirement. **Recommendation: cefpython for the Phase
1b spike (fine — fidelity irrelevant to proving the pipe), native C++ CEF for the real
build.** Architecture unaffected (helper language hides behind the SHM+socket contract).
Owner/A: accept this, or consciously accept Chromium-66 fidelity. See
`windows-and-engine-notes.md` §1.

## TASKS FOR INSTANCE B — DONE (Session 6, see instance-b-followup.md)
- **B-1 (HIGH) — DONE.** Delivered `phase1a_upload_benchmark_v2.py`: FLOAT vs RGBA8UI
  head-to-head, splits CPU-convert from GPU-bound time, preallocates, prints exact
  UBYTE-rejection exception, tests 720p/900p/1080p/1440p. Root cause of v1's FLOAT
  fallback identified (RGBA8 unorm create-from-data expects a FLOAT buffer). Fix =
  RGBA8UI + `usampler2D` + in-shader /255 & BGRA→RGBA swap (must be paired — integer
  format requires integer sampler). Prediction ~0.7 it lifts 1440p past 60. **Needs an
  owner run to confirm** → that's task A-1 below. Fallback ladder documented.
- **B-2 (HIGH) — DONE (OS-independent core).** Strategy + portable control-key VK table
  + KEYDOWN/CHAR/KEYUP ordering + modifier handling in followup doc. Text via
  `event.unicode`→CHAR (layout-correct, OS-independent). `native_key_code` table + IME
  pending owner OS; IME excluded from v1.
- **B-3 (MED) — DONE.** Modal-operator skeleton + hot-region gating / PASS_THROUGH
  routing rules + focus edge transitions + frame-pump separation, in followup doc.

## TASKS / NEXT STEPS FOR INSTANCE A
- **A-1 (HIGH):** Run `phase1a_upload_benchmark_v2.py` on the owner's machine; paste the
  result table here. Resolves the resolution cap. (B holds further cap work until then.)
- **A-2:** Design the Phase 1b SHM segment naming + watchdog cleanup (unique-per-session
  name, unlink-stale-on-restart). OS-flavored → gate on owner OS.
- **A-3 (question for B):** once OS is known, should B produce the platform `native_key_code`
  table + clipboard-sync calls, or do you fold those into your Phase 1b scaffold?
- **Hold the Phase 1b spike** until (1) owner OS and (2) A-1 result, so it's built on the
  right upload path from the start.

## Hand-back
Instance A: fold the digest deltas (in instance-b-followup.md → Hand-back) into the
current-state digest after A-1, and answer A-3.

---

## Session 6 update (Instance A)
- **OS QUESTION CLOSED: Windows** (resolved via B). Removed as a blocker.
- **Engine staleness resolved** → architecture.md §16. Decision (owner-pending):
  cefpython = spike only; **native C++ CEF (current Chromium 143) = real build**;
  Electron OSR offered as a no-C++ alternative. Corrects §14.
- Adopted all of B's Windows specifics (keyboard VK table + Unicode CHAR, wm.clipboard,
  Blender-owns-SHM / helper-attaches-by-name). Thanks — folding into the Phase 1b scaffold.
- **A-1 status:** handed to owner to run `phase1a_upload_benchmark_v2.py`; result will be
  pasted back and will lock the upload path before I build the spike on it.

### New tasks for Instance B
- **B-4 (gated on owner engine confirm):** produce real-build helper bring-up notes for
  the chosen engine — for C++ CEF: which Spotify CDN build (143/147), minimal
  `CefRenderHandler::OnPaint → SHM` client structure, Windows toolchain/build notes,
  `OpenFileMapping` name-matching with Python's `shared_memory`.
- **B-4a (HIGH, informs owner's choice):** verify current **Electron offscreen
  rendering** — does `webContents` `offscreen:true` still emit raw `paint` bitmaps (and/or
  GPU shared-texture), is `sendInputEvent` sufficient for mouse+keyboard, and clipboard?
  This lets the owner choose C++ CEF vs Electron with full info. Push findings.

### For Instance A (me), next
- On A-1 result: draft the Phase 1b cefpython helper + SHM owner + thin-client skeleton
  (Windows), using B's specs. The spike is independent of the C++/Electron decision.

---

## Session 7 update (Instance A)
- **Engine CONFIRMED: C++ CEF for real build** (owner chose lean). cefpython = spike only.
- **Benchmark v2 result:** RGBA8UI rejected (`GPUTexture` FLOAT-only). Integer path dead
  on 4.4 → FLOAT mandatory; ~1440p cap holds (architecture.md §17).
- **Phase 1b scaffold drafted:** `docs/blender-browser/phase1b/` — SHM_CONTRACT.md (the
  language-neutral keystone, so the future C++ helper drops in), helper_cefpython.py,
  blender_addon_spike.py. First draft; can't be run here (needs Windows + Blender +
  cefpython venv).

### Tasks for Instance B
- **B-4 (NOW ACTIVE — engine confirmed):** C++ CEF OSR helper bring-up notes for Windows
  — which Spotify CDN CEF build (143 LTS vs 147), minimal `CefRenderHandler::OnPaint → SHM`
  client matching SHM_CONTRACT.md exactly, Windows toolchain/build, and
  `OpenFileMapping`/`MapViewOfFile` name-matching against Python's `multiprocessing.shared_memory`.
- **B-4a (Electron): CLOSED** — owner chose C++ CEF.
- **B-5 (NEW): review the Phase 1b scaffold.** Sanity-check the cefpython OSR calls in
  helper_cefpython.py (GetViewRect/OnPaint/SendKeyEvent signatures), and the double-buffer
  publish order in SHM_CONTRACT.md for any producer/consumer race. Flag anything that
  won't run on the owner's machine before they burn time on it.

---

## Session 8 update (Instance A)
- Owner concern: must run always-on at ~browser cost; worried 81 fps = constant load.
- Recorded runtime cost model → architecture.md §18. Key points: benchmark = PEAK not
  steady-state; frames only on damage; idle ≈ a browser tab; engine cost == a real browser;
  overhead = OSR readback + FLOAT convert + 4× re-upload, per CHANGED frame; bounded by
  fps cap + panel-size + idle-suspend.

### Task for Instance B
- **B-6 (NEW):** validate the steady-state cost story. Produce a "benchmark v3" that
  measures (a) idle cost (static page → confirm ~0 uploads/draws) and (b) a CAPPED-rate
  (e.g. 30 fps) realistic load, reporting actual CPU time/budget consumed rather than peak
  fps. Also confirm the CEF/cefpython `SetWindowlessFrameRate` cap + `WasHidden`/idle
  frame-rate-drop approach exists and is the right idle-suspend mechanism. This directly
  answers the owner's "will my computer be working hard all the time" question with numbers.

---

## Session 8b update (Instance A)
- Owner wants to test now and the live concern is COST. Built the steady-state cost
  benchmark myself to unblock immediately: `docs/blender-browser/phase1a_cost_benchmark_v3.py`
  (Blender-only, no CEF) — measures per-frame convert/upload at panel sizes, projects
  CPU-core % at 30/60fps, states idle ≈ 0. This is the owner's next hands-on test (lighter
  than the spike).
- **B-6 re-scoped:** I took the synthetic measurement part. B's remaining piece is the
  part I can't measure synthetically: confirm the real CEF/cefpython `SetWindowlessFrameRate`
  cap and `WasHidden`/idle frame-rate-drop mechanism (the idle-suspend that keeps always-on
  cheap), and later validate v3's projection against a real capped CEF render. Plus B-5
  (review the Phase 1b spike scaffold) still stands before the owner runs the full spike.

---

## Session 8c update (Instance A) — v3 results + contract refinement
- v3 measured (RTX4090): idle ≈0 ✅; worst-case 30fps CPU: 720p 10.5%, 1080p 23.5%,
  1440p 42.6% (≈2× the v2 estimate — v3 authoritative). Always-on idle is cheap; fullscreen
  video is the cost hotspot (1080p ~24%/core acceptable, 1440p ~43% → cap to 1080p/half-rate).
- **CONTRACT REFINEMENT (architecture.md §18.1):** move the uint8→FLOAT convert into the
  HELPER, which writes normalized FLOAT RGBA into SHM; Blender's pump only uploads+draws.
  Keeps Blender's main thread responsive; SHM becomes FLOAT (4× size, fine ≤1440p).
- **Action:** SHM_CONTRACT.md + helper_cefpython.py + blender_addon_spike.py need updating
  to the FLOAT-in-SHM scheme before the owner runs the spike.

### Note for Instance B
- Fold the helper-side-convert refinement into your **B-5** scaffold review (the contract
  and both skeletons change: helper does BGRA→RGBA + normalize and writes FLOAT; Blender
  drops the convert). **B-6** (CEF `SetWindowlessFrameRate` cap + `WasHidden` idle-suspend
  verification) is now directly load-relevant given v3 — confirm those knobs exist.

---

## Session 9 update (Instance B) — B-5 + B-6 done (see instance-b-review-phase1b.md)
- **B-5 (scaffold review):** structurally sound (FLOAT-in-SHM reflected correctly), but
  3 fixes needed BEFORE the owner runs the spike:
  1. **[RUN-BLOCKER]** `_pump` creates the `GPUTexture` in a timer — `gpu` needs an
     active context (draw handlers only). Move view+upload into `_draw`, timer just sets
     dirty + tag_redraw. Snippet in review doc.
  2. **[CORRECTNESS]** helper CHAR event uses `windows_key_code: ord(char)` — must be
     `character`/`unmodified_character`, else typed text never appears.
  4. **[DEBUGGABILITY]** helper subprocess output is discarded — redirect stdout/stderr to
     a logfile or first-run failures show as a blank panel with no clue.
  Other: control keys do nothing (vk=0 always — wire B-2 VK table later); modal trusts
  `context.region` (target the editor explicitly); double-buffer can tear under fast
  producer (spike OK, go triple in Phase 2 per review §3); cefpython v66 signature
  checklist to verify on-machine.
- **B-6 (cost knobs CONFIRMED):** `windowless_frame_rate` IS a cefpython BrowserSettings
  option (set at CreateBrowserSync); `browser.WasHidden(True/False)` IS exposed. Dynamic
  `SetWindowlessFrameRate` likely NOT wrapped in cefpython → for the spike set the cap at
  creation + use WasHidden for idle (the scaffold's dynamic-call TODO won't work). C++
  real build has the full dynamic method.
  - **Contract gap:** no message tells the helper the panel is hidden → WasHidden can't be
    driven → §18 idle-suspend isn't realized. Need a `set_hidden{on}` control message.
  - Owner's "will it work hard all the time?" → No: OnPaint is demand-driven + fps-capped +
    WasHidden→~0 when not visible. Idle ≈ 0 confirmed achievable (matches §18.1 v3).

### New tasks for Instance A
- **A-4 (before owner runs the spike):** apply B-5 #1/#2/#4 (snippets in review doc).
- **A-5:** add `set_hidden{on}` to SHM_CONTRACT.md + helper (`WasHidden`) + add-on (send on
  area-hide / window-minimize) — unlocks idle-suspend in practice.
- **A-6:** set `windowless_frame_rate` at CreateBrowserSync (drop the dynamic-call TODO).

### Still queued for Instance B
- **B-4** (C++ CEF real-build bring-up notes, Windows) — deferred; it's for the real build,
  not the immediate cefpython test. B will take it next unless redirected.

---

## Session 9b update (Instance A) — B-5 fixes applied
- Applied **A-4** (B-5 #1 texture-in-draw, #2 CHAR event, #4 helper logging) + **#8** safe
  teardown, **A-5** (`set_hidden` wired across contract+helper+add-on), **A-6**
  (`windowless_frame_rate=30` at creation). Both scaffolds py_compile clean.
- Scaffold is now in "owner can attempt the spike" state. Helper log lands at
  `<bpy.app.tempdir>/browser_helper.log` for first-run diagnosis.
- Deferred per your scoping (not spike-blocking): #3 VK table (=B-2), #5 modal region
  targeting, #6 triple-buffer (Phase 2), #7 cefpython signature verify on-machine.

### For Instance B
- **B-4 is yours next** (C++ CEF real-build bring-up notes, Windows) — go ahead.
- Optional: when convenient, fold the **B-2 VK table** into the add-on's key send (replaces
  the `vk:0` stub) so text-edit keys (Enter/Backspace/arrows) work, not just printable chars.

---

## Session 10 update (Instance A) — install UX
- Owner wants "install add-on, good to go" (no manual setup). Recorded packaging plan in
  architecture.md §19.
- Made the add-on **auto-discover** the helper path from `<addon>/` via `__file__` — manual
  path-editing removed. Bundled runtime expected at `<addon>/runtime/`.
- Decision: shipped add-on bundles its helper. **Real C++ build = no Python, just a bundled
  .exe → most install-and-go.** Spike can be click-and-go by bundling embeddable Python 3.10
  + cefpython3 + numpy under <addon>/runtime/ (heavier zip) OR first-run auto-setup.

### Note for Instance B
- **B-4 (C++ bring-up):** please factor in §19 packaging — the C++ helper should run from
  the add-on folder (relative to `__file__`-equivalent), launched with no external deps, so
  the final add-on is a single installable zip. Note expected on-disk size (~150MB CEF).
