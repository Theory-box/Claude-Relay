# OpenGOAL Jak 1 — Known Bugs & Engine Patches

Bugs confirmed via source analysis and/or REPL debugging. Entries marked **[PATCH REQUIRED]** need a manual engine source change before the feature will work.

---

## [PATCH REQUIRED] vol-control lookup fails for custom levels

**Affects:** Any entity using `vol-control` — water volumes, aggro triggers, camera triggers, checkpoint volumes.

**Symptom:** `pos-vol-count` stays 0. `point-in-vol?` always returns `#f`. Volumes never activate.

**Root cause:** `vol-h.gc` calls `lookup-tag-idx` with `'exact 0.0` to find the `'vol` lump tag. The custom level C++ builder stores ALL res-lump tags at `DEFAULT_RES_TIME = -1000000000.0`. These never match `'exact 0.0`, so the tag is never found.

**REPL diagnosis:**
```lisp
; vol-count should be > 0 after level loads
(let ((w (the water-vol (process-by-name "water-vol-0" *active-pool*))))
  (format #t "vol-count:~d~%" (-> w vol pos-vol-count)))
; If 0 → patch not applied
```

**Fix:** Edit `goal_src/jak1/engine/geometry/vol-h.gc`, change `'exact` to `'base` on two lines:

```lisp
; Line ~50 (pos-vol lookup)
; BEFORE:
(s4-0 (-> ((method-of-type res-lump lookup-tag-idx) (the-as entity-actor s5-1) 'vol 'exact 0.0) lo))
; AFTER:
(s4-0 (-> ((method-of-type res-lump lookup-tag-idx) (the-as entity-actor s5-1) 'vol 'base 0.0) lo))

; Line ~64 (neg-vol / cutoutvol lookup)
; BEFORE:
(s4-1 (-> ((method-of-type res-lump lookup-tag-idx) (the-as entity-actor s5-2) 'cutoutvol 'exact 0.0) lo))
; AFTER:
(s4-1 (-> ((method-of-type res-lump lookup-tag-idx) (the-as entity-actor s5-2) 'cutoutvol 'base 0.0) lo))
```

Recompile after applying. The change is safe for vanilla levels — `'base` ignores timestamp and finds by name only, which works for both vanilla (`key-frame=0.0`) and custom levels (`key-frame=-1e9`).

**Also fixed in:** LuminarLight's LL-OpenGOAL-ModBase ("Hat Kid water hack").

**Confirmed:** via REPL — `vol-count` went from 0 to 1 after patch, water volumes activated correctly.

---

## Vol plane normals must point outward

**Affects:** Any custom code generating `vector-vol` plane data for `vol-control`.

**Symptom:** `point-in-vol?` always returns `#f` even when position is mathematically inside the box.

**Root cause:** `point-in-vol?` returns `#f` (outside) when `dot(P,N) - w > 0`. This means normals must face **outward** from the box, and inside = the negative side of every plane. Inward-facing normals invert the logic.

**Correct plane format for an AABB:**
```json
["vector-vol",
  [0,  1, 0,  surface_m],   // top:   P.y <= surface
  [0, -1, 0, -bottom_m],    // floor: P.y >= bottom
  [1,  0, 0,  xmax_m],      // +X:    P.x <= xmax
  [-1, 0, 0, -xmin_m],      // -X:    P.x >= xmin
  [0,  0, 1,  zmax_m],      // +Z:    P.z <= zmax
  [0,  0,-1, -zmin_m]       // -Z:    P.z >= zmin
]
```

**Confirmed:** via REPL — all 6 planes showed correct raw values but `point-in-vol?` returned `#f`. After flipping normals, water activated correctly.

---


---

## [AUTO-PATCHED] vol-h.gc patch applied automatically on export

As of v1.5.0+ the addon auto-patches `vol-h.gc` on every Export & Build. The patch is idempotent — if already applied it silently skips. The first export after a fresh install will patch and trigger a recompile; subsequent exports are silent.

**Manual patch still valid** if you want to apply it ahead of time or use the level without the addon.

---

## [COSMETIC] _user_dir PermissionError on addon reload with no level set

**Symptom:** Python traceback in console on addon reload or Blender startup:
```
PermissionError: [WinError 5] Access is denied: 'data'
FileNotFoundError: [WinError 3] The system cannot find the path specified: 'data\goal_src\user'
```

**Cause:** `_user_dir()` resolves to a relative `data\` path when `data_path` is not yet set in addon preferences (or before the preference is read). `Path.mkdir(parents=True)` fails trying to create folders relative to the Blender executable directory.

**Impact:** None — cosmetic only. The addon loads and works correctly. The error only fires on the startup path before any level is set.

**Fix:** Set `data_path` in addon preferences (Edit → Preferences → Add-ons → OpenGOAL Tools). Error will not reappear once a valid path is configured.

**Status:** Known, low priority, not blocking any functionality.

---

## [CONFIRMED: NOT ENTITY-SPAWNABLE] Bonelurker has no init-from-entity

**Symptom:** Placing `ACTOR_bonelurker_*` either does nothing at runtime or causes a silent spawn failure.

**Root cause confirmed from source:** `bonelurker.gc` contains no `init-from-entity!` method. The type only defines touch-handler, attack-handler, initialize-collision, and nav-enemy-method-48. In vanilla, bonelurker is exclusively spawned programmatically by `misty-battlecontroller` — it never appears as a direct entity-actor in any level JSONC.

**Fix:** Remove `bonelurker` from `ENTITY_DEFS` entirely. It cannot be used as a standalone placed entity. If the user wants bonelurkers in a level, they must implement a `battlecontroller` setup.

**Previous incorrect theory:** "Type redefinition at GOALC link time / requires battlecontroller.o as compile-time dependency." This was speculation — the actual issue is simply the absence of any init-from-entity handler.

---

## [FIXED] _prop_row write-in-draw crash — Blender 4.4

**Symptom:** Panel settings (platform sync, enemy idle distance, camera blend, etc.) disappear entirely when selecting an actor placed in a previous session. Error in console:
```
AttributeError: Writing to ID classes in this context is not allowed: ACTOR_plat-eco_0,
Object datablock, error setting Object.og_sync_period
```

**Root cause:** Blender 4.4 raised the restriction on writes inside `draw()` to include custom ID property dict writes (`obj["key"] = val`). `_prop_row` in `utils.py` was writing defaults for missing keys during the draw pass, which aborted the entire panel draw from that point down.

**Fix (shipped 2026-04-14):** `_prop_row` now defers the write via `bpy.app.timers.register(fn, first_interval=0.0)` — fires after the current redraw completes. Shows a greyed placeholder on the first frame; live input on next redraw.

**Affected:** Any actor placed before the addon update that lacks custom prop keys (e.g. `og_sync_period`, `og_idle_distance`, `og_cam_interp`). Newly spawned actors are unaffected — keys are initialised in `execute()` context at spawn time.

**Status:** Fixed in main.

---

## [FIXED] Preview meshes exported to game / sorted into Geometry/Solid

**Symptom (pre-fix):** Viz meshes (enemy model previews) appeared in-game after Export & Build, and Sort Collection Objects moved them into the Geometry/Solid sub-collection.

**Root cause:**
1. `_ensure_preview_collection` was setting `col["og_no_export"] = True` (custom prop dict), but `_col_is_no_export` reads `getattr(col, "og_no_export")` which reads the RNA property — a completely separate value. The no-export flag was never seen.
2. `_classify_object` had no guard for `og_preview_mesh` / `og_waypoint_preview_mesh` objects, so sort routed them to `_COL_PATH_GEO_SOLID`.

**Fix (shipped 2026-04-14):**
- `model_preview.py` now sets `col.og_no_export = True` (RNA property).
- `_classify_object` returns `None` for preview mesh objects.
- Export fallback path explicitly filters `og_preview_mesh` / `og_waypoint_preview_mesh`.

**Status:** Fixed in main.

---

## [CONFIRMED] warpgate is process-hidden — not entity-spawnable

**Symptom:** `ACTOR_warpgate_*` empty has no effect in-game.

**Root cause:** Source: `(deftype warpgate (process-hidden) ())` in `village_common/villagep-obs.gc`. `process-hidden` types have no game-loop, no draw method, no `init-from-entity!`. The warpgate visual is a scripted cinematic prop in vanilla, not a placeable entity.

**Fix:** Remove `warpgate` from `ENTITY_DEFS` in `data.py`.

---

## [CONFIRMED] ram is process-drawable, not nav-enemy

**Symptom:** `ACTOR_ram_*` placed in the Enemies panel has no navmesh or waypoint options, does nothing when Jak approaches.

**Root cause:** Source: `(deftype ram (process-drawable) ...)` in `snow/snow-ram-h.gc`. It is not a nav-enemy. Reads `extra-id` (instance index) and `mode` (uint, state variant). Has self-contained movement logic. Cannot be chased, triggered via aggro-trigger, or linked to a navmesh.

**Fix:** Move `ram` from cat `"Enemies"` to `"Objects"` in `ENTITY_DEFS`. Remove it from nav-enemy workflows. Document that it requires Snow tpages.

---

## [CONFIRMED] puffer 'distance' lump is vertical patrol range, not notice distance

**Symptom:** Setting `distance` lump on puffer has unexpected effect on vertical movement, not AI activation range.

**Root cause:** Source: `puffer.gc` reads `res-lump-data arg0 'distance (pointer float)` as a **two-float array**: `[0]` = top Y offset from patrol bottom, `[1]` = bottom Y offset. Both in internal units (divide by 4096 for meters). This is the vertical patrol range, not a notice/activation distance. `notice-dist` is the correct lump for activation range (single float, default 57344 ≈ 14m).

**Fix:** Update lump documentation. Puffer panel (if added) should expose both `notice-dist` (meters) and `distance` (two internal-unit floats for top/bottom Y offset).


---

## [CONFIRMED] one-shot ambient sounds broken in custom levels

**Symptom:** Ambient sound emitters with `cycle-speed < 0` (one-shot mode) play nothing in-game.

**Root cause:** `birth-ambient!` (`ambient.gc` lines 609, 621) uses `'exact 0.0` to look up `effect-name` and `effect-param`. Custom level lumps are stored at key-frame `-1e9` → `'exact 0.0` never matches → entity sets function to `ambient-type-error`.

The loop path (cycle-speed ≥ 0) works because `res-lump-struct` uses `'interp` internally, which does match `-1e9` keys.

**Fix:** In `goal_src/jak1/engine/entity/ambient.gc` change two `'exact` to `'base`:
```lisp
; Line ~609
; BEFORE:
(let ((s5-1 (-> ((method-of-type res-lump lookup-tag-idx) this 'effect-name 'exact 0.0) lo)))
; AFTER:
(let ((s5-1 (-> ((method-of-type res-lump lookup-tag-idx) this 'effect-name 'base 0.0) lo)))

; Line ~621
; BEFORE:
(let ((v1-28 ((method-of-type res-lump lookup-tag-idx) this 'effect-param 'exact 0.0)))
; AFTER:
(let ((v1-28 ((method-of-type res-lump lookup-tag-idx) this 'effect-param 'base 0.0)))
```

**Same fix needed in:** `ambient-type-light` (line ~481), `ambient-type-dark` (~507), `ambient-type-weather-off` (~533) — all use `'exact 0.0` for `'vol` lookup.

**Status:** Unpatched in current bundle. Workaround: use loop sounds (cycle-speed ≥ 0) only.

---

## [CONFIRMED] idle-distance lump is never read by nav-enemy

**Symptom:** Setting Idle Distance in the addon panel has no effect on enemy activation range.

**Root cause:** `idle-distance` is a field in the static `nav-enemy-info` struct (e.g. `*babak-nav-enemy-info*`), not read from entity lumps. The addon emits an `idle-distance` lump that no engine code reads.

**Fix options:**
- Remove the panel and lump emission (simplest)
- Inject a GOAL method override via obs.gc that reads the lump in `nav-enemy-method-48`

**Status:** Panel exists in addon, lump is emitted, has no in-game effect.

---

## [CONFIRMED BUG] Launcher fly-time is 300× too long

**Symptom:** Launcher with a destination set sends Jak flying for ~5 minutes instead of seconds.

**Root cause:** `generic-obs.gc` reads `alt-vector.w` and does `(* 300.0 w)` to convert seconds → frames for `seek-time`. Our export writes `w = fly_time_seconds * 300` (already frames). The engine then multiplies by 300 again: `seek_time_frames = fly_time_seconds * 300 * 300 = fly_time * 90000 frames`.

Source (`generic-obs.gc`):
```lisp
(set! (-> this seek-time) (the-as time-frame (the int (* 300.0 (-> v1-29 w)))))
```

**Fix in export.py:** Change `fw = round((fly_time if fly_time >= 0 else 0.5) * 300, 2)` to `fw = fly_time if fly_time >= 0 else 0.5` — write seconds directly, not frames.

**Status:** Bug in current addon. Launcher destination works spatially; only the fly-time duration is wrong.

---

## [CONFIRMED BUG] Missing crate types in addon

**Symptom:** Crates with `darkeco`, `barrel`, `bucket`, or `none` type are not available in the crate panel.

**Root cause:** The `crate-type` lump in the engine accepts these values but `CRATE_ITEMS` in `data.py` only lists `wood`, `iron`, `steel`.

**Valid crate-type values from `crates.gc`:**
- `wood` — standard breakable (default)
- `iron` — heavy, requires stronger attack
- `steel` — indestructible
- `darkeco` — dark eco crate, damages on break
- `barrel` — barrel visual
- `bucket` — bucket visual  
- `none` — invisible collision-only crate (hidden pickup container)

**Fix:** Add `darkeco`, `barrel`, `bucket`, `none` to `CRATE_ITEMS` in `data.py` and to the crate panel operator list.


---

## [DOCUMENTATION GAP] force-actors? setting not mentioned in getting-started docs

**Symptom:** Custom level entities don't spawn even when Jak is standing next to them.

**Cause:** `ps2-actor-vis? = #t` by default. Entities with `vis-id = 0` (all custom level entities) may fail the visibility AABB check if the camera frustum misses their recorded vis-box.

**Fix:** User adds `(force-actors? #t)` to their OpenGOAL settings file at:
`OpenGOAL/settings/jak1/pc-settings.gs`

This disables the vis check entirely on PC — all entities birth unconditionally. No recompile needed. Should be documented in the addon's getting-started guide.

