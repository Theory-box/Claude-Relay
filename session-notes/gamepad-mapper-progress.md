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

## Blender add-on trimmed to fly-only (v0.8.0)
- tools/gamepad-mapper/blender_gamepad_fly.py rewritten: removed ALL button->keystroke/
  mouse remapping (GamepadBinding, learn/learn-output, Quartz _post_* output, the in-
  Blender mouse-warp "mouse mode", cursor_speed/curve/invert_cursor_y). Add-on now only
  flies the viewport: left stick = move on view plane, right stick = look (yaw/pitch),
  optional boost button. Kept settings: deadzone, move_speed, look_speed, boost_mult,
  invert_left_y/right_y, lx/ly/rx/ry axis indices, boost_btn (-1=off). Still uses pygame.
- New: Fly/Cursor mode toggle. A configurable hotkey (pref toggle_key, EnumProperty of
  common keys, default ACCENT_GRAVE) flips WindowManager.gamepad_cursor_mode. In CURSOR
  mode the modal yields (does nothing) so the standalone GamepadMapper app drives the OS
  pointer; in FLY mode the add-on controls the camera. Key is swallowed while running so
  it doesn't trigger Blender's own shortcut. Panel has Start/Stop + Switch button + mode.
- No Accessibility/Quartz needed anymore (add-on only moves the Blender viewport via bpy).
- No IPC between add-on and app: both can read the pad; mode just controls whether the
  add-on flies. To avoid the app's cursor moving under Blender during flight, stop the app.
