# Windows Specifics + Engine-Staleness Finding (Instance B, Session 6b)

Owner OS confirmed: **Windows.** This resolves the long-standing open question and lets
me finalize B-2's platform codes, clipboard sync, and the shared-memory specifics (the
A-3 deliverable). It also surfaced a finding that revises §14's engine lean — read that
first because it's a decision, not a detail.

---

## ⚠️ FINDING — cefpython3 is stuck on Chromium 66 (revises §14)

**Verified (June 2026):**
- cefpython3's last real release is **v66.1, CEF/Chromium 66.0.3359.181 — from 2018.**
  The project is effectively unmaintained (its own README solicits sponsors for "monthly
  releases with latest Chromium"; only ~50% of the CEF API is exposed). The only newer
  artifacts are *unofficial* rebuilds for Python 3.9/3.10 — **still Chromium 66.**
- Current CEF is **143 (Chromium 143.0.7499.170), Dec 2025.**
- For comparison, the C# binding **CefSharp tracks current Chromium (125+ in 2024)** — so
  staying current is possible for a *bound* CEF, just not via any maintained **Python**
  binding. Python's realistic choices are cefpython (Chromium 66) or native C++ CEF
  (current).

**Why this matters here.** The locked requirement is "real *modern* web pages (working
CSS + JavaScript)." Chromium 66 predates roughly seven years of web-platform features
(large parts of modern CSS layout/container features, many JS APIs, codec/format
support). A Chromium-66 engine will silently misrender or break a meaningful fraction of
today's web. **§14 tilted toward cefpython3 "even for the real build" on packaging
convenience under the personal-use scope, but didn't weigh the Chromium-66 fidelity
cost.** I think that tradeoff flips once fidelity is the point of the project.

**Recommended revision (confidence ~0.8):**
- **Spike (Phase 1b): cefpython3 is fine.** Chromium 66 renders pages well enough to
  prove OSR → SHM → `GPUTexture` → input. Page fidelity is irrelevant to proving the
  pipe, and cefpython gets you there fastest on Windows.
- **Real build: native C++ CEF (current Chromium 143).** This is the only way to meet the
  "modern web" requirement on Python-hosted Blender. It re-confirms the original review's
  §2 position; §14's convenience argument holds only for the throwaway spike, not the
  shippable tool.
- Net: this doesn't change the *architecture* (Option 3 is unaffected — the helper's
  language is an implementation detail behind the SHM + socket boundary). It changes which
  helper you invest in after the spike. The SHM/socket contract should therefore be
  defined language-neutrally now (it already is) so the C++ helper drops in later without
  touching the Blender side.

**Decision needed from owner / Instance A:** accept "cefpython for spike, C++ CEF for real
build," or consciously accept Chromium-66 fidelity for a cefpython-only build. Flagging,
not deciding.

---

## B-2 (Windows) — keyboard finalization

On Windows the portable VK table from `instance-b-followup.md` **is** the
`windows_key_code`, so that table is complete as-is. Remaining Windows specifics:

- **`native_key_code`:** on Windows this is the `lParam`/scan-code form. Blender's modal
  operator does **not** expose scan codes, so deriving it exactly is impractical from the
  add-on. For v1, set **`native_key_code = 0`** and rely on `windows_key_code` (VK) +
  the `CHAR` event from `event.unicode`. This is sufficient for ASCII + the control keys;
  it's the same reason the Unicode-CHAR path was chosen for text. (~0.7)
- **`is_system_key`:** leave `False`; it's a macOS concern, not Windows.
- **Modifier flags:** map `event.ctrl/shift/alt/oskey` → CEF
  `EVENTFLAG_CONTROL_DOWN/_SHIFT_DOWN/_ALT_DOWN/_COMMAND_DOWN` on every event, unchanged
  from the cross-platform plan.
- **Shortcuts (Ctrl+C/V/X/A):** send the letter KEYDOWN with `EVENTFLAG_CONTROL_DOWN`;
  CEF's focused page performs the edit. Clipboard *sync* with the OS is below.

**Conclusion:** B-2 is fully resolved for Windows v1. No further per-OS table needed
unless/until macOS or Linux is targeted.

---

## Clipboard sync (Windows) — use Blender's own clipboard, skip win32

CEF OSR does not auto-sync the OS clipboard. The clean Windows path avoids `pywin32`
entirely by using Blender's built-in clipboard property:

- **Paste (OS → page):** read `bpy.context.window_manager.clipboard` (the OS clipboard
  text) in the add-on, send it to the helper over the control socket as `set_clipboard`,
  and have the helper inject it (or set CEF's clipboard) before forwarding Ctrl+V.
- **Copy (page → OS):** forward Ctrl+C so CEF copies the selection into its own clipboard,
  read it back from the helper (`get_clipboard` → `clipboard_value`), and write it to
  `bpy.context.window_manager.clipboard`, which puts it on the Windows clipboard.

This keeps the Blender side dependency-free (no `win32clipboard`). `wm.clipboard` is
text-only — rich/image clipboard is out of scope for v1. (~0.75)

---

## Shared memory (Windows) — specifics for the spike (Python↔Python)

With cefpython for the spike, both sides are Python, so use
`multiprocessing.shared_memory.SharedMemory`. Windows behaves **differently from POSIX**,
in a way that's actually simpler but has one trap:

- **No manual unlink, no `/dev/shm` leak.** On Windows the segment is a named file
  mapping that the OS frees automatically once **no process holds a handle**. So the
  Linux/macOS `resource_tracker` unlink dance (from the original review §3) **does not
  apply** on Windows.
- **The trap (inverse of POSIX):** because the segment dies when the last handle closes,
  the **long-lived owner must hold the reference for the whole session.** Design:
  **the Blender add-on creates and owns** the `SharedMemory` (it outlives the helper and
  survives helper restarts); **the helper attaches by name** (`SharedMemory(name=...,
  create=False)`). If the helper crashes, the segment survives because Blender still holds
  it; the watchdog respawns the helper and it re-attaches the same name. Do **not** let the
  helper be the creator/owner.
- **Naming:** unique per session (e.g. `blndr_browser_<uuid4hex>`), passed to the helper
  as a launch arg. Avoids collisions across restarts/instances.

**If/when the real build switches to a C++ CEF helper (Python↔C++):** Blender still creates
the mapping via `multiprocessing.shared_memory`; the C++ helper opens the **same name** via
`OpenFileMapping` + `MapViewOfFile`. Confirm the exact mapping-name string Python uses on
Windows during Phase 0 of the C++ port (Python may apply a prefix), and keep the packed
header layout fixed/aligned as in review §3.

---

## Hand-back delta

- **OS question: RESOLVED — Windows.** (handoff "OPEN QUESTION FOR OWNER" can be closed.)
- **A-3 answered:** B has produced the Windows key/clipboard/SHM specifics here; A can
  fold them into the Phase 1b scaffold rather than waiting on B per-step.
- **New decision for owner/A:** engine for the *real build* — cefpython (Chromium 66,
  breaks modern sites) vs C++ CEF (current). Recommend: cefpython spike → C++ real build.
- **Phase 1b is now unblocked on the B side:** OS known, key/clipboard/SHM specs in hand.
  Remaining gate is A-1 (run benchmark v2) to lock the upload path before A builds the
  spike on it.
