# Full Audit Notes — research/community-feedback-apr15

---

## properties.py

### P1 — Expensive filesystem calls inside draw() [PERFORMANCE]
`draw()` in OGPreferences runs on every panel redraw (30fps during interaction).
Contains:
- 2–3 Path.exists() calls for data_path detection
- 2–5 Path.exists() + Path.is_dir() + Path.glob("*.glb") for decompiler detection
- `from pathlib import Path` and `from .build import _data` imported every call
The glob("*.glb") call is the worst — scans a directory on every redraw.
Fix: cache results keyed by (data_path_str, decompiler_path_str).

### P2 — Double is_dir() call [MICRO-BUG]
`(dp / d).is_dir() and any((dp / d).glob("*.glb")) for d in [...] if (dp / d).is_dir()`
`is_dir()` called twice per folder: once in the comprehension `if` clause, once in the body.
Fix: restructure to call once.

### P3 — og_music_amb_flava reset to "default" may not be valid [BUG]
`update=lambda self, ctx: setattr(self, "og_music_amb_flava", "default")`
Resets flava to "default" when bank changes, but "default" may not be a valid
item for every bank. If it isn't, Blender silently keeps old value or picks first.
Fix: reset to first available flava for the new bank, or verify "default" is always present.

### P4 — base_id range max=60000 not enforced across levels [GAP]
Description says "Must be unique across all custom levels" but no audit check verifies
two levels in the same .blend don't share the same base_id. If they do, actor IDs collide.
Fix: add audit check comparing base_ids across all level collections.

### P5 — level_name in OGProperties is legacy fallback, confusing [MINOR]
`level_name` in OGProperties is used when NOT in collection mode (backward compat).
No max-length or character validation on this property — only the operators validate.
If a user sets this directly in Python or through some edge path, invalid names can reach export.

### P6 — Unused imports: Panel, Operator [MINOR]
`from bpy.types import Panel, Operator, PropertyGroup, AddonPreferences`
Panel and Operator are not used in properties.py.


---

## collections.py

### C1 — _link_object_to_sub_collection unlinks from ALL other collections [BUG-RISK]
```python
for col in bpy.data.collections:
    if col == target:
        continue
    if obj.name in col.objects:
        col.objects.unlink(obj)
```
This iterates ALL collections in bpy.data.collections — including collections from
OTHER scenes if they exist. Could unlink objects from unrelated collections.
Fix: only unlink from collections that are children of the scene root, not global.

### C2 — _link_object_to_sub_collection called by spawn camera, not for parented camera [BUG]
Camera empties are now parented to spawn/checkpoint empties. After parenting,
`_link_object_to_sub_collection` routes the camera to Spawns sub-collection.
But the camera is already parented to the spawn empty which may be in a different 
sub-collection. Having the camera in Spawns and the spawn in Spawns is fine,
but the parenting means the camera appears twice in the outliner hierarchy.
Low severity but potentially confusing.

### C3 — _active_level_col fallback to levels[0] silently wrong [UX]
If `active_level` prop doesn't match any collection (e.g. after rename),
falls back to `levels[0]`. User may think they're editing level A but actually
editing level B (whichever is first alphabetically).
Fix: detect the mismatch and update `active_level` prop, or show a warning.

### C4 — _set_level_prop renames collection to sanitised level_name [SIDE-EFFECT]
When `og_level_name` is written, `col.name` is updated to match.
This is correct behaviour but not obvious — changing a level's internal name
also renames the Blender collection. Could surprise users.

### C5 — _all_level_collections only checks top-level scene children [LIMITATION]
Only checks `scene.collection.children` — level collections MUST be at the 
scene root level. Nested level collections (inside another collection) won't
be detected. Not documented as a constraint anywhere.

### C6 — _get_death_plane uses bpy.context directly [THREAD-SAFETY]
`col = _active_level_col(bpy.context.scene) if bpy.context else None`
Called from a Blender RNA getter — bpy.context may not be available in all
contexts (e.g. during modal operators, background threads). The `if bpy.context`
guard helps but doesn't cover all cases.

### C7 — _recursive_col_objects deduplication by name [EDGE-CASE]
Uses `o.name not in seen` for deduplication. Two objects in different collections
with the same name (impossible in Blender — names are globally unique per type)
would still be fine. Non-issue, but worth noting the assumption.


---

## export.py

### E1 — write_jsonc hardcodes "village1" sky/tex/mood [LIMITATION]
```python
"textures": [["village1-vis-alpha"]],
"tex_remap": "village1", "sky": "village1",
```
These are hardcoded, not read from scene properties. Users can't change sky/mood
from Blender. Mood/sky panel exists in properties (from earlier research) but
write_jsonc doesn't read it. Disconnect between what's in the UI and what's exported.
Fix: read sky/tex_remap from scene level props, or document clearly.

### E2 — patch_level_info :index hardcoded to 27 [BUG-RISK]
`:index 27` is hardcoded. The level index must be unique across ALL loaded levels.
If another custom level also uses index 27 and both load simultaneously, undefined
behaviour. The index is used internally by the engine for level slot management.
Fix: auto-generate from hash of level name, or document that index conflicts are
a risk for multi-level mods.

### E3 — patch_level_info regex may match wrong level [BUG-RISK]
```python
re.sub(rf"\n\(define {re.escape(name)}\b.*?\(cons!.*?'{re.escape(name)}\)\n", ...)
```
The `.*?` in DOTALL mode matches across the entire file between `(define name`
and the NEXT `(cons! *level-load-list* 'name)`. If the level name appears anywhere
else in level-info.gc comments or strings, the regex could over-consume.
Also: if patching fails (name not found) it appends, creating duplicates on retry.
Low probability but possible with unusual level names.

### E4 — bsphere computed only from spawn positions [LIMITATION]
The bsphere centre/radius is computed from spawn positions only, not from level
geometry. A level with geometry far from spawns will have an undersized bsphere,
meaning the engine may not load the level when the player is near the geometry
but far from spawns. Could cause level unloading/pop-in.
Fix: use bounding box of all level geometry objects OR let user override.

### E5 — write_jsonc equality check reads file twice [PERFORMANCE]
```python
new_text = f"// OpenGOAL custom level: {name}\n" + json.dumps(data, indent=2)
if p.exists() and p.read_text() == new_text:  # read 1
```
But patch_level_info also does:
```python
original = p.read_text(encoding="utf-8")  # then reads again inside the same call
```
Minor — these are small files.

### E6 — disp1 value not validated against allowed values [BUG]
```python
"disp1": str(o.get("og_disp1", "none") or "none"),
```
Any string the user types into the `og_disp1` custom prop will be passed through.
If user types "DISPLAY" (uppercase) or "spec" (typo), it becomes `'DISPLAY` or `'spec`
in the GOAL output — invalid symbols.
Fix: validate against {"display", "special", "none"} before embedding.

### E7 — collect_spawns: lev1/disp1 use default "" and "none" but _make_continues
checks `if lev1` (empty string is falsy) and `if disp1 and disp1 != "none"`.
This means if lev1="" and disp1="display", disp1_goal would be "'display" but
lev1_goal would be "#f". The combination lev1=#f, disp1='display is nonsensical
(no level to display) but won't crash — it'll just be treated as lev1=#f.
Fix: if lev1 is empty, always force disp1 to #f.

### E8 — export_glb called on MAIN THREAD before background worker [TIMING]
```python
export_glb(ctx, name)  # main thread
threading.Thread(target=_bg_build, ...).start()  # bg thread
```
export_glb modifies scene objects (collects meshes, exports GLB). If export_glb
raises an exception, _bg_build is never started but _BUILD_STATE is not updated.
The operator returns CANCELLED but the state is left in the initial "Starting..." state.
Fix: only set _BUILD_STATE["done"] = False after export_glb succeeds, or handle.
Actually — since _BUILD_STATE is set before export_glb:
```python
_BUILD_STATE.update({"done":False,"status":"Starting...","error":None,"ok":False})
```
Wait, actually _BUILD_STATE is set AFTER the export_glb call. Let me re-check...
Actually the order is: export_glb → then update state → then start thread. So if
export_glb fails, state was never set to "Starting..." — the except branch returns
CANCELLED. Fine actually. Low severity.

### E9 — write_gc `:heap-base #x70` and `:size-assert #xdc` hardcoded [BUG-RISK]
For checkpoint-trigger:
```
":heap-base #x70",
":size-assert #xdc",
```
These struct size/alignment values are computed from field offsets. If the
field list ever changes (new fields added), these values must be updated manually.
Currently they're correct for the 10 fields defined, but fragile.
Fix: compute from field sizes or add a comment with calculation.

### E10 — collect_spawns/collect_actors don't handle meshes with non-uniform scale [LIMITATION]
If a spawn empty has been scaled (e.g. 2x to make it more visible in viewport),
the position export via matrix_world.translation would be correct, but the
rotation matrix would be a scaled rotation, not a pure rotation.
`to_quaternion()` on a scaled matrix produces incorrect results.
Fix: normalize the rotation matrix before converting to quaternion, or
warn/error if scale != (1,1,1).


---

## build.py

### B1 — CRITICAL: _patch_vol_h_enabled def line missing [CRASH]
The `def _patch_vol_h_enabled():` line was accidentally consumed as the anchor
for the `_decompiler_path()` str_replace insertion. The function body is now
floating at module level as orphaned statements.
Result: calling `_patch_vol_h_enabled()` from `_apply_engine_patches()` raises
`NameError` → every Export & Compile crashes at the engine patches step.
Also: the docstring runs as a string expression and the code runs at import time
(bpy.context access at module level can crash Blender on startup).

### B2 — CALL_MARKER in patch_entity_gc silently no-ops if not found [SILENT FAILURE]
```python
txt = txt.replace(CALL_MARKER, "  (custom-nav-mesh-check-and-setup this)\n" + CALL_MARKER, 1)
```
If the `(let* ((entity-type (-> this etype))` marker is not found in entity.gc,
str.replace returns the unchanged string — no error, no log, no indication.
Nav-mesh would be broken silently. BIRTH_MARKER absence now raises, but
CALL_MARKER absence does not. Fix: add explicit check.

### B3 — _data_cache in build.py and export.py are separate dicts [INCONSISTENCY]
Both files define their own `_data_cache: dict = {}`. They both resolve correctly
but independently. If data_path changes, both caches grow independently.
Not a bug (both produce the same result) but confusing. A shared module would
eliminate duplication.

### B4 — launch_goalc/launch_gk pass data_dir as --proj-path [VERIFY]
```python
data_dir = str(_data())
cmd = [str(exe), "--user-auto", "--game", "jak1", "--proj-path", data_dir, ...]
```
After the _data() fix, this now correctly passes the resolved path. But we
established that gk/goalc use --proj-path as the "data folder" directly.
For dev env: _data() = jak-project/ (the repo root). The C++ code auto-detects
dev repo when no --proj-path is given, but WITH --proj-path set to repo root,
it uses that path directly as the data folder. This means gk/goalc would look for
goal_src at jak-project/goal_src/ which is CORRECT. ✓
For release: _data() = release/data/. gk/goalc use release/data/ as data folder. ✓
Low confidence: B4 is likely fine but worth verifying once live.

### B5 — _user_base writes to _data()/goal_src/user/ [VERIFY WITH B4]
After the _user_base fix, startup.gc is written to _data()/goal_src/user/blender/.
For dev env: _data() = jak-project/, so user/ is at jak-project/goal_src/user/blender/.
GOALC with --user-auto should find user.txt at goal_src/user/user.txt then read
goal_src/user/blender/ as the user profile. This is consistent with what gk/goalc
expect. ✓ (Low confidence — verify once live.)

### B6 — _bg_build state dict not reset if export_glb raises [MINOR]
If export_glb raises before _BUILD_STATE is initialised:
```python
try:
    export_glb(ctx, name)
except Exception as e:
    self.report({"ERROR"}, f"GLB export failed: {e}"); return {"CANCELLED"}
_BUILD_STATE.clear()
_BUILD_STATE.update({"done":False,...})
```
If export_glb raises, _BUILD_STATE retains its previous values (from a prior run).
The operator returns CANCELLED so the modal never polls it, but the stale state
is technically incorrect. Not user-visible but could cause confusion in debug.


---

## audit.py

### A1 — No base_id uniqueness check across levels [GAP]
If two level collections in the same .blend both use base_id=10000, actor IDs will
collide and produce ghost entity spawns. No check exists for this.
Fix: add check comparing base_ids of all level collections in the scene.

### A2 — check_navmesh_links uses scene.objects instead of _level_objects [SCOPE BUG]
```python
objects = scene.objects  # line 101
elif objects.get(nm_name) is None:  # checks scene-wide
```
The navmesh link target is checked against the whole scene, not just the active level.
This means it won't flag a broken link pointing to a navmesh in a DIFFERENT level's
collection. Low severity — typically won't cause false positives but is inconsistent
with how all other checks work.

### A3 — check_actor_links uses scene.objects for target lookup [SAME SCOPE BUG]
```python
objects = scene.objects  # line 148
if objects.get(lk.target_name) is None:  # checks scene-wide
```
Same pattern as A2. Actor link targets are validated against the whole scene.

### A4 — check_volumes uses scene.objects [SAME SCOPE BUG]
```python
objects = scene.objects  # line 180
elif objects.get(target) is None:  # checks scene-wide
```
Trigger volume targets validated against whole scene.

### A5 — check_camera_targets uses scene.objects [SAME SCOPE BUG]
Pattern repeated in four checks. All of A2–A5 should use a level-scoped
object set. Fix all four to use _level_objects(scene) dict lookup.

### A6 — check_duplicate_names only checks ACTOR_ objects [GAP]
Duplicate names among SPAWN_, CHECKPOINT_, CAMERA_, VOL_ objects are not checked.
A duplicated SPAWN_start (which Blender auto-renames to SPAWN_start.001) would have
its .001 stripped at export giving two continue-points the same name.
Our scene-wide counters now prevent this for NEW objects, but existing pre-fix
.blend files could still have duplicates.

### A7 — _spawn_objs and _checkpoint_objs don't filter out _CAM suffixes [GAP]
```python
def _spawn_objs(scene):
    return [o for o in _level_objects(scene)
            if o.name.startswith("SPAWN_") and o.type == "EMPTY"]
```
SPAWN_start_CAM also matches this — it starts with SPAWN_ and is an EMPTY.
check_spawn_points would count the camera anchor as a second spawn and generate
a spurious "Multiple Entry Spawns found" INFO message.
Fix: add `and not o.name.endswith("_CAM")` to both helpers.

### A8 — launcherdoor continue-name check references scene.objects [SCOPE BUG]
Same pattern as A2-A5 in check_doors.


---

## utils.py

### U1 — _prop_row timer fires after EVERY redraw until key exists [PERFORMANCE]
```python
bpy.app.timers.register(_init, first_interval=0.0)
```
`_prop_row` registers a new timer on EVERY draw frame where `key not in obj`.
If the panel redraws 30fps and the timer fires slightly late, multiple timers
may be queued simultaneously. Each calls `bpy.data.objects.get(name)` and
redundantly tries to write the default. The timer correctly returns None (no
repeat), but the queuing of multiple timers per key before the first fires is
a concern with fast redraws.
Fix: check if a timer for this key is already pending (hard) OR use a module-
level set to track "already scheduled" keys.

### U2 — _draw_wiki_preview word-wrap hardcodes 52 chars [MINOR]
Word wrap at 52 characters is hardcoded. Doesn't adapt to panel width.
Low severity — most descriptions are short. Not worth fixing now.

### U3 — _is_linkable checks `_is_custom_type(parts[1])` for all ACTOR_ empties [VERIFY]
Custom-type actors are always linkable. This seems intentional for custom GOAL
types with vol-trigger responses. Fine as long as custom types always support it.

---

## __init__.py


### I1 — __init__.py: og_lev1/og_disp1 not registered as RNA properties [DESIGN]
`og_lev1` and `og_disp1` are written as raw custom properties via `obj["key"] = value`.
Unlike registered RNA props (e.g. og_checkpoint_radius which is also raw),
these are new and could benefit from registration for better undo support.
However, ALL actor/spawn custom props use the same raw prop pattern — this is
a deliberate design choice in the addon. Consistent, but means no RNA-level
type enforcement. Note: same pattern as og_checkpoint_radius, og_navmesh_link, etc.

---

## panels.py

### PL1 — Build & Play panel calls .exists() 3 times per draw [PERFORMANCE]
`_gk().exists()`, `_goalc().exists()`, `_game_gp().exists()` on every panel redraw.
Each resolves the path through `_exe_root()` and `_data()`. The path helpers
are cached but `.exists()` still hits the filesystem. Under normal usage the panel
redraws less often than preferences, but during active build the modal fires every 0.5s.

### PL2 — data_ok check in Dev Tools panel is wrong [BUG]
```python
data_ok = _game_gp().parent.parent.parent.exists()  # goal_src/jak1 exists
```
`_game_gp()` = `_data() / "goal_src" / "jak1" / "engine" / "game" / "game.gp"`
So `.parent.parent.parent` = `_data() / "goal_src" / "jak1"` — which is 3 levels up.
Wait: parent1=engine/game, parent2=goal_src/jak1, parent3=goal_src.
Actually parent1=game/, parent2=jak1/, parent3=goal_src/, parent4=_data().
Let me recount: game.gp → parent=engine/game/ → parent=jak1/ → parent=goal_src/ → parent=_data().
So `.parent.parent.parent` = `_data()/goal_src/`. This exists even without jak1/ subfolder.
The comment says "goal_src/jak1 exists" but it actually checks "goal_src/ exists".
Off-by-one in the parent chain — should be `.parent.parent.parent.parent` to check `_data()`,
or just use `_game_gp().parent.exists()` to check `game/` folder.
Doesn't break anything since goal_src/ existing without jak1/ is very unusual.

### PL3 — _draw_lev1_settings shows for ALL spawns including _CAM anchors [UX BUG]
`_draw_selected_spawn` and `_draw_selected_checkpoint` are called for any object
starting with SPAWN_ or CHECKPOINT_ and not ending with _CAM.
BUT: what about SPAWN_start_CAM? It ends with _CAM so it's excluded correctly.
Actually this is fine — the CAM filter is already in the caller. Low severity.

### PL4 — Checkpoints panel _spawn_objs / _checkpoint_objs not filtering _CAM [BUG]
(Mirrors audit.py A7) The Checkpoints panel list uses:
```python
spawns = [o for o in lv_objs if o.name.startswith("SPAWN_") and o.type == "EMPTY"
          and not o.name.endswith("_CAM")]
```
This IS correct (the panel already filters _CAM). But audit.py's _spawn_objs
does NOT filter _CAM — they're different code paths.


---

## Cross-file / systemic

### X1 — _nick() truncates to 3 chars but doesn't verify uniqueness [BUG-RISK]
`_nick(n) = n.replace("-","")[:3].lower()`
Two level names that share first 3 non-dash chars produce identical nicknames.
Example: "my-level" and "my-castle" → both nick = "myc"/"myl"... OK in this case.
But "beach-1" and "beach-2" → both nick = "bea". This causes:
- Identical DGO names (BEA.DGO) — second overwrites first at build time
- Same vis-nick — level-select collisions in the engine
Fix: detect and error at export time if two levels would produce identical nick.

### X2 — _lname() strips and lowercases but doesn't re-validate [GAP]
`_lname()` calls `str(...).strip().lower().replace(" ", "-")` but doesn't re-validate
the regex. A level collection could have `og_level_name = "MY LEVEL!!"` set directly
(not through the validated operator), producing `_lname() = "my-level!!"` which
fails the regex check in operators but would not be caught if called from bg thread.
Fix: validate in `_lname()` itself or at the top of `_bg_build`.

### X3 — collect_spawns called from background thread with stale scene [THREAD RISK]
`_bg_build` runs on a background daemon thread. It calls `collect_spawns(scene)`,
`collect_actors(scene, depsgraph)`, etc. with the scene object passed from main thread.
Blender scenes are not thread-safe. The depsgraph is fetched on the main thread
(`ctx.evaluated_depsgraph_get()`) but scene access during a background thread
while the user modifies the scene could cause crashes or data corruption.
This is a fundamental Blender threading limitation — hard to fix without moving
all collection to the main thread and passing plain data (not Blender objects) to bg.
Low probability since the build takes over the UI (modal prevents most interaction),
but technically unsafe.

### X4 — write_gc, write_gd, write_jsonc are called from background thread [SAME]
These write files from the background thread. File I/O itself is fine, but
they also call _data(), _ldir(), _nick() etc. which access bpy.context —
not safe from bg thread. In practice bpy.context is accessible when the addon's
bg thread is running since Blender is idle (modal loop), but officially unsupported.

### X5 — Model preview GLB path comment in model_preview.py still mentions wrong path structure
Header comment says `<level_name>/<actor>-lod0.glb` but actual structure is
`levels/<level_name>/<actor>-lod0.glb`. Was partially corrected in the decompiler
path PR but the level structure description is wrong.

