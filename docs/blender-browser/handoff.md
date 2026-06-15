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

## TASKS FOR INSTANCE B (do/answer, then push results here or as noted)
**B-1 (HIGH) — Settle the upload ceiling.** §15 shows UBYTE was rejected and FLOAT
inflates cost ~4×. Determine whether Blender 4.4's `gpu` module can upload raw bytes
to an integer texture (`RGBA8UI`) and normalize in a custom `GPUShader`
(`usampler2D`, divide by 255 in GLSL). If yes, provide the exact `GPUTexture` +
`GPUShader` GLSL + `batch_for_shader` calls. Deliver a **benchmark v2**
(`docs/blender-browser/phase1a_upload_benchmark_v2.py`) that:
  (a) separates CPU-conversion time from pure GPU-upload time,
  (b) preallocates the buffer to remove per-frame numpy allocation,
  (c) prints the exact exception when UBYTE→RGBA8 is rejected,
  (d) benchmarks the RGBA8UI+shader path head-to-head against the FLOAT path,
  (e) tests realistic panel sizes (1280×720, 1600×900, 1920×1080, 2560×1440).
Outcome decides whether the ~1440p cap can be raised. Push the script + a findings note.

**B-2 (HIGH) — Keyboard/IME mapping.** Produce a concrete mapping from Blender
modal-operator key events (`event.type`, `event.ascii`, `event.unicode`, modifier
flags) to CEF `SendKeyEvent` (KEYDOWN/KEYUP + CHAR) — at least ASCII + common
modifiers + arrows/enter/backspace/tab/esc. Survey prior art from game-engine CEF
integrations (Unreal Web Browser Widget, Unity CEF wrappers) for key-code/IME
handling. Note OS dependence (needs owner OS). Push as a doc section.

**B-3 (MED) — Modal-operator coexistence.** Draft event-routing rules + a modal
operator skeleton that captures mouse/key/scroll over the browser area WITHOUT
breaking normal Blender input: when to consume vs `PASS_THROUGH`, focus grab/release
on region enter/leave, and coexistence with the timer-based frame pump. Push as a doc
section / skeleton.

## TASKS / NEXT STEPS FOR INSTANCE A (me)
- **Hold the Phase 1b spike** (CEF OSR → SHM → texture) until (1) owner gives OS and
  (2) B-1 reports whether the integer-texture path raises the ceiling — so the spike
  is built on the right upload path from the start, not redone later.
- On owner-OS + B-1 result: draft the Phase 1b helper + SHM scaffold and the add-on
  thin-client skeleton.

## Hand-back
Instance B: after completing the above, update the current-state digest if anything
changed, and leave new tasks/questions for Instance A here.
