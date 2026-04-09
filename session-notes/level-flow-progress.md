# Level Flow Feature — Session Notes
Last updated: April 2026

---

## Status: SESSION 3 COMPLETE — continue-point system implemented, ready for in-game testing

## Active Branch: `feature/level-flow`

---

## What's Been Built (this session)

### `collect_spawns` — fully upgraded
- Reads SPAWN_ and CHECKPOINT_ empties
- Captures facing quaternion from empty rotation (Blender→game remap: bl(x,y,z)→game(x,z,-y), conjugate applied)
- Reads optional linked `SPAWN_<uid>_CAM` / `CHECKPOINT_<uid>_CAM` empty for camera-trans + camera-rot 3×3 matrix
- Falls back to spawn pos + 4m up + identity rotation if no _CAM empty present
- CHECKPOINT_ empties become zero-flag continues (eligible for auto-assignment as player walks)

### `_make_continues` — upgraded
- Writes real `:quat` from spawn facing
- Writes real `:camera-trans` and `:camera-rot` (9 floats, 3×3 row-major)
- Fallback default continue still generated if no spawns placed

### `patch_level_info` — upgraded
- `:bsphere` auto-computed from mean spawn position + 64m padding radius
- `:bottom-height` driven by `og_props.bottom_height` (default -20m, range -500 to -1)
- `:nickname` driven by `og_props.vis_nick_override` (blank = auto 3-letter from level name)
- Falls back to 40km sphere if no spawns

### New operators
- `OG_OT_SpawnCheckpoint` — places CHECKPOINT_ empty (yellow single-arrow, uid=cp0/cp1...)
- `OG_OT_SpawnCamAnchor` — places _CAM empty linked to active SPAWN_/CHECKPOINT_, pre-aimed at it

### New OGProperties
- `bottom_height`: FloatProperty, default -20.0, range -500..−1
- `vis_nick_override`: StringProperty, blank = auto

### OG_PT_Scene → renamed "🗺 Level Flow"
- Lists all SPAWN_ empties with cam status
- Lists all CHECKPOINT_ empties with cam status
- Context-sensitive "Add Camera for SPAWN_X" button when spawn is selected and has no cam
- Death plane + vis nick controls
- Live bsphere radius readout (Blender-space preview)

---

## Testing Checklist

- [ ] SPAWN_start placed — verify continue-point name is `{level}-start` in level-info.gc
- [ ] SPAWN_start facing ≠ default — verify :quat is non-identity in level-info.gc
- [ ] SPAWN_start_CAM placed — verify :camera-trans and :camera-rot match empty positions
- [ ] No _CAM empty — verify camera defaults to spawn pos +4m, identity rot
- [ ] CHECKPOINT_cp0 placed — verify it appears in :continues list as a zero-flag continue
- [ ] Multiple spawns — bsphere centre/radius looks correct in level-info.gc
- [ ] bottom_height = -50 → level-info.gc shows `(meters -50.0)`
- [ ] vis_nick_override = "myv" → level-info.gc shows `'myv` for :nickname
- [ ] Level Flow panel shows cam status correctly (📷 vs "no cam" alert)
- [ ] Player respawns at correct position facing correct direction in game

---

## Next Steps (not started)

- Load boundary export from Blender (polygon → XZ points + top/bot → load-boundary-data.gc entry)
  - This is a separate feature: draw a boundary polygon in Blender, pick fwd/bwd commands
  - Needs research: how to append to load-boundary-data.gc safely
- `continue-name` lump helper: UI for `launcherdoor`/`jungle-elevator` actor placement
  - Add to Place Objects panel: "continue-name" property picker for relevant etypes

---

## Research Sessions (previous)

### Session 1 — April 2026
Files read: engine/game/game-info-h.gc, engine/game/game-info.gc, engine/level/level-info.gc,
level-h.gc, level.gc, load-boundary-h.gc, load-boundary.gc, load-boundary-data.gc,
target-death.gc, logic-target.gc, basebutton.gc, launcherdoor.gc, jungle-elevator.gc

### Session 2 — April 2026
Files read: game-save.gc, goalc/build_level Entity.cpp, ResLump.cpp, goal_constants.h,
test-zone.jsonc, testzone.gd, game.gp, test-zone-obs.gc, task-control-h.gc, game-task-h.gc, logic-target.gc

Knowledge base: `knowledge-base/opengoal/level-flow.md` (17 sections, fully complete)

---

## Pre-Testing Code Review (this session)

### Method
- Pure Python mathematical verification of all formulae
- Cross-referenced against vanilla `level-info.gc` and `level.gc` source
- Sparse-cloned jak-project repo for ground truth

### Bugs Found and Fixed

**BUG 1 — CRITICAL (fixed): spawn facing quat was degenerate**
- Old code rebuilt a rotation matrix from a forward vector
- An unrotated Blender empty produced `w:0.0` — a degenerate 180° quaternion
- Player would spawn facing a broken direction
- Fix: `game_rot = R_remap @ bl_rot @ R_remap^T` — proven to give identity for identity empty
- R_remap = `[[1,0,0],[0,0,1],[0,-1,0]]` (Blender x,y,z → game x,z,-y)

**BUG 2 — CRITICAL (fixed): `_CAM` empties matched SPAWN_/CHECKPOINT_ prefix**
- `SPAWN_start_CAM` starts with `SPAWN_` → was collected as a spurious continue-point
- Also double-counted as both a spawn AND a camera anchor
- Fix: `if o.name.endswith("_CAM"): continue` at top of collection loop

**BUG 3 — REVERTED: vis-nick changed to level nick, then reverted back to `'none`**
- Research showed `test-zone` (official OpenGOAL reference) uses `'none`
- Runtime analysis: `vis? = #f` for custom levels → vis-nick field never acted on
- `'none` is correct. `vis_nick_override` controls `:nickname` in level-load-info (different field)

### Non-Bugs Confirmed
- bsphere `:w` was already raw game units (`r * 4096`) ✓
- bsphere x/y/z converted to raw game units to match vanilla style (was `(meters ...)`, both compile identically)
- `(meters ...)` for continue-point `:trans` and `:camera-trans` is valid GOAL ✓
- camera-rot format matches vanilla exactly ✓
- nREPL `{name}-start` autoload compatibility ✓

### Testing Checklist (updated)
- [ ] SPAWN_start unrotated → `:quat :w 1.0` in level-info.gc
- [ ] SPAWN_start rotated 90°Z → non-identity quat in level-info.gc
- [ ] SPAWN_start_CAM NOT appearing as a continue-point
- [ ] SPAWN_start_CAM present → camera-trans/rot use it; absent → default +4m up/identity
- [ ] CHECKPOINT_cp0 appears in :continues list
- [ ] Player spawns at correct position and facing in game
- [ ] Player respawns facing correct direction after death
- [ ] bsphere centre/radius plausible in level-info.gc output
- [ ] bottom_height and vis_nick_override props work in panel

---

## Second Pre-Testing Review (this session)

### Areas checked that first pass missed
- Operator uid counters (SpawnPlayer, SpawnCheckpoint)
- Panel list comprehensions (spawns, checkpoints display)
- SpawnCamAnchor operator edge cases
- GOAL symbol validity for level names with hyphens
- continue-point :name special character risk
- cam_rot matrix orthonormality
- R_remap construction and transposed() correctness
- bsphere including checkpoints (intentional, confirmed correct)
- bottom_height range bounds
- vis_nick_override length limits
- hardcoded :index 27 (pre-existing, not our issue)

### Bugs Found and Fixed

**BUG 3: SpawnPlayer uid counter counted _CAM empties**
- After placing SPAWN_start + SPAWN_start_CAM, next "Add Player Spawn" would skip uid "spawn1" and jump to "spawn2"
- Fix: `not o.name.endswith("_CAM")` added to len() filter

**BUG 4: SpawnCheckpoint uid counter same issue**
- Fix: same filter

**BUG 5: Level Flow panel listed _CAM empties as spawn/checkpoint points**
- SPAWN_start_CAM appeared in the spawns list, triggered "no cam" alert on itself
- Also inflated bsphere preview calculation with cam anchor positions
- Fix: `not o.name.endswith("_CAM")` on both panel list comprehensions

### Confirmed Non-Issues
- SpawnCamAnchor zero-direction guard present ✓
- GOAL hyphens in symbol names valid ✓
- cam_rot matrix is orthonormal (normalized in formula) ✓
- R_remap row 0:(1,0,0) row1:(0,0,1) row2:(0,-1,0) → game(x=bl_x, y=bl_z, z=-bl_y) ✓
- bsphere including checkpoints is correct/intentional ✓
- Straight-up cam degenerate: same limitation as existing camera system, accepted ✓

### Accepted Known Issues (not fixing now)
- :index 27 hardcoded — pre-existing, multiple custom levels share index (only affects progress menu icon)
- SPAWN_ uid ending in '_CAM' would be silently skipped — pathological naming, not realistic

### Final status
Branch is at 2c02baf. 5 bugs found and fixed across two review passes before any in-game testing.
Ready for testing.

---

## Checkpoint Trigger System (this session)

### Problem
Passive auto-assign requires BSP `inside-boxes?` detection. Custom levels have no
BSP, so `current-level` is never set, and the auto-assign loop never fires.
Player always respawned at start spawn regardless of checkpoint proximity.

### Solution: actor-based trigger
`CHECKPOINT_` empties now export as TWO things:

1. **continue-point record in level-info.gc** (was already working) — holds spawn
   position, camera data, level slot. Required for `set-continue!` to find by name.

2. **`checkpoint-trigger` actor in JSONC** (new) — invisible `process-drawable`,
   no skeleton. Polls player distance every frame. Calls `set-continue!` on first
   entry. One-shot (triggered flag latches, won't re-fire).

### GOAL type
```
(deftype checkpoint-trigger (process-drawable)
  ((cp-name   string  :offset-assert 176)
   (radius    float   :offset-assert 180)
   (triggered symbol  :offset-assert 184))
  :heap-base #x40 :size-assert #xbc)
```
- Reads `continue-name` lump (bare string → ResString)
- Reads `radius` lump (metres, default 3m = 12288 game units)
- Calls `(set-continue! *game-info* (-> self cp-name))`
- Born automatically via entity-actor.birth! when level loads

### Files changed
- `collect_actors`: appends checkpoint-trigger actors after ACTOR_ entities
- `write_gc`: `has_checkpoints` flag, emits type when needed
- All 3 build pipelines updated
- `OG_OT_SpawnCheckpoint`: stamps `og_checkpoint_radius=3.0` custom prop
- Level Flow panel: shows radius next to each checkpoint

### Known risk
`:heap-base #x40` may produce a GOALC assertion warning. Not a crash — just adjust
to match what GOALC reports. Struct size #xbc (188) is verified correct.

### Testing checklist (updated)
- [ ] Export & Build with a CHECKPOINT_ empty in scene
- [ ] Verify `checkpoint-trigger` type appears in obs.gc
- [ ] Verify GOALC compiles without errors (watch for heap-base assertion)
- [ ] Walk into checkpoint sphere in game
- [ ] Die → verify respawn at checkpoint, not at start spawn
- [ ] Walk into checkpoint a second time → verify it doesn't re-trigger
- [ ] Verify start spawn still works as fallback if no checkpoint reached

---

## CRITICAL DEV NOTE — str_replace class header eating

**Bug pattern (happened 4 times):** When inserting a new class before an existing one,
using `class OG_PT_DevTools(Panel):` (or any class header) as the LAST line of `old_str`,
then forgetting to include it in `new_str`. This silently drops the header, causing
`name 'OG_PT_DevTools' is not defined` at Blender addon load time.

**Rule going forward:**
- NEVER use a class header as the boundary/anchor of a str_replace
- When inserting before a class, anchor on content INSIDE the preceding class
  (e.g. the `return {"FINISHED"}` line + blank lines before the next class)
- Always include the preserved class header in BOTH old_str AND new_str
- Run the integrity check script after EVERY edit before committing

**Integrity check (run after every edit):**
```python
import ast, re
src = open('addons/opengoal_tools.py').read()
tree = ast.parse(src)
top = {n.name: n.lineno for n in tree.body if isinstance(n, ast.ClassDef)}
classes_tuple = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'classes' for t in n.targets))
tuple_names = [n.id for n in ast.walk(classes_tuple.value) if isinstance(n, ast.Name)]
nested = [f'{c.name} inside {p.name}' for p in tree.body if isinstance(p, ast.ClassDef) for c in ast.walk(p) if c is not p and isinstance(c, ast.ClassDef)]
missing = [n for n in tuple_names if n not in top]
assert not missing, f'UNDEFINED IN TUPLE: {missing}'
assert not nested, f'NESTED CLASSES: {nested}'
print(f'OK — {len(top)} classes')
```

---

## Future Work

### CP sphere radius UI
Currently `og_checkpoint_radius` is stamped as a custom prop (default 3.0m) when a
CHECKPOINT_ empty is placed, but there's no way to edit it from the panel — you have
to manually edit the custom prop in Blender's object properties sidebar.

When we get around to it: add a per-object float field in the Level Flow panel that
reads/writes `o["og_checkpoint_radius"]` for the selected CHECKPOINT_ empty, similar
to how the Platform panel exposes per-actor sync props. Only show it when no CPVOL_
is linked (since AABB mode ignores the radius anyway).
