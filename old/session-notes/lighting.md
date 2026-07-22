
---

## Session — April 11 2026 — Continued Testing

### What was confirmed
- All 8 TOD slots (_SUNRISE through _GREENSUN) confirmed present in exported GLB via pygltflib inspection
- level-info.gc confirmed correct: `:mood '*village1-mood*`, `:mood-func 'update-mood-village1`, `:sky #t`, `:sun-fade 1.0`
- Baked slots are visually different in Blender (bakes are correct)
- Re-exported with patched addon, rebuilt, tested — geometry still stuck on _SUNRISE regardless of `(set-time-of-day X)` value
- `_SUNRISE` is `COLOR_0` in the GLB (was the active attribute at export time), `COLOR_1`–`COLOR_7` are the remaining slots in order

### Current hypothesis
The level builder reads `COLOR_0`–`COLOR_7` in order as the 8 TOD slots (not by name). Ordering appears correct.
The more likely issue: `time-of-day-interp-colors` (VU-coded) may simply not run on custom-built level tfrag geometry in the current OpenGOAL version. This may be a feature that works for vanilla levels (built from original PS2 data) but is not yet wired for custom levels.

### Not yet confirmed
- Whether OpenGOAL's level builder actually supports TOD vertex color interpolation for custom levels at all
- Best next step: ask in OpenGOAL Discord whether `time-of-day-interp-colors` runs on custom level tfrag geometry (water111 / devs)

### Stop point
Pausing TOD investigation. Resume by: asking OpenGOAL devs if custom level TOD vertex interpolation is supported.
