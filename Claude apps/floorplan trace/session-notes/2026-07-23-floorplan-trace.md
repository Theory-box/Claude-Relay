# Floorplan Trace — Session Notes

Blender add-on (`floorplan_trace.py`, single file, Blender 4.0+) for tracing floorplans and
elevations from reference drawings with CAD/SketchUp-style snapping, plus reference-image
scaling and viewport navigation helpers.

**Branch:** `feature/floorplan-trace` — not merged to main.

---

## Origin / problem being solved

Tracing floorplans in Blender natively is E → axis key → click, repeated per segment. Goal was to
cut that to roughly one click per segment, with snapping that makes walls land accurately without
manual axis constraints.

---

## What it does

**Trace tool** (N-panel → Trace tab, toggle button, works in Edit Mode on a mesh)
- Click-to-place polyline; each click connects to the previous point. Live rubber-band preview.
- **Start/continue rule:** exactly one vertex selected on activation → trace continues from it;
  nothing (or multiple) selected → fresh polyline.
- **Drawing plane** is derived from the view at activation — Top gives ground plane (plans),
  Front/Side gives the vertical plane (elevations). All snapping runs in that plane's own two axes.
  Plane height: continuing → the selected vertex's position; fresh → 3D cursor.
- **Angle snap (within tolerance):** snaps drag direction to nearest allowed angle only if inside the
  tolerance window, else draws true angle. Panel: increment (45° default) + tolerance.
- **Alignment snap:** shares an axis with an earlier point; pink guide line drawn to the source vertex.
  Scope setting: Current Trace vs Whole Object. First point of a fresh line always aligns to existing
  object geometry (otherwise there'd be nothing to snap to).
- **Grid snap:** snaps distance-along-axis when an angle is locked, absolute in-plane position when free.
- **Close-by-merge:** click the start point → closes the loop, then starts a new polyline.
- **Free placement:** hold the configured key (default RMB) → all snapping off.
- Enter/Space finish, Esc cancel, Backspace removes last point (only points it created).
- Object Mode: button creates a fresh empty mesh object, enters Edit Mode, traces. Auto-deletes that
  object if you finish without placing anything.

**Reference Scale** (Object Mode, operates on selected objects)
- **Type Length:** draw a line over a known measurement in the drawing, type its real length
  (`FloatProperty` with `subtype='DISTANCE'`, so `12ft` / `5cm` / `2"` parse). Uniformly scales the
  selection, pivoting on the **first clicked point** so it stays fixed.
- **Fit to Line:** draw a reference line on the drawing, then a target line on the model; the selection
  moves + scales + rotates so the first lands on the second. Full 3D (shortest-arc rotation), so it
  works on elevations, not just ground plane. Target line **snaps to vertices of unselected meshes**
  (green ring highlight). For this mode select ONLY the reference image — anything selected gets moved.

**Viewport helpers**
- Lock View Rotation toggle (panel button, syncs pan keymaps — use this button, not the native View panel).
- Ortho view cross: Up/Down = 90° vertical orbit stepping (top → horizontal → bottom, not absolute
  jumps), Left/Right = 90° side orbit, plus two Roll buttons. All briefly lift the lock so they work
  while locked. Each is a real operator → right-click to assign shortcuts.
- Configurable trackpad nav in Add-on Preferences: modifier rows (Ctrl/Shift/Alt) for
  Pan / Orbit / Zoom (two-finger) and Look (one-finger, cursor-grabbed FPS look).
  Defaults: pan = bare, orbit = Ctrl, zoom = Ctrl+Shift, look = Ctrl. Master on/off toggle.

---

## Hard-won lessons (do not regress these)

1. **Two-finger trackpad ≠ MIDDLEMOUSE.** It emits `TRACKPADPAN`. Binding middle-mouse does nothing
   for a laptop trackpad user.
2. **Don't launch a modal navigation operator per gesture.** Doing that for pan produced sticky
   "grab mode" (one finger kept panning afterward). Use Blender's native `view3d.move` bound to the
   gesture instead.
3. **Custom hand-rolled pan breaks camera view.** A pan that moves `view_location` does nothing in
   camera view. Native `view3d.move` works everywhere — camera, ortho, perspective. **Pan must stay
   native.** A previous attempt at an always-on custom "RTS ground pan" broke orbit and camera view
   badly and had to be pulled.
4. **General principle from that failure:** lean on Blender's built-in operators/keymaps rather than
   shadowing global navigation with custom operators. Custom is fine for things Blender has no
   equivalent of (in-place FPS look, ground-plane zoom feel); it is not fine for core nav.
5. **`invoke_props_dialog` from inside a running modal is unreliable** — the dialog silently never
   appeared. Fix: stash state in a module global, exit the modal, then open the dialog from a
   `bpy.app.timers` callback a beat later.
6. **Ortho vs ground plane:** originally everything assumed top-down Z=0. Generalizing to a
   view-derived drawing plane was required for elevations. Anything new that projects screen→3D must
   use the plane basis, not world XY.

---

## Verified cold (numpy stand-ins, since Blender can't run in the sandbox)

- Scale pivot: first clicked point stays exactly fixed; drawn line hits target length exactly;
  all selected objects keep proportion.
- Line fit: maps ref-point-1 → target-point-1 and ref-point-2 → target-point-2 with correct scale and
  rotation, including the vertical/elevation case.
- Look math: eye position unchanged (rotates in place), horizon stays level (view-right has zero Z),
  basis orthonormal.
- Plane-coordinate snapping: in Top view produces results identical to the old world-XY code
  (no regression to plan tracing); in Front view snaps correctly within the wall plane.

Everything else is syntax-checked + structurally audited only (all registered classes defined,
no dangling references). Runtime feel — snap tolerances, gesture handling — needs real testing.

---

## Open / next up

- **Cut mode (designed, not built).** Trace an outline on a building face and cut it into the surface
  via knife-project — for windows, doors, panel lines on elevation blockouts. Confirmed we *cannot*
  inject our snapping into Blender's interactive Knife modal (internals not exposed to add-ons); the
  approach is trace-with-our-snapping → knife-project on finish. Surface-only, no depth. Smart
  intersections (X welds a vertex) come free with a real surface cut. Driving `knife_project` from
  script is context-finicky — expect a tuning pass. Was awaiting user go-ahead.
- Auto-weld crossings for *non-cut* traces (loose polylines self-connecting) would be a separate opt-in.
- Possible additions discussed but not chosen: segment length readout in the header while tracing,
  numeric length entry mid-trace, wall thickness/offset, one-click walls-from-trace.
- If the RTS ground-slide pan feel is missed in tilted 3D views, add it back as a separate opt-in
  binding — never as the always-on default (see lesson 3).

---

## Install

Edit → Preferences → Add-ons → install from disk → `floorplan_trace.py` → enable.
Panel: 3D View → N-panel → **Trace** tab. Key binds: Add-on Preferences.
Toggle shortcut: right-click the Trace button → Assign Shortcut (deliberately no pre-registered
hotkey, so nothing collides with the user's existing binds).

---

## Update — inference guides (extension, relative-angle, distance memory)

Added three CAD-style inference guides to the trace tool, all working in the drawing-plane (u,v)
coordinates so they hold on plans and elevations alike. Researched against SketchUp inference,
FreeCAD Draft snapping (Snap Extension / Parallel / Ortho), and the Microsoft equal-spacing patent
before building.

- **Extension guides** (`use_extension`): snap the cursor onto the infinite line of any candidate
  edge (chain segments always; whole-object edges when scope = Object). Drawn as a faint blue line.
- **Angle from last edge** (`use_relative_angle`): angle-snap candidates now include multiples of the
  increment measured from the *previous segment's* heading, not just world/plane axes — so you get a
  clean 90° (or 45°, etc.) turn off a diagonal wall. Picks nearest across {world, relative} bases.
- **Distance memory** (`use_distance_memory`, `dist_px`): only while a direction is angle-locked.
  Gathers candidate lengths **scoped to the current guideline** (points/edges collinear with the
  locked direction from the last point): distances to collinear points, lengths of collinear edges,
  and any repeated interval among collinear points. Snaps the current length to the nearest candidate;
  shows a yellow span + tick + numeric label. This is the collinear/point-projection approach — it
  cleanly separates parallel-but-offset guidelines (wall row vs bump-out row) so equal widths repeat
  without the depth edges contaminating them.

Priority order in `compute_target`: close > extension > angle(world+relative) > alignment(free only)
> distance-memory(angle-locked only) > grid. Distance memory is deliberately gated to angle-lock (not
extension) to avoid an ambiguous guideline when the extension edge isn't collinear with the last point.

Panel: new "Inference" box (extension + distance memory + dist px); "Angle from last edge" under Angle.

Verified cold with numpy: extension projection lands on the edge line; 137° drag near a 45° wall
snaps to 135°; distance candidates recover both "same length" matches and repeated intervals.
Not yet tested in Blender — snap feel / tolerances (align_px, dist_px) will likely want a tuning pass,
and the guide visuals (blue extension line, yellow distance tick+label) need an eyeball.

Possible follow-ups if the feel needs it: forward pattern extrapolation (place the *next* point at
last+interval, past existing points), and extension+distance combined once guideline handling is
proven.
