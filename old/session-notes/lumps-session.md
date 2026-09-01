# Lumps — Session Notes

**Branch:** `feature/lumps`
**Status:** Research done, implementation + testing next — on hold
**Last updated:** 2026-04-08

---

## Goal
Implement and test lump field support in the addon — allowing users to configure per-entity lump data from Blender custom properties, and have the exporter write correct JSONC lump blocks.

## What lumps are
Lumps are the key-value metadata blocks attached to entities in the JSONC level format. They drive nearly all per-entity behaviour: camera names, AABB bounds, nav-mesh radii, crate types, etc. The game reads them at entity birth via `res-lump-float`, `res-lump-struct`, etc.

## Known so far
- Lump fields are already used in the camera system (cam-name, bound-x/y/zmin/max)
- `nav-mesh-sphere` lump written as workaround for enemies without real navmesh
- `crate-type` lump written from `og_crate_type` custom property — not yet confirmed in-game
- `buzzer-info` lump for scout flies — behavior with `(game-task none)` unknown
- Eco pickup lumps untested — may need specific fields

## Research done
- See `knowledge-base/opengoal/modding-addon.md` for current lump usage
- See `knowledge-base/opengoal/jak1-level-design.md` for level entity structure
- Camera trigger lumps fully working (cam-name, bounds) — good reference implementation

## Remaining unknowns
- Full set of lump types and their expected value formats (float, string, vector, etc.)
- Which entity types require which lumps to function correctly
- Scout fly `buzzer-info` lump behavior
- Eco pickup required lumps
- Crate contents — confirm `crate-type` lump works in-game

## Implementation plan (when unblocked)
1. Audit all entity types in the addon for lump completeness
2. Confirm crate-type in-game
3. Test eco pickup lumps
4. Resolve buzzer-info behavior for scout flies
5. Expose remaining lump fields as Blender custom properties where missing

## Session log
- 2026-04-08: Branch already existed. Session notes created. Research phase complete, ready for implementation when unblocked.
