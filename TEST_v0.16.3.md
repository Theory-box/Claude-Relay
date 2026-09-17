# v0.16.3: Test Results

**Date:** 2026-09-15
**Setup:** Blender 4.4.3, RTX 4090.
**Changes:** only `engine.py` and `__init__.py`; v0.16.2 is backed up in the scratchpad (`backup_v0162_20260915_173248`).
**Test time:** about 2 min for the main chain, plus one 10 s run against v0.16.2 as a positive control.

**New checks this round:**
- `memo_collide.py` (`-b`): can the `id(mesh)` memo hand one mesh another mesh's signature?
- **EDIT WHILE AWAY:** edit in Solid view, then switch back to Rendered.
- **INSTANCED MESH EDIT:** edit the mesh behind a collection instance while in Rendered view.
- `VLR_VERIFY_ALL=1` in the entry test: every cached Azola object is compared with a fresh extraction.

## Targets

| target | v0.16.2 | **v0.16.3** | |
|---|---|---|---|
| Azola cold entry, near 5.86 s | 10.77 s | **6.65 s** | ✅ (+0.8 s; `_geo_sig` 0.84 s) |
| Triangles in GPU memory, 12.3M (not 18.5M) | 18.52M / 355 unique meshes | **12.26M / 268** | ✅ sharing restored |
| Warm re-entry, near 0.05 s | 0.87 s | **0.05 s** | ✅ |
| Selection click with 150 instance meshes, near 3 ms | 45 ms | **2.5 ms** (0 `_geo_sig` calls) | ✅ |
| Edits in Rendered view | 12/12 | **12/12** | ✅ |
| Share cache bounded | 1 → 1 | **0 → 0** (cleared when the queue drains) | ✅ |
| Instance streaming | 150/150 in 5.1 s | **150/150 in 1.3 s** | ✅ |
| Instanced mesh edit (new check) | – | **PASS** | ✅ the new skip still sees real edits |
| F12, generated scene | 4.5 s | **1.2 s** | ✅ |
| F12, Azola | 28.6 s, 382/382 | **14.8 s, 382/382**, 287 extractions | ✅ |
| `id(mesh)` memo collisions | – | **0 wrong / 300** (300 distinct ids, both loop patterns) | ✅ |
| **Edit while away (new check)** | **6/6** | **0/6** | ❌ **regression** |
| Verify-all, Azola (new check) | – | 393/394 identical; `Cube.124` colours differ | see below |

## ❌ Regression: edits made outside Rendered view are lost on re-entry

**Test:** switch to Solid, make an edit, switch back to Rendered, and compare the engine's cache with a fresh extraction. Each case runs on EditObj and its linked duplicate.

| edit made in Solid | v0.16.2 | v0.16.3 |
|---|---|---|
| move one interior vertex | PASS | FAIL (position off by 0.3) |
| vertex paint | PASS | FAIL (colour off by 1.0) |
| UV edit | PASS | FAIL (UV off by 0.05) |

- **Cause:** the new re-entry verify only compares `(mesh name, vertex count, polygon count, modifiers)`. The notes assumed that *"anything edited while we were away also arrives through view_update"*, but it doesn't. Blender frees the viewport's RenderEngine when the view leaves Rendered, so no engine exists to receive those updates. The new engine starts from the module-level `_PERSIST_*` caches and never hears about the edit.
- **Scenario:** a user paints vertex colours, sculpts, or moves vertices in Solid or Material Preview, then switches to Rendered. The engine shows the pre-edit mesh, until the object is edited again.
- **Fix:** record what changed while no engine was listening, so re-entry only re-checks those objects:
  - add a `bpy.app.handlers.depsgraph_update_post` handler that runs even while nothing is in Rendered;
  - it appends `update.id.original.name` for geometry updates (`update.is_updated_geometry`) to a module-level `_CHANGED_WHILE_AWAY` set;
  - `_needs_verify` marks exactly those names dirty and clears the set.

  That keeps re-entry at 0.05 s and is correct. Falling back to v0.16.2's full hash would also be correct, but costs 0.87 s per re-entry on Azola.

## Cube.124 colour mismatch: pre-existing, not a v0.16.3 regression [likely]

- **What it is:** `Cube.124` has a Geometry Nodes modifier, and its evaluated mesh has **no colour attributes**. For such meshes the extractor fills the slot's vertex colours with a flat copy of the material's `diffuse_color`, taken at extraction time (`engine.py:636-639`). The fresh extraction's colour (0.8 grey, alpha 1) is material `Trim 02`'s current viewport display colour.
- **Why this is the explanation:** a read-only `-b` check extracted it 3 times after re-evaluations and got identical colours, so the geometry and extraction are deterministic. The cached copy therefore holds an older `diffuse_color`. That value changed in the GUI session after the object was extracted; I didn't identify what changed it.
- **The general problem:** slot colours are baked from material state at extraction, and nothing re-extracts an object when a material changes. Changing a material's Viewport Display colour leaves already-loaded objects showing the old tint until they're re-extracted. This is the review's "material state captured at extraction" item (L4/L5), and it's the same in every version since the flat-colour fallback existed.
- **Fix direction:** don't bake the material colour into the vertex buffer. Pass it as a per-slot uniform at draw time (the slot already stores `material_name`), so the vertex colour buffer only carries real attribute colours.

## Bottom line

v0.16.3 meets every performance target the notes set:

| target | v0.16.3 |
|---|---|
| entry | 6.65 s |
| triangles in GPU memory | 12.26M |
| re-entry | 0.05 s |
| clicks | 2.5 ms |
| F12 | 14.8 s |

It keeps all earlier fixes: edits 12/12, 150/150 instances, bounded cache, F12 drains. The memo is safe in practice.

**One regression, which should be fixed before release:** edits made in Solid or Material Preview are lost when switching back to Rendered. The re-entry pre-check relies on `view_update`, and no engine exists to receive it while the view isn't in Rendered. Record geometry updates in an app-level `depsgraph_update_post` handler and re-check only those names. A positive control is available: v0.16.2 passes this exact test 6/6, so the test is valid.

Re-run: `auto_test_v0161.py` (it now includes EDIT WHILE AWAY and INSTANCED MESH EDIT) and `auto_bench_entry.py` with `VLR_VERIFY_ALL=1`.
