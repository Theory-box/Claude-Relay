# OpenGOAL Blender Addon — Session Progress

## Status: v1.1.0 MERGED TO MAIN ✅
## Active branch: feature/enemies (in testing — NOT merged)

## Active Branch: feature/enemies
## Addon file: `addons/opengoal_tools.py`
## Backup: `addons/opengoal_tools_v1.0.0_backup.py`

---

## What's In Main (v1.1.0)

### UI Restructure
- **Level panel** (parent, always open): name, ID, death plane at top
  - Level Flow sub-panel: spawns, checkpoints, bsphere preview
  - Level Manager sub-panel: custom level list, remove/refresh
  - Light Baking sub-panel: vertex color bake
  - Music sub-panel: music bank + sound bank 1/2 selectors
- **Spawn panel** (parent, DEFAULT_CLOSED):
  - Enemies sub: filtered dropdown (enemies + bosses only), inline navmesh link
  - Platforms sub: platform spawn + active platform settings
  - Props & Objects sub: filtered dropdown
  - NPCs sub: filtered dropdown
  - Pickups sub: filtered dropdown
  - Sound Emitters sub: pick sound, add emitter, emitter list
- **Triggers**: always visible (no DEFAULT_CLOSED)
- **Waypoints**: context-sensitive (shows when enemy/platform actor selected)
- **Camera, Build & Play, Dev Tools, Collision**: unchanged

### Features working (confirmed in Blender 4.4)
- ✅ Camera position + rotation export (quaternion formula confirmed)
- ✅ Trigger volumes (AABB, entity-actor, births on level load)
- ✅ Camera switch on enter, revert on exit
- ✅ Look-at target (interesting lump)
- ✅ FOV, blend time, mode (fixed/standoff/orbit)
- ✅ Sound emitters (looping ambients, confirmed working with village1 bank)
- ✅ Music bank + sound bank export in level-info.gc
- ✅ Platform sync/path/phase export
- ✅ Navmesh link UI (inline in Enemies sub-panel)
- ✅ Per-category entity dropdowns (each sub-panel shows only its types)
- ✅ All 37 static analysis checks pass

---

## Camera Quaternion Formula (confirmed working)

```python
m3 = cam_obj.matrix_world.to_3x3()
bl_look = -m3.col[2]
gl = Vector((bl_look.x, bl_look.z, -bl_look.y))
gl.normalize()
game_down = Vector((0, -1, 0))
right = gl.cross(game_down).normalized()
if right.length < 1e-6: right = Vector((1,0,0))
up = gl.cross(right).normalized()
gq = Matrix([right, up, gl]).to_quaternion()
qx, qy, qz, qw = -gq.x, -gq.y, -gq.z, gq.w  # conjugate
```

---

## Feature Branches (all merged, all inactive)

| Branch | What it added | Status |
|---|---|---|
| feature/audio | Sound emitters, music bank, SBK sound picker | ✅ Merged to main |
| feature/camera | Camera actor, trigger volumes, FOV/blend/mode | ✅ Merged to main |
| feature/platforms | Platform types, sync/path/phase UI | ✅ Merged to main |
| feature/lighting | Vertex color light baking | ✅ Merged to main |
| feature/navmesh | Navmesh link/compute/entity.gc patch | ✅ Merged to main |
| feature/lumps | Lump system for actor properties | ✅ Merged to main |
| feature/ui-restructure | Panel groups, per-category dropdowns | ✅ Merged to main (2026-04-09) |

---

## feature/enemies (active, NOT merged)

Adds enemy activation distance control + trigger-driven aggro + a generalized
multi-link volume system. See `knowledge-base/opengoal/enemy-activation.md`
for full engine reference.

### Features
- **Per-enemy idle distance** (`og_idle_distance`, default 80m). Emits
  `idle-distance` lump on every enemy/boss actor. Engine reads it via
  `fact-info-enemy:new` (`fact-h.gc:191`). Lower = enemy stays asleep
  longer; higher = wakes up sooner. UI: `Activation` box on selected enemy
  with -5m / +5m nudge buttons. Range 0–500m.
- **Aggro triggers**: trigger volume → nav-enemy link sends `'cue-chase`
  (or `'cue-patrol` / `'go-wait-for-cue`) on player enter. Implemented as
  new `aggro-trigger` deftype emitted by `write_gc`, polls AABB, looks up
  target via `(process-by-ename ...)` and dispatches event by hardcoded
  `cond` on a uint32 `event-id` lump. Re-fires on re-entry.
- **Multi-link volume system**: replaces single-string `og_vol_link` with
  `og_vol_links` `CollectionProperty(type=OGVolLink)`. One volume can hold
  N links of mixed types (camera + checkpoint + enemy). Three independent
  build passes scan each volume's links and emit one trigger actor per link.
- **Per-link behaviour dropdown** (nav-enemy targets only): each link entry
  has its own `behaviour` enum (`cue-chase` / `cue-patrol` / `go-wait-for-cue`).
  The dropdown only renders for enemy links — camera/checkpoint links show
  just name + unlink button.
- **Auto-migration** from legacy `og_vol_link` strings via `_vol_links()`
  shim — old `.blend` files load transparently.

### Critical limitation
**Process-drawable enemies do NOT respond to `'cue-chase`.** The handler
is on `nav-enemy` only (`nav-enemy.gc:142`). The addon enforces this:
`_actor_supports_aggro_trigger()` checks `ai_type == "nav-enemy"`. UI hides
the trigger behaviour box and "Add Aggro Trigger" button for unsupported
enemies (Yeti, Bully, Mother Spider, Jungle Snake, etc.).

### Volume naming convention
- 0 links → `VOL_<id>`
- 1 link → `VOL_<target_name>`
- 2+ links → `VOL_<id>_<n>links`

Renamed automatically by `_rename_vol_for_links()` after every add/remove.

### Color coding
- Green — camera triggers (existing)
- Yellow — checkpoint triggers (existing)
- Red-orange — aggro triggers (new)

### Duplicate-link rules
- Same vol → same target twice: blocked for all types
- Different vols → same camera/checkpoint: blocked (Scenario B)
- Different vols → same enemy: ALLOWED (Scenario A — multi-region aggro)

### Key files / functions added
- `class OGVolLink(PropertyGroup)` — link entry data type
- `class OG_OT_RemoveVolLink` — per-link X button
- `class OG_OT_AddLinkFromSelection` — append a link from panel
- `class OG_OT_SpawnAggroTrigger` — context-aware "Add Aggro Trigger" button
- `def collect_aggro_triggers(scene)` — build pass
- `def _vol_aabb(vol_obj)` — shared AABB extraction (used by all 3 trigger passes)
- `def _vol_links(vol)` — accessor with legacy migration shim
- `def _rename_vol_for_links(vol)` — naming based on link count
- `def _vols_linking_to(scene, target_name)` — reverse lookup
- `def _vol_remove_link_to(vol, target_name)` — single-entry removal
- `def _classify_target(name)` → 'camera' | 'checkpoint' | 'enemy' | ''
- `def _actor_is_enemy(etype)` / `_actor_supports_aggro_trigger(etype)`
- `def _aggro_event_id(name)` → 0/1/2 for the lump

### Refactored
- `OG_OT_LinkVolume` — appends instead of rejecting
- `OG_OT_UnlinkVolume` — clears all links from selection
- `OG_OT_SpawnVolume` / `OG_OT_SpawnVolumeAutoLink` — collection-based
- `OG_OT_DeleteObject` — removes only matching link entries (vols orphan)
- `OG_OT_CleanOrphanedLinks` — per-entry cleanup, returns tuples
- `_draw_selected_volume` — full multi-link list view
- `_draw_selected_camera` / `_draw_selected_checkpoint` — uses `_vols_linking_to`
- `_draw_selected_actor` — new Activation + Trigger Behaviour boxes for enemies
- `OG_PT_Triggers.draw` — multi-link aware list, count-based orphan check
- `collect_cameras` / checkpoint build pass — iterate `og_vol_links`

### Engine refs (no patches required)
- `fact-h.gc:191` — `idle-distance` res-lump read
- `nav-enemy.gc:142–144` — `'cue-chase` / `'cue-patrol` / `'go-wait-for-cue` handlers
- `entity.gc:92` — `entity-by-name`
- `entity.gc:167` — `process-by-ename`
- `nav-enemy.gc:495,534,709,754` — `idle-distance` AI check
- `battlecontroller.gc:114,203` — base game `(send-event ... 'cue-chase)` reference

---

## Known Limitations / Future Ideas

### Sound emitters
- One-shot sounds crash (engine bug: `lookup-tag-idx 'exact 0.0` on tags at `-1e9`)
- Only looping ambients work via the ambient system
- Music is triggered by `set-setting! 'music` not the music-bank field directly

### Navmesh
- NavMesh panel removed — navmesh link UI now inline in Enemies sub-panel
- og.mark_navmesh, og.unmark_navmesh, og.pick_navmesh operators still registered
  but have no panel UI (orphaned pre-existing operators, harmless)

### Entity picker
- `entity_type` kept in sync for export compatibility when sub-panel spawns entities
- source_prop on SpawnEntity operator routes to correct per-category prop

### Future features (wanted)
- **Collections as levels** — each Blender collection becomes a level with its own settings (name, ID, death plane, etc.). Spawning objects auto-creates and organizes into logical sub-collections. Sub-collections can be marked "no export" to exclude from build output. Enables multi-level workflows in a single `.blend`.
- **Procedural asset tools** — tools for generating common level geometry procedurally: bridges, cliff sides, etc. Reduces manual mesh work for repeated structural elements.
- **Curve-based object placement** — draw a curve in the viewport and spawn objects along it. First target: Precursor orbs along a path. General enough to extend to other pickups/objects.
- **Load boundaries** — add support for `load-boundary` entries (modifying `load-boundary-data.gc`). Base game uses these for checkpoints (71 of 170 boundaries use `cmd = checkpt`). Has `fwd`/`bwd` directional crossing support unlike the current actor-based checkpoint-trigger. Requires engine-side edits, not just JSONC — addon could export boundary code snippets.
- **Per-scene path overrides** — `exe_path` and `data_path` are currently global addon prefs (one value, shared across all files). Add optional per-scene overrides stored in the `.blend` itself. `_exe_root()` / `_data_root()` check scene override first, fall back to global prefs if blank. Lets multi-project users bake paths into each file without changing prefs every switch.

### UX restructure ideas (parking — discuss before implementing)
- **Settings only in active-object panel.** Today some settings live in the per-feature panels (Spawn, Camera, etc.) and some in the selected-object panel. Consolidating *everything* into the selected-object panel means: panels become spawn-only (pick a type, click to place) and all configuration happens after selection. Cleaner mental model — "panels make things, the side panel edits them" — but it's a real restructure across most of the addon, not a quick change. Keep in mind for a future sweep.
- **Settings as 3D-space empties.** Instead of panel-level scene settings (lighting/time-of-day, level music, fog, etc.), spawn empties in 3D space that *represent* those settings. Click the empty → its config appears in the selected-object panel. Examples: a "lighting" empty that holds time-of-day; a "level audio" empty that holds music bank choice; a "fog" empty that holds fog params. Makes scene-level configuration discoverable in the outliner instead of hidden behind tab clicks. Same idea as how cameras/checkpoints already work — generalize the pattern to scene state.

### Optimization ideas (not urgent)
- Tfrag chunking system (see opengoal-progress.md §Future Branch Ideas)
- Music ambient zones (type='music ambient)
- Sound emitter volume/pitch/falloff controls
- One-shot sounds (requires upstream OpenGOAL fix)

---

## Files
- `addons/opengoal_tools.py` — main addon, always installable
- `addons/opengoal_tools_v1.0.0_backup.py` — pre-restructure backup
- `knowledge-base/opengoal/` — system reference docs
- `session-notes/` — per-feature progress tracking

