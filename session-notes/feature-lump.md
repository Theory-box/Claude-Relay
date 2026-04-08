# Feature: Lump System — Session Notes
Last updated: April 2026

---

## Status: Research phase complete. No code written yet.

---

## What We Did This Session

Pulled the full OpenGOAL source and did a comprehensive crawl of every lump key
used across all of `goal_src/jak1/`. Produced a complete knowledge base document.

**Source files analysed:**
- `goalc/build_level/common/ResLump.cpp` — internal storage format, tag/data layout
- `goalc/build_level/common/Entity.cpp` — lump_map, all valid JSONC type strings
- `goalc/build_level/jak1/Entity.cpp` — add_actors_from_json, bare string handling
- `goal_src/jak1/engine/entity/res.gc` — runtime lookup functions
- `goal_src/jak1/engine/entity/ambient.gc` — all ambient lump types
- `goal_src/jak1/engine/entity/entity.gc` — vis-dist, visvol, name
- `goal_src/jak1/engine/common-obs/process-drawable.gc` — universal lumps
- `goal_src/jak1/engine/common-obs/collectables.gc` — eco-info, movie-pos, options
- `goal_src/jak1/engine/common-obs/basebutton.gc` — extra-id, prev-actor
- `goal_src/jak1/engine/common-obs/baseplat.gc` — flags (eco-door-flags)
- `goal_src/jak1/engine/common-obs/generic-obs.gc` — launcher, springbox lumps
- `goal_src/jak1/engine/common-obs/orb-cache.gc` — orb-cache-count
- `goal_src/jak1/engine/common-obs/water-anim.gc` — look, trans-offset
- `goal_src/jak1/engine/util/sync-info.gc` — sync lump (period, phase, in/out)
- `goal_src/jak1/engine/nav/navigate.gc` — nav-mesh-sphere, nav-mesh-actor, nav-max-users
- `goal_src/jak1/engine/camera/cam-layout.gc` — all camera lumps
- `goal_src/jak1/levels/common/battlecontroller.gc` — full arena controller lumps
- `goal_src/jak1/levels/common/launcherdoor.gc` — continue-name
- `goal_src/jak1/levels/swamp/swamp-bat.gc` — num-lurkers
- `goal_src/jak1/levels/snow/yeti.gc` — num-lurkers, notice-dist
- `goal_src/jak1/levels/sunken/puffer.gc` — distance (2-float, internal units)
- `goal_src/jak1/levels/sunken/whirlpool.gc` — speed (2-float)
- `goal_src/jak1/levels/sunken/sunken-fish.gc` — count, speed, distance, path-max/trans-offset
- `goal_src/jak1/levels/jungle/jungle-obs.gc` — height-info
- `goal_src/jak1/levels/jungleb/plat-flip.gc` — delay (2-float), sync-percent
- `goal_src/jak1/levels/maincave/gnawer.gc` — extra-count, gnawer (bitmask), trans-offset
- `goal_src/jak1/levels/maincave/dark-crystal.gc` — mode, extra-id
- `goal_src/jak1/levels/snow/snow-obs.gc` — mode (2-int for snow-piston)
- `goal_src/jak1/levels/citadel/citb-plat.gc` — scale
- Various others for full coverage

**Total unique lump keys found:** 87

---

## Knowledge Base Location

`knowledge-base/opengoal/lump-system.md`

Contains:
- How lump storage works internally
- Full JSONC type string reference (all 18 types)
- Lump sorting behaviour
- Every lump key documented with type, actor, JSONC format, defaults
- Full actor-to-lump quick reference table
- Shared lumps cross-reference
- Addon automation status table

---

## Key Findings

### Lump system is completely open
The engine builder (`add_actors_from_json`) places no restriction on which keys
appear in the lump dict. Any key the actor's GOAL code reads will work. Unknown
keys are silently ignored. This means `og_lump_*` passthrough is fully safe.

### `game_task` accepts raw int OR enum string
`actor_json.value("game_task", 0)` with a branch for string → `get_enum_val`.
Both `0` and `"(game-task none)"` work. Our addon writes the enum string; fine.

### Bare string lump values
- Starts with `'` → ResSymbol (quote is stripped)
- Otherwise → ResString
- This is different from the array `["symbol", ...]` format
- Both produce ResSymbol — but bare strings use a different timestamp (-1e9 vs default)

### `puffer` `distance` lump is INTERNAL UNITS not meters
Two float values, neither scaled. Values like `57344.0` = ~14m. Do NOT use
`["meters", ...]` format for puffer distance — the code reads raw floats.

### `path-k` spline knots
Formula confirmed: `[0,0,0,0, 0,1,2,...,N-1, N-1,N-1,N-1,N-1]` = N+8 total entries.
Community keg-conveyor example matches this exactly (14 path pts → 18 knot values).

### `sync` lump for platforms
`["float", period_sec, phase, in_frac, out_frac]` — period in seconds (×300 for frames).
Min 2 values, max 4. This is the main way to make oscillating platforms sync to each other.

### `battlecontroller` is a full combat arena system
Supports up to 8 spawner groups, each with their own path lump (named numerically).
Most complex actor in the game from a lump standpoint.

---

## What Needs To Be Built (Feature: Lump)

### Priority 1 — `og_lump_*` passthrough (~30 lines)
Reads custom properties on entity empties prefixed `og_lump_` and injects them
into the lump dict. Covers 90% of custom actor needs without any per-type UI.

### Priority 2 — Well-known lumps sub-panel (~100 lines)
When an entity empty is selected, show relevant UI fields:
- Enemy: `num-lurkers` (slider), `notice-dist` (float), `vis-dist` (float)
- Launcher: `spring-height` (float), `alt-vector` (target picker), `mode` (dropdown)
- Platform: `sync` (period, phase sliders), `delay` (float)
- Pickup: `options` (fact-options checkboxes), `movie-pos` (optional)
- Door: `flags` (eco-door-flags checkboxes)
- Water vol: `water-height` (full 5-field panel)

### Priority 3 — Freeform lump list UI
A "Custom Lumps" expandable section on any entity empty.
Shows a list of `[key, type, value]` rows.
User can add/remove rows. Each row writes to `og_lump_<key>` custom property.
Type dropdown from the 18 valid type strings.

### Priority 4 — `path-k` auto-generation
For actor types known to use `curve-control` (keg-conveyor etc.),
auto-generate `path-k` from waypoint count. Checkbox: "Auto-generate path-k".

---

## Branch

Feature work should go on: `feature/lump` (not yet created)

Create when ready to start coding:
```
git checkout main && git pull
git checkout -b feature/lump
git push -u origin feature/lump
```

---

## Files

- `knowledge-base/opengoal/lump-system.md` — full lump reference (DO NOT overwrite without approval)
- `feature-community-questions.md` on `feature/community` — includes keg-conveyor example

