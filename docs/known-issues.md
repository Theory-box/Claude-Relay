# Known Issues & Needed Improvements

Tracked here so nothing gets lost between sessions. Add new entries as they're found during testing.

---

## ❌ Broken / Non-Functional

### Music Panel
- **Status:** Non-functional
- **Detail:** The Music panel UI exists but music does not play in-game. Root cause unknown — likely a GOAL-side issue with how the level's music bank is referenced or loaded.

### Camera Look At
- **Status:** Non-functional
- **Detail:** The "Look At" camera anchor type (`og.spawn_cam_look_at`) does not work in-game. The entity spawns correctly but the camera does not follow the look-at target at runtime.

### Swing Poles
- **Status:** Non-functional
- **Detail:** Swing pole entities spawn and export but do not function in-game. Jak cannot grab them. Likely missing a required lump, a navmesh interaction, or an engine-side patch that hasn't been identified yet.

---

## ⚠️ Limitations / Caveats

### Nav-Enemy Run-to-Position
- **Status:** Not implemented — engine limitation
- **Detail:** Nav-enemies can be sent `cue-chase` (run at Jak) or `cue-patrol` (walk their waypoint path) via the aggro trigger. There is no way to make an enemy *run* to a specific fixed position — the engine's nav-enemy state machine doesn't have a "go-to-pos" event. Implementing this would require a new custom GOAL entity type emitted from export.py, plus a new event handler patched into nav-enemy.

### Aggro Trigger — Nav-Enemies Only
- **Status:** By design, but worth noting
- **Detail:** Aggro triggers only work on nav-enemies (`ai_type: nav-enemy`). Process-drawable enemies (yeti, bully, mother spider, etc.) silently ignore `cue-chase`, `cue-patrol`, and `go-wait-for-cue` events. No workaround currently.

### Vertex Export — Position Only
- **Status:** By design for now
- **Detail:** The "Export As" mesh feature only supports simple entity types that need no settings (orbs, eco pickups, props). Entities requiring lumps (crate type, fuel-cell task, orb-cache count etc.) are excluded. Full lump support per-vertex is not planned.

### Tpage Groups — Max 2 Per Level
- **Status:** Engine limitation
- **Detail:** Mixing enemies from more than 2 tpage groups in a single level risks an out-of-memory crash on level load. The addon warns about this in the Enemies sub-panel but does not hard-block it.

### Navmesh — No Real Pathfinding
- **Status:** Partial workaround in place
- **Detail:** Nav-unsafe enemies (babak, lurker crab, etc.) require a real navmesh to pathfind. The addon injects a `nav-mesh-sphere` lump as a workaround so they don't crash, but they will idle/notice Jak without properly chasing. Full navmesh support is future work.

---

## 🔧 Needs Improvement

### panels.py Size
- **Detail:** `panels.py` is ~3,800+ lines and growing. Could be split into `panels_spawn.py`, `panels_actor.py`, `panels_level.py` etc. Low priority until it becomes a maintenance problem.

### Export As — No Visual Indicator in Viewport
- **Detail:** Meshes tagged with "Export As" have no viewport overlay showing what entity type is assigned or how many actors will be emitted. A custom draw handler or object color change would help.

### Sort Collection Objects
- **Detail:** The "Sort Collection Objects" operator doesn't know about the new `Export As` sub-collection. Objects in that collection may get re-classified incorrectly if sort is run.

---

## 📋 Session Regression Checklist
*(Run after any major change before merging to main)*

- [ ] Addon installs without error
- [ ] N-panel shows in viewport (OpenGOAL category)
- [ ] Level panel shows active level settings
- [ ] Spawn an enemy → routes to correct sub-collection
- [ ] Quick Search bar filters and spawns correctly
- [ ] Export As panel appears on plain mesh, assigns type, moves to collection
- [ ] Export runs without Python error
- [ ] Build & Play completes without GOAL compile error
- [ ] Checkpoint trigger fires and re-arms
- [ ] Aggro trigger wakes nav-enemy on entry
