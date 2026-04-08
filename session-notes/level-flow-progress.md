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
