# OpenGOAL Blender Addon — Session Progress

## Status: WORKING ✅ (camera system in active development on feature/camera)

## Official Addon (main branch)
`addons/opengoal_tools.py` — install this in Blender.

## Active Camera Branch
`feature/camera` — install `addons/opengoal_tools.py` from THIS branch for camera work.

---

## Camera System — Current Architecture

### How it works (entity-based, no nREPL needed)

Two new entity types defined in `{name}-obs.gc`:

**`camera-marker`** — inert process-drawable that holds camera position/rotation.
- Exported as actor with `"etype": "camera-marker"`
- `init-from-entity!`: allocates trsqv root, calls process-drawable-from-entity!, goes idle
- `entity-by-name` finds it → `change-to-entity-by-name "CAMERA_0"` works
- `cam-state-from-entity` reads lump data → `cam-fixed-read-entity` (default, no special lumps)
- Also supports `cam-standoff` (side-scroller) via `align` lump, `cam-circular` via `pivot` lump

**`camera-trigger`** — AABB polling entity-actor that switches the camera.
- Exported as actor with `"etype": "camera-trigger"`
- Reads bounds from `bound-xmin/xmax/ymin/ymax/zmin/zmax` meter lumps
- Reads target camera name from `cam-name` string lump
- `init-from-entity!`: allocates root, reads lumps, goes to `camera-trigger-active`
- `camera-trigger-active` state: polls `*target* control trans` each frame, AABB test
- On enter: `send-event *camera* 'change-to-entity-by-name cam-name`
- On exit: `send-event *camera* 'clear-entity`
- **No nREPL call needed** — births automatically via `entity-actor.birth!` on level load
- Works whether player loads manually or via Build & Play

### Blender workflow
1. **Add Camera** → places `CAMERA_0` Blender camera (Numpad-0 to look through)
2. **Add Volume** → places `CAMVOL_0` wireframe cube (resize to cover trigger area)
3. Shift-select volume + camera → **Link Trigger Volume** (sets `og_cam_link` on volume)
4. Export & Build → level recompiles, both entities appear in JSONC actors array
5. Walk into volume in-game → camera switches automatically

### Camera modes (set via panel or `og_cam_mode` property)
- `fixed` → `cam-fixed-read-entity` — locked position/rotation
- `standoff` → `cam-standoff` — side-scroller (fixed offset from player). Needs `CAMERA_N_ALIGN` empty.
- `orbit` → `cam-circular` — orbits a pivot point. Needs `CAMERA_N_PIVOT` empty.

### deftype field offsets (camera-trigger)
```
process-drawable: 0xb0 = 176 bytes
cam-name  string  :offset-assert 176
xmin      float   :offset-assert 180
xmax      float   :offset-assert 184
ymin      float   :offset-assert 188
ymax      float   :offset-assert 192
zmin      float   :offset-assert 196
zmax      float   :offset-assert 200
inside    symbol  :offset-assert 204
:heap-base #x60   :size-assert #xd0
```

---

## Bug History (camera system)

| Bug | Root cause | Fix |
|---|---|---|
| Art group not found | `camera-tracker` etype doesn't exist; engine called `birth-viewer` which tried to load `camera-tracker-ag.go` | Define `camera-marker` type in obs.gc with proper `init-from-entity!` |
| Level crash on load | `process-drawable-from-entity!` writes to `this->root->trans` but `root` was null | Add `(set! (-> this root) (new 'process 'trsqv))` before call |
| Trigger never fires (manual load) | `my_level_obs_init()` called via nREPL 2s after spawn — never runs when player loads manually | Replaced with `camera-trigger` entity-actor that births on level load |
| Volume visible/collidable | `vol["set_invisible"] = True` (dict-style) exports as JSON bool; C++ uses `.Get<int>()` = 0 | Use `vol.set_invisible = True` (registered BoolProperty) |

---

## Key Source References (from research)

### Camera state selection (camera.gc:101)
```lisp
(cond
  ((res-lump-struct entity 'pivot structure)      cam-circular)
  ((res-lump-struct entity 'align structure)      cam-standoff-read-entity)
  ((get-curve-data! entity ...)                   cam-spline)
  ((< 0 (cam-slave-get-float entity 'stringMaxLength 0)) *camera-base-mode*)
  (else                                           cam-fixed-read-entity))
```

### Camera event API
```lisp
(send-event *camera* 'change-to-entity-by-name "CAMERA_0")  ; activate named camera
(send-event *camera* 'clear-entity)                          ; return to default
```

### entity-by-name search order (entity.gc:92)
1. bsp.actors ← **our camera-marker is found here**
2. bsp.ambients
3. bsp.cameras (always empty for custom levels — LevelFile.cpp bug)

### Minimal process-drawable entity pattern
```lisp
(deftype my-type (process-drawable) () (:states my-state))
(defstate my-state (my-type) :code (behavior () (loop (suspend))))
(defmethod init-from-entity! ((this my-type) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))   ; MUST allocate root first
  (process-drawable-from-entity! this arg0)       ; copies trans/quat from entity
  (go my-state)
  (none))
```

---

## Files
- `addons/opengoal_tools.py` on `feature/camera` — working addon
- `knowledge-base/opengoal/camera-system.md` — full research notes

## Next session
- Test camera trigger in-game (walk through volume, verify camera switches)
- Test camera rotation (does Blender camera -Z look direction export correctly?)
- Test standoff mode for side-scroller
- If working → merge to main
