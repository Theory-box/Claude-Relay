# Session notes — Push Panels

**Folder:** `Claude apps/push panels/`
**Pushed straight to `main`** (user granted explicit permission; works well
enough for main even though not considered perfect).

## Goal

Resize Blender editor areas by pushing their dividers with the cursor. Hold a
key; when the cursor reaches an area edge, that divider moves so the user can
shove it outward, like the cursor is physically colliding with the boundary.
Motivating case: enlarge one panel in a 2x2 quadrant layout without dragging
each separator line in turn.

## Decisions made

- **Target version: Blender 4.4** (user's version; API read from the 4.4.3
  source tree).
- **Trigger is user-rebindable** via a live keymap widget in preferences.
  Default `F6`. User wants Command eventually but accepted a normal key for now.
- **Two modes shipped:** Grab (default, native handoff) and Push (self-driven
  fallback). Grab is smooth; Push is push-only but jittery when fast.
- **Push-only physics feel** was a user preference but is only preserved in Push
  mode; user accepted Grab's bidirectional behaviour in exchange for smoothness.

## The core constraints (from Blender 4.4.3 source)

All three came out of reading `editors/screen/screen_ops.cc`,
`screen_geometry.cc`, and `windowmanager/intern/wm_event_system.cc`:

1. `screen.area_move` poll = `ED_operator_screen_mainwinactive`, which fails
   while `screen->active_region != nullptr` — i.e. the cursor is more than
   `BORDERPADDING` inside a region rather than over a divider. `active_region`
   is not exposed to Python and cannot be cleared from script.
2. `active_region` is only recomputed on **unconsumed** events
   (`wm_event_do_handlers`: it runs after `wm_handlers_do` only when
   `WM_HANDLER_BREAK` is clear). A modal returning `RUNNING_MODAL` sets that
   flag and freezes `active_region` → poll fails forever. Fix: return
   `PASS_THROUGH` on mouse motion. Also no `BLOCKING` op flag.
3. `area_move` snaps the **absolute** edge position to `AREAGRID` (4 px) each
   call, and reads fresh screen verts internally while Python's `area.width`
   lags a redraw. `BORDERPADDING = (3.0*UI_SCALE_FAC) + U.pixelsize`.

## Version history / what broke and why

- **v0.1–0.2:** self-driven push. Worked but had a fatal `snap=` kwarg (does not
  exist in 4.4 → TypeError), fixed. Then edges wouldn't move at all —
  active_region poll (fact 1/2). Fixed with PASS_THROUGH + no BLOCKING.
- **v0.3:** edges moved. But the cursor snapped back when moving fast.
- **v0.4:** tried delta+debt with grid quantisation. Still snapped back.
  Root cause: the cursor "park" position was computed from the **stale**
  `area.width`, so at speed (several mouse events per redraw) the warp target
  was a phantom edge many pixels behind, and the warp yanked the cursor back
  every frame. This was the persistent "jitter when fast" the whole time.
- **v0.5:** self-tracked the edge (never re-read `area.width` mid-gesture), kept
  it one grid-unit ahead of the cursor, warped only on genuine strand. Also
  fixed a tracking desync: `area_move` snaps the absolute position, so
  `edge += delta` drifted from reality when the starting edge was off-grid;
  mirror the snap and carry the true shortfall as debt. Simulation looked great,
  but on real hardware it still jittered when fast — because repeated `area_move`
  calls **re-poll every frame**, and keeping the poll satisfied at speed still
  needs warps.
- **v0.6:** abandoned imitation. **Grab mode** hands off to Blender's native
  `area_move` modal, which polls once and never warps → speed-immune. Preserved
  hold-and-release by binding the trigger key's RELEASE to the native confirm
  (`APPLY`) on the "Standard Modal Map". Kept the v0.5 push logic as the Push
  fallback. User confirmed: "much smoother when it works."
- **v0.7 (current):** the remaining failure was the poll
  timing at the **grab moment** — a fast sweep crosses the divider zone between
  frames, so the handoff frame sees a stale active_region and the native invoke
  raised the poll RuntimeError (user saw the error). Fix: on poll failure while
  arming, warp the cursor onto the edge (updates `win->eventstate->xy`, which is
  what `active_region` is recomputed from) and **retry** the handoff for up to
  MAX_GRAB_TRIES frames instead of erroring. Converges in 1–2 frames.
- **v0.7 bugfix:** user hit `UnicodeDecodeError: 'utf-8' codec can't decode byte
  0xff` in `_clear_release_confirm`. Cause: the release→APPLY keymap items were
  stored as `(km, kmi)` object references and reused across the operator's life,
  but Blender reallocates the `keymap_items` list when it changes, leaving those
  stored `kmi` pointers dangling — `remove()` then read a dead item and decoded
  garbage. Fix: never cache keymap-item references. Track only the key string
  (`_CONFIRM_KEY`) and, on clear, re-find matching items (propvalue APPLY, our
  key, RELEASE) in the current maps and remove those. Stress-tested against
  keymap churn; bl_info bumped to (0, 7, 0).

## How Grab mode works now

- Our modal watches the cursor. When it comes within `grab_reach` of an edge, we
  lock that edge and "arm": warp the cursor onto it, set the release→confirm
  binding, and invoke `screen.area_move('INVOKE_DEFAULT')`.
- If the invoke returns `RUNNING_MODAL`, native grabbed → our modal FINISHES and
  native owns the drag. Release of the trigger key → modal map → APPLY → native
  confirms. Esc/right-click cancels.
- If the invoke poll-fails (fast sweep, active_region not yet clear), we stay
  armed, keep the cursor pinned on the edge, and retry next frame.

## Testing done

- All registration / unregister / re-register cycles pass in Blender 4.4.3.
- Modal-map confirm binding add/remove/dedup and no-leak-after-unregister
  verified.
- Native handoff return-value handling and the arming retry loop verified with
  the real methods driven through a Blender-accurate simulator (edge grid-snap
  + one-redraw geometry lag + poll timing).
- Could NOT run a live interactive Blender headless (Xvfb/GHOST input never
  delivered synthetic key events reliably in the sandbox), so the actual
  interactive handoff and feel were confirmed by the user in the running editor.

## Open / next time

- **Modifier keys + Grab:** releasing a modifier (e.g. Command) during an
  unrelated Standard-Modal operator could confirm it, because the release→APPLY
  binding is global while set. Needs tighter scoping (add the binding only for
  the duration of an active grab, or find a non-modal-map confirm path) before
  Command is safe. This is the main thing to revisit when the user moves to
  Command.
- **Push-only in Grab mode:** not possible while delegating to native (native is
  bidirectional). If push-only is wanted with smoothness, would need a different
  approach than either current mode.
- **Grab reach / feel:** the one-off grab snap onto the edge is at most
  `grab_reach` px; tune if it feels jarring.
