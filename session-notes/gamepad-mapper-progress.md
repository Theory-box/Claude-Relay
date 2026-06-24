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
- v1 engine + GUI. Engine verified by tools/gamepad-mapper/test_engine.py (11/11):
  shift-click flag, momentary + latched layers, exit_layer, revert-on-release,
  layer resolution precedence. GUI construct + field-edit path smoke-tested under Xvfb.
- Fixed: UI instability (field edits no longer rebuild/destroy the active widget; they
  update listbox labels in place). Added cursor/feel settings panel (deadzone, cursor
  speed/accel/invert, stick axes). Added modifier keycodes so a 'shift' keystroke (hold)
  works in addition to the modifier action. tkinter import made optional so engine is
  importable headlessly.

## Shift (two working paths)
- Action type 'modifier' = shift (held): ORs Shift into other fired events -> shift-click.
- Action type 'key', key='shift', hold on: posts a real Shift key down/up.

## Tauri rewrite (current direction)
- tools/gamepad-mapper/app/ = Tauri 2 app, NORMAL window (not a desktop overlay).
  Rust backend: engine.rs (config + layer/stacked-action logic, unit tests pass on CI),
  macout.rs (core-graphics CGEvent output), main.rs (gilrs polling thread + commands
  get_config/set_config/set_running/learn_next + status/learned events). Web editor in
  dist/ (index.html, app.js, style.css). Build: .github/workflows/build-mac-app.yml on
  macos-latest -> cargo tauri build -> GamepadMapper.app (~2.5MB), zipped artifact.
- Inputs are gilrs SEMANTIC names: RT=RightTrigger2, LT=LeftTrigger2, LB=LeftTrigger,
  RB=RightTrigger, A=South, B=East, X=West, Y=North, L3/R3=Left/RightThumb, DPad*. Sticks
  LeftStickX/Y, RightStickX/Y. Learn input captures whatever button is pressed.
- Build went green after one fix: core-graphics scroll-event constructor differs by
  version; scroll output is STUBBED (no-op) for now -> needs wiring with correct API.
- Tkinter app (tools/gamepad-mapper/gamepad_mapper.py) still exists/works; Tauri is the
  new path. Both unsigned -> Gatekeeper "Open Anyway" each rebuild.

## Next
- Device-test the Tauri app: launch, grant Accessibility, Start, learn inputs, verify
  clicks/keys/layers/cursor fire system-wide.
- Wire real scroll output (confirm core-graphics scroll API for the pinned version).
- Blender add-on regression: most likely conflict from running standalone app + addon
  together; confirm with standalone quit. (was: tools/gamepad-mapper/blender_gamepad_fly.py)
- Possible later: Apple Developer ID signing/notarization in CI to kill Gatekeeper,
  per-app auto layer switching, profiles.
