# Cycle Relay

Tap **one key** during a Blender transform to cycle the axis constraint:
`X → Y → Z → X…`, and with Shift, `XY → XZ → YZ…`.

Blender has no such feature and cannot be given one from Python (see
[Why a middleman](#why-a-middleman)). This works around that with a small
macOS helper that rewrites your keystroke into the `X`/`Y`/`Z` that Blender
already understands — so **native transform does all the actual work**.

macOS only.

---

## Install

1. Install `cycle_relay.py` as a normal Blender add-on and enable it.
   Setup runs automatically: it installs [Hammerspoon](https://www.hammerspoon.org/)
   if missing, writes the relay script, and starts it.
2. Grant **Hammerspoon** permission under
   *System Settings → Privacy & Security → Accessibility*.
   This is the one step that cannot be automated — macOS deliberately forbids
   an app granting itself input-interception rights.
3. In the add-on preferences set:
   - **Shortcut you use to move an object** — press *Detect* to read it from
     Blender's keymap, or *Set* and press the combo.
   - **Key that cycles X / Y / Z** — *Set*, then press it. Bare `Cmd`/`Ctrl`/`Alt`
     are allowed.
4. Press **Apply Changes**.

> ⚠️ **Turn the watcher off before changing the Accessibility checkbox.**
> Toggling that permission while event taps are live can hang macOS input
> entirely. The add-on's Off button quits it safely.

---

## Why a middleman

Blender's axis constraints live in the **Transform Modal Map**, where each entry
maps an event to a value from an enum **compiled into Blender's C code**
(`AXIS_X`, `PLANE_Y`, `CONFIRM`, …). Python can add *items* to that modal keymap
but cannot define new actions — so "cycle to the next axis" cannot be written as
an add-on, however small the feature looks.

Injecting a synthetic `X` into the running transform from Python is also out:
`hs.window.event_simulate` exists but requires `--enable-event-simulate`, and
with that flag Blender ignores real keyboard input.

The only place left to intervene is **upstream of Blender**, at the OS input
layer. Hence Hammerspoon.

A previous approach reimplemented Move/Rotate/Scale as a custom modal operator.
It was abandoned: reproducing Blender's transform maths meant reproducing its
edge cases too (off-screen pivots made movement wildly over-sensitive). Wrapping
native transform is strictly better.

---

## Architecture

```
Blender add-on (Python)          Hammerspoon (Lua)
─────────────────────────        ─────────────────────────
simple UI: 2 settings            reads config.json
    ↓ generates                  watches OS input events
rule list → config.json  ──────► matches rules
                                 posts X / Y / Z to Blender
                                 quits when last Blender closes
```

- `cycle_relay.py` — the add-on. Embeds the Lua, installs and manages
  Hammerspoon, writes the config.
- `relay.lua` — extracted copy of the embedded script, for reading. **Not the
  source of truth**: edit `LUA_SOURCE` inside `cycle_relay.py`.

**Config** `~/.config/blender-cycle-relay/config.json`
**Logs** `~/.cache/blender-cycle-relay/recent.log` — deliberately *not* in the
config dir; see session notes.

### Arming

The relay cannot ask Blender whether a transform is running, so it infers it:
your move shortcut and `G`/`R`/`S` arm it; a click, `Esc` or `Enter` disarm it;
it self-disarms after a timeout. This matters because a cycle rule **hides** the
key from Blender — without arming, binding `Tab` would permanently break Tab's
Edit Mode toggle. Arming is internal and has no UI.

---

## Safety

Event taps sit at the OS input layer, so a runaway one can lock the machine.
Active at all times:

- synthetic events are tagged and skipped → cannot feed back on itself
- only keys whose rule says so are ever hidden from Blender
- burst limiter auto-disables the taps
- every handler is `pcall`-wrapped; an error disables rather than blocks
- dead-man timer
- menubar **Stop**
- inert unless Blender is frontmost

Menubar shows `R:` idle, `R*` armed, `R:off` stopped.

---

## Testing

The Lua runs headlessly against a stubbed Hammerspoon
(see session notes for the harness), and the add-on runs under
`blender --background`. Both are worth using before shipping a change —
several bugs here were invisible to reasoning but obvious to a test.

What cannot be tested off-Mac: whether a synthesized key actually lands in
Blender's transform modal. That needs a real machine.
