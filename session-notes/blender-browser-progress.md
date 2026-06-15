# Blender Browser — Progress Notes

**Branch:** `research/blender-browser`
**Topic:** Embedding a fully interactive web browser inside Blender as an add-on.

## Current state (session 1)
- Explored 3 architectures. **Chose Option 3:** bundled helper process + raw
  shared-memory frame transport + small control socket. Engine = CEF off-screen.
- Rationale: self-contained, full fidelity, no compressed streaming, and decoupled
  from Blender's Python version (helper has its own runtime) — important because
  Blender 4.4=Py3.11 but 5.1=Py3.13.
- Wrote full design doc: `docs/blender-browser/architecture.md`.
- Doc includes open design decisions (§9), a phased plan (§10, Phase 1 spike is the
  gate), and a question set for a collaborating AI instance (§11).

## Decision state
- LOCKED: add-on only, no source edits, self-contained, no JPEG streaming, full
  fidelity, interactive. Option 3 architecture.
- OPEN: helper impl (cefpython vs C++ CEF), CEF bundle-vs-download, frame buffering
  scheme, control transport, host display surface, keyboard/IME scope, partial
  texture update availability.

## Session 2 — collaborating-instance review (done)
- Wrote `docs/blender-browser/collaborator-review.md` answering §11 + §9.
- Verdict: APPROVE Option 3 as-is. Architecture is right; do not relitigate.
- Grounded against live sources (CEF accel-paint state, Ultralight/Servo caps,
  Blender current `gpu` texture API).
- Key calls: engine = CEF for v1 (Ultralight fails fidelity: no WebGL/WebRTC,
  paid license; Servo = v2 watch). Helper = cefpython spike → C++ ship (security
  patchability, not just robustness). Frame proto = triple buffer + atomic publish
  index, full-frame. Host = SpaceImageEditor for spike. Keyboard = Unicode-CHAR +
  small VK table, no IME in v1.
- Verified API limits: Python `gpu` has NO partial sub-region texture update and no
  PBO path → assume FULL re-upload per frame. Zero-copy is walled off for an add-on
  (gpu exposes no device handle / external-memory import) — assumption confirmed.
- Reframed the real risk: NOT the SHM transport. It's (a) Python full-frame
  GPUTexture upload throughput at 4K, and (b) keyboard/IME + modal-op coexistence.
- Recommended splitting Phase 1: 1a = pre-CEF SHM→GPUTexture fps benchmark at
  1080p/1440p/4K (isolates the worst unknown); 1b = swap in CEF OSR.
- Flagged missing item: ongoing CEF security-patch cadence for a live-web Chromium.

## Open question for owner (next session)
- Phase 0 policy check: does the official Blender Extensions platform allow
  fetching native executables at runtime? Decides bundle-vs-download (§9.2).

## Next steps
- Owner reviews collaborator-review.md, accepts/rejects the §9 calls.
- Phase 0: confirm 4.4 bpy/gpu API limits + pick helper impl + pin CEF build +
  resolve extensions-platform download policy.
- Phase 1a: pre-CEF SHM→GPUTexture upload-fps benchmark (the de-risk move).
- Phase 1b: the spike proper (CEF OSR → SHM → GPUTexture → visible page).

## Verified facts (Jun 2026)
- 4.4 = Python 3.11.11; 5.0 = 3.11; 5.1 = Python 3.13 + Vulkan default.
- cefpython has no 3.11/3.13 binding → engine must live in a decoupled helper.

## Session 3 (other instance — policy + de-risk build)
- RESOLVED §9.2 distribution policy via web research:
  - Official extensions.blender.org forbids download-at-runtime (self-contained, no
    remote code exec, no auto-updater) and treats large unreviewable bundled binaries
    as an unsolved review problem.
  - Decision: v1 = self-hosted / Install-from-Disk (or third-party repo) with helper
    bundled. Official listing = later/uncertain, not a v1 constraint.
- Folded collaborator corrections into architecture.md §13 (engine=CEF locked,
  Ultralight rejected, Servo=v2, no partial texture update → full re-upload, zero-copy
  walled off, Phase 1 split into 1a/1b).
- Built Phase-1a scaffold: docs/blender-browser/phase1a_upload_benchmark.py
  (synthetic full-frame GPUTexture upload+draw fps at 1080p/1440p/4K; also live-checks
  UBYTE vs FLOAT upload dtype on 4.4). Owner runs it interactively; share numbers.
- Noted (collaborator's flag): bundled live-web Chromium needs an ongoing CEF
  security-patch cadence. Self-hosted distribution means manual user updates (consistent
  with the no-auto-updater rule) — track as a maintenance item, not a v1 blocker.

## Next steps (after 1a numbers)
- If 4K/60 clears: proceed to Phase 1b (CEF OSR → SHM → texture).
- If 4K short: cap render resolution / half-rate video; re-benchmark.
- Still open for Phase 0: confirm no Python space-type registration + no GPU device
  handle against 4.4 API; pick helper impl (cefpython spike vs C++ ship).

## Session 4 (owner: personal-use scope)
- Owner confirmed PERSONAL USE only — no distribution requirements.
- Supersedes §9.2: bundle-vs-download is now free choice; platform rules don't apply.
- Knock-on: helper runtime can be a local venv (`pip install cefpython3` on Py3.9/3.10)
  set up once; no 150MB bundle needed. §9.1 tilts toward cefpython3 for the real build,
  not just the spike. C++ CEF kept as fallback.
- Recorded as architecture.md §14. Architecture/engine/Phase plan all unchanged.

## Session 5 (Phase 1a results)
- Ran benchmark: Blender 4.4.3 / OpenGL. 1080p 93fps, 1440p 39fps, 4K 12fps — all FLOAT.
- KEY: UBYTE upload rejected → forced FLOAT (4× bytes + per-frame CPU normalize),
  inflating cost. Superlinear scaling confirms conversion+bandwidth dominate.
- DECISION: Phase 1b not blocked. Render at browser-area pixel size, soft-cap ~1440p,
  half-rate video at larger sizes. No true-4K/60.
- OPT TRACK: probe UBYTE/RGBA8UI + in-shader normalize (benchmark v2) — could lift cap.
- CEF note: do BGRA→RGBA swap in shader; FLOAT normalize is the only forced CPU cost.
- Recorded as architecture.md §15.

## Session 5b (collaboration protocol + task board)
- Owner instruction: keep ALL knowledge in the repo (no chat-only conclusions); two
  instances assign each other tasks and stay active; relay turns; keep each other
  filled in.
- Created docs/blender-browser/handoff.md = shared task board + protocol + state digest.
- Queued for Instance B: B-1 upload-ceiling/integer-texture benchmark v2 (HIGH),
  B-2 keyboard/IME mapping (HIGH), B-3 modal-op coexistence (MED).
- OPEN for owner: which OS (Win/Mac/Linux) — blocks CEF build, IPC, clipboard, keycodes.
- Instance A holding Phase 1b until owner-OS + B-1 result.

## Session 6 — Instance B follow-up (B-1/B-2/B-3 done)
- B-1: wrote `phase1a_upload_benchmark_v2.py` (FLOAT vs RGBA8UI head-to-head, splits
  convert vs GPU time, preallocates, prints UBYTE-rejection reason, 720p–1440p).
  Root cause of v1 FLOAT fallback = RGBA8 unorm create-from-data wants a FLOAT buffer.
  Fix = RGBA8UI + usampler2D + in-shader /255 & BGRA->RGBA (paired requirement).
  Prediction ~0.7 it raises the 1440p cap. NEEDS an owner run (task A-1) to confirm.
- B-2: keyboard strategy = event.unicode -> CEF CHAR for text (layout-correct,
  OS-independent) + portable Windows-VK control-key table + modifier bitfield.
  native_key_code table + IME pending owner OS; IME out of v1.
- B-3: modal-operator skeleton + hot-region gating + PASS_THROUGH discipline + focus
  edge transitions + frame-pump separation. Phase-3 gate: Blender stays fully usable.
- All in `docs/blender-browser/instance-b-followup.md`. Handoff board updated; new
  tasks A-1/A-2/A-3 left for Instance A.
- STILL BLOCKING (owner): target OS (Windows/macOS/Linux).
