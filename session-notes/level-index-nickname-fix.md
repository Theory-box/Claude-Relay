# Level Index + Nickname Fix — Session Notes

**Branch:** `fix/level-index-nickname`
**Status:** Implemented, awaiting user test in Blender
**Last updated:** 2026-04-23

---

## Problems addressed
1. **Level index hardcoded to 27.** Every level created with the addon wrote `:index 27` into its `level-load-info` block, so multi-level blends exported with colliding indices.
2. **Nicknames could collide.** `og_vis_nick_override` existed as a property but was not surfaced at level creation time. The default auto-generated 3-letter nick (`_nick(name)` = first 3 chars, dashes stripped) would collide whenever two level names shared a prefix (e.g. `training-a` and `training-b` both → `tra`).

## Approach
- Added `og_level_index` as a level-collection custom property, mirrored by an `IntProperty` on `OGProperties`.
- Added collision helpers in `collections.py` that iterate `_all_level_collections(scene)` and reject or auto-suggest values.
- Surfaced both index + vis_nick in the Create, Assign, and Edit dialogs.
- Added lazy migration: old levels missing `og_level_index` get a unique value assigned on first export or on first Edit-Level open.

## Files changed
- `addons/opengoal_tools/collections.py` — added `og_level_index` to `_LEVEL_COL_DEFAULTS` + `_LEVEL_PROP_KEY_MAP`; added helpers: `_next_free_level_index`, `_level_index_in_use`, `_resolve_vis_nick`, `_vis_nick_in_use`, `_suggest_unique_vis_nick`, `_ensure_level_index`, `_migrate_all_level_indices`.
- `addons/opengoal_tools/properties.py` — added `level_index: IntProperty(default=100, min=1, max=10000)` next to `base_id`.
- `addons/opengoal_tools/operators.py` — `OG_OT_CreateLevel`, `OG_OT_AssignCollectionAsLevel`, `OG_OT_EditLevel` all now take `level_index` + `vis_nick`, auto-populate on invoke, and reject collisions on execute.
- `addons/opengoal_tools/export.py` — `patch_level_info` now reads `og_level_index` (replaces hardcoded 27); calls `_migrate_all_level_indices(scene)` on the scene before reading to cover pre-fix blends.
- `addons/opengoal_tools/panels.py` — active-level info label now shows `Idx: N` and the effective nick (override or auto).

## Design choices
- **Starting index = 100.** Docs (`knowledge-base/opengoal/player-loading-and-continues.md`) advise avoiding vanilla range and use 99 as an example. 100+ is safe.
- **Collision behaviour = reject, not auto-resolve.** Operators raise a user-visible error if the dialog's chosen index/nick is already used. Auto-suggestion happens on `invoke`, so a fresh dialog always starts from a free value.
- **Nick suggestion.** `_suggest_unique_vis_nick` tries `_nick(name)` first, then appends a digit 0-9 to differentiate if that's taken.
- **Lazy migration, not big-bang.** `_migrate_all_level_indices` walks every level and fills in missing `og_level_index` values using `_next_free_level_index`. Called from export and Edit-Level invoke. Safe to call repeatedly.
- **Dialog field length.** `vis_nick` is a freeform `StringProperty`; execute rejects anything over 3 chars. Considered using a fixed-width 3-char input but Blender doesn't have one cleanly.

## Verification done
- All five modified files pass `py_compile` and `ast.parse`.
- Logic hand-traced against Create → Assign → Edit flows.

## Verification NOT done (user to test)
- Blender registration: no errors on addon reload (the new `IntProperty` on `OGProperties` is the main risk — if Blender complains about a schema change, the user may need to disable/re-enable the addon).
- Multi-level blend export: two levels side-by-side should now emit distinct `:index` values and distinct `:nickname` values.
- Old single-level blends: open, export, confirm `:index` is no longer 27 (should be 100 after migration).
- Edit Level dialog: shows correct existing values, rejects obvious collisions, accepts valid edits.

## If the test passes
User will say "merge to main". Then:
```
git checkout main && git merge fix/level-index-nickname && git push origin main
git branch -d fix/level-index-nickname
git push origin --delete fix/level-index-nickname
```

## If the test fails
Describe the failure; most likely issue would be a registration error from `properties.py` or a collection-property type mismatch. The `level_index` IntProperty on `OGProperties` is scene-scoped and mostly acts as a fallback for `_get_level_prop` — the authoritative storage is still the collection custom-property `og_level_index`.

## Return to refactor
After this fix lands, return to:
- Inheritance refactor for `LUMP_REFERENCE` (discussed in chat, not yet in a session-notes file — create one when work begins).
- Consider splitting `data.py` into `data/entities.py`, `data/lumps.py`, `data/pat.py`, `data/actor_links.py`, `data/wiki.py` either during or immediately after the inheritance work.

## Open question from the user's initial prompt
User also asked about splitting the database into categories. Short answer given in chat: yes, do it with the inheritance work or immediately after, split by domain not by entity-type. Not started.
