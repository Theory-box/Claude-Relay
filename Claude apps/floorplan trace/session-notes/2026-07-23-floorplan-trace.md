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

---

## Update — nav revert + inference-guide bugfix (tested in real Blender 4.4.3)

Downloaded Blender 4.4.3 and ran headless harnesses (register/enable/disable, property + keymap
creation, and a driver that calls `compute_target` with mocked projection). Catches the whole
"won't install / API mismatch / bad keymap" class; can't test interactive feel / GPU rendering.

**Navigation reverted to stock + lock-pan.** User changed their mind: two-finger should ORBIT
normally, and pan only when the view is locked. Fix = `custom_nav` now defaults **False**, so the
two-finger pan/orbit/zoom remap and one-finger look are off by default (opt-in in prefs). The
lock-pan (`view3d.move` on TRACKPADPAN + MMB, `active=False`, toggled by lock via `_resync_pan`)
is separate and still gives two-finger pan while locked. Verified: with custom_nav off, only the
lock-pan bindings exist; native orbit is untouched.

**Inference-guide bug found and fixed.** User reported none of extension / relative-angle /
distance-memory appeared to work. Driving `compute_target` in Blender showed extension and
relative-angle actually worked, but **distance memory never fired in its own use case**: when you
draw along a line collinear with existing edges (continuing a wall, or a repeated bump-out width),
the extension guide grabs the cursor, and distance memory had been gated to `angle_locked` only
(deliberately excluding extension, to avoid an ambiguous guideline). So it was disabled exactly when
needed. Fix: when extension is active AND the last point lies on the extension line (collinear
check via perpendicular distance), extension now supplies the locked direction, enabling distance
memory. Verified: dragging 2.05 along a row of 2.0 segments snaps to 2.0 (`dist=2.0`).

Also fixed the extension guide **visual** (was drawn as a 10,000-unit world line that projects
off-screen and doesn't render) — now a finite 3000px screen-space line through the target along the
edge direction. Added a faint green angle-lock guide ray so relative/world angle snaps are visible
(there was no visual before, so angle snapping was invisible even when working). `res['dir']` now
carries the locked direction for that overlay.

Verified in Blender 4.4.3 via `compute_target` driver:
- [A] 45° wall, drag 133° -> snaps 135° (locked)
- [B] hover near a line's extension -> snaps onto it
- [C] row of 2.0 segments, drag 2.05 -> snaps length to 2.0
- [D] 30° wall, drag 118° -> snaps 120° (30+90, which world-axis snap would miss)

Still untested (needs a human in a live viewport): actual snap feel/tolerances, overlay rendering,
whether guides trigger too eagerly. `dist_px`/`align_px` are the tuning knobs.

---

## Update — snapping priority fix: guideline crossings keep the axis lock (tested 4.4.3)

Bump-out bug: drawing a horizontal segment toward an earlier line's vertical guideline, the extension
snap reprojected the whole point onto that line, discarding the horizontal angle lock, so the corner
wasn't square. Fix: `compute_target` now establishes the angle lock FIRST, and when locked, extension
/ alignment / distance / grid become LENGTH candidates along the lock ray (each guideline intersected
with the ray -> candidate distance t; nearest within tolerance wins). Direction stays square, length
lands on the guideline crossing (CAD "intersection of two inferences"). Unlocked behaviour unchanged.
Verified [E]: horizontal drag toward an earlier vertical line -> (0,-3): square AND on guideline.

---

## Update — remove custom zoom, restore RTS pan (tested 4.4.3)

Custom zoom (Ctrl+two-finger) removed entirely: the `floorplan_zoom` operator, its prefs
(zoom_ctrl/shift/alt, zoom_invert), the keymap binding, and the `exp` import are gone. Nothing binds
Ctrl+two-finger now, so it falls through to Blender native zoom (was overriding it before). RTS ground
pan restored as `VIEW3D_OT_floorplan_rts_pan` (per-gesture, hybrid `_do_pan`: ground-slide in
perspective, in-plane pan in ortho so elevations still pan). Added to the custom-nav prefs section
as the "RTS Pan" modifier row (default Ctrl+Shift on two-finger) plus RTS invert X/Y in the feel box.
Verified in 4.4.3: zoom operator absent, rts_pan bound to Ctrl+Shift+TRACKPADPAN, pan/orbit/look/lock-pan intact.

---

## Update — Cut / Project Cut (knife_project), built modular (4.4.3 plumbing tested)

Added surface-cutting via a shared core `_do_knife_project(context, cutter, target, cut_through,
keep_cutter)` that selects cutter+target, edits the target, runs `mesh.knife_project` from the
current view with a region override, then restores mode and (optionally) deletes the cutter.

Three thin wrappers:
- **Trace** (existing) - polyline into a new/active object (cut_mode=False).
- **Cut Trace** - `mesh.floorplan_trace` with cut_mode=True: appears in edit mode on a mesh; traces
  into a temp CutTrace object, and on confirm (Enter or close-loop) knife-projects onto the edited
  mesh, deletes the temp cutter, and re-enters edit mode on the target. Esc cancels (no cut).
- **Project Cut** - `object.floorplan_project_cut`: an object-picker (project_cutter PointerProperty)
  + button; projects the chosen object onto the edited mesh, keeps the cutter.

Settings: `cut_through` toggle (front-face vs both sides). Panel: "Cut Into This Mesh" box shown
only while editing a mesh.

TESTED in 4.4.3 headless: registration clean (13/13), cut_mode property + cut_through +
project_cutter + project_cut op all register, `_do_knife_project` runs without crashing and keeps/
deletes the cutter as asked. NOT testable here: the actual knife_project cut needs a GPU viewport
(confirmed: --background has no GPU, and GUI-under-xvfb segfaults on software GL). So the cut firing
correctly is the one unverified piece - needs a real-Blender test pass. Everything around it is solid.

Known future work discussed: non-destructive/editable cuts would need a boolean-modifier approach
(cutter stays live) rather than knife_project (bakes the result); object-mode cutting; keep-curve option.

---

## Update — KNIFE PROJECT NOW ACTUALLY CUTS (root cause found + verified live)

The cut had never worked (Cut Trace and Project Cut both gave "No other selected objects have wire
or boundary edges to use for projection"). I had wrongly written this off as a headless-only
artifact. Got a LIVE Blender running under xvfb (LIBGL_ALWAYS_SOFTWARE=1, build meshes from data /
edit-mode bmesh to avoid the GL-op segfault, defer the test via bpy.app.timers, flush stdout) and
reproduced + fixed it.

ROOT CAUSE: knife_project reads the cutters *depsgraph-evaluated* mesh. Our old flow selected
cutter+target BEFORE entering edit mode and never refreshed the depsgraph, so the evaluated cutter
mesh was EMPTY (0 edges) at cut time -> the operator honestly reported "no wire/boundary edges."
The error message is misleading; it is not about selection or GPU.

FIX (in _do_knife_project), matching Blenders own documented knife_project order:
  1. deselect all; select the TARGET; make it active
  2. enter edit mode on the target
  3. THEN select the cutter (after edit mode)
  4. context.view_layer.update()  <-- refreshes the depsgraph so the evaluated cutter is populated
  5. knife_project with a minimal temp_override (window/area/region/space_data)
Also keeps the earlier _move_cutter_in_front fix (slides cutter along the view axis so it sits in
front of the target; silhouette preserved so the cut lands where drawn) and now returns (ok, msg)
so the real error surfaces instead of a generic warning.

VERIFIED LIVE (xvfb, Blender 4.4.3), faces increase on the target in every case:
  cutter in front / behind / coplanar, and cut_through=True -> all WORK. Registration 13/13.

HARD-WON LESSON: to test viewport/GPU operators (knife_project, anything projecting from the view),
run Blender NON-background under xvfb with software GL, build geometry from data (not primitive ops,
which segfault on llvmpipe), defer via a timer, and flush prints. --background cannot test these.

---

## Update — Cut Trace: multiple outlines, one confirm

Cut Trace no longer cuts on the first closed loop. Closing a loop now starts a fresh outline (same
as normal Trace), so you can trace several openings (windows + door) into the one temp cutter. Enter
(or Space) then knife-projects them ALL at once; Esc cancels. Removed the close->finish path and the
_finish_requested flag. Verified live (xvfb 4.4.3): a cutter with 3 separate loops cuts the wall face
1 -> 5 in a single pass. Registration 13/13.

---

## Update — face-limited cutting (selected faces only)

Both Cut Trace and Project Cut now respect a face selection on the target: if any of the target
 mesh faces are selected when you cut, the cut is limited to just those faces; if none are selected,
it cuts the whole thing as before. Implemented in the shared _do_knife_project by replicating the
manual Shift+H workflow behind the scenes -- detect selected faces (target.data.polygons[*].select
after the object-mode flush), and if any, mesh.hide(unselected=True) before knife_project and
mesh.reveal(select=False) after. Verified live (xvfb 4.4.3) on a 4x4 grid wall + a full-width cutter:
no-selection added 7 faces, 4-faces-selected added only 2, and nothing was left hidden. Reg 13/13.

---

## Update — snap to target geometry while cutting + vertex/edge snap + guide visuals

Three things:

1. Snap to the mesh youre cutting into. In cut mode the target walls verts/edges are now fed into
the same guide system as tracing. Cached at invoke into _target_verts_world / _target_segs_uv and
appended in align_candidates() / _segments_uv(). If the target has selected faces, only those faces
verts/edges are used (matches the face-limited cut and keeps the candidate set small); else the whole
target. Setting: use_target_guides (default True).

2. Explicit VERTEX snap (Blender-like). New step 1b in compute_target: within align_px of an existing
candidate point (target geom, object verts, earlier trace points -- but not the point youre drawing
from), land exactly on it (res[vert]) with top priority after close. Edge snapping continues via the
extension guide. Verified: near a vertex snaps exactly to it; along an edge snaps to the edge line.

3. Guide visuals. All snap options consolidated under a Guides panel section (Angle / Alignment+Vertex
/ Inference / Grid / Cutting / Appearance). Guide lines now drawn as filled quads (thick() helper) so
thickness is honoured on macOS/Metal (which caps GPU line width at 1px). New settings guide_line_width
(default 2.5) and guide_marker_size. Cyan diamond marks a vertex snap.

Verified live/headless (4.4.3): target verts/edges feed snapping; vertex snap exact; inference [A]-[E]
unchanged; TRIS quad batch builds + offscreen-draws OK; new settings register; reg 13/13.

---

## Update — Cut Trace: Confirm / Edit / Cancel dialog + edit-before-cut

Cut Trace no longer cuts on Enter. It now stashes the outline (_pending_cut global: cutter/target/
cut_through) and opens a deferred dialog (via bpy.app.timers, since dialogs-from-modals are unreliable)
with three choices:
  - Apply Cut  -> knife-project now
  - Edit Outline -> drop into edit mode on the cutter to refine it with native tools, then Apply
  - Cancel -> discard, no cut

While a cut is pending, the N-panel shows a red Cut Pending box with Apply Cut / Cancel buttons that
are ALWAYS available (poll = _pending_cutter_valid) -- this is the reliable backbone; you can never get
stuck. Safety net: an msgbus subscription to (bpy.types.Object, mode) watches for leaving edit mode
with a cut pending and pops an Apply/Edit/Cancel prompt. If msgbus does not fire, the panel buttons
still resolve it. Validity guard (_pending_cutter_valid) clears state + unsubscribes if the cutter
object gets deleted (no ReferenceError crash). Cleaned up on unregister.

Operators added: MESH_OT_floorplan_cut_dialog (stage INITIAL/LEAVE, action CONFIRM/EDIT/CANCEL),
MESH_OT_floorplan_apply_cut, MESH_OT_floorplan_cancel_cut. Shared helpers _apply_pending_cut /
_cancel_pending_cut / _enter_cut_edit / _watch_cut_mode.

Because knife_project accepts CURVES (verified: bezier-circle cutter cuts fine) and subdivided-edge
meshes, the Edit step gives true curves + bevels for free via Blenders native tools -- convert the
cutter to a curve, adjust handles, Apply.

Verified live (xvfb 4.4.3): Apply cuts (faces 1->3) + clears pending; Cancel removes cutter unchanged;
Edit enters edit-on-cutter; leave-edit watcher resets state; msgbus (Object,mode) key valid; validity
guard handles deleted cutter. Registration 13/13; inference [A]/[E] unchanged.

NOTED FOR LATER (user request, not built): distance-memory guides that remember lengths across
*parallel* guidelines (same horizontal/vertical length even when not collinear), and optionally a mode
that remembers ALL lengths regardless of direction.

---

## Update — smarter distance memory (angle-grouped, promoted, tolerant)

Reworked distance memory around *recurrence* so it scales to big floorplans without a candidate
explosion. Module-level `_dim_memory`: bucket int(0..179 undirected degrees) -> list of
{len,count,promoted}. A drawn segment's length is tallied per angle bucket in place() (clustered by
`dist_tol`%); it is *promoted* to a remembered dimension per `dist_promote`:
  - Reused: only when placed while snapped to that length (collinear repeats)
  - Drawn 2x (default): once the same length is drawn twice within tolerance
  - Drawn 3x
Only promoted dims are offered as candidates (in `_distance_candidates` via `_dim_offer`), scoped by
`dist_scope`: Same Angle (default -- horizontals share, don't bleed into verticals; +/-2deg bucket
match so 45deg walls share) or Any Angle. This gives the user's cases: 3 horizontals at different
heights share a width; 15 45deg walls share; verticals optional. Panel readout lists remembered
"len xN" with a trash/forget button (MESH_OT_floorplan_forget_dims). New settings: dist_scope,
dist_promote, dist_tol. Cleared on unregister.

Verified: pure algorithm (bucketing/tolerance/promotion/scope); registration + module helpers in
4.4.3; full integration -- two 2.0 horizontals at different y promote to (2.0 x2), a third horizontal
snaps to it, a vertical (same-axis) correctly does not.

NOTE: sandbox filesystem reset mid-session; re-applied these edits from scratch and re-downloaded
Blender to re-verify. Everything above re-tested green.

STILL ON THE TABLE (discussed, not built): on-screen-only + basics-only hold-keys; snap Sources vs
Types panel split; world-axis global guide planes (X/Y/Z + offset, view-independent, taggable from
objects); a cursor readout of *why* it snapped.

---

## Update — calibrate tools (Type Length / Fit to Line) snap like the trace tool

The two-click calibrate line-drawers now share the tracing tool's snapping niceties while keeping the
same buttons/flow:
  - Angle snapping (view-plane) on the END point of each drawn line, using the shared use_angle_snap /
    angle_increment / angle_tolerance settings. New helper _angle_snap_point (right/up from
    rv3d.view_rotation, snap dir to increment within tolerance). Faint green guide ray drawn when locked.
  - Alt = free placement (no snap), via _free_held() mapping prefs.free_placement_key to the event
    modifier (alt/ctrl/shift/oskey; falls back to tracked state for non-modifier keys).
  - Vertex snapping generalized: reference/measure line snaps to the DRAWING (selected objects),
    LINE-mode target line snaps to the MODEL (unselected). invoke builds snap_sel / snap_unsel (200k
    cap). get_point(context, coord, event) now does free -> vertex -> angle in priority order.
Header now shows "Alt: free (no snap)". Verified in 4.4.3: 44.4deg->45, 26.6deg->free, ~2deg->0;
_line_start correct for n=1/2/3; Alt free-held true; enable/disable x3 clean; calibrate RNA intact.
