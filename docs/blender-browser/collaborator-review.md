# In-Blender Web Browser — Collaborator Review & Recommendations

**Role:** Second collaborating instance, responding to `architecture.md` §11 (and §9).
**Posture:** Direct critique invited by the doc. I agree with the spine of the design;
my value is in the corners where I think the doc is either too optimistic or hasn't
named the real risk. Confidence scores are attached throughout.
**Grounding:** Where a claim depends on the current state of CEF / Ultralight / Servo /
Blender's `gpu` module (June 2026, past my training cutoff), I verified against live
sources rather than memory. Those are flagged inline.

---

## 0. Verdict on the idea itself

**Approve. Build it. Option 3 is the correct architecture and I would not relitigate it.**
Confidence ~0.85.

The reasoning that wins it isn't "shared memory is fast" — it's the *decoupling*
argument. A separate helper with its own runtime is immune to Blender's Python churn
(3.11 → 3.13) and to Vulkan-by-default, while the only in-Blender code is `bpy` + `gpu`
+ `mmap` + `socket`, all stable. That single property is worth more than any
micro-optimization, and it's the reason Option 2 is correctly dead and gets *worse*
over time, exactly as the doc says.

But the doc misplaces where the project actually dies. It treats the SHM transport as
the interesting part. The SHM transport is solved engineering. **The two things that
will quietly kill this if underestimated are (1) per-frame GPUTexture upload throughput
from Python at high resolution, and (2) input fidelity — keyboard/IME plus a modal
operator coexisting with Blender's own event handling without breaking Blender.** The
review below pushes hardest on those two, and proposes splitting the Phase-1 spike to
attack the worse one first.

---

## 1. Engine choice — CEF vs Ultralight vs Servo

**Recommendation: CEF for the shipped product. Do not adopt Ultralight. Watch Servo for v2.**
Confidence ~0.8.

**Ultralight (verified ultralig.ht, Dec 2025 coverage).** It is genuinely attractive on
the two axes the doc cares about — tiny footprint vs Chromium, and a *GPU-native*
renderer (D3D/Metal/OpenGL, or a custom GPUDriver) instead of a CPU buffer. If the goal
were a constrained HTML *panel*, I'd seriously consider it. But it disqualifies itself
for a *general web browser* on fidelity: Ultralight has **no WebGL, no WebRTC, and only
experimental HTML5 video/audio.** The locked requirement is "real modern web pages
(working CSS + JavaScript)"; a browser that can't run WebGL or play video fails that on
arrival. Secondary problem: the core is **proprietary, commercial-license** — a real
per-product cost and legal step, where CEF is BSD. Tertiary, and worth calling out
because it's counterintuitive: Ultralight's GPU-native edge is *partly neutralized by
the same wall that limits CEF here* — you still cannot hand Blender's GPU device to an
external process from an add-on, so you'd still copy out to a buffer and re-upload. The
headline advantage shrinks in this specific deployment.

**Servo (verified servo.org, embedding work through 2025).** Now has a real `WebView`
API, an `OffscreenRenderingContext`, multi-webview support, and — unlike Ultralight —
**WebGL and WebGPU.** Memory-safe Rust is a nice property for a process exposed to the
live web. But embedding is still maturing: the production reference is `servoshell`, and
the general-purpose embeddable path (the Tauri/WRY integration) was described by the
project itself as not production-ready. For a v1 you'd be betting the spike on a moving
target. **My call: not for v1, but it's the most interesting "revisit in 12–18 months"
option, especially if Chromium's footprint/maintenance becomes painful.**

**CEF.** Full Chromium fidelity (WebGL, WebRTC, non-DRM video), mature OSR, the largest
body of prior art for exactly this "render off-screen, blit into our app" pattern, and a
permissive license. Cost is the ~150 MB footprint and the obligation to keep it patched
(see §2 and §10). For v1 it's the only choice that satisfies the locked requirements
without a research gamble.

| Engine | Fidelity (WebGL/WebRTC/video) | Footprint | License | OSR maturity | Verdict |
|---|---|---|---|---|---|
| **CEF** | Full | ~150 MB | BSD-ish (free) | High | **v1 choice** |
| Ultralight | No WebGL/WebRTC, video experimental | Small | Proprietary, paid | GPU-native | Rejected for a general browser |
| Servo | WebGL + WebGPU | Medium | MPL (free) | Improving, not production-general | v2 watch |

---

## 2. Helper: cefpython3 vs native C++ CEF

**Agree with the doc's lean, and I'd state the security argument more forcefully than it does.**
Spike in **cefpython3**; ship in **native C++**. Confidence ~0.8.

- **cefpython binding ceiling is a non-issue for the spike** (verified: cefpython3
  official support tops out ~Py3.9, unofficial 3.10). Because the helper runs its *own*
  Python, it never has to match Blender's interpreter — this is the whole point of
  Option 3, and it holds.
- **Why C++ for the shipped product, stated bluntly:** this helper is a *real Chromium
  exposed to the live web on the user's machine.* cefpython's release cadence lags
  upstream Chromium, which means shipping it = shipping an unpatched browser to end
  users. That's not a polish concern; it's a standing CVE surface. C++ CEF lets you
  track upstream and rebuild on a security cadence. The doc frames C++ as "more robust";
  the sharper framing is "C++ is how you stay patchable." This is the strongest single
  argument and it's underweighted in §9.1.
- **Failure modes to plan for.** cefpython: stale Chromium (security), binding gaps
  (clipboard hooks, `OnAcceleratedPaint`, newer CEF settings), and update friction.
  C++: more upfront dev, and per-platform **build + code-signing/notarization**
  (macOS notarization and Windows signing are mandatory for a browser users will trust,
  and are real calendar time). Neither failure mode is fatal; both are budgetable.

---

## 3. Shared-memory frame protocol

**Recommendation: triple buffer, atomic publish index, full-frame writes, lock-free hot path.**
Confidence ~0.8.

- **Triple, not double, for the shipped product.** Double buffering stalls the producer
  whenever the consumer is mid-read of the other slot. With a 60 fps CEF producer and a
  ~60 Hz Blender timer that can drift or skip, a third slot lets the producer always
  have a free slot to write while the consumer holds one and a published one waits.
  *Double is fine for the spike* — don't over-build before Phase 1 proves the pipe.
- **Publish discipline (single-producer/single-consumer).** Header carries an atomic
  64-bit `frame_seq` and an atomic `active_index`. Producer: write pixels into a back
  slot → **release-store** `active_index` → increment `frame_seq`. Consumer: **acquire-load**
  `frame_seq`; if changed, acquire-load `active_index`, read that slot. No mutex on the
  hot path. The release/acquire pairing is what prevents tearing without a lock.
- **Python `multiprocessing.shared_memory` pitfalls — these are the ones that bite:**
  1. **`resource_tracker`.** On Linux/macOS, Python's resource tracker tries to unlink
     the segment when a process it knows about dies, and will emit warnings / cause
     premature unlink for a *shared* long-lived segment. For a buffer two processes
     co-own, you typically have to work around the tracker (unregister the segment) or
     drop to POSIX `shm_open` directly. Budget time for this — it's the #1 source of
     "works on my machine, leaks/crashes on yours."
  2. **Name collisions on restart.** Generate a unique segment name per session
     (UUID-suffixed) and pass it to the helper as an arg; never hardcode.
  3. **Stale segments after a crash.** The watchdog must unlink the known-named segment
     before recreating on helper restart, or `/dev/shm` accumulates.
- **Python↔C++ boundary (the shipped path).** Do **not** rely on
  `multiprocessing.shared_memory` semantics on the C++ side. Use a plain named mapping
  (`shm_open`+`mmap` POSIX / `CreateFileMapping` Windows) with a **fixed, explicitly
  packed C-struct header**: pad the header to a page boundary, put each atomic on its own
  64-byte cache line, align pixel slots to 4096. Alignment and a frozen header layout are
  mandatory across the language boundary — mismatched struct packing is a silent
  corruption bug, not a crash.

---

## 4. GPU upload cost — the honest answer

**Expect FULL re-upload per frame. It's fine at 1080p/60, probably fine at 1440p, and is
the genuine risk corner at sustained 4K/60.** Confidence ~0.75.

I verified the current Blender `gpu.types` API. The Python surface gives you `GPUTexture`
constructed from a `gpu.types.Buffer` (full data) and image-datablock paths
(`gpu.texture.from_image`); there is **no documented partial/sub-region texture-update
method and no PBO / persistent-mapped-buffer path exposed to Python.** `bgl` (which used
to give you `glTexSubImage2D`) is deprecated/removed for the Vulkan transition. So the
realistic per-frame path is: build a `Buffer` from the BGRA bytes and (re)create/upload
the whole texture each frame.

**The math.** 3840×2160×4 ≈ **33.2 MB/frame**; at 60 fps ≈ **2.0 GB/s**. The PCIe bus and
driver eat that easily. **The bottleneck is the Python side**, not the bus: constructing a
33 MB `Buffer` from a `bytes`/`memoryview` every frame, under the GIL, with copies, on the
main thread alongside everything else Blender does. At 1080p (8.3 MB, ~0.5 GB/s) it's
comfortable; 4K/60 sustained full-frame is where pure-Python upload may not hold.

**Mitigations, in priority order:**
1. **Only upload on a new `frame_seq`.** Most browsing is *not* 60 fps of full-frame
   change — a static article uploads ~0 frames. This alone removes most of the cost.
2. **Cap `windowless_frame_rate`** (e.g. 30) at high resolutions.
3. **Render the page at the region's native resolution**, not always 4K. The "crisp text"
   lever is DPR-correct rendering, not maximum pixels.
4. Dirty rects help the *SHM copy* but **not** the GPU upload, because Python can't do a
   sub-region texture update. Be honest in the design that dirty-rect optimization is a
   helper-side / bandwidth win, not a GPU-upload win, given the API.

**Action:** make upload-fps-at-resolution a measured number in Phase 2 — or better, in a
pre-CEF micro-spike (see §10). This is the kind of thing you want to fail *fast*.

---

## 5. Zero-copy, revisited — your "walled off" assumption holds (with one nuance)

**Confirmed walled-off for an add-on. Don't spend Phase-1 budget here.** Confidence ~0.8.

Verified current CEF state: `OnAcceleratedPaint` with `shared_texture_enabled` **does**
exist and **does** work **on Windows** via a D3D11/DXGI shared handle (prior art:
`cef-spout` / `cef-mixer`). Three caveats make it a trap for v1:
- It's **version-fragile** — e.g. a CEF 143 release (Dec 2025) shipped with the
  `shared_texture_handle` coming back **null** on Windows. You'd be chasing CEF-version
  regressions on your critical path.
- **Dirty-rect info in the accelerated path** was historically a *feature request*, not a
  guarantee.
- **macOS/Linux fall back to `OnPaint`** (CPU buffer) — there is no portable cross-platform
  texture-sharing story.

And even on Windows where you *get* a DXGI shared handle, you'd then have to **import it
into Blender's GPU context** as a texture. The `gpu` module exposes **no device handle and
no external-memory import** to Python from an add-on. So the helper-side half is possible
on one platform; the Blender-side half is the actual wall, and it's the half an add-on
cannot reach. **Net: the single-upload cost is correctly accepted. Re-open this only if
Blender ever exposes external-memory import in `gpu` — not soon, don't bet on it.**

---

## 6. Keyboard / IME — rank this the #2 risk, not a detail

**Strategy: Unicode-driven CHAR events for text + a small explicit table for control keys.
No IME in v1, declared as a known limitation.** Confidence ~0.7 (the messy edges are real).

Do **not** try to hand-map Blender `event.type` → native virtual-key codes for *text*.
Split the problem:
- **Text input:** use `event.unicode` (the character Blender already resolved for the
  user's layout) to drive CEF **CHAR** events. This gets correct characters across
  non-US layouts for typed text without you reimplementing a keymap.
- **Control/navigation keys** (arrows, enter, tab, backspace, delete, esc, home/end,
  function keys, modifier state): map `event.type` → CEF `windows_key_code`/`native_key_code`
  via a small per-platform table, sending `KEYDOWN`/`KEYUP` pairs.
- **IME (CJK and friends):** Blender's modal operator does **not** surface IME composition
  events. This is a real wall for an add-on. **v1 target: committed-Unicode text only, no
  live composition.** Declare it. Full IME would need platform-native IME hooks the add-on
  can't cleanly obtain.
- **Prior art to copy, not reinvent:** game-engine CEF integrations solved exactly this.
  Unreal Engine's `WebBrowser`/`WebBrowserWidget` key-translation code and the
  `cef-mixer` input handling are the references; lift the VK mapping table from there.

---

## 7. Host display surface

**Spike with `SpaceImageEditor`. Re-evaluate only if its chrome/gizmos interfere.**
Confidence ~0.7.

`SpaceImageEditor` is the lowest-friction route to "a live page visible in Blender": it's
a clean image-display region, and the `draw_handler_add(..., 'WINDOW', 'POST_PIXEL')` +
modal-operator pattern over it is well-trodden. Costs: it carries its own header/tools you
must hide, and its native event handling can fight your modal operator. A full-window
`POST_PIXEL` handler on a `wm.window_new` window gives the cleanest full-bleed but makes
you fight more overlays/gizmos.

- **Phase 0 check:** confirm you can suppress the image editor's header/overlays from the
  add-on. If not, that pushes you toward the bespoke full-window approach sooner.
- **Modal-operator coexistence (this is where you break Blender if careless):** capture
  events **only** while the pointer is inside the region *and* the browser is focused;
  return `PASS_THROUGH` for everything you don't consume; release on mouse-leave/blur. A
  modal operator that consumes too broadly will silently eat Blender's global shortcuts.
  Treat "Blender stays fully usable with the browser open" as an explicit Phase-3
  acceptance test.

---

## 8. Packaging — download-on-first-run, signed, with a bundle fallback

**Recommendation: signed/hashed download-on-first-run; keep bundling as a fallback. But
check distribution-channel policy first.** Confidence ~0.65.

~150 MB × 3 platforms bundled is large but not unprecedented for a Blender Extension, and
the extension system does handle per-platform binaries. Download-on-first-run keeps the
extension artifact small and lets you ship a platform-matched CEF, but it adds real
obligations: a **host you control**, **integrity + signature verification** (you are
downloading a *browser engine* — unverified download of executable code is a supply-chain
hole, not a convenience), offline/partial-download handling, and an update flow.

**The constraint that decides it:** if you target the **official Blender Extensions
platform**, verify their policy on extensions that *fetch native executables at runtime* —
review guidelines often restrict this. If the policy forbids it, you either bundle, or
self-host/side-load the extension (which loses you the in-app discovery but frees the
constraint). **Resolve this policy question in Phase 0**, because it changes the packaging
design, not just an option toggle.

---

## 9. Loop integration

**`CefDoMessageLoopWork` pumped on a timer, socket serviced on a worker thread that
`CefPostTask(TID_UI, …)`s input onto CEF's UI thread.** Confidence ~0.8.

- Pump CEF with `CefDoMessageLoopWork` on a short interval rather than `CefRunMessageLoop`,
  so the helper can also service the control socket. (Or run CEF's loop on the helper's
  main thread and service the socket on a worker — cleaner.)
- **Hard rule the doc already states, restated because it's the classic crash:** every
  `CefBrowserHost` input call (`SendKeyEvent`, `SendMouseClickEvent`,
  `SendMouseWheelEvent`) must run on CEF's **UI thread**. The socket thread must
  `CefPostTask(TID_UI, …)`, never call directly. Direct cross-thread calls here are
  intermittent corruption, not clean failures.
- **macOS specifics:** CEF must own the process main thread with a proper `NSApplication`
  run loop; service the socket on another thread. Don't put CEF's loop on a secondary
  thread on macOS.
- Consider `external_begin_frame_enabled` if you want to drive cadence yourself; otherwise
  `windowless_frame_rate` governs it. Watch for the message-loop interval starving the
  socket — a dedicated socket thread avoids the tradeoff.

---

## 10. Biggest risk + how I'd de-risk before Phase 1

**Don't revisit Option 1 or 2** — CDP violates self-contained + no-streaming; in-process
is correctly dead and the Python churn makes it worse. The architecture is right. (~0.85)

**Single biggest risk:** the combination of **(a) Python-side full-frame GPUTexture upload
throughput at high resolution** (§4) and **(b) input fidelity + modal-operator coexistence**
(§6/§7). Both are unglamorous, both are easy to under-budget, and either can make the
result feel broken even with a flawless SHM transport.

**Concrete de-risking move — split the spike so the worst unknown fails first:**

- **Phase 1a (hours, no CEF):** a ~50-line standalone writer process draws a moving test
  pattern straight into the SHM buffer at the target resolution. A minimal Blender script
  mmaps it, uploads to a `GPUTexture` each frame, blits a quad, and **prints achieved fps
  at 1080p / 1440p / 4K.** This isolates the single riskiest number (§4) from all CEF
  complexity. If 4K/60 full-frame can't hold in Python, you learn it in an afternoon and
  can adjust the resolution/frame-rate strategy *before* investing in CEF wiring.
- **Phase 1b:** replace the test writer with CEF OSR `OnPaint` → SHM. Now "live page
  visible in Blender" is the gate, and the upload path underneath it is already a known
  quantity.

This reorders the doc's Phase 1 so the make-or-break performance unknown is attacked
before the integration effort, instead of discovered after it.

**Second risk to name explicitly:** ongoing **security maintenance**. A live-web Chromium
shipped to users needs a patch cadence; cefpython lagging upstream is a standing
liability. This is a real argument for C++ CEF (§2) and for budgeting recurring
CEF-update work into the roadmap, which the current plan doesn't show.

---

## 11. Consolidated calls on the §9 open decisions

| # | Decision | Call | Confidence |
|---|---|---|---|
| 9.1 | Helper impl | cefpython3 spike → **C++ CEF** shipped (security/patchability) | 0.8 |
| 9.2 | CEF distribution | **Download-on-first-run, signed/hashed**, bundle fallback; verify channel policy in Phase 0 | 0.65 |
| 9.3 | Frame protocol | **Triple** buffer (double for spike), **atomic** publish index, full-frame writes | 0.8 |
| 9.4 | Control transport | **localhost TCP + length-prefixed JSON** for spike; binary / Unix-socket later if rate matters | 0.75 |
| 9.5 | Host surface | **`SpaceImageEditor`** for spike; bespoke full-window only if chrome interferes | 0.7 |
| 9.6 | Keyboard/IME v1 | **Unicode-CHAR for text + small VK table for control keys; no IME in v1** | 0.7 |
| 9.7 | Multiple instances | **Defer to v2** (CEF supports N browsers/helper; SHM-per-instance; not spike-worthy) | 0.75 |
| 9.8 | Partial texture update | **Not exposed in Python `gpu`; assume full re-upload** (verified) | 0.75 |

---

## 12. Where I'd push back on the doc, in one place

1. **The risk framing is misaimed.** The doc's "hard part" energy is on transport; the
   real hard parts are upload throughput and input. Reweight §10 accordingly. (~0.75)
2. **Security maintenance is missing from the plan.** A shipped live-web Chromium is a
   recurring patch obligation, and it strengthens the C++ decision beyond "robustness." (~0.8)
3. **Dirty-rect optimization is oversold for the GPU side.** Given Python can't do
   sub-region texture updates, dirty rects help bandwidth/SHM, not the upload. Say so. (~0.75)
4. **Phase 1 should be split (1a/1b)** so the performance unknown fails before the
   integration cost. (~0.7)

Everything else in `architecture.md` I'd ship as written. It's a good doc — these are
refinements to a sound plan, not a redirection of it.
