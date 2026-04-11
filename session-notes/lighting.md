# Lighting Session Notes

## Status: TOD system implemented — ready for testing

## Branch: feature/lighting

## Base
Addon replaced with main branch (10,738 lines) as clean starting point.
All previous feature/lighting work (mood dropdown, sky, sun_fade, bake ops) has been re-implemented on top of main.

---

## What's Implemented (this session)

### Constants (top of file, after enum items)
- `MOOD_ITEMS` — 21 mood presets with descriptions
- `MOOD_FUNC_OVERRIDES` — handles beach→village1 mood-func quirk
- `TOD_SLOTS` — 8 slots: _SUNRISE, _MORNING, _NOON, _AFTERNOON, _SUNSET, _TWILIGHT, _EVENING, _GREENSUN
- `TOD_COLLECTION_NAMES` / `TOD_SLOT_IDS` — convenience lists

### OGProperties (new fields)
- `mood` — EnumProperty(MOOD_ITEMS, default="village1")
- `sky` — BoolProperty(default=True)
- `sun_fade` — FloatProperty(0.0–1.0, default=1.0)
- `tod_slot` — EnumProperty(TOD_SLOTS, default="_NOON")

### patch_level_info update
- Reads mood/sky/sun_fade from scene.og_props (was hardcoded village1/#t/1.0)
- Writes: `:mood '*{mood_id}-mood*`, `:mood-func 'update-mood-{mood_func}`, `:sky #t/#f`, `:sun-fade {val}`
- beach override handled via MOOD_FUNC_OVERRIDES

### New Operators
- `OG_OT_SetupTOD` (og.setup_tod) — creates `{level}_TOD` collection inside level collection, with 8 sub-collections named `{level}_TOD_Sunrise` etc.
- `OG_OT_BakeToDSlot` (og.bake_tod_slot) — bakes selected slot on selected meshes using BYTE_COLOR/CORNER attribute
- `OG_OT_BakeAllToDSlots` (og.bake_all_tod_slots) — bakes all 8 slots, resets active to _NOON

### New Panel: OG_PT_TODSub
- Location: Levels > Light Baking > Time of Day (DEFAULT_CLOSED)
- Section 1 — Level Lighting Settings box: mood dropdown, sky toggle, sun_fade slider
- Section 2 — TOD Collections box: description + Setup TOD button
- Section 3 — Bake ToD Slots box: mesh count, slot picker, Bake Slot button, Bake All 8 button + warning

---

## UI Location
Levels → Light Baking → 🕐 Time of Day

---

## Next Steps
- [ ] Test in Blender — install addon from feature/lighting
- [ ] Verify Setup TOD creates correct collection hierarchy
- [ ] Test Bake Slot on a mesh — confirm _NOON attribute created + baked
- [ ] Verify patch_level_info emits correct mood/sky/sun_fade on export
- [ ] Test beach mood → emits update-mood-village1 (not update-mood-beach)
- [ ] Future: expose num-stars control
- [ ] Future: custom mood tables (still requires manual GOAL)
- [ ] Merge to main when tested and approved

## Known Gaps
- Custom mood tables (fog/lights/sun per slot) still require manual GOAL editing
- Blender <3.4: export_attributes not available, ToD slots bake but won't export
