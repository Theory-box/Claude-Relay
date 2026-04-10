# Feature: Lump System — Session Notes
Last updated: April 2026

---

## Status: Research complete. Branch set up. Ready for design discussion.

---

## Branch: `feature/lumps`

Addon: `addons/opengoal_tools.py` — copied from main (v1.2.0, 8726 lines) as of this session.
Previous branch addon was ~5250 lines (old). Now up to date.

---

## What We Did This Session

1. Cloned repo, read CLAUDE-SKILLS.md and session notes
2. Read full knowledge-base/opengoal/lump-system.md (721 lines)
3. Surveyed current addon structure:
   - `collect_actors()` at line 3164 — builds lump dicts from ACTOR_ empties
   - `_draw_selected_actor()` at line 7205 — actor UI in the Selected Object panel
   - All UI panels catalogued (OG_PT_Level, OG_PT_Spawn, OG_PT_SelectedObject, etc.)
4. Copied main addon to feature/lumps and pushed

## Current lump handling in the addon

The addon already builds lumps for actors — but all lump values are HARDCODED.
There is no way for users to set arbitrary lump values from Blender.

Currently supported (hardcoded per-etype):
- `name` — always set
- `eco-info` / `cell-info` / `buzzer-info` — fuel-cell, buzzer, crate, money
- `crate-type` — crate only
- `nav-mesh-sphere` — nav-unsafe enemies (auto)
- `path` / `pathb` — from waypoint empties
- `sync` — platforms (og_sync_period, og_sync_phase, og_sync_ease_out, og_sync_ease_in)
- `options` (wrap-phase bit) — sync platforms
- `notice-dist` — plat-eco (og_notice_dist)
- `idle-distance` — all enemies (og_idle_distance)
- `vis-dist` — all enemies (hardcoded 200m)

og_ properties currently on actors:
- og_crate_type
- og_nav_radius
- og_sync_period, og_sync_phase, og_sync_ease_out, og_sync_ease_in, og_sync_wrap
- og_notice_dist
- og_idle_distance
- og_navmesh_link

## What Lump Data Is

87 unique lump keys documented in knowledge-base/opengoal/lump-system.md.
18 valid JSONC type strings.
Lumps are per-actor config data: behavior flags, spawn tables, path params, distances, modes, etc.

Key points for UI design:
- Different actors read completely different lump keys
- Most keys are only relevant to 1-3 actor types
- Unknown keys are silently ignored by the engine (safe to add extras)
- Some keys are universal (vis-dist, name, options, shadow-mask, light-index)
- Values are typed: floats, ints, vectors, symbols, enums, bitfields

## Design Discussion Needed

See scratch/lump-design-discussion.md (to be written) for full breakdown.

High-level options:
1. og_lump_* passthrough — user adds custom props with prefix, addon reads & injects
2. Well-known lump sub-panel — actor-type-aware UI for the common lumps
3. Freeform lump list UI — a "Custom Lumps" section with key/type/value rows
4. Auto-generation helpers — path-k, etc.

Decision pending on: which approach first, how they layer, how to surface discoverability.

---

## Previous Research

### Knowledge Base Location
`knowledge-base/opengoal/lump-system.md`

Contains:
- How lump storage works internally
- Full JSONC type string reference (all 18 types)
- Every lump key documented with type, actor, JSONC format, defaults
- Full actor-to-lump quick reference table

### Key Findings (from previous session)
- Lump system is completely open — any key is safe to add
- Bare string lumps: starts with ' → ResSymbol; otherwise → ResString
- puffer distance lump is INTERNAL UNITS, not meters
- path-k spline knots: formula [0,0,0,0, 0,1,...,N-1, N-1,N-1,N-1,N-1]
- sync lump: period in seconds (×300 for frames)
- battlecontroller is the most complex actor (up to 8 spawner groups)

---

## Files

- `knowledge-base/opengoal/lump-system.md` — full lump reference (DO NOT overwrite without approval)
- `addons/opengoal_tools.py` — working addon on this branch
- `scratch/lump-design-discussion.md` — design notes (to be created)


---

## Design Direction (settled)

### Lump panel purpose
- Custom Lumps panel = power user escape hatch + learning tool for how lumps work
- Not the primary way to configure actors — that's the dedicated per-type UI
- Long term: every lump an actor reads gets its own proper context-aware field/panel/tool in the addon
- Lump panel stays for: custom/exotic lumps, overrides, experimentation

### Long term goal
Eventually every meaningful lump for every actor type becomes a proper UI element
(like idle-distance, sync, notice-dist already are). Lump panel is the fallback
for anything not yet promoted to first-class UI.

---

## TODO: Unsupported Actors

Need to audit ALL actor types in the OpenGOAL source and find everything
not currently in ENTITY_DEFS. Document them with:
- etype name
- source file
- what lumps they read
- complexity to add

Known missing so far:
- keg / keg-conveyor  (misty-conveyor.gc) — uses path-k spline, complex
- barrel              (beach level — need to verify etype name)
- Many others likely missing — full audit needed

Suggested location for the full list: knowledge-base/opengoal/unsupported-actors.md
(propose content in chat before writing, per kb rules)
