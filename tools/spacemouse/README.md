# SpaceMouse → Joystick

Single-file Python tool that maps 3Dconnexion SpaceMouse input to a virtual Xbox 360 controller.

## Mapped axes

| SpaceMouse | Action | Controller output |
|---|---|---|
| X | Left / right pan | Left Stick X |
| Y | Forward / back push | Left Stick Y |
| Rz | Yaw / twist | Right Stick X |
| Z, Rx, Ry | Up/down, tilt | Ignored |

## Requirements

- Python 3.8+
- Windows: [ViGEmBus driver](https://github.com/nefarius/ViGEmBus/releases/latest)
- Linux: `sudo modprobe uinput` and add user to `input` group

Dependencies (`hidapi`, `vgamepad`) are installed automatically on first run.

## Usage

```
py spacemouse_joystick.py
```

## Features

- Auto-detects SpaceMouse on launch, re-checks every 3 seconds
- Auto-learns axis range from your device (no hardcoded max values)
- Deadzone and sensitivity sliders
- Per-axis invert toggles
- Live axis output bars with raw value display
