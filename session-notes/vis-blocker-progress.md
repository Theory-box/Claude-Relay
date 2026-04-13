# Vis Blocker — Session Notes

**Branch:** `feature/vis-blocker`
**Status:** Core implementation complete — syntax verified, ready for in-game testing
**Last updated:** 2026-04-13

---

## What Was Built

A system for hiding/showing mesh objects in a level via trigger volumes, without
needing separate Blender scene files or any manual file management.

### The Constraint (important)
Only **spawned actors** (process-drawables) support `draw-status hidden`.
Baked level geometry (TFRAGs/TIEs — the main level mesh) **cannot** be hidden at runtime.
The blocker mesh must be a separate object.

---

## How It Works (User Workflow)

1. In Blender, create a mesh and name it `VISMESH_<anything>` (e.g. `VISMESH_wall-1`)
2. Place it where you want the blocking mesh to appear in the level
3. Place a `VOL_` trigger volume where the player walks
4. Shift-select the VISMESH_ and the VOL_, use the Triggers panel to link them
5. In the vol link dropdown, choose: **Hide on enter**, **Show on enter**, or **Toggle on enter**
6. Hit Build — the addon handles everything else automatically

That's it. No extra files, no GOAL code to write manually.

---

## What Happens at Export

### GLB Export
- `VISMESH_` objects are **excluded** from the main level GLB
- Each `VISMESH_` gets its own GLB exported alongside the level:  
  `VISMESH_wall-1` → `custom_assets/jak1/levels/<name>/wall-1.glb`
- The GLB stem is derived by stripping `VISMESH_` prefix and `-ag` suffix

### JSONC
- Each `VISMESH_` becomes a `vis-blocker` entity in the actors list
- Its `art-name` lump points to its art-group (e.g. `wall-1-ag`)
- Its `hidden` lump is 0 (visible) or 1 (hidden) based on `og_hidden_at_start` prop
- Each `VOL_` → `VISMESH_` link becomes a `vis-trigger` entity with:
  - `target-name` = the vis-blocker's lump name (`vis-blocker-wall-1`)
  - `action` uint32: 0=hide, 1=show, 2=toggle
  - `bound-*` AABB from the VOL_ mesh

### GOAL Code (obs.gc)
Two new deftypes emitted when vis-blockers are present:

**`vis-blocker`** — a process-drawable that:
- Loads its mesh via `initialize-skeleton-by-name` using the `art-name` lump
- Starts hidden or visible based on `hidden` lump
- Responds to `'draw #t/#f` event (show/hide) and `'toggle` event

**`vis-trigger`** — an AABB polling actor that:
- Reads `target-name`, `action`, and bound-* lumps
- Polls player position every 4 frames (same pattern as camera-trigger)
- On rising edge (player enters): calls `process-by-ename` on the target, sends the action

---

## Name Derivation

| Blender name | Art-group | Skeleton symbol | Lump name | GLB file |
|---|---|---|---|---|
| `VISMESH_wall-1` | `wall-1-ag` | `*wall-1-sg*` | `vis-blocker-wall-1` | `wall-1.glb` |
| `VISMESH_my_blocker` | `my-blocker-ag` | `*my-blocker-sg*` | `vis-blocker-my-blocker` | `my-blocker.glb` |

Underscores in the object name become dashes everywhere downstream.

---

## Files Changed

| File | What changed |
|---|---|
| `export.py` | `_classify_target` → vis-blocker; `collect_vis_blockers`; `export_vis_blocker_glbs`; `collect_vis_trigger_actors`; `write_gc` has_vis_blockers param + GOAL emission; `write_jsonc` vis_blockers kwarg; VISMESH_ excluded from level GLB |
| `build.py` | All 3 build paths call collect/export vis-blocker functions; pass flag to write_gc |
| `operators.py` | 3 export operators call `export_vis_blocker_glbs`; new `OG_OT_ToggleVisBlockerHidden` |
| `panels.py` | VOL link UI shows HIDE_OFF icon + dropdown for vis-blocker targets; new `_draw_selected_vis_blocker`; new `OG_PT_VisBlockerInfo` panel |
| `properties.py` | `OGVolLink.behaviour` now dynamic — shows hide/show/toggle for VISMESH_ targets |
| `data.py` | Added `VIS_TRIGGER_ACTIONS` + `VIS_TRIGGER_ENUM_ITEMS` |
| `utils.py` | `_is_linkable` now accepts VISMESH_ meshes |
| `__init__.py` | Registered `OG_PT_VisBlockerInfo` and `OG_OT_ToggleVisBlockerHidden` |

---

## What Still Needs Testing

- [ ] In-game: does `initialize-skeleton-by-name` work with a custom GLB art-group?
- [ ] In-game: does `process-by-ename` find the vis-blocker by its lump name?
- [ ] In-game: does `send-event target 'draw #f` actually hide the mesh?
- [ ] Edge case: vis-blocker that spawns hidden (`og_hidden_at_start = True`) — verify lump write
- [ ] Edge case: multiple VOL_ volumes each hiding a different VISMESH_
- [ ] Edge case: toggle action — does the `'inside` flag reset correctly on exit?

---

## Known Gaps / Future Work

### Collision
The vis-blocker uses a plain `trsqv` root (no collision shape). If the blocking mesh
should also be physically solid (player can't walk through it), it needs a
`collide-shape-prim-mesh` added to the init. This is intentionally not included
in v1 — a transparent or decorative blocker doesn't need it.

### Custom Actors (Phase 2)
The next step is supporting fully custom meshes as actors (not just vanilla prop
art-groups). This requires understanding how custom GLB → custom art-group → custom
skeleton-group pipeline works in the build system. The vis-blocker implementation
already does this implicitly — once confirmed working, it IS the custom actor pipeline.

### Re-show on Exit
The vis-trigger currently only fires on **enter** (rising edge). There's no re-show
on exit. To get "show while inside, hide on exit" you'd need two VOL_ volumes with
opposite actions, or a second trigger. A future improvement would be an
`og_vis_trigger_exit_action` lump.

### Persistence Across Respawn
If the player hides a mesh and then dies, the mesh respawns visible (because the
actor re-inits). To persist the hidden state across deaths you'd need to write to
a game-task or global boolean. Not implemented.

---

## Session Log

- 2026-04-13 (Session 1): Research + full implementation complete. 466 lines added,
  all 7 modified files pass py_compile. Committed and pushed to feature/vis-blocker.
  Ready for in-game testing.
