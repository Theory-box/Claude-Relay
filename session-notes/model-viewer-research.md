# Model Viewer + Texture Browser — Research Notes
Last updated: April 12, 2026
Branch: `feature/model-viewer`
Status: Research complete. Ready for implementation.

---

## PART 1: ENEMY MODEL PREVIEW

### 1A. Where the GLBs Actually Live

**Confirmed from jak-project source** (`fr3_to_gltf.cpp`, `extract_level.cpp`):

```
decompiler_out/jak1/levels/<level_name>/<merc_ctrl_name>.glb
```

**NOT** a flat `glb_out/` folder. Each enemy's GLB is nested inside its source level's subfolder.

The `<merc_ctrl_name>` is the **lod0-mg element name without the `-mg` suffix**:
- `babak-ag` → `decompiler_out/jak1/levels/beach/babak-lod0-mg.glb`
- `kermit-ag` → `decompiler_out/jak1/levels/swamp/kermit-lod0-mg.glb`
- `hopper-ag` → `decompiler_out/jak1/levels/jungle/hopper-lod0-mg.glb`

This is derived from `MercCtrl::name` which comes directly from the GOAL `merc-ctrl` object's name string.

### 1B. Complete etype → GLB path mapping

| etype | GLB path (relative to decompiler_out/jak1/) |
|---|---|
| babak | levels/beach/babak-lod0-mg.glb |
| lurkercrab | levels/beach/lurkercrab-lod0-mg.glb |
| lurkerpuppy | levels/beach/lurkerpuppy-lod0-mg.glb |
| lurkerworm | levels/beach/lurkerworm-lod0-mg.glb |
| hopper | levels/jungle/hopper-lod0-mg.glb |
| junglesnake | levels/jungle/junglesnake-lod0-mg.glb |
| swamp-rat | levels/swamp/swamp-rat-lod0-mg.glb |
| kermit | levels/swamp/kermit-lod0-mg.glb |
| swamp-bat | levels/swamp/swamp-bat-lod0-mg.glb |
| snow-bunny | levels/snow/snow-bunny-lod0-mg.glb |
| ice-cube | levels/snow/ice-cube-lod0-mg.glb |
| yeti | levels/snow/yeti-lod0-mg.glb |
| lightning-mole | levels/rolling/lightning-mole-lod0-mg.glb |
| double-lurker | levels/sunken/double-lurker-lod0-mg.glb |
| bully | levels/sunken/bully-lod0-mg.glb |
| puffer | levels/sunken/puffer-main-lod0-mg.glb |
| bonelurker | levels/misty/bonelurker-lod0-mg.glb |
| muse | levels/misty/muse-lod0-mg.glb |
| quicksandlurker | levels/misty/quicksandlurker-lod0-mg.glb |
| robber | levels/misty/robber-lod0-mg.glb |
| baby-spider | levels/maincave/baby-spider-lod0-mg.glb |
| mother-spider | levels/maincave/mother-spider-lod0-mg.glb |
| gnawer | levels/maincave/gnawer-lod0-mg.glb |
| dark-crystal | levels/maincave/dark-crystal-lod0-mg.glb |
| driller-lurker | levels/maincave/driller-lurker-lod0-mg.glb |
| cavecrusher | levels/robocave/cavecrusher-lod0-mg.glb |
| flying-lurker | levels/ogre/flying-lurker-lod0-mg.glb |
| plunger-lurker | levels/ogre/plunger-lurker-lod0-mg.glb |
| green-eco-lurker | levels/finalboss/green-eco-lurker-lod0-mg.glb |
| aphid | levels/finalboss/aphid-lurker-lod0-mg.glb |
| ram | levels/village1/ram-lod0-mg.glb |

**Add to ENTITY_DEFS:** A `"glb"` field with path relative to `decompiler_out/jak1/` for each enemy. Do NOT derive from ag name — the mapping is not mechanical.

### 1C. rip_levels flag — disabled by default

Source confirms: `"rip_levels": false` in `jak1_config.jsonc`.

Users need to set this to `true` and re-run the extractor before GLBs exist. Same pattern as `save_texture_pngs`. Both features should share a single "assets not extracted" warning + extraction button.

**Detection:** Check if `decompiler_out/jak1/levels/beach/babak-lod0-mg.glb` exists. If it doesn't, none of them do. Show warning.

### 1D. GLB internals — what's inside

Confirmed from source (`fr3_to_gltf.cpp`):
- **Textures are EMBEDDED** (`embedImages: true`) — no external PNG dependency
- **Armature/skeleton is included** — each GLB has a skin + joint hierarchy
- **Multiple LOD meshes** per art group (lod0, lod1, lod2, shadow) — each is a **separate GLB file**
- **Only lod0 is written once per model** (the decompiler writes one GLB per merc-ctrl)
- Vertices pre-scaled by `/ 4096.0` so 1 Blender unit = 1 game meter ✓

### 1E. Blender import implementation

**Context issue:** `bpy.ops.import_scene.gltf` requires a VIEW_3D area in context.
```python
# Pattern to use:
for area in bpy.context.screen.areas:
    if area.type == 'VIEW_3D':
        with ctx.temp_override(area=area, region=area.regions[-1]):
            bpy.ops.import_scene.gltf(filepath=str(glb_path))
        break
```

**Post-import cleanup pattern:**
```python
before = set(bpy.data.objects)
# ... import ...
after = set(bpy.data.objects)
new_objs = after - before

# Move entire group to cursor location
for obj in new_objs:
    if obj.parent is None:  # root objects only
        obj.location = cursor_loc

# Tag all new objects
for obj in new_objs:
    obj["og_preview_mesh"] = True

# Parent armature (root) to ACTOR empty
# Do NOT re-parent mesh — it needs the armature modifier for correct shape
for obj in new_objs:
    if obj.parent is None and obj.type == 'ARMATURE':
        obj.parent = actor_empty
```

**Linked duplicate for multiple instances:**
```python
# Check if mesh data already loaded
mesh_name = f"{glb_name}"  # e.g. "babak-lod0-mg"
existing = next((o for o in bpy.data.objects if o.get("og_preview_mesh") and 
                 mesh_name in o.name.split('.')[0]), None)
if existing:
    # Re-use existing data — just create a linked copy
    new_obj = existing.copy()
    new_obj.location = cursor_loc
    bpy.context.collection.objects.link(new_obj)
else:
    # Full import
    ...
```

### 1F. Export safety — CONFIRMED SAFE

**Inspected `export_glb()` in `export.py`:**
- In collection mode (normal use): only exports objects inside the `Geometry` sub-collection
- Preview meshes will be placed in the enemy's sub-collection (e.g. `Enemies/Beach/`)
- The Geometry collection only contains actual level geometry
- **Preview meshes will NOT be in Geometry** → safe by default
- The fallback (`use_selection=False`) WOULD export everything — but this only triggers when no level collection exists (old projects). Tag `og_preview_mesh=True` anyway as belt-and-suspenders: filter them out at export even in fallback mode.

**Fix needed in export fallback path:** Filter objects tagged `og_preview_mesh=True` from the fallback export list.

---

## PART 2: SPECIAL CASES IN ENTITY_DEFS

These enemies have non-standard art group structures. The `glb` field in ENTITY_DEFS must be explicit, not derived:

### Puffer — two body forms
`puffer-ag` has `puffer-main-lod0-mg` (default) AND `puffer-mean-lod0-mg` (puffed state).
→ `glb: "levels/sunken/puffer-main-lod0-mg.glb"`

### Double Lurker — two art groups
`double-lurker-ag` (bottom) + `double-lurker-top-ag` (rider on top).
→ `glb: ["levels/sunken/double-lurker-lod0-mg.glb", "levels/sunken/double-lurker-top-lod0-mg.glb"]`
Import both, parent both armatures to same ACTOR empty.

### Gnawer — sub-mesh
`gnawer-segment-lod0-mg.glb` exists alongside `gnawer-lod0-mg.glb`.
→ `glb: "levels/maincave/gnawer-lod0-mg.glb"` (ignore segment)

### Mother Spider — sub-mesh
`mother-spider-leg-lod0-mg.glb` alongside `mother-spider-lod0-mg.glb`.
→ `glb: "levels/maincave/mother-spider-lod0-mg.glb"` (ignore leg)

### Bully — broken cage sub-mesh
`bully-broken-cage-lod0-mg.glb` alongside `bully-lod0-mg.glb`.
→ `glb: "levels/sunken/bully-lod0-mg.glb"` (ignore broken-cage)

### Dark Crystal + Ice Cube — explode/break variants
These are separate art groups (`dark-crystal-explode-ag`, `ice-cube-break-ag`).
→ Use only the base model GLB, ignore variants.

---

## PART 3: TEXTURE BROWSER

No major changes from `session-notes/texturing-progress.md` research. Key updates:

- **PNG path**: `decompiler_out/jak1/textures/<tpage_name>/<tex_name>.png`
- **Independent** of model preview — GLBs embed their textures, PNGs are separate
- `save_texture_pngs` and `rip_levels` are separate flags — user may have one but not the other
- **Shared extraction button**: One operator that sets BOTH flags and re-runs the extractor

### Extraction operator:
```python
class OG_OT_ExtractAssets(Operator):
    """Sets rip_levels=true AND save_texture_pngs=true, then runs extractor"""
    bl_idname = "og.extract_assets"
    # 1. Find jak1_config.jsonc
    # 2. Set both flags to true
    # 3. Run extractor executable
```

---

## PART 4: SCALE VERIFICATION

From `fr3_to_gltf.cpp` line 156:
```cpp
float xyz[3] = {vtx.pos[0] / 4096.f, vtx.pos[1] / 4096.f, vtx.pos[2] / 4096.f};
```

And `bsphere` comment in `Tfrag3Data.h`:
```cpp
math::Vector<float, 4> bsphere;  // the bounding sphere, in meters (4096 = 1 game meter)
```

**Confirmed: GLBs are in meters. No scale correction needed in Blender.**

---

## PART 5: IMPLEMENTATION RISKS BY PRIORITY

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| 1 | GLB path wrong (level subfolder not flat) | **CRITICAL** | Use explicit per-enemy path table in ENTITY_DEFS |
| 2 | Export fallback includes preview meshes | **HIGH** | Filter `og_preview_mesh` in fallback export path |
| 3 | bpy.ops.import_scene.gltf needs VIEW_3D context | **HIGH** | Always use `temp_override` with first VIEW_3D area |
| 4 | Active collection wrong during import | **MEDIUM** | Override active collection before import, restore after |
| 5 | Armature re-parenting breaks skinning | **MEDIUM** | Parent armature root to ACTOR empty, don't touch mesh-to-armature link |
| 6 | Model rotation after import (Y-up vs Z-up) | **MEDIUM** | Test on real GLB. If rotated, apply rotation on armature root. |
| 7 | Blender name collision on duplicate spawn | **LOW** | Use `obj.name.split('.')[0]` for mesh identity checks |
| 8 | Memory waste from duplicate imports | **LOW** | Check bpy.data.objects for existing og_preview_mesh of same model |
| 9 | rip_levels=false — no GLBs exist | **HANDLED** | Existence check + warning + extraction button |
| 10 | puffer/double-lurker special cases | **LOW** | Explicit glb field in ENTITY_DEFS handles it |

---

## PART 6: EXTRACTION BUTTON IMPLEMENTATION

Both features (textures + models) need the decompiler re-run. The `jak1_config.jsonc` path:
```
<data_path>/data/decompiler/config/jak1/jak1_config.jsonc
```

The extractor binary (already known):
```
<exe_path>/extractor[.exe] <iso_path>
```

The ISO path is unknown to the addon — user needs to have it accessible. We may need a 3rd path preference `iso_path`. OR: the extractor reads the ISO path from its own config — need to verify.

**Open question:** Does `extractor.exe` take the ISO path as CLI arg, or read it from a config file? This was marked as unknown in `texturing-progress.md` — still unresolved. Need a real install to check.

---

## PART 7: NEW FIELDS NEEDED IN ENTITY_DEFS

```python
"babak": {
    ...,  # existing fields
    "glb": "levels/beach/babak-lod0-mg.glb",    # NEW: path from decompiler_out/jak1/
    "glb_level": "beach",                          # NEW: which level to check for extraction
}
```

For double-lurker (list of GLBs):
```python
"double-lurker": {
    ...,
    "glb": ["levels/sunken/double-lurker-lod0-mg.glb",
            "levels/sunken/double-lurker-top-lod0-mg.glb"],
    "glb_level": "sunken",
}
```

---

## NEXT STEPS (implementation order)

1. Add `glb` field to all enemy ENTITY_DEFS entries
2. Create `model_preview.py` module with:
   - `_glb_path(etype)` — path construction from prefs + ENTITY_DEFS
   - `_models_available()` — checks if rip_levels was run
   - `import_enemy_preview(etype, cursor_loc, actor_empty)` — full import flow
   - `remove_preview(actor_empty)` — removes og_preview_mesh children
3. Modify `OG_OT_SpawnEntity.execute()` — after placing empty, call `import_enemy_preview`
4. Add panel toggle: `og_props.show_preview_models: BoolProperty` (default True)
5. Fix export fallback in `export.py` to filter `og_preview_mesh`
6. Create combined `OG_OT_ExtractAssets` operator for both textures + models
7. Merge `feature/texturing` research into this branch

## FILES

- `addons/opengoal_tools/model_preview.py` — new module (to create)
- `addons/opengoal_tools/data.py` — add `glb` field to ENTITY_DEFS
- `addons/opengoal_tools/operators.py` — modify spawn operator
- `addons/opengoal_tools/export.py` — fix fallback export filter
- `session-notes/model-viewer-research.md` — this file

---

## PART 8: NO-ARMATURE APPROACH (final decision)

### What Blender sees when it imports the GLB

From source inspection, each GLB contains:
- **One mesh node** (e.g. `babak-lod0-mg`) with the full geometry
  - Multiple primitives (one per texture draw call, e.g. body/belt/eyes)
  - Each primitive has its own PBR material with `baseColorTexture` pointing to embedded PNG
  - `baseColorFactor = {2.0, 2.0, 2.0, 2.0}` (PS2 blending compensation)
  - `POSITION`, `TEXCOORD_0`, `COLOR_0`, `JOINTS_0`, `WEIGHTS_0` attributes
- **One skin** (the armature) with N bone nodes
- The mesh node has `node.skin` set — it's a skinned mesh

On import, Blender creates:
1. An `Armature` object (with all bones in bind pose)
2. A `Mesh` object parented to the armature, with Armature modifier
3. The mesh lands at world origin in bind/rest pose

### Simplified import strategy — just the mesh

Since we only want a static visual stand-in, we don't want the armature at all. Options:

**Option A — Import then strip armature (safe, simple):**
```python
before = set(bpy.data.objects)
# import...
new_objs = set(bpy.data.objects) - before

mesh_obj = next((o for o in new_objs if o.type == 'MESH'), None)
arm_obj  = next((o for o in new_objs if o.type == 'ARMATURE'), None)

if mesh_obj and arm_obj:
    # Unparent mesh from armature, keep world transform
    bpy.ops.object.select_all(action='DESELECT')
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_obj
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    
    # Remove armature modifier from mesh
    for mod in list(mesh_obj.modifiers):
        if mod.type == 'ARMATURE':
            mesh_obj.modifiers.remove(mod)
    
    # Delete the armature object
    bpy.data.objects.remove(arm_obj, do_unlink=True)
```

**Option B — Use `import_scene.gltf` with `import_pack_images=True` + no_import_animations:**
The gltf importer has flags but no "skip armature" flag — armature is always created for skinned meshes. Option A is the only way.

**After stripping:**
- Mesh object is free-standing, positioned at world origin (bind pose)
- Materials intact with embedded textures as Blender Image nodes
- Move mesh to cursor: `mesh_obj.location = cursor_location`
- Parent to ACTOR empty: `mesh_obj.parent = actor_empty; mesh_obj.matrix_parent_inverse = actor_empty.matrix_world.inverted()`
- Tag: `mesh_obj["og_preview_mesh"] = True`

### Mesh bind-pose position

The model will be in its **bind/rest pose** (T-pose or standing idle). For a Blender viewport stand-in this is exactly what we want — a static recognisable silhouette.

The bind pose root bone is typically at world origin with the model standing upright. After `/4096` scaling the model should be ~1–2m tall, standing on Z=0. This may need a small Z offset depending on model origin — but testing will confirm.

### Linked data for duplicate spawns

When spawning a second babak, re-use mesh data instead of re-importing:
```python
existing_mesh = bpy.data.meshes.get("babak-lod0-mg")  # or with .001 suffix check
if existing_mesh:
    new_obj = bpy.data.objects.new("babak-lod0-mg", existing_mesh)
    bpy.context.collection.objects.link(new_obj)
    new_obj.location = cursor_loc
    new_obj.parent = actor_empty
    new_obj["og_preview_mesh"] = True
else:
    # full import + strip
```

This is O(1) memory for N spawns of the same type.

### Material note — baseColorFactor = 2.0

The decompiler sets `baseColorFactor = {2.0, 2.0, 2.0, 2.0}` to compensate for PS2 blending. In Blender's Eevee/Cycles this means materials render brighter than the texture alone — colours will look washed out/bright. This is expected and intentional for the PS2 look. For a viewport stand-in it's fine. No adjustment needed.


---

## PART 9: Implementation Complete

Branch: `feature/model-viewer` — commit `f1255f4`

### Files changed
- `model_preview.py` — new module (249 lines)
- `data.py` — `glb` field on all 37 ENTITY_DEFS entries
- `operators.py` — spawn hook + `OG_OT_ClearPreviews`
- `panels.py` — preview toggle + warning in Enemies panel
- `export.py` — fallback export filters `og_preview_mesh`
- `properties.py` — `preview_models` BoolProperty
- `__init__.py` — registers `OG_OT_ClearPreviews`

### Known unknowns (need real install to verify)
1. Bind-pose model origin — does babak stand at Z=0 (feet), Z=1 (center), or somewhere else? May need per-enemy Z offset.
2. Model rotation after import — GLTF Y-up → Blender Z-up conversion should be handled by the importer, but if models come in rotated 90° we add a `mesh_obj.rotation_euler = (math.radians(90), 0, 0)` after import.
3. `rip_levels` GLB subfolder name — confirmed from source as `levels/<level_name>/` but `<level_name>` is the BSP name not the DGO filename. The mapping in the `glb` field was derived from known level names — may need tweaking for one or two entries.

