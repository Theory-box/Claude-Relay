# Instance B — Phase 1b scaffold review (B-5) + idle-suspend verification (B-6)

Reviews `phase1b/SHM_CONTRACT.md`, `helper_cefpython.py`, `blender_addon_spike.py`
against "will it run on the owner's Windows machine," and answers B-6 (the always-on cost
knobs). The owner wants to test now, so B-5 is ordered by severity: run-blockers first.
I'm flagging with exact fixes rather than editing A's scaffold (A owns it).

## Overall
The scaffold is structurally sound — the §18.1 helper-side FLOAT convert is correctly
reflected (Blender's pump does no convert, just views float32 and uploads), the
publish-before-sequence ordering is right, and the B-3 modal pattern was adopted well.
But there are **two issues that will likely stop the spike from working on first run**
(B-5 #1 and #2) and one that will waste the owner's debugging time (#4). Fix those three
before the owner runs it.

---

## B-5 — findings (severity-ordered)

**#1 [RUN-BLOCKER, ~0.8] `GPUTexture` is created in the timer, not in a draw callback.**
`_pump` is a `bpy.app.timers` callback and calls `gpu.types.GPUTexture(...)` /
`gpu.types.Buffer(...)`. The `gpu` module requires an **active GPU context**, which is
guaranteed only inside draw handlers — **not** in timers. This typically errors or is
unstable. Fix: the timer should only detect a new frame and request a redraw; do the
view+upload inside `_draw` (valid context).
```python
# _pump (timer): no gpu calls
def _pump():
    shm = _S["shm"]
    if shm is None:
        return None
    seq = struct.unpack_from("<I", shm.buf, 28)[0]
    if seq != _S["last_seq"]:
        _S["last_seq"] = seq
        _S["dirty"] = True
        for area in bpy.context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                area.tag_redraw()
    return 1.0 / 60.0

# _draw (draw handler, valid GPU context): build the texture here
def _draw():
    if _S.get("dirty"):
        buf = _S["shm"].buf
        active = struct.unpack_from("<I", buf, 24)[0]
        off = HEADER + active * (WIDTH * HEIGHT * 16)
        arr = np.frombuffer(buf, np.float32, count=WIDTH*HEIGHT*4, offset=off)
        fb = gpu.types.Buffer('FLOAT', WIDTH*HEIGHT*4, arr)
        _S["tex"] = gpu.types.GPUTexture((WIDTH, HEIGHT), format='RGBA8', data=fb)
        _S["dirty"] = False
    # ... existing draw of _S["tex"] ...
```

**#2 [CORRECTNESS, ~0.75] Helper CHAR event is malformed.** In `helper_cefpython.py`
`_dispatch`, the CHAR event sets `"windows_key_code": ord(char)`. cefpython CHAR events
carry the character in `character` / `unmodified_character` (a UTF-16 code unit), not
`windows_key_code`. As written, typed text won't appear. Fix:
```python
if msg["down"] and msg.get("char"):
    cp = ord(msg["char"])
    host.SendKeyEvent({"type": cef.KEYEVENT_CHAR,
                       "character": cp, "unmodified_character": cp,
                       "modifiers": msg.get("mods", 0)})
```

**#3 [FUNCTIONALITY GAP] Control keys do nothing (`vk=0` always).** The add-on always
sends `"vk": 0`, so once #2 is fixed, printable text works via CHAR, but
Enter/Backspace/Tab/arrows produce nothing (no char, vk=0). Fine for the "a click
registers" success gate; wire the B-2 VK table (`event.type → windows_key_code`) before
text fields are actually usable. (Note: `ESC` is in `PASSTHROUGH`, used to release focus,
so it intentionally won't reach the page.)

**#4 [DEBUGGABILITY — high practical value] Helper subprocess output is discarded.**
`subprocess.Popen([...])` captures no stdout/stderr. If the helper dies on a cefpython
import or a signature mismatch (likely on first run with Chromium-66 cefpython), the
Blender side just shows a blank panel with zero diagnostics. For "test now," redirect to
a log:
```python
logf = open(os.path.join(bpy.app.tempdir, "browser_helper.log"), "w")
_S["proc"] = subprocess.Popen([...], stdout=logf, stderr=subprocess.STDOUT)
```
This converts most first-run failures from "blank panel, no idea" into a one-line error.

**#5 [CONTEXT] Modal operator trusts `context.region`.** In a modal operator
`context.region` is whatever region the pointer is over — not necessarily the Image
Editor the browser opened in. Hovering another editor could misroute clicks. Capture the
target area/region at `invoke` and validate events against that specific region.

**#6 [SHM RACE — matches review §3] Double buffer can tear under fast-producer/slow-consumer.**
Publish order is correct for single-producer/single-consumer, but with only two slots a
producer running ≥2 frames ahead overwrites the slot the consumer is mid-reading (frame
N+2 reuses the slot taken at frame N). At a 30 fps cap with a fast GPU upload the window
is tiny, so **the spike is acceptable as-is**, but this is exactly why review §3
recommended **triple buffering** — adopt it in Phase 2, not the spike.

**#7 [cefpython v66 signature checklist — verify on-machine].** These are version-sensitive;
confirm against the installed `cefpython3` before a long debugging session:
- `browser.SetClientHandler(handler)` — correct (cefpython inspects handler members by
  name: `OnPaint`, `GetViewRect`). ✓
- `GetViewRect(self, rect_out)` → `rect_out.extend([0,0,w,h]); return True`. ✓
- `paint_buffer.GetString(mode="bgra", origin="top-left")` — confirm kwarg names in v66.
- `host.SendMouseClickEvent(x, y, button, mouseUp, clickCount)` — confirm kwarg ordering.
- `cef.PostTask(cef.TID_UI, fn, *args)` — confirm it forwards extra args (it does in v66).

**#8 [MINOR] `_stop` ordering / Windows `unlink`.** `_stop` may free the SHM while a
queued `_pump`/`_draw` still runs — remove the draw handler + unregister the timer and set
`_S["shm"]=None` *before* `close()`. `SharedMemory.unlink()` is a no-op on Windows
(harmless to leave).

---

## B-6 — always-on cost knobs (this answers the owner's live worry)

**Confirmed against cefpython's API (Chromium-66 build):**
- **`windowless_frame_rate` IS a cefpython BrowserSettings option** (min 1, max 60,
  default 30). Set it at creation to cap how often `OnPaint` fires:
  ```python
  state.browser = cef.CreateBrowserSync(win, url=a.url,
                                        settings={"windowless_frame_rate": 30})
  ```
- **`browser.WasHidden(True/False)` IS exposed in cefpython** (listed in its API index).
  Call `WasHidden(True)` when the panel isn't visible → CEF drops frame production to
  ~idle; `WasHidden(False)` to resume.

**Caveat:** the *dynamic* `SetWindowlessFrameRate(n)` method may **not** be wrapped in
cefpython (it exposes ~50% of the CEF API; I could not confirm the binding). So for the
**spike**, set the cap at creation via `windowless_frame_rate` and use `WasHidden` for
idle — do **not** rely on the scaffold's `TODO: SetWindowlessFrameRate(30)` dynamic call.
For the **C++ real build**, `SetWindowlessFrameRate` is fully available for dynamic tuning.

**Contract gap that blocks idle-suspend (action needed):** `SHM_CONTRACT.md` has **no
message to tell the helper the panel is hidden/shown**, so `WasHidden` can't be driven.
Add to Blender→helper:
```
set_hidden{on: bool}   # Blender sends on=True when the Image Editor area is closed/hidden
                       # or the Blender window is minimized; helper calls WasHidden(on)
```
Without this wiring the always-on cost story (§18) isn't realized in practice.

**Bottom line for the owner's question ("will my computer work hard all the time?"):**
No — and it's mechanically guaranteed, not hand-waving. `OnPaint` is demand-driven (fires
only on page damage), the rate is capped by `windowless_frame_rate`, and `WasHidden(True)`
drops a non-visible panel to ~0. A static or hidden page produces ~0 frames → ~0 cost,
matching the §18.1 v3 measurement (idle ≈ 0). The cost only appears while something is
actually animating on a visible panel (video being the hotspot — cap to 1080p/half-rate
per §18.1). The one thing required to make idle-suspend real is the `set_hidden` wiring
above.

---

## Hand-back to Instance A

**Done:** B-5 (scaffold reviewed — 3 fixes needed before the owner runs: #1 texture-in-draw,
#2 CHAR event, #4 helper logging; rest are gaps/minor). B-6 (cost knobs confirmed:
`windowless_frame_rate` at creation + `WasHidden`; dynamic `SetWindowlessFrameRate`
unconfirmed in cefpython → use creation-time cap for the spike).

**New tasks / asks for A:**
- **A-4 (do before owner runs):** apply B-5 #1, #2, #4 to the scaffold (snippets above).
- **A-5:** add `set_hidden{on}` to `SHM_CONTRACT.md` + the helper (`WasHidden`) + the
  add-on (send on area-hide / window-minimize). Unlocks the §18 idle-suspend in practice.
- **A-6:** change the helper to set `windowless_frame_rate` at `CreateBrowserSync` instead
  of the dynamic `SetWindowlessFrameRate` TODO.

**Still queued for B:** **B-4** (C++ CEF real-build bring-up notes for Windows — CEF build
choice 143-LTS vs 147, `OnPaint→SHM` C++ client matching the contract, toolchain,
`OpenFileMapping` name-matching). Deferred this turn because it's for the real build, not
the immediate cefpython test; I'll take it next unless you'd rather I do something else
first.
