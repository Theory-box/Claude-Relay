# Feature: gamepad-mapper
Branch: feature/gamepad-mapper

## What this does
Standalone macOS controller remapper (system-wide), plus a Blender fly-camera add-on.
Two separate things:
- `tools/gamepad-mapper/gamepad_mapper.py` — single-file app: engine + ugly Tkinter
  editor. Reads controller via pygame, fires OS keyboard/mouse via Quartz (pyobjc),
  supports layers + stacked actions. Packaged to a .app by CI.
- `tools/gamepad-mapper/blender_gamepad_fly.py` — Blender add-on for API-based fly
  camera (left stick fly/strafe, right stick FPS look, R3 mouse mode, plus an in-Blender
  OS-action mapper). Stays in Blender because it drives the viewport API directly.
- `tools/gamepad-mapper/blender_gamepad_tester.py` — diagnostic: live axis/button/hat
  readout + log session that writes a report.

## Build
`.github/workflows/build-mac.yml` builds GamepadMapper.app on a macos-latest runner
with PyInstaller (`--windowed --collect-all pygame`), ad-hoc signs it, uploads
`GamepadMapper-mac.zip` as an artifact. Download from Actions, right-click > Open,
grant Accessibility.

## Engine model
Config = layers -> bindings -> ordered action stack (on_press). Actions: key, mouse,
scroll, modifier(hold), enter_layer(momentary/latched/toggle), exit_layer. Held effects
(momentary layers, modifiers, hold clicks) auto-revert on input release, keyed by input
signature. Modifiers from held bindings OR into the flags of other fired events.
Config persists at ~/.gamepad_mapper.json.

## Known controller (test rig)
Xbox 360 Controller: axes 0/1 = left stick, 2/3 = right stick, 4 = LT, 5 = RT
(triggers rest -1, go +1 — analog axes, not buttons). 15 buttons (0-14), no hats.

## Status
- v1 engine + GUI written, not yet device-tested. Quartz output + Tk modifier capture
  on macOS are the most likely spots needing iteration.
- CI build untested (first run will reveal PyInstaller/pyobjc bundling tweaks).

## Next
- Confirm CI produces a launchable .app; fix packaging if needed.
- Tk learn-output modifier bits on macOS (Cmd detection) may need adjustment.
- Possible: profiles, per-app layer auto-switching, GUI polish.
