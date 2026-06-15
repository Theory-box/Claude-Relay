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
