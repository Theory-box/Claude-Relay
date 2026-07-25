# Push Panels

Blender addon for resizing editor areas by shoving their dividers with the
cursor instead of grabbing each divider line by hand.

Hold a key, glide the cursor toward the edge of an area, and the divider grabs
so you can move it — release the key to drop it. In a quadrant layout you can
enlarge one panel by pushing outward from inside it, rather than dragging each
separator in turn.

## Requirements

- Blender 4.4 (built against 4.4's screen operators; see behaviour notes)
- Tested on macOS (Retina). Should work on other platforms but only macOS has
  been exercised.

## Install

1. Edit > Preferences > Add-ons
2. Top-right dropdown > Install from Disk
3. Select `push_panels.py`
4. Enable the checkbox

## Keybinding

The default trigger is `F6`. Rebind it in the addon preferences: the keybinding
row is a live keymap widget — click it and press any key you want.

## Modes

Set the mode in the addon preferences.

**Grab (default) — smooth.** Hands off to Blender's own edge-drag operator, so
the motion is as fluid as dragging a divider by hand, at any cursor speed. Hold
the key, reach an edge to grab it, release to drop. Right-click or Esc cancels a
grab in progress. Because it uses the native drag, the edge moves in both
directions (push and pull).

**Push — release-to-stop.** Moves the edge itself each frame. Strictly
release-to-stop and push-only (it will not pull an edge inward), but it can
jitter or lag when the cursor moves fast. Kept as a fallback.

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| Mode | Grab | Grab (native, smooth) or Push (self-driven, push-only) |
| Grab reach | 12 | Grab mode: how close (px) the cursor must come to an edge to grab it |
| Pass mouse motion through | on | Push mode only: required so Blender keeps updating its active region |
| Report diagnostics | off | Print engagement/handoff messages to an Info editor |

## Behaviour notes

The design is dictated by three facts about Blender 4.4's `screen.area_move`,
confirmed from source:

- **Its poll rejects the move unless the cursor is over a divider**
  (`ED_operator_screen_mainwinactive` requires `screen->active_region` to be
  null). Blender only recomputes that flag on unconsumed events, so this addon
  returns `PASS_THROUGH` on mouse motion; consuming it would freeze the flag and
  fail the poll for the rest of the session.
- **The native modal checks that poll only once,** then drags from a fixed
  mouse+edge anchor without re-polling or warping the cursor. That is why the
  native drag is speed-immune — and why Grab mode delegates to it rather than
  imitating it.
- **On a fast sweep the cursor crosses the divider zone between two frames,** so
  the handoff frame can see a stale active-region flag and the poll fails. Grab
  mode handles this by warping the cursor onto the edge (which updates the
  position Blender reads for that flag) and retrying the handoff for a few
  frames until it succeeds, instead of erroring.

Grab mode preserves the hold-and-release feel by temporarily binding the trigger
key's release to the native confirm action, via the "Standard Modal Map" that
`area_move` uses.

## Known limitations

- **Grab mode is bidirectional.** The push-only "physics" feel (push an edge out
  but never pull it in) is only available in Push mode, because Grab hands off to
  the native drag which moves both ways.
- **Shared dividers.** In a quadrant layout built by splitting one direction
  first, the divider between two panels may span the full width/height and be
  shared, so pushing one edge also moves the neighbouring row/column. This is a
  property of Blender's screen layout, not the addon.
- **Modifier trigger keys + Grab.** Binding Grab to a modifier such as Command is
  not fully safe yet: the release-to-confirm binding lives on the shared modal
  map, so releasing a modifier during an unrelated modal operator could confirm
  it. Prefer a non-modifier key for Grab mode until this is scoped more tightly.

## Development status

Working and in use. Grab mode is smooth in normal use; fast sweeps grab a frame
or two later rather than failing. Validated against Blender 4.4.3: registration,
the native-handoff return handling, and the modal-map confirm binding were tested
headlessly. The live interactive handoff itself was confirmed by the user in the
running editor, not in an automated test.
