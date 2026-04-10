# Feature: Lump System — Session Notes
Last updated: April 2026

---

## Status: Phase 1 complete. Ready for testing/review.

---

## Branch: `feature/lumps`

Addon: `addons/opengoal_tools.py` — copied from main (v1.2.0) at session start, now at ~9700 lines.

---

## What Was Built This Session

### 1. Assisted Lump Row Panel (OG_PT_SelectedLumps)
- `OGLumpRow` PropertyGroup (key, ltype, value) stored as `og_lump_rows` CollectionProperty on Object
- `LUMP_TYPE_ITEMS` — all 18 valid JSONC type strings with descriptions
- `_parse_lump_row()` — typed value parser, space-separated multi-values
- `_LUMP_HARDCODED_KEYS` — conflict detection set
- `OG_UL_LumpRows` UIList — scrollable, live error icon per row
- `OG_PT_SelectedLumps` sub-panel — poll: ACTOR_ empties only, DEFAULT_CLOSED
- `OG_OT_AddLumpRow` / `OG_OT_RemoveLumpRow` operators
- Export wiring in `collect_actors()` — rows merge after hardcoded values, highest priority
- Conflict logging: warns if row overrides a hardcoded key

### 2. Lump Reference Panel (OG_PT_SelectedLumpReference)
- `LUMP_REFERENCE` table — per-etype lump key list with type + description
- `UNIVERSAL_LUMPS` — 8 keys that apply to all actors
- `_enemy` sentinel — nav-mesh-sphere + nav-max-users injected for all enemies/bosses
- `_lump_ref_for_etype()` helper
- `OG_OT_UseLumpRef` — pre-fills a new Custom Lumps row with key + type on click
- `OG_PT_SelectedLumpReference` sub-panel — read-only reference, DEFAULT_CLOSED

### 3. Selected Object panel refactor
- Main panel (OG_PT_SelectedObject) now shows only name/type label + Frame/Delete
- All content moved to sub-panels with appropriate poll functions:
  - OG_PT_ActorActivation (idle-distance, enemies)
  - OG_PT_ActorTriggerBehaviour (aggro, nav-enemies)
  - OG_PT_ActorNavMesh (navmesh link, nav-enemies)
  - OG_PT_ActorPlatform (sync/path/notice-dist, platforms)
  - OG_PT_ActorCrate (crate type)
  - OG_PT_ActorWaypoints (path + pathB)
  - OG_PT_SpawnSettings (SPAWN_)
  - OG_PT_CheckpointSettings (CHECKPOINT_)
  - OG_PT_AmbientEmitter (AMBIENT_)
  - OG_PT_CameraSettings (CAMERA_)
  - OG_PT_CamAnchorInfo (_CAM suffix)
  - OG_PT_VolumeLinks (VOL_)
  - OG_PT_NavmeshInfo (NAVMESH_)

---

## Verified Working (from user log)

Export log confirmed lump rows exported correctly:
```
[WARNING] ACTOR_babak_0 lump row 'vis-dist' overrides addon default
[lump-row] ACTOR_babak_0  'vis-dist' = ['meters', 22.0]
[WARNING] ACTOR_babak_4 lump row 'vis-dist' overrides addon default
[lump-row] ACTOR_babak_4  'vis-dist' = ['meters', 10.0]
```

Note: vis-dist doesn't visually cull actors in custom levels (no BSP vis system).
Not a bug — expected behaviour. Documented for users.

Also noted: Dev Tools panel has a recurring crash when no level is set after addon
reload — `_user_dir()` resolves to relative `data\` path and fails with PermissionError.
Not blocking, but should be fixed separately.

---

## Design Direction (settled)

### Lump panel purpose
- Custom Lumps = power user escape hatch + learning tool
- Not the primary config path — dedicated per-type UI fields are preferred
- Long term: every lump an actor reads becomes a proper first-class UI element
- Lump panel stays for: exotic overrides, custom data, experimentation

### Priority rule (dedup at export)
1. Hardcoded addon values (lowest)
2. Assisted lump rows (highest — override anything above)
Conflicts logged as warnings, not blocked.

---

## Unsupported Actors Audit

Full audit complete. Results in `scratch/unsupported-actors-draft.md`.
Awaiting approval to promote to `knowledge-base/opengoal/unsupported-actors.md`.

Summary:
- 73 actor types currently in ENTITY_DEFS
- 164 additional placeable types found in source, not yet supported
- Tier 1 (~55): pure props, easy batch add
- Tier 2 (~65): read a few lumps, need testing
- Tier 3 (~35): complex multi-actor systems
- Tier 4 (~9): final-boss/cutscene only, unlikely to be useful

Quick-add batch of ~55 Tier 1 props identified — could be done in one session.

---

## Known Issues / Follow-up

- Dev Tools panel crash on reload with no active level (`_user_dir()` relative path bug)
- Standalone `OG_PT_Waypoints` panel still exists alongside new `OG_PT_ActorWaypoints`
  sub-panel — decide whether to remove the standalone one
- `vis-dist` behaviour in custom levels should be documented in UI tooltip
- Unsupported actors draft needs approval before kb promotion

---

## Files

- `addons/opengoal_tools.py` — working addon on this branch
- `scratch/unsupported-actors-draft.md` — actor audit (pending kb promotion)
- `knowledge-base/opengoal/lump-system.md` — full lump reference (DO NOT overwrite)

---

## Research Session — April 2026

Full non-prop actor research complete. File: `scratch/actor-research.md`

### Key corrections vs the earlier audit

| etype | audit said | reality |
|---|---|---|
| `sunkenfisha` | `count, speed, distance, path-max-offset, path-trans-offset` | correct keys, but `speed` is float[2] lo/hi range (not one value), and no `distance` lump |
| `sharkey` | `water-height, speed, delay, distance` | also reads `scale` (5 lumps total) |
| `spider-egg` | standard | also reads `alt-actor 0` for notify-actor (optional) |
| `cave-trap` | standard | reads `'path` + `alt-actor[]` array for spider-egg links |
| `swamp-rat-nest` | `num-lurkers` | also reads `'path` (required!) |
| `villa-starfish` | `num-lurkers` | also reads `'path` (required!) |
| `breakaway-*` | standard | reads `height-info` float[2] |
| `springbox` | `spring-height, art-name` | NO art-name lump — art group is hardcoded to `bouncer` |

### Zero-lump actors confirmed (just need ENTITY_DEFS entry + art group stem)
Enemy: `darkvine`, `quicksandlurker`, `peeper`, `spider-vent`
Platform: `qbert-plat`, `cavetrapdoor`, `ogre-bridgeend`, `swampgate`, `ceilingflag`
NPC: `bird-lady`, `bird-lady-beach`, `minertall`
Other: `swingpole` (no art either!), `boatpaddle`, `accordian`, `snow-eggtop`, `snow-switch`
Lava: `lavafall`, `lavafallsewera`, `lavafallsewerb`, `lavabase`, `lavayellowtarp`, `chainmine`, `balloon`, `crate-darkeco-cluster`

### Actors with surprise lumps (not obvious from type name)
- `windturbine`: `particle-select` uint (enable particles)
- `pontoon`: `alt-task` uint (second task gate)
- `mis-bone-bridge`: `animation-select` uint (1/2/3/7 — bone type)
- `caveflamepots`: `cycle-speed` float[3] (period, offset, pause) — all 3 packed in one key
- `snow-bumper`: `rotmin` float[2] (base_ry, max_diff_ry)

### Next step: implementation
Research complete. Ready to implement in order:
1. Tier 1 enemies (zero lumps — darkvine, quicksandlurker, peeper, spider-vent, spider-egg)
2. Then balloonlurker (alt-actor perm check)
3. Then cave-trap (path + alt-actor array)
4. Then eco pickups (ecovent/ventblue/red/yellow — alt-actor blocker)
5. Then springbox, swingpole, oracle (1 lump each)
6. Then sharkey, sunkenfisha, water-vol (multi-lump water actors)
7. Then platforms (orbit-plat, square-platform, caveflamepots, etc.)

---

## Implementation Session — April 2026

Added 59 new actor types across all four data structures.

Commit: f5544dd

### What was added
- **ENTITY_DEFS**: all 59 actors with correct cat, tpage_group, ag, nav_safe, needs_path, color, shape
- **ACTOR_OBJECTS**: .o injection entries (o_only=True) for all 59
- **ETYPE_TPAGES**: 7 new tpage group constants + 59 etype→tpages mappings
- **LUMP_REFERENCE**: per-etype lump hint entries with type strings and descriptions

### New tpage constants
LAVATUBE_TPAGES, FIRECANYON_TPAGES, VILLAGE1_TPAGES, VILLAGE2_TPAGES, VILLAGE3_TPAGES, ROLLING_TPAGES, TRAINING_TPAGES

### Known gaps (not implemented this session)
- Prop batch (~30 Tier 1 pure props) — deferred per user request
- babak-with-cannon — needs research
- lavashortcut — not implemented yet
- snow-ball, snow-log, snow-log-button, snow-switch, snow-button, snow-bumper — not implemented (need snow-log-master which isn't supported yet)
- sun-iris-door, helix-button, helix-slide-door, helix-water — not implemented (Tier 3 puzzle systems)
- citb-drop-plat, qbert-plat-master — Tier 3, deferred
- Tier 3 complex systems (battlecontroller, mistycannon, racer, race-ring, keg-conveyor, periscope, reflector-*) — not implemented

### Next steps
1. Test in Blender — verify actor picker shows new types
2. Test export — check a few actors actually spawn in-game
3. Address any o_only issues (some .o names may need verification)
4. Decide which Tier 3 actors to tackle next

---

## Entity Link System — April 2026

Commit: e31b776

### What was built
Full actor-to-actor link system matching the volume trigger UI pattern.

**Data:** `OGActorLink` PropertyGroup (lump_key, slot_index, target_name) stored as `og_actor_links` CollectionProperty on every Object.

**ACTOR_LINK_DEFS:** 23 etypes, 26 slots. 8 required slots (marked with *).

**UI:** `OG_PT_ActorLinks` sub-panel. Polls only for etypes with defined slots. Shows each slot with current link state, Link → button (appears on shift-select of compatible actor), X to clear. Type validation per slot.

**Export:** `_build_actor_link_lumps()` writes `["string", name0, name1, ...]` lumps. Engine resolves via `entity-by-name`. Runs before custom lump rows so rows can override. Required unset slots emit `[WARNING]` in export log.

### JSONC output example
```json
"alt-actor": ["string", "ogre-bridgeend-0"]
"water-actor": ["string", "water-vol-0"]  
"state-actor": ["string", "eco-door-controller-0"]
```

### Known gaps not yet in ACTOR_LINK_DEFS
- snow-log-master (not in ENTITY_DEFS yet — needs adding before snow-log links are useful)
- helix-slide-door, helix-water (not in ENTITY_DEFS yet)
- eco-door state-actor target — any entity works, not just specific types
