# Lighting Research Session Notes

## Status: Research COMPLETE — Addon implementation COMPLETE — ready for testing

## Branch: feature/lighting

## Completed This Session
- Full source read of all lighting-related .gc files in jak-project
- Created `knowledge-base/opengoal/lighting-system.md` — comprehensive doc (now on main)
- Implemented all lighting addon features (see below)
- Two full bug-audit passes

## Addon Changes (addons/opengoal_tools.py)
### New properties on OGProperties
- `mood` — EnumProperty, 21 presets, default=village1
- `sky` — BoolProperty, default=True
- `sun_fade` — FloatProperty 0.0–1.0, default=1.0
- `tod_slot` — EnumProperty, 8 ToD slots (_SUNRISE→_GREENSUN), default=_NOON

### New data
- `MOOD_ITEMS` — 21 mood presets with descriptions
- `MOOD_FUNC_OVERRIDES` — handles beach→update-mood-village1 mismatch
- `TOD_SLOTS` — ordered list matching tod_slot enum

### New operators
- `OG_OT_BakeToDSlot` — bake current lighting into selected ToD slot
- `OG_OT_BakeAllToDSlots` — bake all 8 slots with same lighting, resets active to _NOON

### Modified
- `patch_level_info` — now reads mood/sky/sun_fade from scene props
- `export_glb` — adds export_attributes=True on Blender >=3.4
- `OG_PT_LevelSettings` — new Lighting box with mood/sky/sun_fade
- `OG_PT_LightBaking` — ToD slot picker + bake operators, warning labels
- `OG_OT_BakeLighting` — fixed active_object restoration (was targets[0], now prev_active)

## Bugs Found and Fixed (audit passes)
1. beach mood → update-mood-beach (doesn't exist) → fixed via MOOD_FUNC_OVERRIDES
2. sun_fade :g format → '1' not '1.0' (GOAL needs float literal) → fixed with :.1f for integers
3. export_attributes TypeError on Blender <3.4 → guarded with version check + log warning
4. Active object not restored after bake (all 3 operators) → save/restore prev_active
5. Unused prev_device variable in original BakeLighting → removed
6. BakeAllToDSlots left active_color on _GREENSUN → resets to _NOON after completion
7. Bake button showed raw '_NOON' id → now shows display name 'Noon'
8. BakeAll had no UI warning about identical lighting → added ERROR icon warning row

## Next Steps
- [ ] Test in actual Blender — install addon on feature/lighting branch
- [ ] Verify mood dropdown correctly writes GOAL on export
- [ ] Bake a test level with 2–3 ToD slots and confirm export includes _SUNRISE etc.
- [ ] Test beach mood generates correct :mood-func 'update-mood-village1
- [ ] Custom mood tables — still requires manual GOAL if needed beyond presets

## Branch: feature/lighting

## Completed This Session
- Full source read of all lighting-related .gc files in jak-project
- Created `knowledge-base/opengoal/lighting-system.md` — comprehensive doc covering:
  - All type definitions (vu-lights, light-group, mood-context, mood-fog, mood-lights, mood-sun, etc.)
  - Time-of-day process (clock tick, API, star/sun visibility thresholds)
  - Mood system frame-by-frame flow
  - Vertex color baking (8 ToD slots, Blender attribute names)
  - All per-level mood callbacks and which globals they use
  - Dynamic effects (flames, lightning, lava, caustics)
  - Zone-based lighting (light-group slots, set-target-light-index)
  - Level config fields (mood, mood-func, sky, sun-fade)
  - palette-fade-controls system
  - Implementation guide for custom levels

## Key Findings
- Lighting has 3 separate pipelines: vertex colors (geometry), mood system (fog/sun/sky), light-groups (actors)
- mood-func is a per-level callback called every frame — this is the hook for all custom lighting
- *time-of-day-effects* global gates all dynamic effects — easy to toggle for testing
- *default-mood* uses village1 tables — current custom levels inherit this
- Light group slots 1-7 are zone-specific, player switches via set-target-light-index
- Custom level needs: mood global + mood-lights/fog/sun tables + update-mood-* function + level-info entries

## Next Steps (implementation)
- [x] Decide on desired ToD features: expose all moods as presets via UI
- [ ] Create custom mood tables (fog/lights/sun) for target level — village1 tables in knowledge doc are copy-paste ready
- [ ] Write update-mood-LEVELNAME callback in mood.gc
- [ ] Register mood global in mood-tables.gc
- [x] Wire :mood and :mood-func in level-info.gc — done via addon
- [ ] Bake vertex colors in Blender using the 8 _SUNRISE/_MORNING/etc. attributes
- [ ] Test with (set-time-of-day 12.0) etc. in REPL to verify transitions

## Files Read
- goal_src/jak1/engine/gfx/lights-h.gc
- goal_src/jak1/engine/gfx/mood/mood-h.gc
- goal_src/jak1/engine/gfx/mood/time-of-day-h.gc
- goal_src/jak1/engine/gfx/mood/time-of-day.gc
- goal_src/jak1/engine/gfx/mood/mood.gc (full — very long)
- goal_src/jak1/engine/gfx/mood/mood-tables.gc (structure + globals)
- goal_src/jak1/engine/gfx/sky/sky-h.gc
- goal_src/jak1/engine/level/level-h.gc (level-load-info, level types)
- goal_src/jak1/engine/level/level-info.gc (mood-func + sky field survey)
- goal_src/jak1/engine/game/main-h.gc (global toggles)
- goal_src/jak1/pc/pckernel-impl.gc (mood override debug)
- goal_src/jak1/levels/maincave/cavecrystal-light.gc (palette-fade example)
