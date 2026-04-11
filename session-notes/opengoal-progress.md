# OpenGOAL Blender Addon — Session Progress

## Status: v1.2.0 MERGED TO MAIN ✅
## Active branch: main (feature/enemies merged 2026-04-10)

## Active Branch: main
## Addon file: `addons/opengoal_tools.py`
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

## Trigger System Research — April 2026

### Camera triggers
Native vol-lump camera region system exists in engine (`master-check-regions`, `in-cam-entity-volume?`, `vol`/`pvol` plane lumps on `entity-camera`) but is NOT reachable from custom levels. The C++ builder (`build_level/jak1/LevelFile.cpp`) has the cameras section entirely commented out — `EntityCamera` is an empty stub struct, the JSONC cameras array is never read, so `entity-camera.birth!` never fires and `*camera-engine*` stays empty.

**Decision: Keep `camera-trigger` custom deftype. It is the only working approach.**

Future upstream path: implement `add_cameras_from_json()` in build_level, then use `vol` lumps directly on camera-marker entities. See `knowledge-base/opengoal/trigger-systems.md`.

### Checkpoint triggers
`static-load-boundary` with `checkpt` command is the native approach — pure GOAL, no born process, proper XZ polygon crossing detection with fwd/bwd direction, fires `set-continue!` on crossing. Called every frame in `render-boundaries` walking `*load-boundary-list*`.

**Decision: Replace `checkpoint-trigger` deftype with `static-load-boundary` GOAL emission.**

Implementation plan:
1. New `collect_load_boundaries(scene)` → list of boundary dicts (xz polygon, top/bot, cp_name)
2. `write_gc`: remove `checkpoint-trigger` deftype; emit `(defun setup-level-checkpoints () ...)` that creates and links load-boundary objects at level load time
3. Stop emitting `checkpoint-trigger` JSONC actors in `collect_actors`

Coordinate conversion: boundary x = bl_x * 4096, boundary z = -bl_y * 4096, top/bot = bl_z * 4096. Points are RAW game units, not meters.

### Enemy aggro triggers
No native equivalent. Keep `aggro-trigger` custom deftype.

## feature/native-checkpoints — April 2026

### What changed
Replaced `checkpoint-trigger` custom GOAL deftype with native `load-boundary` engine system.

**Removed:**
- `checkpoint-trigger` deftype + state + init-from-entity! from obs.gc (~70 lines)
- checkpoint-trigger JSONC actor emission from collect_actors
- `has_cps` bool detection in all 3 build pipeline call sites

**Added:**
- `collect_load_boundaries(scene, name)` — extracts CHECKPOINT_ empties + linked VOL_ meshes into boundary dicts with convex-hull XZ polygon coordinates
- `_convex_hull_2d(pts)` — Andrew's monotone chain for clean polygon footprints from arbitrary VOL_ mesh vertex clouds
- `write_gc` now emits `define-perm`/`when`/`set!` reload guard + `load-boundary-from-template` calls per checkpoint

**Generated GOAL pattern:**
```lisp
(define-perm *my-level-lb-tail* load-boundary #f)

(when *my-level-lb-tail*
  (set! *load-boundary-list* *my-level-lb-tail*))  ; reload: snip old entries
(set! *my-level-lb-tail* *load-boundary-list*)     ; save vanilla head

(load-boundary-from-template
  (new 'static 'boxed-array :type array :length 4 :allocated-length 4
    (the binteger 3)                         ; flags = player|closed
    (new 'static 'boxed-array :type float :length N :allocated-length N
      top bot x0 z0 x1 z1 ...)              ; raw game units
    '((the binteger 6) "continue-name" #f)   ; fwd = checkpt
    '((the binteger 0) #f #f)))              ; bwd = invalid
```

**Verified:**
- `define-perm` semantics (define-once, skips if already set) — correct
- `load-boundary-from-template` argument structure — exact match to engine source
- flags=3 (player|closed), checkpt=6, invalid=0 — confirmed against enum values
- Coordinate conversion: bl_x*4096=bnd_x, -bl_y*4096=bnd_z, bl_z*4096=top/bot
- Convex hull with 4-point box test — correct extents
- First-load / reload execution trace — no accumulation, vanilla list untouched
- `border?` confirmed set by target-continue `:exit` handler — boundaries fire in gameplay

### Status
Branch: `feature/native-checkpoints` — READY FOR IN-GAME TEST
Not yet merged to main.

### Test checklist (before merge)
- [ ] Place CHECKPOINT_ empty in a level, export and build — obs.gc compiles without error
- [ ] Player walks through checkpoint area — continue-name updates (check via REPL: `(-> *game-info* current-continue name)`)
- [ ] Player dies — respawns at checkpoint, not level start
- [ ] Hot-reload via nREPL (`(mi)`) — no duplicate boundaries, checkpoints still fire
- [ ] Level with no checkpoints — obs.gc compiles cleanly (no load-boundary code emitted)
- [ ] VOL_ mesh linked to CHECKPOINT_ — convex hull boundary matches mesh footprint in-game

### Additional bugs caught pre-test (same session)

**Bug 3 — First-load list wipe** (caught during review):
Unconditional `(set! *load-boundary-list* *lb-tail*)` ran on first load when `*lb-tail*` was `#f` — wiping all 170 vanilla boundaries. Fixed with `(when *lb-tail* ...)` guard.

**Bug 4 — Quoted-pair binteger (critical, would have silently misfired or crashed)**:
`'((the binteger 6) "name" #f)` in a quoted context does NOT evaluate `(the binteger 6)` — GOAL stores the literal symbol-list as the pair's car. Engine then reads `(/ (the-as int car) 8)` expecting a boxed integer and gets a pair pointer.
Fixed: use `(static-load-boundary :fwd (checkpt "name" #f) ...)` directly — the macro evaluates `(the binteger ...)` at compile time, same as all 170 vanilla boundaries in `load-boundary-data.gc`.

**Bug 5 — Stale entries when removing all checkpoints**:
Cleanup guard was inside `if boundaries:` — rebuilding with 0 checkpoints left stale entries from the previous build in `*load-boundary-list*` indefinitely.
Fixed: always emit the `define-perm` + `(when ...)` guard at top level regardless of checkpoint count.

### Final generated GOAL (with checkpoints)
```lisp
;; load-boundary cleanup guard for my-level.
(define-perm *my-level-lb-tail* load-boundary #f)
(when *my-level-lb-tail*
  (set! *load-boundary-list* *my-level-lb-tail*))
(set! *my-level-lb-tail* *load-boundary-list*)

(load-boundary-from-template
  (static-load-boundary
    :flags (player closed)
    :top 12288.0 :bot -4096.0
    :points (32768.0 -28672.0 49152.0 -28672.0 49152.0 -12288.0 32768.0 -12288.0)
    :fwd (checkpt "my-level-cp1" #f)
    :bwd (invalid #f #f)))
```

### Version
v1.3.0 on branch `feature/native-checkpoints`

### Test checklist
- [ ] Build compiles without error (GOALC)
- [ ] Walk through CHECKPOINT_ zone → `(-> *game-info* current-continue name)` updates
- [ ] Die → respawn at checkpoint, not level start
- [ ] Hot-reload `(mi)` → no duplicate entries, checkpoint still fires
- [ ] Remove all checkpoints, rebuild → no stale trigger from previous build
- [ ] Level with no checkpoints → builds clean

---

## Session — April 11 2026: Trigger System Research + native-checkpoints

### What we set out to do
Investigate whether our custom trigger types (camera-trigger, checkpoint-trigger, aggro-trigger) were bypassing working engine systems. Answer: partially yes.

### Research findings (trigger-systems.md)

**Camera triggers** — engine HAS a native vol-lump region system (`master-check-regions`, `in-cam-entity-volume?`, `vol`/`pvol` plane lumps on `entity-camera`). But the C++ level builder (`build_level/jak1/LevelFile.cpp`) has the cameras section entirely commented out — `EntityCamera {}` is an empty stub, no JSONC cameras array is read, so `entity-camera.birth!` never fires and `*camera-engine*` stays empty for custom levels. Our `camera-trigger` deftype is the only working approach. Native system requires upstream C++ fix.

**Checkpoint triggers** — `static-load-boundary` with `checkpt` command is engine-native pure GOAL. 170 vanilla boundaries already use this. `render-boundaries` → `check-boundary` runs every frame. No custom deftype, no born process, proper XZ polygon crossing with fwd/bwd direction. Fully replaceable.

**Enemy aggro triggers** — no native equivalent. Keep custom `aggro-trigger`.

### What changed: feature/native-checkpoints (v1.3.0)

**Removed:**
- `checkpoint-trigger` deftype + state + `init-from-entity!` from obs.gc (~70 lines)
- `checkpoint-trigger` JSONC actor emission from `collect_actors`
- `has_cps` bool + all three `_lv_objs` scans in build pipeline

**Added:**
- `collect_load_boundaries(scene, name)` — extracts CHECKPOINT_ + linked VOL_ meshes → boundary dicts with convex-hull XZ polygon in raw game units
- `_convex_hull_2d(pts)` — Andrew's monotone chain
- `write_gc` now unconditionally emits `define-perm` + reload guard, then conditionally emits `load-boundary-from-template(static-load-boundary ...)` per checkpoint

**5 bugs caught before any in-game test:**
1. Reload accumulation — `load-boundary-from-template` prepends on every eval; fixed with perm+restore guard
2. First-load list wipe — unconditional restore with `#f` tail would nuke all vanilla boundaries; fixed with `(when *lb-tail* ...)`
3. Quoted-pair binteger (critical) — `'((the binteger 6) ...)` doesn't evaluate in GOAL quote context; engine reads pair pointer instead of boxed int → silent misfire. Fixed by using `static-load-boundary` macro directly
4. Stale entries on checkpoint removal — cleanup guard was inside `if boundaries:`; fixed by making it unconditional
5. Redundant `import math` inside function — cleaned up

**Bug 6 — border? never set (found from first in-game test, commit 8181ce3):**
`render-boundaries` only calls `check-boundary` when `(-> *target* control border?)` is `#t`.
In vanilla levels this is set by `target-continue`'s `:exit` handler after first respawn.
Custom levels never go through that path so `border?` stays `#f` forever — all load-boundary
crossings silently ignored. Fixed by emitting `(when *target* (set! (-> *target* control border?) #t))`
before the `load-boundary-from-template` calls. Guard is safe on cold load (Jak not yet spawned).

### Branch status
`feature/native-checkpoints` — fix pushed (commit 8181ce3), needs re-test in-game.

Active branch: `feature/native-checkpoints`
Working file: `addons/opengoal_tools.py`

### Next session
Test the branch in-game. If passing, merge to main. Key REPL check:
```lisp
(-> *game-info* current-continue name)  ; should update as you cross the zone
```
