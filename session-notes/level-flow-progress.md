# Level Flow Feature — Session Notes
Last updated: April 2026

---

## Status: MERGED TO MAIN ✅
Commit: `6be87e3` on main

## Active Branch: `feature/level-flow` (for continued work)
Backup of pre-triggers main: `backups/opengoal_tools_pre_triggers_backup.py`

---

## What's In Main (current addon state)

### Continue-point system
- `SPAWN_` empties → continue-points in level-info.gc with real facing quat + camera data
- `CHECKPOINT_` empties → continue-points in level-info.gc + `checkpoint-trigger` actors in JSONC
- Spawn facing uses matrix conjugation: `game_rot = R_remap @ bl_rot @ R_remap^T`
- `_CAM` empties filtered everywhere (endswith guard)
- `SPAWN_<uid>_CAM` / `CHECKPOINT_<uid>_CAM` empties set camera-trans + camera-rot on respawn
- patch_level_info: bsphere auto-computed from spawn positions, bottom_height + vis_nick_override driven by scene props

### checkpoint-trigger GOAL type (in obs.gc)
```
(deftype checkpoint-trigger (process-drawable)
  ((cp-name   string  :offset-assert 176)
   (radius    float   :offset-assert 180)
   (triggered symbol  :offset-assert 184)
   (use-vol   symbol  :offset-assert 188)
   (xmin/xmax/ymin/ymax/zmin/zmax  float  :offset-assert 192-212))
  :heap-base #x70  :size-assert #xd8)
```
- Sphere mode (no VOL_ linked): polls distance vs radius lump
- AABB mode (VOL_ linked): polls 6 bound-* lumps from volume mesh
- One-shot: triggered flag latches, never re-fires
- Calls `(set-continue! *game-info* (-> self cp-name))`
- Born automatically via entity-actor.birth!

### Generic VOL_ trigger volume system
- All volumes are `VOL_N` (replaces old CAMVOL_/CPVOL_ split)
- Single `og_vol_link` prop links a volume to any target (camera, spawn, checkpoint)
- `og_vol_id` stores original number for name restore on unlink
- Volume renamed on link: `VOL_0` → `VOL_CAMERA_3` / `VOL_CHECKPOINT_cp0`
- Volume renamed on unlink: reverts to `VOL_<og_vol_id>`
- Export: `collect_cameras` + `collect_actors` both scan `og_vol_link`

### New operators (53 classes total, all registered)
- `OG_OT_SpawnVolume` — spawn VOL_N, auto-links if linkable target active
- `OG_OT_SpawnVolumeAutoLink` — spawn + link to explicit target (from panel buttons)
- `OG_OT_LinkVolume` — manual link: vol + target both selected, any order
- `OG_OT_UnlinkVolume` — unlink + restore name
- `OG_OT_CleanOrphanedLinks` — strip links whose targets were deleted
- `OG_OT_SelectAndFrame` — make active + `view3d.view_selected()`
- `OG_OT_DeleteObject` — delete + clean linked vols + delete _CAM/_ALIGN/_PIVOT
- `OG_OT_ReloadAddon` — hot-reload from disk via importlib.reload
- `OG_OT_CleanLevelFiles` — delete obs.gc/jsonc/glb/gd for clean rebuild
- `OG_OT_SpawnCheckpoint` — CHECKPOINT_ empty (yellow single-arrow)
- `OG_OT_SpawnCamAnchor` — _CAM empty linked to active spawn/CP

### Panels
- **Level Settings**: name, base ID, death plane, vis nick override
- **Level Flow (🗺)**: spawns + checkpoints, collapsible, view/delete per row, context buttons
- **Triggers (🔗)**: all VOL_ meshes, link status, link/unlink/view/delete, orphan cleanup
- **Camera (📷)**: camera list collapsible, view/delete per row, Add Volume auto-links

### Dev Tools
- 🔄 Reload Addon — hot-reload, clears sys.modules cache
- 🗑 Clean Level Files — deletes generated files for current level

### Orphan cleanup
- `_clean_orphaned_vol_links(scene)` runs at start of all 3 build pipelines
- Triggers panel shows orphaned links in red, cleanup button appears automatically

---

## Known Issues / Limitations

### :index 27 hardcoded in level-load-info
Pre-existing. Multiple custom levels share the same index. Only affects progress menu icon display, not gameplay. Would need a level registry to fix properly.

### CP sphere radius not editable from panel
`og_checkpoint_radius` is a custom prop (default 3.0m). Currently requires manual editing in Blender's object properties. Future work: add per-object float field to Level Flow panel, only when no VOL_ is linked.

### Spawn/checkpoint camera angle untested
Position confirmed correct. Camera rotation formula is consistent with confirmed-working camera-marker system but hasn't been verified against a known respawn result in-game.

### bpy.types.Operator base class
`OG_OT_ReloadAddon` originally used `bpy.types.Operator` as base — caused load failure. Fixed to use imported `Operator`. Always use the imported name.

---

## CRITICAL DEV RULES

### str_replace class header eating (happened 5+ times)
**NEVER use a class header as the boundary of a str_replace.**
The class header of the NEXT class must appear in BOTH old_str AND new_str.
When inserting before a class, anchor inside the preceding class body.

### Mandatory integrity check after every edit
```python
import ast
from collections import Counter
src = open('addons/opengoal_tools.py').read()
tree = ast.parse(src)
top = {n.name: n.lineno for n in tree.body if isinstance(n, ast.ClassDef)}
ct = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'classes' for t in n.targets))
tn = [n.id for n in ast.walk(ct.value) if isinstance(n, ast.Name)]
dups = {k:v for k,v in Counter(n.name for n in tree.body if isinstance(n, ast.ClassDef)).items() if v > 1}
miss = [n for n in tn if n not in top]
nest = [f'{c.name}←{p.name}' for p in tree.body if isinstance(p, ast.ClassDef) for c in ast.walk(p) if c is not p and isinstance(c, ast.ClassDef)]
assert not dups, f'DUPLICATES: {dups}'
assert not miss, f'UNDEFINED IN TUPLE: {miss}'
assert not nest, f'NESTED: {nest}'
print(f'OK — {len(top)} classes, {len(tn)} in tuple')
```

### Scratch file workflow
- Always work in `scratch/opengoal_tools_triggers_wip.py` for large features
- Run integrity check on scratch before copying to `addons/`
- Duplicate classes accumulate in scratch — run dedup check before committing

---

## Future Work

### CP sphere radius UI
Add per-object float field in Level Flow panel reading `o["og_checkpoint_radius"]`.
Only show when no VOL_ is linked (AABB mode ignores radius).

### Load boundary export
Draw boundary polygon in Blender → XZ points + top/bot → append to load-boundary-data.gc.
Research needed: safe append pattern, avoid breaking vanilla boundaries.

### continue-name lump UI
Add `continue-name` property picker to Place Objects panel for `launcherdoor` / `jungle-elevator`.

### VOL_ volume improvements
- Multiple volumes per target (e.g. two trigger zones for one camera)
- Volume shape options beyond AABB cube
