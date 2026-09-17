# v0.16.4: Test Results

**Date:** 2026-09-15
**Setup:** Blender 4.4.3, RTX 4090.
**Changes:** only `engine.py` and `__init__.py` (the new `_on_depsgraph_update` handler and the `_EDITED_WHILE_AWAY` set). v0.16.3 is backed up in the scratchpad (`backup_v0163_20260915_174605`).
**Test time:** about 80 s for the chain, plus a 20 s rerun with two new cases.

## Everything from v0.16.3 still holds

| check | v0.16.4 |
|---|---|
| Edits in Rendered view | 12/12 |
| Share cache | bounded (0 → 0) |
| Instance streaming | 150/150 in 1.3 s |
| Selection click, 150 instance meshes | 2.5 ms |
| Instanced mesh edit in Rendered | PASS |
| Azola cold entry | 6.69 s, 12.26M triangles, 268 unique meshes |
| Azola warm re-entry | 0.04 s |
| F12 Azola | 14.6 s, 382/382 |
| F12 generated | 1.2 s |
| Verify-all Azola | 393/394 (only `Cube.124`, the older material-colour issue from the v0.16.3 report) |

## ❌ Edits made in Solid view: fixed only if you wait 2 seconds

| edit made in Solid view | handler recorded | result |
|---|---|---|
| **immediately** after leaving Rendered (vertex move, paint, UV) | `[]` (nothing) | **0/6 FAIL** |
| **after waiting 2.5 s** (same edits) | `['EditDup', 'EditObj', 'mesh:VLR_T_EditMesh']` | **6/6 PASS** |
| instanced (scatter) mesh, after waiting 2.5 s | `[]` | **FAIL** (position off by 0.5) |

### Bug 1: the 2-second timestamp guard drops real edits

- **Cause:** `_on_depsgraph_update` returns early when `time.time() - _LAST_VIEW_UPDATE[0] < 2.0`. `_LAST_VIEW_UPDATE` is the time of the last *depsgraph update* the Rendered engine saw, not whether a Rendered viewport still exists.
- **Scenario:** you do anything in Rendered (move an object, tweak a value), switch to Solid, and edit within 2 seconds. That edit is never recorded, so it's lost on return to Rendered. The test hit this every time, because it edits right after leaving Rendered.
- **Fix:** replace the timestamp with a check of whether a Vertex-Lit Rendered viewport actually exists right now. Blender doesn't need to notify anyone for this: just look at the screens.

  ```python
  def _rendered_view_exists():
      if bpy.context.scene.render.engine != 'VERTEX_LIT':
          return False
      for win in bpy.context.window_manager.windows:
          for area in win.screen.areas:
              if area.type == 'VIEW_3D' and area.spaces.active.shading.type == 'RENDERED':
                  return True
      return False
  ```

  The handler skips only when this returns True. It's exact and self-correcting, with no stale state. Edits made in Solid viewport B while viewport A is Rendered reach engine A's `view_update`, so skipping is correct there too.

  The simpler alternative is to always record and accept an occasional redundant re-extract on the next re-entry. The set is bounded by object count, and it's cleared at every re-entry.

### Bug 2: instanced meshes edited while away are never refreshed

- **Cause 1:** the re-entry verify only marks names in `current`, which holds non-instance objects. The instance loop's skip (`cached_ok and not _force_full and name not in _dirty_objects`) never looks at `_EDITED_WHILE_AWAY`, so a cached `i:<mesh>` key is reused as-is.
- **Cause 2:** when the scatter's source objects aren't in the view layer (the common setup, and the test's), the depsgraph update doesn't name the source mesh, so the handler records nothing.
- **Scenario:** edit a scatter's source mesh in Solid view, then switch to Rendered, and every instance shows the old geometry.
- **Fix:**
  - in the instance loop, also treat `'mesh:' + mesh_name in _EDITED_WHILE_AWAY` (or the source object's name) as dirty;
  - in the handler, when an update is for an instancer (an object with `instance_type != 'NONE'`, or one carrying a Geometry Nodes modifier) or for a `Collection`, record a flag such as `'*instances*'`. On re-entry, the flag makes the instance loop hash its cached instance keys once. That costs about 0.3 s only when such an edit actually happened while away.

## Test additions (in `auto_test_v0161.py`)

- `away_tests(me, wait=...)` now runs twice: immediately and after 2.5 s. Before re-entry it logs what the handler recorded.
- The new `inst_away_test()` edits an instanced mesh in Solid view (after 2.5 s), re-enters Rendered, and compares the cached `i:` key with a fresh extraction.
