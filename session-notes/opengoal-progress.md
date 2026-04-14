# OpenGOAL Blender Addon — Session Progress

## Status: v1.4.0 MERGED TO MAIN ✅
## Active branch: main (depsgraph thread-safety fix merged 2026-04-11)

## Active Branch: main
## Addon file: `addons/opengoal_tools/` (split module)
## Backups: `addons/opengoal_tools_v1.0.0_backup.py`, `addons/opengoal_tools_v1.1.0_backup.py`

---

## What's In Main (v1.2.0)

### v1.2.0 additions (from feature/enemies)
- **Per-enemy idle distance** — `og_idle_distance` (default 80m), emitted as `'idle-distance` lump on every enemy/boss. Engine reads via `fact-info-enemy:new` (fact-h.gc:191). Lower = enemy stays asleep longer; higher = wakes up sooner.
- **Trigger-driven aggro** — new `aggro-trigger` GOAL deftype emitted by `write_gc` when any vol has nav-enemy links. Polls AABB, looks up target via `(process-by-ename ...)`, dispatches `'cue-chase` / `'cue-patrol` / `'go-wait-for-cue` based on a uint32 `event-id` lump. Re-fires on re-entry.
- **Multi-link volume system** — replaces single-string `og_vol_link` with `og_vol_links` `CollectionProperty(type=OGVolLink)`. One volume can hold N links of mixed types (camera + checkpoint + enemy). Three independent build passes scan each volume's links and emit one trigger actor per link. Auto-migration shim for legacy `.blend` files.
- **Volume naming**: 0 links → `VOL_<id>`; 1 link → `VOL_<target>`; 2+ links → `VOL_<id>_<n>links`.
- **Per-link behaviour dropdown** — only renders for nav-enemy links; camera/checkpoint links show name + unlink button only.
- **Critical limitation**: only nav-enemies (Babak, Lurker Crab, Hopper, Snow Bunny, Kermit, etc.) respond to `'cue-chase`. Process-drawable enemies (Yeti, Bully, Mother Spider, Jungle Snake, etc.) don't have the engine handler. Addon enforces this — UI hides aggro trigger box for unsupported enemies.
- See `knowledge-base/opengoal/enemy-activation.md` for full engine references.

### v1.1.0 baseline (UI Restructure)
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
| feature/enemies | Idle distance, aggro triggers, multi-link volumes (v1.2.0) | ✅ Merged to main (2026-04-10) |

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


---

## v1.4.0 — Limit Search + Quick Search Dropdown (feature/limit-search → main)

### Status: MERGED TO MAIN ✅
### Branch: main (merged from feature/limit-search)

---

### What was built

#### Tpage data fixes
- `lightning-mole` tpage_group: `Unknown` → `Rolling` (confirmed from `rol.gd` / `rolling-lightning-mole.o`)
- `ice-cube` tpage_group: `Unknown` → `Snow` (confirmed from `textures.gc`: `icecube-*` uses `snow-vis-pris`)
- `fireboulder` tpage_group: `Unknown` → `Village2` (confirmed from `vi2.gd` / `fireboulder-ag.go`)
- `Unknown` group is gone entirely — all three resolved from jak-project source
- `TPAGE_GROUP_ORDER` in `_build_entity_enum` updated to match (added Rolling, Lavatube, Firecanyon, Village2/3, Training; removed Unknown)

#### New: GLOBAL_TPAGE_GROUPS constant
`{"Village1", "Village2", "Village3", "Training"}` — always resident in memory, never incur heap cost, never filtered.

#### New: Limit Search sub-panel (`OG_PT_SpawnLimitSearch`)
- Child of Quick Search panel (`bl_parent_id = "OG_PT_spawn_search"`, `DEFAULT_CLOSED`)
- Toggle checkbox in panel header (`tpage_limit_enabled`, default off)
- Two dropdowns side by side: `tpage_filter_1`, `tpage_filter_2` — each picks one tpage group from 13 cost groups in world order
- Slot 2 greyed out when slot 1 is `NONE`
- Warning label if both slots select the same group
- Entire dropdown col greyed when toggle is off

#### Filter behaviour
1. **Toggle off** → everything visible, identical to pre-feature
2. **Toggle on, both slots NONE** → still show all (no restriction declared)
3. **Toggle on, slots selected** → only entities whose `tpage_group` is in the selected set are shown
4. **Always visible regardless**: entities with no `tpage_group` field (pickups, most platforms, props, NPCs), entities in `GLOBAL_TPAGE_GROUPS`
5. **Scope**: Spawn Objects panel and all children only

#### Filter indicator
Parent `OG_PT_Spawn.draw()` shows `🔍 Filtered: Group1 + Group2` when filter is active and at least one group selected.

#### Filter implementation
Three consistent implementations (verified to produce identical results):
- `_tpage_filter_passes(etype, g1, g2, enabled)` in `data.py` — importable core logic
- `_entity_passes_filter(etype, props)` in `panels.py` — used by Quick Search
- Inline in `_search_results_cb` — used by the search enum cache

#### Sub-panel dropdowns
All five category dropdowns (Enemies, Props, NPCs, Pickups, Platforms) switched from static `items=LIST` to dynamic callbacks (`_enemy_enum_cb` etc.) built via `_make_filtered_enum()`. Callbacks re-run on redraw; only return matching items when filter is active. Blender-safe: built from stable base lists, integer IDs preserved.

#### New: Quick Search scrollable dropdown
- Replaced manual button list (20-result cap, collapsible) with `entity_search_results: EnumProperty(items=_search_results_cb)`
- `_search_results_cb`: cached by `(query, enabled, g1, g2)` key — only rebuilds when state changes, stable between redraws (avoids Blender dynamic enum crash pattern)
- Returns `__empty__` sentinel for empty query and no-match states
- `update=` lambda syncs `entity_search_selected` on selection change
- Panel draw: search field → dropdown → spawn button. Three lines, no collapsible, no cap.
- `OG_OT_SearchSelectEntity` still registered but now dormant (unused by Quick Search; harmless)

#### Known non-issue
Vertex Export panel (line ~1509 in panels.py) reuses `entity_search` string and still has old 20-result manual list. Intentional — separate feature, not broken.

### New properties
```python
tpage_limit_enabled:   BoolProperty(default=False)
tpage_filter_1:        EnumProperty(items=TPAGE_FILTER_ITEMS, default="NONE")
tpage_filter_2:        EnumProperty(items=TPAGE_FILTER_ITEMS, default="NONE")
entity_search_results: EnumProperty(items=_search_results_cb, update=<sync lambda>)
```

### Future: Level Audit (parked, wanted)
Under Level panel, sub-panel "Level Audit". General scene checker — first use: scan ACTOR_ empties, count distinct non-global tpage groups, warn if > 2. Design to be generalised beyond tpages. Build when requested.


---

## Water System Research + feature/water branch

### Status: feature/water — active, awaiting test
### Branch: feature/water
### Working file: addons/opengoal_tools/export.py

---

### What was researched (jak-project source)

Full water system documented in `knowledge-base/opengoal/water-system.md`.

Key finding: **water-vol was completely broken** in custom levels. Root cause:
- `water-vol` uses `vol-control` to define its activation zone
- `vol-control` reads a `'vol` res-lump: 6 convex hull planes (not the bsphere)
- Without the `'vol` lump: `pos-vol-count = 0`, `point-in-vol?` always `#f`
- Jak never enters the zone, no wading/swimming, nothing

Secondary issue: `bsph_r` was hardcoded to `10.0` for all actors. Water-vol needs
a bsphere that covers its full box or the process gets renderer-culled.

### Fix in export.py

1. **`'vol` lump** — 6 `vector-vol` planes computed from the empty's world scale:
   - `ws = o.matrix_world.to_scale()`
   - `hx = abs(ws.x)`, `hz = abs(ws.y)` (game X and Z half-extents)
   - Normals point INWARD. Inside condition: `dot(P, N) >= d`
   - top cap: `[0, -1, 0, -surface_y]`
   - floor:   `[0,  1, 0,  bot_y]`  where `bot_y = surface + bottom_offset`
   - ±X/Z caps from `gx ± hx`, `gz ± hz`

2. **`bsph_r` override** for water-vol: `sqrt(hx² + hz²)` — XZ half-diagonal

### Usage
- Place `ACTOR_water-vol` empty
- Scale it to cover water area (scale = half-extent in meters; scale 10 = 20m wide box)
- Use selected-object panel to set surface Y, wade, swim depths
- Sync Surface from Object Y button sets surface from empty's world Z
- Export → wading/swimming should work

### water-anim (visual water surface) — NOT yet in addon
- Requires art assets from level-specific DGOs (e.g. training lake needs TRA.DGO)
- 48 built-in looks via `'look` lump (0–47)
- Best starting look for custom levels: 36 (training lake)
- Ripple shader is vertex deformation — needs dense mesh geo (not a single quad)
- Phase 2 work: water sub-panel, look picker, water-anim entity support

### Plane math reference (for future water-anim or other vol work)
- lump type: `"vector-vol"` → C++ multiplies w by 4096 automatically
- format: `[nx, ny, nz, d_meters]`
- engine test: `dot(P, N) - d < 0` → outside (i.e. inside when `dot(P,N) >= d`)
- all normals must point inward for convex hull


---

## Water System — COMPLETE (feature/water merged to main)

**Status:** Working. Confirmed in-game via REPL debugging.

**Two fixes required outside the addon:**
1. `vol-h.gc` patch: change `'exact` → `'base` on lines ~50 and ~64 (lookup-tag-idx for 'vol and 'cutoutvol)
2. User must recompile after applying the patch

**Root causes found (in order of discovery):**
1. `level_objs` scope — WATER_ block was in wrong function
2. `o.dimensions = 0` for empties — switched to mesh approach  
3. `bot_y` calculation wrong
4. wade/swim stored as absolute Y — engine expects depths
5. `wt02/wt03` never set — `logior! wt23` runs before `(zero? flags)` check
6. `water.o` DGO injection — was `o_only`, should be `in_game_cgo`
7. WATER_ mesh included in GLB geometry
8. `SetWaterAttack` not registered
9. WATER_ mesh block in wrong function (`collect_ambients` not `collect_actors`)
10. `vol-h.gc` key-frame mismatch — `'exact 0.0` vs `DEFAULT_RES_TIME = -1e9` → `vol-count:0`
11. Vol plane normals pointing inward — `point-in-vol?` requires outward normals

**Addon version at merge:** v1.4.x (feature/water → main)

---

## feature/vol-patch — NEEDS LIVE TEST

Auto-patches `vol-h.gc` on every export+build (idempotent). Added to `_bg_build` in `build.py`.

**Test checklist:**
- [ ] Fresh install — confirm `vol-h.gc` is found at expected path (`data_root/goal_src/jak1/engine/geometry/vol-h.gc`)
- [ ] First export+build patches the file and logs `[patch] vol-h.gc patched`
- [ ] Second export+build is silent (no re-patch, file already correct)
- [ ] Water volumes still work after the auto-patch triggers a recompile
- [ ] Confirm build doesn't fail if `vol-h.gc` path doesn't exist (graceful skip)

**Branch:** feature/vol-patch — do NOT merge to main until tested.

---

## feature/doors — Door System (active)

### Status: feature/doors — pushed, awaiting test
### Branch: feature/doors
### Working files: addons/opengoal_tools/data.py, export.py, panels.py, __init__.py

---

### What was researched (jak-project source)

**Door types documented:**
- `eco-door` (base) — opens on proximity + blue eco OR perm-complete OR state-actor link OR one-way exit side
- `sun-iris-door` — opens via `'trigger` event OR proximity lump; most useful for custom levels
- `launcherdoor` — opens when Jak is on launch-jump surface below thresh-y
- `basebutton` — flop-attack (ground pound) to press; sends `'trigger` to alt-actor on press
- `plat-button` — floor pressure plate; path-driven, sets perm-complete

**Key finding — why eco-door never worked:**
- Requires blue eco OR perm-complete. Custom levels never have blue eco nearby.
- Flag bits were WRONG: `auto-close=1, one-way=2` should be `auto-close=4, one-way=8`

**sun-iris-door is the recommended door for custom levels** — responds to `'trigger` from trigger volumes or basebutton alt-actor link.

### Changes made

#### data.py
- Added `sun-iris-door` entity def + DGO mapping (`sun-iris-door.o`)
- Added `basebutton` entity def + DGO mapping (`basebutton.o`)
- Updated `LUMP_REFERENCE` for all door types and basebutton
- Added `basebutton` → `alt-actor` slot in `ACTOR_LINK_DEFS` (targets door)
- Updated `eco-door` ACTOR_LINK_DEFS comment

#### export.py
- **FIXED eco-door flags bits**: `auto-close=4` (was 1), `one-way=8` (was 2)
- Added `starts_open` export: emits `perm-status` lump so door spawns pre-opened
- Added `sun-iris-door` proximity + timeout export
- Added `basebutton` timeout export

#### panels.py
- Expanded `OG_PT_ActorEcoDoor`: open-condition hint box explaining blue eco requirement; new Starts Open toggle
- New `OG_PT_ActorSunIrisDoor`: proximity toggle + timeout nudger
- New `OG_PT_ActorBaseButton`: timeout nudger + usage hint

#### __init__.py
- Registered `OG_PT_ActorSunIrisDoor` and `OG_PT_ActorBaseButton`

### Door wiring patterns (for testing)

**Pattern 1 — Always-open eco-door:**
- Place `ACTOR_eco-door`, enable "Starts Open" in panel → door spawns open

**Pattern 2 — Proximity iris door:**
- Place `ACTOR_sun-iris-door`, enable "Open by Proximity" → opens when Jak walks up

**Pattern 3 — Button → iris door:**
- Place `ACTOR_basebutton` + `ACTOR_sun-iris-door`
- In basebutton's ActorLinks panel: set alt-actor 0 = the sun-iris-door
- Ground-pound button → door opens

**Pattern 4 — Trigger volume → iris door:**
- Place `ACTOR_sun-iris-door` (proximity OFF)
- Add a VOL_ trigger volume, link it to the sun-iris-door via vol link system
- (Note: trigger vol currently sends `'notify` not `'trigger` — may need engine check)

**Pattern 5 — Blue eco door (vanilla):**
- Place `ACTOR_eco-door` with no extra settings
- Door opens only when Jak has blue eco and walks close

### Known open questions

- [ ] Does trigger volume send `'trigger` or `'notify` to linked actors? If `'notify`, sun-iris-door won't respond (it listens for `'trigger`). Need to verify event name in aggro-trigger GOAL code.
- [ ] `sun-iris-door.o` — confirm this is the correct .o filename in the DGO system (may be `sunken-obs.o` instead)
- [ ] `basebutton.o` — confirm correct .o filename (may be in `GAME.CGO` already as `basebutton.o`)
- [ ] Test `perm-status` lump approach for starts_open — engine may not read this lump in init path


---

## Headless Test Environment (session 2026-04-13)

### Toolchain setup (persists in /tmp until VM resets)
- OpenGOAL v0.3.1 extracted to `/tmp/opengoal/`
- iso_data extracted to `/tmp/iso_extract/iso_data/` and symlinked into toolchain
- Decompiler already run — `decompiler_out/` exists and tpage-dir.txt present
- Blender 4.4.3 at `/tmp/blender-4.4.3-linux-x64/blender`
- Addon installed at `/root/.config/blender/4.4/scripts/addons/opengoal_tools/` (feature/doors)

### Rebuild steps if VM resets
```bash
# Reassemble toolchain
cd /home/claude/Claude-Relay/blender
cat blender-4_4_3-linux-x64.part_a* > /tmp/blender.tar.xz && tar -xf /tmp/blender.tar.xz -C /tmp/
# OpenGOAL — user must re-upload opengoal-linux-v0.3.1.tar.gz and iso_data parts
# Then: mkdir /tmp/opengoal && tar -xzf <upload> -C /tmp/opengoal
# Then: unrar x iso_data_part1.rar /tmp/iso_extract/ (parts 1-3)
# Then: ln -s /tmp/iso_extract/iso_data /tmp/opengoal/data/iso_data
# Decompiler: cd /tmp/opengoal && ./extractor --decompile --proj-path data/ data/iso_data/jak1/
```

### Test approach
Use Blender headlessly to generate the level JSONC via the addon's export operator,
then compile with goalc, then boot with gk under Xvfb. All driven from Python scripts
calling Blender's addon operators — same code path as the user's real workflow.

### Door crash root cause found
- `eco-door` is abstract — no skeleton init in base `eco-door-method-25` (returns 0)
- Exporting `etype: "eco-door"` causes null skeleton dereference in `door-closed` state
- Fix: remap `eco-door` → `jng-iris-door` at export time (done in feature/doors)

### Open question
- Does `jng-iris-door` actually work after the remap fix? Need live test.
- Does `basebutton` spawn without crash? It should (nav-mesh-connect is safe with no mesh)


---

## v1.7.0 — Door System (feature/doors → main)

### Status: MERGED TO MAIN ✅

### What shipped
- `jng-iris-door`, `sidedoor`, `rounddoor`, `sun-iris-door`, `basebutton` entity defs + DGO mappings
- eco-door etype crash fix (remaps to jng-iris-door at export — abstract base has no skeleton)
- eco-door flags bits fixed (auto-close=4, one-way=8, was wrong 1/2)
- ecdf00 auto-set when state-actor linked (door locks until button pressed)
- starts_open toggle (perm-status=64, unverified — may not be read by engine)
- New panels: OG_PT_ActorEcoDoor (expanded), OG_PT_ActorSunIrisDoor, OG_PT_ActorBaseButton
- **Global actor link name fix**: was writing Blender object name, now writes entity lump name

### Wiring pattern that works
- Place ACTOR_eco-door + ACTOR_basebutton
- Select eco-door → Actor Links → state-actor → basebutton
- Export: door gets flags=1 (ecdf00), state-actor="basebutton-N"
- In game: door spawns locked, button press unlocks it, blue eco opens it
- Add One Way to skip blue eco requirement

### Unverified
- starts_open (perm-status lump may not be engine-readable)
- Trigger volume → sun-iris-door (event name mismatch: notify vs trigger)
- rounddoor, sidedoor live spawn test

---

## Level Audit — UPDATED for v1.7.0, 31/31 tests passing

**Branch:** feature/level-audit @ e799f2d
**Status:** Ready to merge when user approves

### What changed this session
- Merged main (v1.7.0 doors) into feature/level-audit
- Added `check_doors()` — 9 door-specific rules covering:
  - eco-door / jng-iris-door / sidedoor / rounddoor: state-actor target type check
  - launcherdoor: continue-name required + existence check
  - basebutton: warns if no door listens to it
- Added `check_entity_defs_audit_blocks()` — data-driven runner for
  `custom_checks` declared in ENTITY_DEFS `"audit"` blocks. Future
  features declare their checks in data.py; this fires them automatically.
- Added `_REGISTERED_CHECKS` list at bottom of audit.py — append here to add checks
- Fixed `_actor_get_link` usage — returns OGActorLink object, not string
- All objects.get() calls wrapped in try/except for Blender collection safety

### Test results
- 17 regression checks (original): all pass
- 8 door-specific checks: all pass
- 1 custom_block future-proof check: pass
- 5 integration checks: pass
- **Total: 31/31**

### Pending: vis-blocker (feature/vis-blocker not yet merged to main)
When vis-blocker merges, add to audit:
- `VISMESH_` prefix objects: check they have valid mesh geometry (not zero-vert)
- Add to `_REGISTERED_CHECKS` — no other changes needed if ENTITY_DEFS audit
  block pattern is followed



---

## feature/goal-code — GOAL Code Panel + Custom Type Spawner

### Status: feature/goal-code — active, not yet merged
### Branch: feature/goal-code

---

### What was built

#### GOAL Code Panel (Level 3 text-block injection)
- `OGGoalCodeRef` PropertyGroup: `text_block` (PointerProperty→bpy.types.Text) + `enabled` bool
- Registered as `bpy.types.Object.og_goal_code_ref` on every object
- `OG_PT_ActorGoalCode`: sub-panel of Selected Object, polls any ACTOR_ empty (not wp)
  - Header dot lights when block is active+enabled
  - No block: Create boilerplate button + manual picker
  - Block assigned: name picker, enabled toggle, X disconnect, line count status,
    Create/Open in Editor buttons, shared-block warning
- `OG_OT_CreateGoalCodeBlock`: creates text block with etype-specific boilerplate
- `OG_OT_ClearGoalCodeBlock`: disconnects without deleting
- `OG_OT_OpenGoalCodeInEditor`: switches first open Text Editor area to the block
- `write_gc()` now accepts `scene=None`, scans ACTOR_ empties, deduplicates by
  text block name, appends enabled blocks verbatim to *-obs.gc after addon types
- All 3 `write_gc()` call sites in build.py updated to pass `scene=scene`

#### Custom Type Spawner
- `_is_custom_type(etype)` helper in data.py: returns True for any etype not in ENTITY_DEFS
- `custom_type_name: StringProperty` on OGProperties for the spawn panel input
- `OG_OT_SpawnCustomType`: validates name (lowercase+hyphens, not built-in), places
  ACTOR_<name>_N empty at cursor, yellow-green colour to distinguish from built-ins
- `OG_PT_SpawnCustomTypes`: Spawn sub-panel "⚙ Custom Types"
  - Type name input + live-updating spawn button label
  - How-it-works hint box (6-step workflow)
  - Lists existing custom actors in scene with code-block status (✓ or ✗)

### Workflow to test
1. Spawn sub-panel → ⚙ Custom Types → type `spin-prop` → Spawn
2. Select the empty → Selected Object → GOAL Code → Create boilerplate block
3. Open Text Editor (Shift+F11) → GOAL Code panel → Open in Editor
4. Replace boilerplate with spin-prop code from knowledge-base/opengoal/goal-scripting.md
5. Export+Build → check build log for "[write_gc] injected 1 custom GOAL code block"
6. Open goal_src/levels/<n>/<n>-obs.gc — custom code at bottom
7. In-game: ACTOR_spin-prop_0 spawns and its transform rotates

### Known gap (no blocker)
- collect_actors falls through all etype-specific guards for custom types — this is correct
- Custom types get a minimal lump dict (name/trans/quat/bsphere) — no special lumps
- Any lumps needed (e.g. 'spin-rate') must be added via the Custom Lumps panel

### Knowledge docs updated (on main)
- `knowledge-base/opengoal/goal-scripting.md` — full GOAL language reference, unit system,
  entity patterns, 5 complete working examples, addon workflow section (How Code Gets Into the Game)
  https://github.com/Theory-box/Claude-Relay/blob/main/knowledge-base/opengoal/goal-scripting.md
- `knowledge-base/opengoal/modding-addon.md` — GOAL Code panel section + Custom Type spawner
  section added; panel reference table updated; obs.gc stale references fixed
  https://github.com/Theory-box/Claude-Relay/blob/main/knowledge-base/opengoal/modding-addon.md
