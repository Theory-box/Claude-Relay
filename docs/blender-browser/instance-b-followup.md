# Instance B — Follow-up (B-1 / B-2 / B-3)

Companion to `architecture.md` and `phase1a_upload_benchmark_v2.py`. Responds to the
three tasks Instance A queued in `handoff.md`. Confidence scores attached.

---

## B-1 — Settle the upload ceiling (RGBA8UI integer-texture path)

**Deliverable:** `phase1a_upload_benchmark_v2.py` (runs head-to-head FLOAT vs RGBA8UI,
splits CPU-convert from GPU-bound time, preallocates, and prints the exact UBYTE
rejection). It must be run on the owner's machine — I can't execute Blender here — so
below is the prediction and the decision tree for whatever the script reports.

**Why v1 was forced to FLOAT (root cause, ~0.8).** Blender's Python
`GPUTexture(format='RGBA8', data=Buffer)` path validates the `Buffer` dtype against the
format's component type. `RGBA8` is a *normalized/unorm* format, and the create-from-data
path expects a `FLOAT` buffer (values 0..1), so a `UBYTE` buffer is rejected. That forced
the uint8→float32 normalize (the recurring CPU tax) **and** quadrupled the bytes on the
bus (33 MB → 132 MB at 4K). Both are artifacts of the format choice, not a hard GPU wall —
matching §15's "wall is partly self-imposed" read.

**The fix being tested.** `RGBA8UI` is a true unsigned-integer format. It legitimately
accepts a `UBYTE` buffer (no convert, 1× bytes), but it **must** be sampled with a
`usampler2D` — the GLSL spec makes reads undefined if an integer image format is bound to
a float `sampler2D` (verified against the Khronos GLSL sampler rules). So the texture
change requires the shader change; they're a package. Normalize and do the BGRA→RGBA swap
in-shader (`vec4(c.b,c.g,c.r,c.a)/255.0`), which is free, per A's CEF-pipeline note.

**Prediction (~0.7):** the RGBA8UI + `usampler2D` path builds and runs on 4.4/OpenGL and
removes the convert tax + 4× bandwidth, plausibly lifting 1440p past 60 fps and 4K from
"not viable" to "marginal." I hold this at 0.7, not higher, because two things can still
bite and only the benchmark settles them:

1. **`GPUTexture(format='RGBA8UI', data=Buffer('UBYTE',...))` might still reject the
   data-at-construction path** in 4.4 (the create-from-data path historically leaned
   float). The script prints the exact exception if so.
2. **Integer textures force NEAREST filtering** (can't be linearly filtered). For a
   native-resolution 1:1 panel blit that's correct and even sharper, so it's a non-issue
   *here* — but it means this texture can't be cheaply downscaled with bilinear if you
   ever render the page larger than the panel. Note it; don't let it surprise a future
   you.

**Fallback ladder (if the benchmark rejects RGBA8UI-from-data):**
- **F1:** create the RGBA8UI texture once, update via a write path. ✗ — there is no
  `GPUTexture.write()`/sub-image method in the Python API (confirmed; it's an open
  feature request on devtalk). So per-frame full re-create is unavoidable regardless.
- **F2:** keep FLOAT but kill the avoidable CPU cost — preallocate the float32 target
  (done in v2) and vectorize the normalize with numpy `out=` (done). This alone should
  beat v1's numbers even without the integer path, since v1's wording suggests per-frame
  allocation. Measure the delta; it may already move 1440p toward 60.
- **F3:** if FLOAT stays mandatory, the byte→float normalize is the one unavoidable
  recurring CPU cost (A's §15 conclusion stands) and the ~1440p soft cap holds.

**Outcome routing:** if v2 shows UINT < FLOAT and RGBA8UI was accepted → raise the soft
cap (propose 1440p/60 target, 4K marginal-but-allowed). Otherwise → keep the §15 cap and
the resolution strategy unchanged. Either way **Phase 1b is not blocked** — the panel-size
reality (≤1080p typical) already has headroom.

---

## B-2 — Keyboard mapping (Blender modal events → CEF SendKeyEvent)

**Strategy (OS-independent core; ~0.75).** Don't hand-map every key to a virtual-key
code. Split by purpose:

- **Printable text → CEF `CHAR` events, driven by `event.unicode`.** Blender already
  resolved the layout/modifiers into the actual character. Send a CEF key event of type
  `KEYEVENT_CHAR` whose `character`/`unmodified_character` is that Unicode codepoint. This
  gets correct text on non-US layouts *without* you reimplementing a keymap — it's the
  single most important decision and it's fully OS-independent.
- **Non-printable / control keys → `KEYDOWN`+`KEYUP` with a virtual-key code.** Set CEF
  `windows_key_code` from the table below. CEF uses Windows VK codes as the canonical
  `windows_key_code` on *all* platforms, so this table is portable; `native_key_code` is
  the OS-specific refinement (see OS note).
- **Per physical key, the real sequence is:** `RAWKEYDOWN` (or `KEYDOWN`) → `CHAR` (only
  if it produced text) → `KEYUP`. Editing keys (backspace, enter, arrows, etc.) skip the
  CHAR.
- **Modifiers:** fold Blender's `event.shift/ctrl/alt/oskey` into CEF's
  `modifiers` bitfield (`EVENTFLAG_SHIFT_DOWN`, `_CONTROL_DOWN`, `_ALT_DOWN`,
  `_COMMAND_DOWN`) on every event.

**Control-key table (Blender `event.type` → CEF `windows_key_code`).** Canonical VK
codes, portable as `windows_key_code`:

| Blender `event.type` | CEF windows_key_code | VK |
|---|---|---|
| `RET` / `NUMPAD_ENTER` | VK_RETURN | 0x0D |
| `BACK_SPACE` | VK_BACK | 0x08 |
| `DEL` | VK_DELETE | 0x2E |
| `TAB` | VK_TAB | 0x09 |
| `ESC` | VK_ESCAPE | 0x1B |
| `LEFT_ARROW` | VK_LEFT | 0x25 |
| `RIGHT_ARROW` | VK_RIGHT | 0x27 |
| `UP_ARROW` | VK_UP | 0x26 |
| `DOWN_ARROW` | VK_DOWN | 0x28 |
| `HOME` | VK_HOME | 0x24 |
| `END` | VK_END | 0x23 |
| `PAGE_UP` | VK_PRIOR | 0x21 |
| `PAGE_DOWN` | VK_NEXT | 0x22 |
| `INSERT` | VK_INSERT | 0x2D |
| `SPACE` | VK_SPACE | 0x20 (also produces a CHAR) |
| `F1`..`F12` | VK_F1..VK_F12 | 0x70..0x7B |
| letters/digits (when needed as keycode) | VK_A..VK_Z / VK_0..VK_9 | 0x41.., 0x30.. |

Shortcuts (Ctrl+C/V/X/A) work by sending the letter's KEYDOWN with the control modifier
flag set; CEF's focused page handles the edit command. Clipboard *sync* with the OS is a
separate concern (architecture.md §6) and is OS-dependent.

**Prior art to copy, not reinvent:** Unreal Engine's `WebBrowser` plugin
(`SlateInputMappings` / its CEF key-event translation) and CEF's own `cefclient` OSR
handlers are the canonical references for the VK table + the KEYDOWN/CHAR/KEYUP ordering;
Unity CEF wrappers (e.g. the various `UnityCef`/`ZenFulcrum` integrations) solve the same
split. Lift their table; don't derive it.

**OS dependency (blocked on owner OS — flagged in handoff):**
- `native_key_code` (and `is_system_key` on macOS) differ per platform: Windows = scan
  code, macOS = `kVK_*` carbon codes, Linux/X11 = keycode (keysym+8). For ASCII v1 you
  can often leave `native_key_code = 0` and rely on `windows_key_code` + `CHAR`; some keys
  (notably on macOS) want the native code to behave. Finalize this table once the owner's
  OS is known.
- **IME stays out of v1** (CJK/composition): Blender's modal operator surfaces no IME
  composition events, so live composition can't be fed to CEF from an add-on. v1 target =
  committed Unicode only. Declared limitation.

---

## B-3 — Modal-operator coexistence (don't break Blender's input)

**Skeleton + routing rules (OS-independent; ~0.75).** The failure mode to design against:
a modal operator that consumes too much globally eats Blender's own shortcuts. Rules:

1. **Capture only when "hot":** pointer is inside the browser region AND the browser is
   focused. Compute hot-ness from `event.mouse_region_x/y` against the region size each
   event.
2. **When hot:** translate the event, forward it over the control socket, and return
   `{'RUNNING_MODAL'}` (consume) for events the page should own — mouse move/click/scroll,
   text/edit keys.
3. **When not hot, or for events the browser shouldn't own** (Blender hotkeys, e.g. a
   global save), return `{'PASS_THROUGH'}` so Blender behaves normally.
4. **Focus transitions:** send `focus` to the helper on region-enter, `blur` on
   region-leave; track with an internal `self._focused` flag toggled from mouse position.
5. **Never block the frame pump:** the modal op only forwards input. The
   `bpy.app.timers` frame pump (texture upload + `tag_redraw`) runs independently on the
   main thread — they must not call each other; they share only the texture handle.
6. **Lifecycle:** start the modal op when the browser area opens; end it (`{'CANCELLED'}`)
   on area close / add-on disable, and tear down focus + socket cleanly.

```python
class BROWSER_OT_input(bpy.types.Operator):
    bl_idname = "browser.input"
    bl_label = "Browser Input Capture"

    def invoke(self, context, event):
        self._focused = False
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _hot(self, context, event):
        r = context.region
        if r is None:
            return False
        x, y = event.mouse_region_x, event.mouse_region_y
        return 0 <= x < r.width and 0 <= y < r.height

    def modal(self, context, event):
        # End conditions first (area gone / browser closed).
        if not browser_is_open(context):
            self._send("blur")
            return {'CANCELLED'}

        hot = self._hot(context, event)

        # Focus edge transitions.
        if hot and not self._focused:
            self._focused = True
            self._send("focus")
        elif not hot and self._focused:
            self._focused = False
            self._send("blur")

        if not hot:
            return {'PASS_THROUGH'}          # outside region -> Blender owns it

        et = event.type
        if et == 'MOUSEMOVE':
            self._send_mouse_move(event); return {'RUNNING_MODAL'}
        if et in {'LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE'}:
            self._send_mouse_button(event); return {'RUNNING_MODAL'}
        if et in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            self._send_wheel(event); return {'RUNNING_MODAL'}

        # Let a few global Blender shortcuts through even when hot (tune to taste):
        if et in PASSTHROUGH_HOTKEYS:        # e.g. {'ESC'} to release, save combos
            return {'PASS_THROUGH'}

        if event.value in {'PRESS', 'RELEASE'}:
            self._send_key(event)            # KEYDOWN/KEYUP (+CHAR via event.unicode)
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    # _send_* methods marshal to the control socket; never call gpu here.
```

**Acceptance test for Phase 3:** with the browser open and focused, Blender's global
shortcuts outside the region still fire; with the pointer outside the region, all keys
behave as vanilla Blender. Treat "Blender stays fully usable with the browser open" as a
pass/fail gate, not a nicety.

---

## Hand-back to Instance A

**Status:** B-1 (script delivered, needs an owner run), B-2 (delivered, native_key_code
table pending OS), B-3 (delivered).

**Digest deltas to fold in:**
- Upload-ceiling decision is now *pending one benchmark-v2 run*; resolution strategy
  unchanged until then.
- Keyboard architecture decided: Unicode-CHAR for text + portable VK table for control
  keys; no IME in v1.
- Modal coexistence pattern decided (hot-region gating + PASS_THROUGH discipline).

**New tasks / questions for Instance A:**
- **A-1:** Run `phase1a_upload_benchmark_v2.py` on the owner's machine (or have the owner
  run it) and paste the table back here. That single run resolves the cap.
- **A-2:** For the Phase 1b helper, decide the SHM segment naming + watchdog cleanup
  scheme (unique per session, unlink-stale-on-restart — architecture.md §3 of the review).
  This is OS-flavored; gate on owner OS.
- **A-3 (question for me/B):** once OS is known, do you want B to produce the
  platform-specific `native_key_code` table and the clipboard-sync calls, or fold that
  into the Phase 1b scaffold you own?

**Still blocking (owner):** target OS (Windows/macOS/Linux) — gates B-2's native codes,
SHM specifics, and clipboard sync.
