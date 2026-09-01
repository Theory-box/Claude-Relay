# Platform System — Session Progress

## Status: REBASED ON MAIN + PLATFORM PANEL ADDED — ready for in-game testing

## Active Branch: `feature/platforms`

---

## What's Done

- ✅ Rebased on main (level flow, UI tweaks, camera CAMVOL_ rename all included)
- ✅ `knowledge-base/opengoal/platform-system.md` — complete source reference (on main)
- ✅ Entity defs: all 14 platform types have `needs_sync`, `needs_path`, `needs_notice_dist` flags
- ✅ `PLATFORM_ENUM_ITEMS` — platform-only enum for spawn dropdown
- ✅ `platform_type` EnumProperty on OGProperties
- ✅ `show_platform_list` BoolProperty on OGProperties
- ✅ `_actor_is_platform()` helper
- ✅ `_actor_uses_waypoints()` — updated to include `needs_sync` (Waypoints panel works for moving platforms)
- ✅ Duplicate `_actor_uses_waypoints` definition removed (was in main twice)
- ✅ Lump export in `collect_actors`:
  - `sync` lump: `["float", period, phase, ease_out, ease_in]` — only when waypoints present
  - `options` lump: `["uint32", 8]` when og_sync_wrap=1 (wrap-phase bit 3 = value 8)
  - `path` lump: for plat-button (needs_path) and sync platforms with waypoints
  - `notice-dist` lump: `["meters", val]` for plat-eco
- ✅ `OG_OT_NudgeFloatProp` — generic nudge with val_min/val_max clamping
- ✅ `OG_OT_TogglePlatformWrap` — toggles og_sync_wrap 0↔1
- ✅ `OG_OT_SetPlatformDefaults` — resets sync props to defaults
- ✅ `OG_OT_SpawnPlatform` — places ACTOR_<etype>_<uid> empty at 3D cursor
- ✅ `OG_PT_Platforms` panel:
  - Spawn section (always visible): type dropdown + Add Platform at Cursor button
  - Settings section (shown only when a platform actor is the active object):
    - Sync: period, phase, ease-out, ease-in, wrap-phase toggle, reset button
    - Path status for plat-button
    - Eco notice-dist for plat-eco
  - Collapsible scene list: all ACTOR_plat* empties, frame-select + delete per entry
  - Framing an entry selects it → settings section appears naturally

---

## Per-Actor Custom Properties

| Property           | Default | Range    | Notes                                    |
|--------------------|---------|----------|------------------------------------------|
| `og_sync_period`   | 4.0     | 0.5–300s | Seconds for one full A→B→A cycle         |
| `og_sync_phase`    | 0.0     | 0–0.9    | Staggers multiple platforms              |
| `og_sync_ease_out` | 0.15    | 0–0.5    | Fraction of period spent easing out      |
| `og_sync_ease_in`  | 0.15    | 0–0.5    | Fraction of period spent easing in       |
| `og_sync_wrap`     | 0       | 0 or 1   | 0=ping-pong, 1=one-way loop              |
| `og_notice_dist`   | -1.0    | -1 or ≥0 | plat-eco only; -1=always active          |

---

## Testing Checklist

- [ ] plat with 2 waypoints moves back and forth in game
- [ ] plat sits idle when placed without waypoints
- [ ] plat-eco sits idle, activates when player has blue eco (notice-dist > 0)
- [ ] plat-eco always moves when notice-dist = -1
- [ ] plat-button moves when Jak stands on top
- [ ] wrap-phase: loops one-way when og_sync_wrap=1
- [ ] phase offset: two platforms with phase=0.0 and phase=0.5 are staggered
- [ ] Platform panel: spawn dropdown shows all platform types
- [ ] Platform panel: Add Platform places correct actor at cursor
- [ ] Platform panel: settings hidden when no platform selected
- [ ] Platform panel: selecting from list makes settings appear
- [ ] Platform panel: collapsible list shows all platforms in scene
- [ ] Platform panel: frame button selects + frames the platform
- [ ] Platform panel: delete button removes the platform
- [ ] Waypoints panel still appears for sync platforms (plat, plat-eco)

---

## Code Review Log

### Round 1 bugs fixed (commit eb3762a)
1. `OG_OT_SpawnPlatform` used `base_id` for uid — corrupts level actor ID space. Fixed to count-based.
2. `plat-button` hit enemy path block AND platform path block — double emit + double warn. Fixed by guarding enemy block with `cat != "Platforms"`.
3. `_draw_platform_settings` used `bpy.data.objects` (all scenes) for wp_count. Fixed to `scene.objects`.

### Round 2 — all clean
- PLATFORM_ENUM_ITEMS: 13 types, sorted alphabetically, valid 4-tuple format ✓
- SpawnPlatform uid prefix isolation: `plat` vs `plat-eco` not conflated ✓
- DeleteObject does NOT clean wp_ waypoints on platform delete — pre-existing gap, same for enemies, out of scope
- All None guards in panel draw verified ✓
- Missing custom props handled via o.get(prop, default) everywhere ✓
- Old OG_PT_Platform (singular) panel: zero remaining references ✓
- og_sync_wrap: written as int 0/1, read via bool() — consistent ✓
- og_notice_dist clamping: -5m button can't accidentally reach -1 (always-active requires explicit button) ✓
- platforms flow through _canonical_actor_objects correctly ✓
- No cross-panel regressions in Waypoints, Place Objects, or NavMesh panels ✓

---

## In-Game Test Results (2026-04-09)

### Working ✓
- `plat` — moves, collision correct
- `plat-eco` — eco activation works, notice-dist works
- `plat-button` — moves when Jak stands on it

### Broken standalone ✗ (game-side, not addon bugs)
- `balance-plat` — hit-by-others collision list, needs actor-link chain to receive 'grow, Jak passes through
- `wall-plat` — spawns retracted with collision cleared, needs 'trigger message from external entity
- `teetertotter` — Misty-specific scripted sequence, animated joints start in non-collidable position
- `plat-flip` — JungleB-specific, collision at animated transform-index, not suitable for general use

### Not yet tested
- side-to-side-plat, revcycle, wedge-plat, launcher, warpgate
- wrap-phase, phase staggering, plat-button bidirectional

### Future work logged in knowledge-base/opengoal/platform-system.md §13

---

## Final Status (2026-04-09)

**Merged to main via feature/ui-restructure.**

Platform panel now lives as **Spawn > Platforms sub-panel** inside the Spawn group.
All platform functionality preserved: type picker, Add Platform, active settings,
sync/phase/wrap controls, platform list. Confirmed working in Blender 4.4.

Platforms still untested: side-to-side-plat, revcycle, wedge-plat, launcher, warpgate.
Broken standalone (game-side): balance-plat, wall-plat, teetertotter, plat-flip.

---

## Bug Fix — 2026-04-14 (Blender 4.4 write-in-draw)

**Symptom:** Platform Settings panel disappeared entirely when selecting a `plat-eco` (or any platform actor placed in a previous session).

**Error:** `AttributeError: Writing to ID classes in this context is not allowed: ACTOR_plat-eco_0, Object datablock, error setting Object.og_sync_period`

**Root cause:** Blender 4.4 now raises `AttributeError` on `obj[key] = val` inside any `draw()` context — including custom ID property dict writes, which earlier Blender versions allowed. `_prop_row` was writing the default value when a key was missing on the object, which aborted the entire panel draw.

**Fix:** `_prop_row` in `utils.py` now uses `bpy.app.timers.register(fn, first_interval=0.0)` to schedule the default write outside the draw context. Shows a greyed placeholder on the first frame; live input field on next redraw.

**Affected actors:** Any actor placed before the addon was updated (missing custom prop keys). New actors spawned via SpawnPlatform/SpawnEntity already have all keys initialised in `execute()` — not affected.

**Status:** Fixed in main as of 2026-04-14.
