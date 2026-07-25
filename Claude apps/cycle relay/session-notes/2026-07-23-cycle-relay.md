# Cycle Relay — Session Notes

Built 2026-07-23. Goal: tap one key mid-transform to cycle Blender's axis
constraint (`X→Y→Z`), Shift for planes. Working end-to-end at v8.2.

---

## Why the architecture is what it is

Two dead ends were ruled out with evidence before settling on a middleman:

**1. Pure add-on — impossible.** The Transform Modal Map maps events to values
from a **C-compiled enum**. Python can add keymap *items* but cannot define a new
action, so "cycle to next axis" cannot exist as an add-on. The feature is tiny —
roughly an enum value plus a case in the transform event handler — but it has to
be written in C. This is an access boundary, not a difficulty one. Worth filing
upstream someday.

**2. Event injection — impossible.** `hs.window.event_simulate` requires
`--enable-event-simulate`, and with that flag real keyboard input is ignored.
Mutually exclusive with using Blender.

**3. Reimplementing transform — abandoned.** A custom modal operator (v1–v2 of
this project) worked but inherited every edge case Blender already solved. It
died on off-screen pivots: projecting the mouse ray onto a plane through a
distant pivot amplifies movement enormously. Wrapping native transform is
strictly better than re-deriving it.

---

## Bugs found, with root causes

Recording these because several were **invisible to reasoning** and cost hours.

### The arming bug (the big one)
**Symptom:** cycling only worked with a "always armed" override, which broke
Tab's Edit Mode toggle. Arming appeared to fire, then silently stopped.

**Cause:** the relay wrote its **log file into the directory it watched for
config changes**. Every log line — including "ARMED" — retriggered the config
watcher, which called `loadConfig()`, which reset `st.armed = false`. A race:
sometimes the reload landed before the next keypress, sometimes after, so it
looked arbitrary (R and S "worked", G didn't).

**Fix:** logs moved to `~/.cache/`; `loadConfig()` no longer touches live state;
identical config content is ignored entirely.

**Why it was never caught:** the test harness stubbed `hs.pathwatcher` as a
no-op, so the bug could not manifest. Making the stub *fire like the real one*
reproduced it in one run. **Lesson: stubs that are more convenient than reality
hide exactly the bugs worth finding.**

### Silent no-op reload
`open -g hammerspoon://reload` only works if a handler is bound for it; the
default config binds none. It silently did nothing, leaving the **old script
running** while new versions were written to disk. Explains a stretch where
fixes appeared to have no effect. Fix: always hard quit + relaunch.

### Orphan quit
`_deferred_start` quit Hammerspoon unconditionally but only relaunched it if
`auto_launch` was set. That pref had defaulted to `False` in an earlier version,
and **Blender persists add-on preferences across versions**, so a new
`default=True` never applied. Result: startup killed the watcher and nothing
worked, with a UI that looked perfectly healthy. Fix: never quit without
relaunching; watcher state shown prominently.

### Corrupted Hammerspoon install
Python's `zipfile` **does not preserve symlinks**, which macOS `.app` bundles
depend on. Extracting that way broke `LuaSkin.framework` and Hammerspoon refused
to start. Fix: extract with `ditto -x -k`.

A follow-up: the integrity check looked for `luaskin.lua` *anywhere* under the
framework — it exists as a real file even in a broken bundle, so the check passed
falsely and skipped the repair. Correct test is whether the **symlinked path**
resolves (`Versions/Current` is a link, `Resources/luaskin.lua` resolves).

### Modifier bleed
Sending `g` while Cmd was physically held arrived at Blender as **Cmd+G =
Create New Collection**. Clearing flags on the synthetic event is not enough —
the OS merges in real modifier state. Fix: explicitly post release events for
held modifiers before sending.

### Bare modifiers aren't key events
`Cmd` alone produces `flagsChanged`, never `keyDown`. Using it as the cycle key
requires the modifier-tap path (press+release with nothing in between). Routed
automatically when the chosen cycle key is `cmd`/`ctrl`/`alt`.

### macOS input lockup
Toggling the Accessibility permission **while event taps were live** hung all
input (mouse moved, nothing clickable). Recovery: force power off. Never change
that checkbox without stopping the watcher first — now documented in the UI.

---

## Design notes

**Arming is internal.** It was briefly exposed in the UI as arm/disarm/when/
swallow rules and was rightly rejected as incomprehensible. There is exactly one
correct configuration, so the add-on now *generates* the rule list from two
settings. The rule engine remains underneath and is reachable under
*Advanced* — a good generalisation point if this becomes a broader middleman.

**Don't hijack what Blender can do itself.** The move shortcut originally sent
`G`. Better: bind Cmd+click in Blender's own keymap and have the relay merely
*notice* it. Nothing sent, nothing swallowed, modifier bleed sidestepped.

---

## Testing setup

Both halves are testable off-Mac and should be exercised before shipping:

- **Add-on:** `blender --background --python test.py` — install, enable, dump the
  generated `config.json`.
- **Lua:** a stubbed `hs` table capturing tap callbacks, then feeding synthetic
  events through them. Must stub `pathwatcher` so it **actually fires**.

Untestable off-Mac: whether a synthesized key lands in Blender's transform modal.

---

## Possible next steps

- Generalise into a broader Blender middleman (rule engine already supports it).
- Windows/Linux backends (AutoHotkey / `evdev`).
- File the upstream Blender request for a native constraint-cycling action.
