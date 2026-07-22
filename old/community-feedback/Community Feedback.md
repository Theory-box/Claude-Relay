# Community Feedback

---

## Table of Contents
- [Macros \& Level Info](#macros--level-info)
- [Level UI / Settings](#level-ui--settings)
- [Platforms](#platforms)
- [Pickups / Collectables](#pickups--collectables)
- [Checkpoints](#checkpoints)
- [Baking \& Lighting](#baking--lighting)
- [Bugs \& Misc](#bugs--misc)
- [Feature Questions \& Analysis](#feature-questions--analysis)

---

## Macros & Level Info

Hat Kid [GOAL] suggests adding macros for level-info to keep code shorter and easier to generate from the plugin — for example, continue point macros like those used in TFL. A `define-level` macro with sensible defaults where you only need to specify what differs would be ideal.

Reference: the TFL continue point macro implementation can be seen here:
- [tfl-dev-commentary-data.gc L1205–L1242](https://github.com/Kuitar5/the-forgotten-lands/blob/e8618a3022879ce45eee7ffd227e7d41949638df/goal_src/jak1/levels/tfl_common/commentary/tfl-dev-commentary-data.gc#L1205-L1242)
- [tfl-dev-commentary-data.gc L1292–L1296](https://github.com/Kuitar5/the-forgotten-lands/blob/e8618a3022879ce45eee7ffd227e7d41949638df/goal_src/jak1/levels/tfl_common/commentary/tfl-dev-commentary-data.gc#L1292-L1296)

barg [GOAL] shared a commonly used macro for meters-based vectors:

```lisp
(defmacro static-vector-meters (x y z)
  `(new 'static 'vector :x (meters ,x) :y (meters ,y) :z (meters ,z) :w 1.0))
```

---

## Level UI / Settings

### Level Settings Tab
Consider promoting **Level Settings** to its own tab in the Level section rather than hiding it behind the **Edit** button. Music already has its own category, so the current split feels inconsistent — a dedicated tab would unify level-wide configuration in one place.

---

### Level Nickname Collisions
When creating a new level, the auto-generated nickname doesn't check existing levels, so collisions are possible (e.g. `test-1` and `test-2` both get the nickname `tes`). Either auto-differentiate on collision or allow the user to override the nickname during creation.

---

### Renaming a Level Leaves Stale Files
Changing a level's name does not clean up the file edits made under the old name — it simply creates a whole new set of files and edits, leaving the originals orphaned. Full cleanup from the addon may be difficult, but at minimum a clear warning should be shown before the rename is applied so the user knows manual cleanup is needed.

---

### Level Index & Base Actor ID Defaults
Both the level **index** and **Base Actor ID** default to `27` for every newly created level, which causes collisions across multiple custom levels. These should auto-increment by 1 per new level, and remain editable in case the user needs to set them manually.

---

### Additional Level Settings to Expose (JSONC)
Three level-scoped settings should be exposed in the UI. They already exist as top-level JSONC keys — the addon writes them but doesn't let the user edit them from Blender:

| Setting | Type | Default |
|---|---|---|
| Automatic wall detection | true / false | `true` |
| Automatic wall angle | 0–180° | `45` |
| Double-sided collide | true / false | `false` |

Natural home for these is the proposed Level Settings tab (see [Level Settings Tab](#level-settings-tab)).

---

### Additional Level-Info Settings to Expose (`level-info.gc`)
Per-level settings that live in `level-info.gc` and should be exposed in the UI (parallel to the JSONC settings above, but written to a different file):

| Setting | Type | Default | Notes |
|---|---|---|---|
| `index` | int | `27 + # of existing levels` | Must be unique — see [Level Index & Base Actor ID Defaults](#level-index--base-actor-id-defaults) for broader discussion. |
| `bsphere` | vector + radius | centered in level, radius ~300–900m | Sphere enveloping the level; used for mood transitions when moving between levels. UX suggestion: spawn a linked sphere empty in Blender so the user can position and resize it visually. |
| `sky` | true / false | `true` | |
| `mood` | string | `'*village1-mood*` | Mood table defined in `mood-tables.gc` — controls Jak and actor lighting, fog, sun, shadows. |
| `mood-func` | string | `'update-mood-village1` | Function that updates mood effects, time of day, etc. |
| `ocean` | string | `#f` | See [JakMods.dev](https://jakmods.dev) for custom oceans. Could also reuse an existing ocean or ship a mask-less default (no holes) for simplicity. |

Natural home for these is the proposed Level Settings tab (see [Level Settings Tab](#level-settings-tab)).

---

### Level Audit
Currently errors because there's no `spawn` — doesn't actually matter in practice.

Things that would be nice to have in the audit:
- **Visual model checks:** if the audit can inspect exported visual models, warn on ones with no texture or no color attribute, and ideally provide a one-click way to select the flagged models so they can be found and fixed quickly.
- **Mesh stats:** material/texture count, and vertex and triangle counts for both the visual mesh and the collision mesh.

---

## Platforms

### General Platform Feedback
- Most platform crashes are caused by code not being included in the level. Much of that code lives in a specific level's `-obs.gc` file; some platforms have their own code file.
- For platforms with their own code file: add it to the level's `.gd`.
- For platforms with code in another level's `-obs.gc`: copy only the required code blocks rather than importing the whole file — cleaner, and allows custom res-lump additions.
- Consider renaming **Waypoints** to **Path** and keeping both the existing waypoint attachment method and adding a new button to connect to an existing path using the `path-k` lump. More info on curves: [JakMods.dev](https://jakmods.dev)
- Add a *select without centering view* button next to waypoints.
- Consider adding cameras as children of platforms, similar to checkpoints — though note that you may sometimes want to move the platform without moving the path. Since the platform would go to the path automatically anyway, this is less of an issue; Blender also has a *Move Parents Only* option for these cases.

---

### Button Platform
- Disappears when button is pressed by default. Consider auto-adding two waypoints so it works out of the box — though the UI already tells you to do this, so it may not be necessary.
- With two or more waypoints added, works correctly — moves from 1st to last waypoint through all intermediate points.
- No default length/speed; stuck at default duration unless code is edited.
  - Useful res-lump to expose: `bidirectional` (int, `0`/`1`) — allows the platform to be used again once it reaches the end, travelling back the way it came (continuous back-and-forth, not just a single return).

---

### Cave Flame Pots
- **Compiler crash:** `No rule to make out/jak1/obj/caveflamepots-ag.go` — no art group exists; visuals are all particles defined in code.
- Probably should not be in Platforms — it is an obstacle (damages the player, not something to stand on). Possible alternatives: Enemies, Props/Objects, or a new Obstacles section — though it's not entirely clear where they belong.

---

### Cave Spatula Plat / 2
- **Compiler crash:** `No rule to make out/jak1/obj/cavespatula-ag.go` — the actual art group names are:
  - `cavespatula-darkcave-ag.go` (single)
  - `cavespatulatwo-ag.go` (double)

---

### Dark Eco Barrel
- **Crashes the game.**
- Same as flame pots — probably should not be in Platforms.

---

### Eco Platform
- Activates by default — consider making it inactive by default, since as-is it is functionally identical to a plain platform. Setting eco notice distance to `~2m` restores expected behaviour.
- A way to keep the platform active after death exists but needs investigation.

---

### Flip Platform
- Works fine out of the box.
- Useful res-lumps to expose:
  - `delay` (float) — seconds the platform stays upright
  - `sync-percent` (float, `0.0`–`1.0`) — phase offset to desync multiple flip platforms

---

### Floating Platform
- Works fine.

---

### Launcher
- Works fine out of the box.
- **Fly time** does not appear to be working — it should control how long the player is locked into the trajectory before being free to move, but no value seems to change anything right now.
- Pressing X on the destination does not delete the destination empty (may or may not be intended).
- Suggestion: display the destination empty as a single arrow whose size matches the height of the launcher jump. This makes it very easy to visualise in-level how high the player will go and when that value should be adjusted.

---

### Lava Balloon
- Works fine (implemented by loading `lavatube-obs.gc` in the level's `.gd`).
- The warning may not be necessary since it works without it.
- Probably should not be in Platforms.

---

### Ogre Bridge
- Works fine (same approach as Lava Balloon).
- Not yet investigated for additional settings potential.

---

### Ogre Drawbridge
- **Blender error on export:** `cannot access local variable '_actor_get_link' where it is not associated with a value`

---

### Orbit Platform
- No obvious way to link the alt-actor for the center entity — tried adding a random empty but that doesn't seem to work. If a specific actor type is required, it should be documented and a button added to spawn it directly.
- **Export error:** `cannot access local variable '_actor_get_link' where it is not associated with a value`

---

### Platforms Currently Crashing the Game
- Balance Platform
- Bone Bridge
- Breakaway Plat L / M / R
- Cave Elevator
- Dark Eco Barrel
- Cave Trap Door
- Tar Platform

---

### Platforms Not Yet Tested
- Pontoon Training / Village2
- Rope Bridge
- Side-to-Side Plat
- Square Platform
- Warp Gate
- Wedge Platform

---

### Pontoon Training / Village2
- **Compiler crash:** `No rule to make out/jak1/obj/tra-pontoon-ag.go` — correct art groups:
  - `pontoonfive-ag.go`
  - `pontoonten-ag.go`
  - `allpontoons-ag.go`
- Will also need to be linked to a water volume/actor.

---

### Rope Bridge
- Collision loads but visuals do not. There are 6 different bridge art groups depending on the bridge — best to read the `art-name` res-lump setting and include only the relevant AG.
- See `init-from-entity` in `ropebridge.gc` for the full `art-name` res-lump list.

---

### Rotating Platform
- Consider spawning the recycle actor instead — it is the zoomer visual mesh.

---

### Side-to-Side Plat
- Works fine when `sunken-obs` is loaded.

---

### Square Platform
- Linking mechanism unclear — water volume added but linking option not found.
- Loads fine in game otherwise.
- Can be linked to a button or other platforms to move up and down.

---

### Teeter Totter
- Works fine, has its own file.
- No exposed settings currently — at minimum a jump height parameter would be useful.

---

### Wall Platform
- Visual model loads.
- Missing sync parameters (same as floating platforms) for in/out of wall timing.
- No collision unless manually added.

---

### Warp Gate
- Probably should not be in Platforms.
- The original warp gate is an actual mess and very not modular — a custom, more modular version is worth building. Zed's *Jak the Chicken* has some custom warp gates, or at least heavily modified ones, which may be a good reference.
- Does nothing currently without a linked button.

---

### Wedge Platform
- Loads fine.
- Needs `wedge-plat-master` for the rotation center and a way to link it.
- Missing `wedge-plat-outer` for the outer ring.
- Res-lumps to expose:
  - `rotspeed` (float) — master
  - `rotoffset` (float) — both plats
  - `distance` (float) — both plats

---

## Pickups / Collectables

### General Pickups Feedback
- Almost every collectable supports the `eco-info` res-lump to control what is given/spawned on break — at minimum this should be in the lump documentation. Note that many actors here are just wrappers that set this argument on their parent: for example, `ventblue` simply sets the `pickup-type` of a vent to `eco-blue`. This parent/child relationship is worth documenting.
- The `options` lump is already referenced in the lump documentation but currently has no explanation of which options are valid — this needs to be filled in.
- `collectables.o` does not need to be in a level's `.gd` — it is loaded via `game.gd`. As a general rule, anything already loaded in `game.gd` never needs to be re-loaded in a specific level.
- Vents could be unified like crates: one list entry, then a selector for eco type. The same approach could work for eco blobs. Note: technically vents can also be configured to give other collectables entirely (e.g. a vent that gives infinite orbs) — whether that should be an exposed option is an open question.

---

### Blue Eco
- Listed as *Blue Eco Vent* — should be renamed.
- Works fine.
- Suggestion: quantity setting (grants more than 1 eco meter unit without spawning extra blobs).

---

### Blue Eco Vent
- **Compiler crash:** `No rule to make out/jak1/obj/vent-ag.go` — no art group exists for eco-vents; the vent itself is part of the geometry. For some vents the particle blocker is in common, so it doesn't need to be loaded separately.
- The blocker triggers when its object is destroyed, not through a task.
- Needs a parameter to activate only when a specific task is complete (see fire canyon vents for reference).

---

### Blue Eco Vent (alt)
- Purpose unclear — if this is just a pre-blocked variant, it should be a parameter on the normal Blue Eco Vent rather than a separate entry.

---

### Crate
- Works fine.
- Suggested defaults per crate type:

| Type | Default Content |
|------|----------------|
| Steel | 1 orb |
| Wood | Empty (gives random eco-pill amounts based on *you suck* value) |
| Iron | Scout Fly |
| Dark Eco | Empty |
| Barrel | Empty (same behaviour as Wood) |
| Bucket | Empty |

- Missing eco-pill content type (small health), which also accepts a numeric quantity.
- Orb count description of `1–5` is misleading — base game includes crates with 10 orbs (e.g. fire canyon).
- Suggestion: button to auto-align a crate to the ground beneath it. This is already doable manually via Blender's *Snap to Face* with *Align Rotation to Target*, but having it as a one-click button would be a quality-of-life improvement.
- Scout Flies require special handling: the `amount` field identifies which of the 7 flies for a specific task it is. There may be an easier way to set these up compared to the past — worth investigating. Multiple scout flies currently can't all be collected to spawn the cell. Required setup:
  - `game-task` res-lump
  - `movie-pos` to place the cell when the final fly is collected
- `crate-ag.go` does not need to be loaded in the level's `.gd`.

---

### Eco Pill (Health)
- **Compiler crash:** `No rule to make out/jak1/obj/eco-pill-ag.go` — no art group needed; purely particle-based.
- Suggestion: quantity setting (grants more than 1 eco-pill unit without spawning extras).

---

### Green Eco
- Listed as *Green Eco Vent* — should be renamed.
- Does not work — type is wrong, should be `health`.
- Suggestion: quantity setting.

---

### Orb (Precursor)
- Works fine.
- Suggestion: button to float selected orbs at a consistent height above the ground (`1`–`2` metres default), with multi-selection support so all orbs can be adjusted at once.
- Feature idea (also suggested by another community member) — distribute orbs along a curve. There could be several ways to implement this; one possible approach:
  1. Spawn the desired orbs
  2. Create a curve
  3. Select orbs + curve and use a link option
  4. Orbs spread evenly along the curve and follow edits to it
  5. Optional height offset so the curve can be drawn on the ground and orbs float consistently above it

---

### Orb Cache
- Works fine.
- Default of 20 orbs may be high but is easy to change.
- `active-distance` and `inactive-distance` would be useful settings — currently hard-coded and require a code edit to expose.

---

### Power Cell
- Requires an associated `game-task` or the cell does nothing.
- *Skip jump animation* only prevents one specific animation, not the full collect animation.
- Consider a way to place the `mov-pos` (where the collect animation plays from), similar to scout flies.
- The fuel-cell art group does not need to be loaded — it is in `common/game`.

---

### Power Cell (alt)
- Appears to be specific to the final boss door visual — it is likely what is used for the cells that visually fly out of Jak toward the door, as stand-ins rather than real cell actors. Probably should not be in Collectables.

---

### Red Eco
- Listed as *Red Eco Vent* — should be renamed.
- Works fine.
- Suggestion: quantity setting.

---

### Red Eco Vent
- Same issues as Blue Eco Vent.

---

### Scout Fly
- Does not spawn.
- Requires all setup described in the [Crate](#crate) section (`game-task` lump, `movie-pos`, correct `amount` index, etc.).
- **Note from barg:** scout flies can also use a `movie-pos` res-lump for the cell destination / animation origin when it is the 7th fly. Without this, the cell spawns at the fly/crate location.

---

### Yellow Eco
- Listed as *Yellow Eco Vent* — should be renamed.
- Works fine.
- Suggestion: quantity setting.

---

### Yellow Eco Vent
- Same issues as Blue Eco Vent.

---

### Eco Vent (Rock)
- Works fine.
- Probably should not be in Collectables — it is just a rock that breaks. It can be used to block a vent, but so can any actor, so there is nothing collectable-specific about it.
- How the cell spawn from these works is unclear; may be tightly coupled to the Beach cell.

---

### Missing Collectables
- Green Eco Vent
- `pickup-spawner` — can spawn nearly anything and can be triggered by other actor code rather than spawning automatically. Very useful to add.

---

## Checkpoints

### Multi-Level Display
Currently you can't load both levels at once through checkpoints because the level-display handling isn't implemented yet. Workaround: use the in-game debug menu to display both simultaneously. Once checkpoint level-display logic is in place, this should be driven by the checkpoint config rather than requiring debug.

See also: *Feature Questions & Analysis → Additional Note — Spawn Checkpoint in `mod-settings.gc`* for a related but distinct checkpoint-plugin gap (which checkpoint the player spawns at vs. which levels a checkpoint loads).

---

## Baking & Lighting

### Material Preview in Blender
You can get a rough preview of how a model will appear in-game by adding the color attribute into the material and mixing it with the texture. This is also required if you want to use vertex alpha — see below.

---

### Vertex Alpha Export
Vertex alpha only exports if you export vertex color via Blender's **Material** option. Exporting via the **Active Attribute** option drops the alpha portion of the color attributes. Needs retesting on newer Blender versions — may have been fixed upstream.

---

### Recommended Bake Settings
**Diffuse** pass with **Direct** and **Indirect** selected, but **Color** unchecked — this prevents the texture/material from being mixed into the bake. Unclear whether the addon already accounts for this in its baking setup.

---

### Emissive Materials
Materials that emit light don't bake well under the recommended diffuse-only settings above. It would be useful to combine an **Emit** bake on top of the **Diffuse** bake, ideally with a control for how strongly the emissive bake contributes to the diffuse result.

---

### OpenGOAL Lighting Range
Two brightness limits in how OpenGOAL handles baked lighting, plus a color-count note:

- **0.25 floor:** anything below `0.25` brightness is treated as fully black by the engine. It doesn't render as pure black in-game, but the entire `0.0`–`0.25` range looks identical.
- **0.75 ceiling:** the "full bright" / no-lighting look sits at `0.75` brightness. Above that, surfaces start to look overexposed, as if they're emitting light.
- **Color count:** there's a cap on the number of distinct colors that can be used, but the current level builder does a good job indexing colors, so probably nothing needs to change here — just worth keeping in mind.

---

### Brightness-Range Remapping
GratefulForest had a baking script that scaled the baked result into the `0.25`–`0.75` range to respect the OpenGOAL limits above. Opinion from the feedback: it made lighting look too bland — dark areas almost disappeared and peak brightness lost its punch. A better approach would be to give more control at both ends rather than a flat rescale.

---

## Bugs & Misc

- **Collection visibility export bug:** Making the collection containing the level un-selectable (a common workflow so you don't constantly accidentally select the level while working on actors) causes it to disappear on export. Suspected cause: the addon performs a selection-only export pass and marking the collection un-selectable breaks it. Needs investigation.
- **Empty lines in `game.gp` before custom-level entries:** The plugin inserts ~100 blank lines into `game.gp` before the `build-custom-level` / `custom-level-cgo` / `goal-src` block on export. Cosmetic rather than functional, but worth cleaning up.

---

## Feature Questions & Analysis

Analytical deep-dives on community-raised questions and feature requests. Each entry includes the original quote, current behaviour analysis, and implementation options. Collected for future documentation / FAQ coverage.

---

### Q1 — Custom Actors & Custom Lumps

> "How does it deal with custom actors and custom actor lumps? Do these need to be added to the addon or there's a way to add custom types and lumps directly?"

#### Current behaviour
**Custom actor types: not supported directly.** The entity picker is a hardcoded enum (`ENTITY_DEFS` dict). Every actor type currently in the addon is explicitly listed with metadata (art group path, nav type, tpage group, etc.). If your custom actor isn't in that list, you can't place it from the UI.

**Custom lumps: also not directly supported.** The lump dict for each entity is built in `collect_actors()` in pure Python. Only a small number of lump keys are ever written, driven by per-type logic (crate-type, eco-info, nav-mesh-sphere, path, vis-dist). There is no mechanism to attach arbitrary extra lump keys to an individual entity empty in Blender.

#### What it would take to add both

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

#### Recommendation
Implement `og_lump_*` passthrough first — it's ~10 lines of code and immediately unlocks custom lumps for any actor. Custom actor type support (Option A) is the second step. Together they make the addon usable for fully custom actor workflows without needing to patch the addon itself.

---

### Q2 — Multiple Levels Per Blend File

> "Does it only work as 1 level per blend file? When working on TFL, I had several levels all loaded at once, in different collections with each their own export settings, so it was really easy to work on both levels at the same time and make them match and export the GLB to the correct locations."

#### Current behaviour
**One level per blend file.** All export settings (level name, base actor ID, sound banks, etc.) live in `OGProperties`, which is registered as `bpy.types.Scene.og_props` — one instance per scene. Every ACTOR_, AMBIENT_, CAMERA_, TRIGGER_ object in the entire scene is exported as part of that single level. There is no concept of per-collection level grouping.

Export operators (`OG_OT_ExportLevel`, build operators) also use `ctx.scene.og_props.level_name` and run `collect_actors(scene)` which iterates `scene.objects` globally — no collection filter.

#### What multi-level support would need

1. **Per-collection level settings** — a `CollectionProperties` group (registered on `bpy.types.Collection.og_level`) holding: level name, output path, base actor ID, sound banks, etc.

2. **Collection-scoped object collection** — `collect_actors()`, `collect_ambients()`, `collect_camera_actors()` would each need a `collection` argument and filter `objects` to only those in (or under) that collection.

3. **Export UI per collection** — a panel in the Collection Properties sidebar showing the level settings and an "Export This Level" button.

4. **Naming convention** — objects would still be prefixed ACTOR_/AMBIENT_/CAMERA_ but the collection they belong to determines which level they export to.

This is a moderate amount of work (a few hundred lines) but architecturally clean — the current system is already mostly functional-style with `scene` passed around, so adding a `collection` parameter is straightforward.

#### Workaround until then
Multiple Blender scenes in the same .blend file. Each scene has its own `og_props`, its own objects, and its own export settings. You can reference geometry across scenes via Linked Objects. It's not as seamless as TFL's collection-per-level approach but it works today.

---

### Q3 — Full JSON Regeneration vs Incremental

> "Does it regenerate the whole json every time or does it edit it somehow? If it's the latter, is it possible to have some part of the json that are manually added and don't get wiped out?"

#### Current behaviour
**Full regeneration every time.** `write_jsonc()` builds the entire JSONC data dict from scratch in Python and calls `p.write_text(new_text)` — it overwrites the file completely. There is one small optimisation: if the new text is identical to what's already on disk, the write is skipped. But if anything changed, the whole file is replaced.

This means any manual edits to the JSONC are wiped on the next export.

The JSONC is a single flat JSON object with these top-level keys, all written by the addon:
```
long_name, iso_name, nickname, gltf_file, automatic_wall_detection,
automatic_wall_angle, double_sided_collide, base_id, art_groups,
custom_models, textures, tex_remap, sky, tpages, ambients, actors
```

#### What it would take to preserve manual additions

**Option A — Passthrough block (simplest)**  
Read the existing JSONC before export. Look for a special key (e.g. `"_manual"`) that the addon never writes. Merge its contents into the output dict before writing. Users can manually add `"_manual": { "extra_key": [...] }` to the file and it will survive exports.

**Option B — Merge strategy**  
Read existing JSONC. For each top-level key, if the value in the existing file is not generated by Blender (i.e. it's not in the set of keys the addon manages), preserve it. Riskier — harder to define the boundary of "addon-owned" vs "user-owned" keys.

**Option C — Solve it at Q1 instead (recommended)**  
If `og_lump_*` custom property passthrough is implemented (see Q1), and a custom actor type is supported, there should be no reason to manually edit the JSONC at all. Every field you'd need to tweak would be settable in Blender. This is the cleanest long-term solution.

#### Current workaround
Set all needed fields via Blender custom properties before export, and accept that the JSONC is always addon-owned. If you need one-off JSONC fields not covered by the addon, add them after export as a post-processing step (a small script that loads the JSONC, patches it, and writes it back).

---

### Summary Table

| Question | Current State | Effort to Fix | Priority |
|---|---|---|---|
| Custom actor types | Hardcoded enum only | Low (Option A) / Medium (Option B) | Medium |
| Custom lumps per actor | Not supported | Low (`og_lump_*` passthrough ~10 lines) | High |
| Multi-level per blend | One scene = one level | Medium (collection properties) | Medium |
| JSON preservation | Full regen, manual edits wiped | Low (passthrough block) | Low if Q1 solved |

---

### Additional Note — Spawn Checkpoint in `mod-settings.gc`

> "Also you should definitely change the spawn checkpoint in `mod-settings.gc` if you're using mod-base :p"

This is a tip about mod-base workflow, not a question — but worth documenting.

When using mod-base, the spawn checkpoint is defined in `mod-settings.gc`. If you don't change it, you'll spawn at whatever the default is (likely a vanilla level start point), not your custom level. The addon currently patches `level-info.gc` to register the level and its continue points, but it may not be guiding users to also update `mod-settings.gc` to actually spawn there.

**Things to check:**
- Does the addon's onboarding / documentation mention `mod-settings.gc` at all?
- Should the Build & Export flow include a step or reminder to set the spawn checkpoint?
- Could the addon write or patch `mod-settings.gc` automatically (set spawn to the first continue point of the exported level)?
- Or at minimum, add a UI reminder in the Build & Play panel: "Don't forget to set your spawn in mod-settings.gc"

**Context:** This is probably catching out new users who follow the export flow, get into the game, and find themselves spawning somewhere completely wrong.
