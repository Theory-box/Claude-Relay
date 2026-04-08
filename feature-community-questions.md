# Community Questions — Jak 1 Addon

Collected for future documentation / FAQ coverage.
Source: community feedback on the addon.

---

## Q1 — Custom Actors & Custom Lumps

> "How does it deal with custom actors and custom actor lumps? Do these need to be added to the addon or there's a way to add custom types and lumps directly?"

### Current behaviour
**Custom actor types: not supported directly.** The entity picker is a hardcoded enum (`ENTITY_DEFS` dict). Every actor type currently in the addon is explicitly listed with metadata (art group path, nav type, tpage group, etc.). If your custom actor isn't in that list, you can't place it from the UI.

**Custom lumps: also not directly supported.** The lump dict for each entity is built in `collect_actors()` in pure Python. Only a small number of lump keys are ever written, driven by per-type logic (crate-type, eco-info, nav-mesh-sphere, path, vis-dist). There is no mechanism to attach arbitrary extra lump keys to an individual entity empty in Blender.

### What it would take to add both

**Custom actor types (two options):**

Option A — "Custom Actor" entry in the picker  
Add a catch-all `"custom"` entity type to `ENTITY_DEFS`. When spawned, the user types the actor type string directly into a custom property (`og_custom_type`) on the empty. `collect_actors()` would use that string as the etype instead of the object name. This requires no addon registry changes per-actor.

Option B — Register custom types in the addon  
Expose a small UI in the panel: "Add custom actor type" → name + art group path → stored in scene custom props or a JSON sidecar. Rebuilds `ENTITY_DEFS` dynamically on startup. More powerful but more work.

**Custom lumps (straightforward to add):**

Blender already supports arbitrary custom properties on any object. The pattern already exists in the addon — `og_crate_type`, `og_nav_radius`, `og_cam_mode`, etc. are all written as `o["og_key"] = value` on the empty and read back in `collect_actors()`.

We could add a general freeform lump pass at the bottom of `collect_actors()`:

```python
# After all standard lumps are built, apply any user-defined overrides/extras
for key, val in o.items():
    if key.startswith("og_lump_"):
        lump_key = key[len("og_lump_"):]   # strip prefix
        lump[lump_key] = _parse_lump_value(val)  # parse "['meters', 4.0]" etc.
```

The user would set custom properties like:
- `og_lump_initial-angle` → `["float", 1.5708]`
- `og_lump_speed` → `["meters", 4.0]`
- `og_lump_idle-distance` → `["float", 20.0]`

This is low-effort to implement and would cover almost any use case.

### Recommendation
Implement `og_lump_*` passthrough first — it's ~10 lines of code and immediately unlocks custom lumps for any actor. Custom actor type support (Option A) is the second step. Together they make the addon usable for fully custom actor workflows without needing to patch the addon itself.

---

## Q2 — Multiple Levels Per Blend File

> "Does it only work as 1 level per blend file? When working on TFL, I had several levels all loaded at once, in different collections with each their own export settings, so it was really easy to work on both levels at the same time and make them match and export the GLB to the correct locations."

### Current behaviour
**One level per blend file.** All export settings (level name, base actor ID, sound banks, etc.) live in `OGProperties`, which is registered as `bpy.types.Scene.og_props` — one instance per scene. Every ACTOR_, AMBIENT_, CAMERA_, TRIGGER_ object in the entire scene is exported as part of that single level. There is no concept of per-collection level grouping.

Export operators (`OG_OT_ExportLevel`, build operators) also use `ctx.scene.og_props.level_name` and run `collect_actors(scene)` which iterates `scene.objects` globally — no collection filter.

### What multi-level support would need

1. **Per-collection level settings** — a `CollectionProperties` group (registered on `bpy.types.Collection.og_level`) holding: level name, output path, base actor ID, sound banks, etc.

2. **Collection-scoped object collection** — `collect_actors()`, `collect_ambients()`, `collect_camera_actors()` would each need a `collection` argument and filter `objects` to only those in (or under) that collection.

3. **Export UI per collection** — a panel in the Collection Properties sidebar showing the level settings and an "Export This Level" button.

4. **Naming convention** — objects would still be prefixed ACTOR_/AMBIENT_/CAMERA_ but the collection they belong to determines which level they export to.

This is a moderate amount of work (a few hundred lines) but architecturally clean — the current system is already mostly functional-style with `scene` passed around, so adding a `collection` parameter is straightforward.

### Workaround until then
Multiple Blender scenes in the same .blend file. Each scene has its own `og_props`, its own objects, and its own export settings. You can reference geometry across scenes via Linked Objects. It's not as seamless as TFL's collection-per-level approach but it works today.

---

## Q3 — Full JSON Regeneration vs Incremental

> "Does it regenerate the whole json every time or does it edit it somehow? If it's the latter, is it possible to have some part of the json that are manually added and don't get wiped out?"

### Current behaviour
**Full regeneration every time.** `write_jsonc()` builds the entire JSONC data dict from scratch in Python and calls `p.write_text(new_text)` — it overwrites the file completely. There is one small optimisation: if the new text is identical to what's already on disk, the write is skipped. But if anything changed, the whole file is replaced.

This means any manual edits to the JSONC are wiped on the next export.

The JSONC is a single flat JSON object with these top-level keys, all written by the addon:
```
long_name, iso_name, nickname, gltf_file, automatic_wall_detection,
automatic_wall_angle, double_sided_collide, base_id, art_groups,
custom_models, textures, tex_remap, sky, tpages, ambients, actors
```

### What it would take to preserve manual additions

**Option A — Passthrough block (simplest)**  
Read the existing JSONC before export. Look for a special key (e.g. `"_manual"`) that the addon never writes. Merge its contents into the output dict before writing. Users can manually add `"_manual": { "extra_key": [...] }` to the file and it will survive exports.

**Option B — Merge strategy**  
Read existing JSONC. For each top-level key, if the value in the existing file is not generated by Blender (i.e. it's not in the set of keys the addon manages), preserve it. Riskier — harder to define the boundary of "addon-owned" vs "user-owned" keys.

**Option C — Solve it at Q1 instead (recommended)**  
If `og_lump_*` custom property passthrough is implemented (see Q1), and a custom actor type is supported, there should be no reason to manually edit the JSONC at all. Every field you'd need to tweak would be settable in Blender. This is the cleanest long-term solution.

### Current workaround
Set all needed fields via Blender custom properties before export, and accept that the JSONC is always addon-owned. If you need one-off JSONC fields not covered by the addon, add them after export as a post-processing step (a small script that loads the JSONC, patches it, and writes it back).

---

## Summary Table

| Question | Current State | Effort to Fix | Priority |
|---|---|---|---|
| Custom actor types | Hardcoded enum only | Low (Option A) / Medium (Option B) | Medium |
| Custom lumps per actor | Not supported | Low (`og_lump_*` passthrough ~10 lines) | High |
| Multi-level per blend | One scene = one level | Medium (collection properties) | Medium |
| JSON preservation | Full regen, manual edits wiped | Low (passthrough block) | Low if Q1 solved |


---

## Additional Note from Same Person

> "Also you should definitely change the spawn checkpoint in `mod-settings.gc` if you're using mod-base :p"

This is a tip about mod-base workflow, not a question — but worth documenting.

When using mod-base, the spawn checkpoint is defined in `mod-settings.gc`. If you don't change it, you'll spawn at whatever the default is (likely a vanilla level start point), not your custom level. The addon currently patches `level-info.gc` to register the level and its continue points, but it may not be guiding users to also update `mod-settings.gc` to actually spawn there.

**Things to check:**
- Does the addon's onboarding / documentation mention `mod-settings.gc` at all?
- Should the Build & Export flow include a step or reminder to set the spawn checkpoint?
- Could the addon write or patch `mod-settings.gc` automatically (set spawn to the first continue point of the exported level)?
- Or at minimum, add a UI reminder in the Build & Play panel: "Don't forget to set your spawn in mod-settings.gc"

**Context:** This is probably catching out new users who follow the export flow, get into the game, and find themselves spawning somewhere completely wrong.

