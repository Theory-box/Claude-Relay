# Time of Day / Mood System — OpenGOAL Jak 1

> Source: Kuitar [DUST] community knowledge, April 2026.
> Status: Confirmed workflow, actor handling confirmed.

---

## Overview

Jak 1 uses a **time-of-day (ToD) / mood** system that affects level lighting and color grading across named time slots. The system is split between Blender (color attribute baking) and OpenGOAL game code (`mood-tables.gc`).

---

## Blender Side — Color Attribute Setup

Each time of day is stored as a **vertex color attribute** on the level mesh. All attribute names start with `_` (underscore prefix).

### Known time slots
| Attribute Name | Time |
|---|---|
| `_SUNRISE` | Dawn |
| `_MORNING` | Morning |
| `_NOON` | Midday |
| `_AFTERNOON` | Afternoon |
| `_SUNSET` | Dusk |
| `_TWILIGHT` | Twilight |
| `_EVENING` | Night |
| `_GREENSUN` | Green sun (special/alternate sky) |

### Workflow
1. Set up color attributes on the mesh using the names above.
2. Bake lighting to each color attribute slot individually.
3. Export — the exporter reads these attributes and maps them to the correct ToD slots.

This is intentionally **user-friendly**: the only Blender-side requirement is that the color attributes exist with the correct `_NAME` format.

---

## Game Code Side — `mood-tables.gc`

**Actors** (enemies, NPCs, interactive objects) are **handled separately** from the level geometry for time-of-day changes.

Actor mood/lighting behavior is defined in:
```
goal_src/jak1/engine/gfx/mood/mood-tables.gc
```

This file controls how actor colors/shading respond to each ToD slot. If you want actors to change appearance with time of day (rather than stay static), this is where that logic lives.

### Key points
- Level geometry ToD is driven by the baked vertex color attributes.
- Actor ToD is driven by `mood-tables.gc` — separate pipeline.
- Custom levels currently default to `village1` mood (see `modding-addon.md` known limitation).
- Other mood options exist in the test-zone JSONC but are untested for custom levels as of the current addon.

---

## `mood-tables.gc` — Table Structure

> Source: Kuitar [DUST], April 2026. Marked iirc where confidence is lower.

Each level defines three named tables in this file.

---

### `levelname-mood-light-table`
Controls actual lighting applied to actors. Each entry in the array corresponds to one time of day. Levels with no day/night cycle may have only a single entry.

Can technically be used for purposes beyond time of day.

| Field | Purpose |
|---|---|
| `direction` | Direction of the main light (e.g. sun direction) |
| `lgt-color` | Color of the main light (e.g. sun color) |
| `prt-color` | Unknown — not recalled |
| `amb-color` | Ambient color applied across the whole model |
| `shadow` | Direction of the shadow cast — separate from `direction` for unknown engine reasons |

---

### `levelname-mood-sun-table`
Controls the appearance of the sun and sky itself (iirc). Distinct from actor lighting.

---

### `levelname-mood-fog-table`
Controls distant fog — color and distance falloff.

---

## Open Questions / Unknowns
- ⚠ `prt-color` field purpose unknown.
- ⚠ Why `shadow` direction is separate from `direction` — likely an engine quirk, exact reason unclear.
- ⚠ Whether custom levels can define new mood table entries (vs only referencing existing ones) is untested.
- ⚠ `_GREENSUN` slot — relationship to sky type not fully confirmed.
- ⚠ `levelname-mood-sun-table` exact structure not yet documented.

---

## See Also
- `modding-addon.md` — known limitation re: sky/mood hardcoded to village1
- `jak1-level-design.md` — level geometry structure
