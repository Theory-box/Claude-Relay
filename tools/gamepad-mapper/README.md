# Gamepad Mapper (macOS)

A standalone system-wide controller remapper. Maps buttons / triggers / sticks to
real keystrokes, key combos, mouse clicks, scroll, and **layers** — so a button can
fire an action, switch what every other button does, or both at once. Works in any
app, not just Blender.

## Get the app (no Terminal)

1. Go to the repo's **Actions** tab → the latest **build-mac** run.
2. Download the **GamepadMapper-mac** artifact and unzip it.
3. First launch: **right-click `GamepadMapper.app` → Open** (it's unsigned, so
   Gatekeeper asks once).
4. Grant it **Accessibility** when prompted, or in
   System Settings → Privacy & Security → Accessibility. Without this, synthetic
   clicks/keystrokes are silently dropped.

## Using it

- **Start** begins reading the controller and firing events.
- **Layers** hold **Bindings**; each binding is an input → an ordered **stack of
  actions** that all fire on press.
- **Learn input**: click it, then press a controller control to capture it.
- **Learn output**: on a key/mouse action, click it, then press the keystroke or
  mouse button to capture it.
- Action types: `key`, `mouse`, `scroll`, `modifier` (hold), `enter_layer`
  (momentary / latched / toggle), `exit_layer`.
- **Save** writes `~/.gamepad_mapper.json`.

### Examples the model supports
- **LB → enter "alt" layer (momentary) + hold Shift** — while held, other buttons
  remap and clicks become shift-clicks; reverts on release.
- **G → type G + enter "grab" layer (latched); in that layer, left-click does its
  click + exit_layer** — i.e. "press G, buttons change until left-click."

## Run from source (dev)

```
pip install pygame pyobjc-framework-Quartz pyobjc-framework-ApplicationServices
python3 gamepad_mapper.py
```

## Notes
- Build happens on a GitHub macOS runner (see `.github/workflows/build-mac.yml`);
  a Mac binary can't be cross-built elsewhere.
- The Blender fly-camera stays a separate add-on (`blender_gamepad_fly.py`) because
  it drives Blender's viewport API directly — that can't move out of Blender.
