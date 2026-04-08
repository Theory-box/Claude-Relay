# Lighting Research Session Notes

## Status: Research phase — knowledge doc complete, implementation not started

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
- [ ] Decide on desired ToD features: full 8-slot cycle? or simplified static?
- [ ] Create custom mood tables for test level
- [ ] Wire up mood-func in level-info
- [ ] Test vertex color baking workflow in Blender with the 8 attribute names
- [ ] Investigate sky-tng.gc for sky renderer hook points

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
