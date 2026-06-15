# In-Blender Web Browser — Architecture & Design (Option 3)

**Status:** Reviewed (session 2). Pre-spike. See §13 for review outcomes & locked decisions.
**Branch:** `research/blender-browser`
**Target host:** Blender 4.4 (user's current build). Forward-looking to 5.0 / 5.1.
**Audience:** This doc guides implementation and is written to be picked up by a
second collaborator (another Claude instance). A dedicated section at the bottom
poses open questions and explicitly invites that collaborator's critique and
alternative ideas. Please engage with it directly.

---

## 1. The goal in one paragraph

Deliver a **fully interactive web browser that lives inside Blender**, shipped as
an **add-on** (no edits to Blender's own source). It must render real modern web
pages (working CSS + JavaScript), support text selection, copy/paste, clicking,
scrolling, typing, and navigation, feel responsive (target ~60 fps, crisp text),
and be **self-contained** — it must not depend on an external browser the user has
to install and launch. Critically, it must **not** work by shipping compressed
image/video snapshots between two programs (the thing the project owner explicitly
rejected). The display surface inside Blender will ultimately be a GPU texture —
that is unavoidable and accepted — but the *transport* feeding that texture must be
raw, local, and cheap.

---

## 2. Hard constraints (locked) and accepted trade-offs

**Locked requirements**
- Add-on only. No Blender source edits, no custom Blender build.
- Self-contained: the engine ships with the add-on; no reliance on the user's Brave/Chrome.
- No compressed frame *streaming* between processes (no JPEG-over-socket roundtrip).
- Full fidelity: real Chromium-class rendering + JS.
- Interactive: mouse, keyboard, scroll, clipboard, navigation.
- Owner is fine with this being hard.

**Accepted trade-offs / known walls**
- The final display in Blender is a **GPU texture** (Blender paints its whole UI as
  GPU pixels; there is no HTML layout engine inside Blender, and the `gpu` module
  does not expose a raw device/context handle to an external renderer). *Confidence
  this is a true wall for an add-on: ~0.75 — must be re-confirmed in Phase 0.*
- **No native editor-type entry.** Python cannot register a new Blender editor/space
  type (only node-editor-style subtypes). We get the "Browser window" UX by
  repurposing an existing editor area and opening it in its own window via
  `wm.window_new`; the user selects it from the add-on's own UI, not Blender's native
  editor dropdown. *Confidence: ~0.8.*
- **No DRM/Widevine video** (Netflix etc.). Protected content does not render in
  off-screen mode. Hard wall, no workaround. *Confidence: ~0.85.*
- **Not zero-copy.** One raw buffer → GPU-texture upload per frame remains. Removing
  even that last copy needs GL/Vulkan external-memory interop against Blender's device
  handle, which the add-on cannot reach without source access. We accept the single
  upload; performance is effectively in-process-equivalent.

---

## 3. Why Option 3 (and not 1 or 2)

Three architectures were considered for "interactive web content inside Blender":

| Option | Engine location | Pixel transport | Verdict |
|---|---|---|---|
| 1 — CDP bridge | User's installed Brave/Chrome (separate) | CDP screencast (JPEG over socket) | Rejected: not self-contained; it *is* the compressed-streaming model the owner rejected. Good only as a throwaway prototype. |
| 2 — In-process engine | Native module loaded inside Blender's Python | Renders to buffer in Blender's process | Rejected: most fragile. cefpython has no binding for Blender's Python (3.11), let alone 3.13. Would require rebuilding a native binding for every Blender Python bump. |
| **3 — Bundled helper + shared memory** | **Separate helper process shipped with the add-on, with its own runtime** | **Raw BGRA via shared memory; small control socket for events** | **Chosen.** |

**Decisive reasoning for Option 3:**
- It is self-contained (helper ships inside the add-on) and full-fidelity (CEF).
- The "no compressed streaming" requirement is honored: pixels move via **raw
  shared memory** (no encode, no decode, no network) — categorically different from
  CDP's JPEG-over-socket.
- It is **resilient to Blender's Python-version churn.** Verified facts:
  - Blender 4.4 → Python **3.11.11**
  - Blender 5.0 → Python 3.11 (VFX Platform 2025)
  - Blender 5.1 (current latest, Mar 2026) → Python **3.13** + **Vulkan default**
  Because the helper runs its **own** runtime (its own Python for cefpython, or a
  compiled C++ CEF binary with no Python at all), it is decoupled from whatever
  Python Blender ships. The only code inside Blender is a thin client using
  `bpy`, `gpu`, `mmap`/`shared_memory`, and `socket` — all stable across 3.11 and
  3.13. Option 2 gets *worse* with this churn; Option 3 is unaffected.
- Bonus: the helper is a real browser process, so **audio plays through the OS for
  free**, and a helper crash is isolated — it does not take Blender down.

---

## 4. High-level architecture

```
+--------------------------------------------------------------+
|  BLENDER PROCESS  (Python 3.11 on 4.4 / 3.13 on 5.1)         |
|                                                              |
|  Add-on (thin client)                                        |
|   - lifecycle manager  (spawn / watchdog / kill helper)      |
|   - SHM reader         (mmap the frame buffer)               |
|   - frame pump         (bpy.app.timers ~1/60s)               |
|        -> upload latest frame to gpu.types.GPUTexture        |
|        -> area.tag_redraw()                                  |
|   - draw handler       (blit textured quad into the region)  |
|   - modal operator     (capture mouse/key/scroll over region)|
|        -> translate coords + DPI -> send over control socket |
|   - UI: open-in-window, URL bar, back/fwd/reload             |
+----------------------------+---------------------------------+
            ^   read pixels    |   send input / commands
            |  (shared memory) |   (control socket: 127.0.0.1 / pipe)
            |                  v
+----------------------------+---------------------------------+
|  HELPER PROCESS  (own runtime — NOT Blender's Python)        |
|   - CEF off-screen browser (OSR mode)                        |
|   - OnPaint(dirtyRect, BGRA buffer) -> write into SHM        |
|   - control listener: navigate/resize/mouse/key/scroll/      |
|        clipboard/reload/back/fwd/exec-js/focus               |
|   - plays audio directly via OS                              |
|   - own CEF message loop                                     |
+--------------------------------------------------------------+
```

**Two channels, deliberately separate:**
1. **Frame channel = shared memory** (helper → Blender). Big, high-bandwidth, raw
   pixels. No serialization.
2. **Control channel = local socket / named pipe** (Blender ↔ helper). Small, ordered,
   request/response messages (input events, navigation, clipboard queries).

Keeping pixels off the socket is what makes this "not streaming."

---

## 5. Component detail

### 5.1 Helper process ("render server")
- Embeds CEF in **off-screen rendering (OSR)** mode: no native window; CEF hands us
  the rendered page as a CPU pixel buffer via the `OnPaint` callback.
- On `OnPaint(browser, type, dirtyRects, buffer, width, height)`: copy the BGRA
  buffer (or just the dirty rects) into the shared-memory frame slot, bump the frame
  sequence number, flip the ready flag / buffer index.
- Runs CEF's message loop (`CefDoMessageLoopWork` pumped on a timer, or
  `CefRunMessageLoop`). Note: CEF input calls (`SendMouseClickEvent`,
  `SendKeyEvent`, `SendMouseWheelEvent`) must be issued on CEF's UI thread — the
  control listener must **post** events onto that thread, not call directly from a
  socket thread.
- Implementation choice is an open decision (see §9): **cefpython3** under its own
  bundled Python 3.9/3.10 (fast to prototype) vs a **native C++ CEF binary** (more
  robust, fully decoupled from any Python).

### 5.2 Frame channel (shared memory)
- Cross-platform option: Python `multiprocessing.shared_memory.SharedMemory`
  (available in both Blender's Python and a 3.8+ helper Python). For a C++ helper:
  POSIX `shm_open`+`mmap` / Windows named file mapping, with a matching name.
- **Layout:** small header + pixel region.
  - Header: magic, version, width, height, stride, pixel format (BGRA8), active
    buffer index, frame sequence number, dirty-rect bounds (x,y,w,h), a ready/lock
    flag or atomic.
  - Pixels: **double-buffered** (two full slots) so the helper writes slot B while
    Blender reads slot A; swap by writing the active index last. This avoids tearing
    without a heavy mutex. (Triple buffering is a possible upgrade.)
- **Sizing:** allocate for the max expected viewport (e.g. 3840×2160×4 ≈ 33 MB per
  slot). Re-allocate / re-create the segment on resize beyond capacity.
- Blender side: `mmap` the segment, read the header, and on a new sequence number
  upload the active slot to a `GPUTexture`.

### 5.3 Control channel
- A `127.0.0.1` TCP socket (simplest cross-platform) or a Unix domain socket /
  Windows named pipe. Bound to localhost only.
- Length-prefixed JSON messages for the spike (readable, debuggable); can move to a
  compact binary struct later if message rate matters.
- **Blender → helper:** `mouse_move`, `mouse_down`, `mouse_up`, `wheel`, `key_down`,
  `key_up`, `char`, `navigate{url}`, `resize{w,h}`, `set_scale{dpr}`, `reload`,
  `back`, `forward`, `focus`, `blur`, `get_clipboard`, `set_clipboard{text}`,
  `shutdown`.
- **Helper → Blender:** `title_changed`, `url_changed`, `loading_state`,
  `cursor_changed{type}` (so Blender can set the matching cursor), `clipboard_value`,
  `ack`/`error`. (Frame readiness can also simply be polled from the SHM header,
  avoiding a per-frame message.)

### 5.4 Blender add-on (thin client)
- **Lifecycle manager:** on "open browser", spawn the bundled helper with args
  (SHM name, control port, initial WxH, initial URL). Watchdog detects a stalled
  frame counter / dead process and restarts it, re-attaches SHM, reloads last URL.
  On Blender quit (`bpy.app.handlers` / `atexit`), send `shutdown`, then join/kill.
- **Frame pump:** `bpy.app.timers.register(cb)` returning ~1/60. The callback reads
  the SHM sequence number; if new, uploads the active slot to the `GPUTexture` and
  calls `area.tag_redraw()`. **All `gpu` calls happen here, on the main thread.**
- **Draw handler:** `SpaceImageEditor.draw_handler_add(..., 'WINDOW', 'POST_PIXEL')`
  (or the chosen host space) draws a textured quad filling the region using a
  `gpu.types.GPUShader` + `GPUBatch`.
- **Modal operator:** runs while the browser area is focused; in `modal()` it
  captures `MOUSEMOVE`, `LEFTMOUSE`, `RIGHTMOUSE`, `WHEELUPMOUSE`/`WHEELDOWNMOUSE`,
  key events, and modifiers, translates them (see §6), and sends them over the
  control channel. Returns `PASS_THROUGH` for events it doesn't consume so Blender
  stays usable.
- **UI:** an operator/button that opens the browser in its own window
  (`wm.window_new` → set the new area to the host space), a URL bar (header field +
  StringProperty + "Go" operator), and back/forward/reload buttons.

---

## 6. Input mapping detail

- **Coordinate origin:** Blender region coords are bottom-left origin; web/CEF is
  top-left. Flip Y. Then scale region pixel coords → page pixel coords by the ratio
  of (page render size) / (region size). Render the page at the region's **native
  pixel resolution × device-pixel-ratio** so text stays crisp (this is the main
  lever for the "clear" requirement).
- **Mouse:** map to `SendMouseMoveEvent` / `SendMouseClickEvent` (down+up with
  button + modifiers) / `SendMouseWheelEvent` (deltas).
- **Keyboard (hard sub-problem):** Blender's `event.type` enum + `event.ascii` +
  modifier booleans must be translated into CEF key events (a `KEYDOWN`/`KEYUP`
  pair plus a `CHAR` event for text). CEF expects platform-native key codes /
  Windows virtual-key codes. International layouts and IME are the messy edge.
  *Flag: needs prior-art research; see questions §10.*
- **Clipboard:** CEF OSR does not auto-sync the clipboard. For copy: forward
  Ctrl+C (CEF performs the selection copy into its own clipboard), then read it and
  sync to the OS clipboard. For paste: read the OS clipboard in Blender and inject.
  *Flag: confirm exact CEF clipboard hooks.*
- **Focus:** send `focus` when the modal op is active and the cursor is inside the
  region, `blur` otherwise.
- **Cursor:** update Blender's cursor from the helper's `cursor_changed` messages
  (link → hand, text → I-beam). Nice-to-have, not v1-critical.

---

## 7. Threading / event-loop model

- **Blender main thread:** all `bpy` + `gpu` calls. The frame pump (timer) and the
  modal operator both run here. Never touch the GPU from another thread.
- **Helper:** CEF owns a message loop. `OnPaint` fires on CEF's UI thread — writing
  to SHM there is fine. The control-socket listener runs on its own thread but must
  **post input events onto CEF's UI thread** before calling `SendKeyEvent` etc.
- **Decoupling:** Blender reads whatever the latest SHM frame is; the helper writes
  at its own cadence. No lockstep, no blocking handshake on the hot path.

---

## 8. Lifecycle, packaging, robustness

- **Packaging:** ship as a Blender Extension (4.2+ system). The helper binary +
  CEF runtime is large (~150 MB per platform). Two strategies (open decision §9):
  bundle everything, or download the CEF runtime on first run.
- **Per-OS builds:** separate helper binaries for Windows / macOS / Linux.
- **Crash isolation:** helper death never crashes Blender; watchdog restarts it.
- **Clean shutdown:** tear down SHM, close sockets, kill helper on add-on disable
  and on Blender exit.
- **Security:** control socket bound to localhost only; validate/whitelist message
  types; consider CEF sandbox settings.

---

## 9. Open design decisions (need a call)

1. **Helper implementation:** cefpython3 (own Python 3.9/3.10, fast prototype) vs
   native C++ CEF binary (robust, no Python coupling). *Leaning C++ for the shipped
   product, cefpython for the Phase-1 spike — but want a second opinion.*
2. **CEF distribution:** bundle (~150 MB × 3 platforms) vs download-on-first-run.
3. **Frame protocol:** double vs triple buffer; atomic index vs lock; full-frame vs
   dirty-rect uploads.
4. **Control transport:** localhost TCP vs Unix socket / named pipe; JSON vs binary.
5. **Host display surface:** repurpose `SpaceImageEditor` vs a full-window
   `POST_PIXEL` draw handler vs another space — which gives a clean full-bleed area
   with the least interference from Blender's native gizmos/overlays.
6. **Keyboard/IME mapping** completeness target for v1 (ASCII-only first?).
7. **Multiple simultaneous browser instances** — defer to v2?
8. **Partial `GPUTexture` sub-region update** — is it available across both the
   OpenGL (4.4) and Vulkan (5.1) backends, or is full re-upload the only path?

---

## 10. Phased plan

- **Phase 0 — Confirm-on-build & decisions (~1 day).** Verify against Blender 4.4's
  actual `bpy`/`gpu` API: (a) no Python space-type registration, (b) no GPU device
  handle exposed, (c) whether `GPUTexture` supports partial sub-region updates. Pick
  helper implementation (§9.1) and pin a CEF build. Resolve §9 decisions where possible.
- **Phase 1 — SPIKE (the gate).** Minimal helper renders a hardcoded URL via CEF OSR
  and writes BGRA into shared memory; a minimal Blender script mmaps it, uploads to a
  `GPUTexture`, and draws it in a region. **Success = a live page visible inside
  Blender.** If this works, the project is real. If it doesn't, we learn it on day one.
- **Phase 2 — Frame pump + resize.** Timer-driven uploads, `tag_redraw`, handle
  region resize → resize the browser + reallocate SHM.
- **Phase 3 — Input.** Mouse (move/click/scroll) → control channel → CEF. Then
  keyboard, then clipboard, then focus handling.
- **Phase 4 — Add-on packaging.** Lifecycle manager, open-in-own-window UI, URL bar,
  nav buttons, cursor sync, crash watchdog.
- **Phase 5 — Polish.** Native-DPI clarity, dirty-rect optimization, per-platform
  helper builds, audio verification, clean shutdown.

Realistic effort: weeks, with **Phase 1 as the make-or-break gate.** If the spike
lands, the rest is known engineering rather than research.

---

## 11. Questions for the collaborating AI (please answer / push back)

This is where a second perspective is most valuable. Treat these as open — and if
the whole approach is wrong, say so.

1. **Engine choice.** Is CEF the right engine for an off-screen, self-contained,
   shippable Blender add-on, or would **Ultralight** (lighter, has a GPU-driver
   model, built for app embedding) or **Servo / WebRender** (now that it is more
   mature in 2026) be a better fit on fidelity vs package-size vs OSR support vs
   licensing? Does any of them open a cleaner path than CEF here?

2. **Helper: Python vs C++.** For the *shipped* product (not the spike), which would
   you choose and why — cefpython3 on a bundled Python, or a native C++ CEF binary?
   What are the failure modes you'd worry about for each inside an end-user Blender
   add-on?

3. **Shared-memory frame protocol.** What is your recommended tear-free,
   single-producer/single-consumer scheme for ~33 MB BGRA frames at 60 fps —
   double vs triple buffer, atomics vs lock, dirty-rect handling? Any specific
   pitfalls with Python `multiprocessing.shared_memory` across a Python↔Python *or*
   Python↔C++ boundary (alignment, lifetime, name collisions, cleanup on crash)?

4. **GPU upload cost.** What's the most efficient way to push a full BGRA buffer to a
   `gpu.types.GPUTexture` every frame in Blender — is there a partial/sub-region
   update, a persistent-mapped buffer, or a PBO-style path exposed through the `gpu`
   module on **both** OpenGL (4.4) and Vulkan (5.1)? Or is full re-upload the only
   realistic option, and is that fast enough at 4K/60?

5. **Zero-copy, revisited.** Is there *any* add-on-only path (no Blender source
   edits) to a **shared GPU texture** between the helper and Blender — e.g. GL/Vulkan
   external memory, or a DXGI shared handle on Windows fed by CEF's
   `OnAcceleratedPaint` — given the `gpu` module doesn't expose Blender's device
   handle? Or is this genuinely walled off? (We've assumed walled-off; challenge it.)

6. **Keyboard/IME.** Cleanest strategy to map Blender modal-operator key events to
   CEF `SendKeyEvent` across Windows/macOS/Linux, including non-US layouts and IME?
   Any existing prior art (game-engine CEF integrations) worth copying?

7. **Host surface.** Best way to commandeer a Blender area for a full-bleed
   interactive texture with input capture — `SpaceImageEditor` repurpose, a
   full-window `POST_PIXEL` draw handler, or another approach — without Blender's
   native overlays/gizmos interfering, and with the modal operator coexisting
   cleanly with normal Blender event handling?

8. **Packaging.** Bundle CEF (~150 MB/platform) inside a Blender Extension vs
   download-on-first-run — cleaner UX? Any precedent in existing large Blender
   extensions for shipping/fetching big native runtimes?

9. **Loop integration.** Gotchas pumping CEF's message loop in a standalone helper
   while also serving a control socket, and reliably marshalling input onto CEF's UI
   thread?

10. **Poke holes in the whole thing.** Is helper + shared-memory the right call, or
    is there a simpler/more robust design we're missing? Given the Python-version
    churn (3.11 → 3.13) and Vulkan-by-default in 5.1, would you revisit Option 1
    (CDP bridge) or Option 2 (in-process) at all? What's the single biggest risk you
    see, and what would you do to de-risk it before Phase 1?

**Your opinion on the idea itself is wanted, not just answers to the above.** If you
think there's a fundamentally better way to get interactive web content inside
Blender as an add-on, propose it.

---

## 12. Appendix — verified facts (June 2026)

- Blender 4.4 bundled Python: **3.11.11**.
- Blender 5.0 (Nov 2025): Python 3.11, VFX Platform 2025.
- Blender 5.1 (Mar 2026, current latest): **Python 3.13**, **Vulkan enabled by
  default** (moving away from OpenGL), VFX Platform 2026.
- Blender's bundled Python is **not swappable**; add-on native deps must match it.
- Custom editors via Python are limited to node-editor-style subtypes (no arbitrary
  new space type) — confirm against 4.4 API in Phase 0.
- cefpython3: official support tops out around Python 3.9 (unofficial 3.10); no
  3.11/3.13 binding — a key reason the engine lives in a *decoupled* helper.

---

## 13. Session 2 — Collaborator review outcomes (decisions locked)

A second instance reviewed §1–12. Approves Option 3 (~0.85): the decoupling
argument carries it; architecture not relitigated. Resulting locks:

**Engine — CEF for v1 (locked).**
- Ultralight rejected: verified no WebGL, no WebRTC, only experimental video, and a
  paid proprietary license — fails the fidelity requirement outright.
- Servo: now has WebGL/WebGPU and an offscreen `WebView` API, but its general
  embedding path isn't production-ready → **v2 watch**, not v1.

**Risk model corrected.** The SHM transport is *not* the main risk (solved
engineering). The real risks are:
1. **Python-side full-frame `GPUTexture` upload at 4K** (the worst unknown).
2. **Keyboard/IME mapping + modal-operator coexistence** with normal Blender events.

**§9.8 resolved — no partial texture update.** The current Blender `gpu` API exposes
no partial sub-region texture update and no PBO path. **Plan for full re-upload every
frame.** Dirty rects help SHM *bandwidth*, not the GPU upload cost. This makes risk
#1 above the thing to measure first.

**§11.5 resolved — zero-copy stays walled off.** CEF `OnAcceleratedPaint`
shared-texture is Windows-only and version-fragile (a CEF 143 build shipped a
null-handle regression in Dec 2025), and Blender's `gpu` exposes no device handle to
import such a texture anyway. **Do not spend spike budget here.**

**§9.2 resolved — distribution.** Official `extensions.blender.org` forbids
download-at-runtime (must be self-contained, no remote code execution, no
auto-updater) and treats large unreviewable bundled binaries as an open/unsolved
review problem. Therefore **v1 = self-hosted (Install-from-Disk or third-party repo)
with the helper bundled.** Official-platform listing is a later, uncertain goal, not a
v1 requirement. (Network permission, if ever used, must check `bpy.app.online_access`.)

**Phase 1 split (locked).** De-risk by failing the worst unknown cheaply:
- **Phase 1a — pre-CEF upload benchmark.** Measure SHM-style full-frame
  `GPUTexture` upload + draw fps at 1080p / 1440p / 4K with synthetic frames, *before*
  wiring CEF. If 4K/60 isn't reachable on target hardware, we learn it in an afternoon
  and adjust (e.g. cap render resolution, half-rate video) instead of after a full CEF
  integration. Scaffold: `docs/blender-browser/phase1a_upload_benchmark.py`.
- **Phase 1b — CEF OSR → SHM → texture.** The original Phase-1 spike, run only after
  1a clears.

**Remaining Phase-0 confirmations** (unchanged): no Python space-type registration;
no exposed GPU device handle. The benchmark also doubles as a live check of which
`Buffer` dtype the `GPUTexture` upload path accepts (UBYTE vs FLOAT) on 4.4.

---

## 14. Session 4 — scope narrowed to PERSONAL USE (supersedes parts of §9.2 / §13)

Owner confirmed this is **personal use only**; it does not need to meet
extensions.blender.org distribution requirements. Implications:

- **§9.2 distribution analysis is now moot.** No platform review, so the
  self-contained / no-remote-code / no-auto-updater rules do not apply. Both bundling
  AND download-on-first-run are fine — choose by convenience, not policy.
- **Packaging burden drops sharply.** Instead of bundling ~150 MB of CEF per platform,
  the helper's runtime can be set up once on the owner's own machine (e.g. a dedicated
  Python 3.9/3.10 venv with `pip install cefpython3`, or a fetched CEF build). A
  first-run setup step is perfectly acceptable.
- **§9.1 helper-impl tilts toward cefpython3 (own venv) even for the real build**, not
  just the spike — there's no need for a clean distributable artifact, and cefpython
  sidesteps the C++ build entirely. Native C++ CEF stays as a fallback if cefpython's
  age/stability bites.
- Security-cadence note still applies (a live-web Chromium wants patches), but a
  single-user, self-controlled surface makes manual updates acceptable.
- **Unchanged:** Option 3 architecture, CEF engine, full-frame re-upload, zero-copy
  walled off, Phase 1a/1b split. The scope change only relaxes packaging/distribution.

---

## 15. Session 5 — Phase 1a benchmark results & decision

Ran on owner's machine: **Blender 4.4.3, OpenGL backend.**

| res   | dtype | upload ms | frame ms | fps  |
|-------|-------|-----------|----------|------|
| 1080p | FLOAT | 10.71     | 10.71    | 93.4 |
| 1440p | FLOAT | 21.75     | 25.72    | 38.9 |
| 4K    | FLOAT | 85.46     | 80.82    | 12.4 |

**Key finding — dtype fell back to FLOAT.** 4.4's `GPUTexture(format='RGBA8',
data=Buffer)` rejected UBYTE, so every frame ships 4× the bytes (132 MB vs 33 MB at
4K) *plus* a per-frame CPU uint8→float32 normalize. The superlinear scaling (4× pixels
→ ~7.5× frame time) is consistent with conversion + bandwidth dominating, not fixed
overhead — i.e. the FLOAT requirement is inflating these numbers, the wall is partly
self-imposed.

**Viability (worst-case FLOAT path):** 1080p comfortable (93 fps), 1440p fine for
browsing/scrolling but not smooth video (39 fps), 4K not viable (12 fps).

**Decisions:**
- **Phase 1b is NOT blocked.** A browser *panel* renders at its editor-area pixel size
  — typically ≤1080p, sometimes 1440p — where there's already headroom.
- **Resolution strategy (locked):** render the page at the browser area's actual pixel
  size (native DPI), soft-cap ~1440p, offer half-rate frames for video at larger sizes.
  Do NOT target true-4K/60.
- **Optimization track (optional, not a gate):** confirm whether a UBYTE / integer-
  texture path (`RGBA8UI` + in-shader normalize) is reachable in 4.4. If so it removes
  the float conversion and cuts upload bandwidth 4×, plausibly lifting 1440p past 60 and
  4K to marginal. Benchmark v2 would split conversion-vs-upload time, preallocate to kill
  per-frame numpy alloc, and capture the UBYTE rejection reason.
- **CEF-pipeline note:** CEF `OnPaint` returns BGRA UBYTE. Do the BGRA→RGBA channel swap
  **in the shader** (free), never on CPU. If FLOAT stays mandatory, the byte→float
  normalize is the one unavoidable recurring CPU cost — the main reason to chase the
  UBYTE/integer path.

---

## 16. Session 6 — engine staleness resolved (corrects §14); OS = Windows

Instance B flagged, and this confirms independently: **cefpython3 is frozen on Chromium
66 (2018) and unmaintained.** Current **CEF = 143.0.13 / Chromium 143.0.7499.170 (Dec
2025)**, actively maintained (BSD), with off-screen rendering as a first-class CEF use
case; CefSharp ships even newer (147, May 2026). So a *modern* Chromium engine is
available — just not via any maintained **Python** binding.

**This corrects §14.** §14 leaned toward cefpython3 for the REAL build on packaging
convenience and missed the Chromium-66 fidelity/security cost. Since "modern web" is the
whole point, that tradeoff flips. §14's convenience argument now applies ONLY to the
throwaway spike.

**Engine decision (locked, pending owner confirm):**
- **Spike (Phase 1b) = cefpython3.** Chromium 66 renders well enough to prove
  OSR → SHM → GPUTexture → input. Page fidelity is irrelevant to proving the pipe, and
  cefpython is the fastest route on Windows (both sides Python).
- **Real build = native C++ CEF (current Chromium 143/147).** The only way to meet the
  "modern web" requirement on Python-hosted Blender. **The architecture is engine-
  agnostic** — the helper sits behind the SHM + socket boundary, so swapping
  cefpython → C++ CEF touches ZERO Blender-side code. Keep the SHM/socket contract
  language-neutral (it already is).
- **Alternative for owner to weigh:** an **Electron** helper (current Chromium, JS/Node,
  no C++ build) using offscreen rendering (`paint` raw frames + `sendInputEvent`). Avoids
  C++ at the cost of a heavier runtime; OSR API to be verified (task B-4a). Same Option-3
  architecture.
- **NOT recommended:** cefpython-only real build (ships Chromium-66 breakage + security
  liability for live browsing).

**OS = Windows (RESOLVED).** B finalized Windows specifics:
- *Keyboard:* portable VK table = `windows_key_code`; `native_key_code = 0` for v1; text
  via `event.unicode` → CEF CHAR event; no IME in v1.
- *Clipboard:* use `bpy.context.window_manager.clipboard` both directions; no pywin32;
  text-only v1.
- *Shared memory:* **Blender add-on creates and OWNS** the
  `multiprocessing.shared_memory` segment (survives helper restarts); **helper attaches
  by name** (uuid-named, passed as launch arg). Windows frees the mapping when the last
  handle closes — no manual unlink, but Blender must hold the reference for the session.
  A future C++ helper opens the same name via `OpenFileMapping`/`MapViewOfFile`.

**Phase 1b is NOT gated by the engine decision** (the spike uses cefpython regardless).
Remaining gate: **A-1** — run `phase1a_upload_benchmark_v2.py` to lock the upload path.

---

## 17. Session 7 — benchmark v2 result; integer path dead; engine confirmed

**Engine CONFIRMED by owner: real build = native C++ CEF (current Chromium).** Electron
not pursued. cefpython = spike only.

**Benchmark v2 (Blender 4.4 / OpenGL / RTX 4090):**
- **RGBA8UI integer-texture path REJECTED — hard API limit.** Explicit error:
  `GPUTexture.__new__: Only Buffer of format FLOAT is currently supported`. So 4.4's
  create-from-data path is FLOAT-only; no UBYTE/RGBA8UI upload exists. B-1 fallback ladder
  resolves to **F3: FLOAT is mandatory.** The convert tax + 4× bandwidth are locked in.
- FLOAT path (preallocated + vectorized convert) — total ms / fps:
  720p 6.36/157 · 900p 9.38/107 · 1080p 12.32/81 · 1440p 20.29/49.
  Split: convert (CPU) 1.7→7.3 ms, gpu upload 4.6→13.0 ms — both inflated by FLOAT,
  neither removable on 4.4.

**Decisions:**
- **Integer-texture optimization CLOSED.** Upload dtype cannot raise the cap on 4.4.
  §15 resolution strategy stands unchanged.
- **Resolution reality:** 1080p comfortably >60 even with the FLOAT tax; 1440p ~49 fps
  (fine for browsing, marginal for 60 fps video). CAVEAT: numbers are on an RTX 4090 — the
  gpu column scales with GPU, the convert column with CPU, so weaker hardware lowers the
  effective cap. Render at panel size, soft-cap ~1440p, half-rate video above.
- **Future:** if Blender 5.x (Vulkan) is targeted, recheck for a non-FLOAT upload /
  partial-update path; could lift the cap. Not available in 4.4.
- **Phase 1b fully unblocked.** Scaffold drafted (SHM contract + cefpython helper +
  Blender thin client) on the FLOAT / full-reupload path → `docs/blender-browser/phase1b/`.

---

## 18. Runtime cost model — "always on, ~browser cost?" (owner concern, Session 8)

**The benchmark measured PEAK throughput, not steady-state load.** The v2/v1 numbers come
from a tight loop uploading+drawing flat-out with zero idle time, to find the ceiling.
That is NOT how the system runs. 81 fps at 1080p means "each upload+draw costs ~12 ms and
the loop did them back-to-back" — it is headroom, not constant work.

**Frames are produced only on damage.** CEF's `OnPaint` fires only when the page actually
changes. A static page → zero frames → zero uploads → zero draws. Real cost =
(per-changed-frame pipeline cost) × (frames actually changing per second).

**Engine cost is identical to a real browser — because it IS one.** The helper runs the
same Chromium engine a normal browser would. Our only OVERHEAD vs a native browser is the
per-changed-frame pixel path: off-screen readback (GPU→CPU), the 4.4-forced uint8→float32
convert, and the 4× re-upload (CPU→GPU). A native browser keeps this on the GPU; we pay to
move it through CPU + shared memory.

**Per-frame overhead on owner HW (RTX 4090, from v2 split):** ~3.9 ms CPU convert + ~8.5 ms
GPU upload at 1080p (the GPU figure is mostly driver/sync; actual 4090 utilization is low).

**Steady states:**
- **Idle (page just sitting there):** ≈ zero added CPU/GPU. RAM ≈ one Chromium process
  (browser-like). Always-on idle cost ≈ an open browser tab. ✅ meets the "not much more
  than a browser" bar.
- **Active scroll / 30 fps video @ 1080p, capped:** ~30 × 3.9 ms ≈ 120 ms CPU/sec added
  (~12% of one core) on top of the engine's own work (same as a browser). GPU upload is
  trivial on this GPU class. Acceptable.
- **Worst case (large panel, sustained 60 fps video, high res):** overhead grows and this
  is where it's meaningfully MORE than a native browser. Bounded by the caps below.

**Levers that keep always-on cheap (design):**
1. **Cap the CEF off-screen frame rate** (`SetWindowlessFrameRate`, e.g. 30). A browser
   panel does not need 60; this directly halves active cost vs 60.
2. **Render at the panel's pixel size** (already the resolution strategy).
3. **Upload only on damage** — never re-upload an unchanged frame (the pump already gates
   on the sequence number).
4. **Suspend when hidden/unfocused** — `WasHidden(true)` / drop frame rate to ~1 when the
   browser area isn't visible or focused, so background cost ≈ idle.

**Net:** idle ≈ a browser tab; active = the same engine cost + a bounded readback/convert
overhead that's more than a native browser during video but tunable via fps + resolution
caps. With a 30 fps cap, panel-size rendering, and idle-suspend, "always on, ~browser cost"
holds for typical use; sustained high-res video is the one case that's noticeably heavier.

**Open:** the peak benchmark doesn't directly report steady-state CPU%. A "benchmark v3"
should measure idle (≈0 uploads) and a capped-rate realistic load, reporting actual
CPU/budget rather than peak fps → queued as B-6.
