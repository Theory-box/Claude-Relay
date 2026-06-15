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

## OPEN QUESTION FOR OWNER (blocks several tasks below)
- **What OS is the owner on — Windows / macOS / Linux?** This drives the
  CEF/cefpython build choice, shared-memory specifics, clipboard sync, and keyboard
  key-code mapping. Tasks B-1(e), B-2, and the Phase 1b scaffold need it.

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
