# Research Notes — Community Feedback (15/04/2026)

Deep-dive into all issues raised by community tester.
Env: Blender 5.0.1 · mod-base `5599be3` · addon `b0577ea`

**Status:** Path bug fix implemented — commit `2bc1234` on `research/community-feedback-apr15`.
Awaiting test on a real dev build before merge to main.

---

## 1. 🔴 Dev Build Path Bug — Full Root Cause

### The single-line culprit

Both `export.py:35` and `build.py:86` define:

```python
def _data(): return _data_root() / "data"
```

Every path the addon uses (`_levels_dir`, `_goal_src`, `_level_info`, `_game_gp`, `_entity_gc`)
builds off `_data()`. So **every path the addon resolves silently appends `/data`** to whatever
the user set as `data_path`.

### Dev vs release folder structure

**Dev environment (jak-project clone):**
```
jak-project/
├── custom_assets/jak1/levels/     ← where files SHOULD go
├── goal_src/jak1/                 ← level-info.gc, game.gp live here
├── decompiler_out/jak1/levels/    ← where rip_levels GLBs land
└── (NO data/ subfolder)
```

**Release build:**
```
opengoal_vX.Y.Z/
└── data/
    ├── custom_assets/jak1/levels/ ← correct for release users
    ├── goal_src/jak1/             ← correct for release users
    └── decompiler_out/jak1/       ← correct for release users
```

For a release user, `data_path = opengoal_vX.Y.Z/`, so `_data()` = `opengoal_vX.Y.Z/data/` ✓

For a dev user, `data_path = jak-project/`, so `_data()` = `jak-project/data/` ✗ (folder doesn't exist, created on first write)

### Full blast radius

Every path resolution in the addon is broken for dev env:

| Path function | Broken result (dev) | Correct dev path |
|---|---|---|
| `_levels_dir()` | `jak-project/data/custom_assets/jak1/levels/` | `jak-project/custom_assets/jak1/levels/` |
| `_goal_src()` | `jak-project/data/goal_src/jak1/` | `jak-project/goal_src/jak1/` |
| `_level_info()` | `jak-project/data/goal_src/.../level-info.gc` | `jak-project/goal_src/.../level-info.gc` |
| `_game_gp()` | `jak-project/data/goal_src/jak1/game.gp` | `jak-project/goal_src/jak1/game.gp` |
| `_user_base()` (build.py:216) | `jak-project/data/goal_src/user/` | `jak-project/goal_src/user/` |
| `--proj-path` to gk/goalc | `jak-project/data/` (nonexistent) | `jak-project/` |
| `_glb_path()` in model_preview.py | `jak-project/data/decompiler_out/...` | `jak-project/decompiler_out/...` |

### The inverse bug (release breakage)

`build.py:100` uses `_data_root()` directly instead of `_data()`:

```python
vol_h = _data_root() / "goal_src" / "jak1" / "engine" / "geometry" / "vol-h.gc"
```

- **Dev env:** `data_root/goal_src/` exists → vol-h.gc patch works ✓
- **Release env:** `data_root/goal_src/` does NOT exist (it's at `data_root/data/goal_src/`) → patch silently skips ✗

So the vol-h.gc patch (trigger volume fix) is broken for release users. Opposite of the main bug.

### Why "Missing paths — open Developer Tools" appears

`panels.py:4050` checks:
```python
gk_ok  = _gk().exists()    # exe_path/gk — usually fine
gc_ok  = _goalc().exists()  # exe_path/goalc — usually fine
gp_ok  = _game_gp().exists() # data_path/data/goal_src/jak1/game.gp — DOESN'T EXIST on dev
```

The error label fires because `game.gp` resolves to a nonexistent path. Fix the path bug → error disappears.

### How gk/goalc handle --proj-path

From `common/util/FileUtil.cpp:201`:
1. If `--proj-path` passed → use it directly as "the data folder"
2. Else if `data/` folder exists next to exe → use that (release auto-detect)
3. Else if exe path contains `"jak-project"` → use the repo root (dev auto-detect)

The addon currently passes `_data()` (= `data_root/data`) as `--proj-path`. On dev env this
folder doesn't exist, so gk/goalc would fail immediately on launch. Fix: pass `_data()` after
it resolves correctly.

### Recommended fix: auto-detect in `_data()`

```python
def _data():
    root = _data_root()
    # Release: user points to parent of data/ — so data/goal_src exists
    data_sub = root / "data"
    if (data_sub / "goal_src").exists() or (data_sub / "custom_assets").exists():
        return data_sub
    # Dev env: user points to project root — goal_src/ is at root level
    return root
```

This requires zero UI changes and works transparently. Apply same logic in all three files
(`export.py`, `build.py`, `model_preview.py`). Also fix the `vol_h` path in `build.py` to
use `_data() / "goal_src"` instead of `_data_root() / "goal_src"` — resolving both bugs
at once.

---

## 2. Data Folder Documentation

### Current property description (properties.py:44)

```
"Your active jak1 source folder — the one that contains data/goal_src.
Usually .../jak-project/ or .../active/jak1/"
```

This description is contradictory: "contains data/goal_src" implies a release structure,
but "Usually .../jak-project/" is a dev environment. The auto-detect fix makes this moot,
but documentation should clarify the two cases anyway.

### Suggested updated description

```
"Project root folder. For a release build, point to the versioned folder
containing the 'data/' subfolder. For a dev environment (jak-project clone),
point directly to the repository root."
```

---

## 3. Per-Blend File Path Override

Currently `data_path` is an addon-level preference (`AddonPreferences`), shared across all
`.blend` files. To support multiple simultaneous projects, it would need to be promoted to a
scene-level `OGProperties` field with an "override" flag.

Architecture:
```python
# In OGProperties (scene-level):
data_path_override: StringProperty(
    name="Data Path Override",
    description="Override the global data path for this blend file only. Leave blank to use addon preferences.",
    subtype="DIR_PATH",
    default="",
)
```

Then `_data_root()` in export.py becomes:
```python
def _data_root():
    # Check scene-level override first
    scene = bpy.context.scene
    if scene and scene.og_props.data_path_override.strip():
        p = scene.og_props.data_path_override
    else:
        prefs = bpy.context.preferences.addons.get("opengoal_tools")
        p = prefs.preferences.data_path if prefs else ""
    return Path(p.strip().rstrip("\\").rstrip("/")) if p.strip() else Path(".")
```

This is a moderate amount of work (update all 3 files + add UI field + expose in panels).

---

## 4. Extracted Models Folder (Background Geometry)

### What already exists

`model_preview.py` already loads enemy preview GLBs from the decompiler output:
```
decompiler_out/jak1/levels/<level>/<model>-lod0-mg.glb
```

Enabled by `rip_levels: true` in `jak1_config.jsonc`. The addon reads these as viewport
stand-ins for enemy actors. When the path bug is fixed, this will also work for dev users.

### The user's proposal

A third preference path pointing to a folder of extracted level geometry GLBs. Two uses:
1. **Visual reference:** Load a vanilla level's background geometry as a template to help
   place custom level elements relative to existing geometry.
2. **Actor model loading:** When spawning a custom actor type, load its GLB from this folder
   so the addon doesn't need to bundle game assets (legal + file size win).

### What it would take

The decompiler already extracts level background meshes via `rip_levels: true`:
```
decompiler_out/jak1/levels/beach/beach-vis-tfrag-0-mg.glb  (example)
```

A new preference path field pointing to a folder (defaulting to `decompiler_out/jak1/levels/`)
would let users browse and import these. The addon would need:

1. New pref: `models_path: StringProperty(subtype="DIR_PATH")` — defaults to auto-resolved
   `decompiler_out/jak1/` relative to `_data_root()`.
2. A "Import Background Geo" operator that lists GLBs in the selected level folder and imports
   them as non-exportable reference objects.
3. For actor model loading: the actor spawn flow could check `models_path / "<etype>*.glb"`
   before falling back to bundled preview images.

Effort: medium. The heavy lifting (GLB import pipeline) already exists in `model_preview.py`.

---

## 5. "Level Flow" Panel Rename

### Current code (panels.py:112)

```python
class OG_PT_SpawnLevelFlow(Panel):
    bl_label = "🗺  Level Flow"
```

One-line change. Suggested: `"🚩  Checkpoints"` or `"🚩  Checkpoints & Boundaries"`.

The class name `OG_PT_SpawnLevelFlow` can stay as-is (internal identifier, not user-visible).

---

## 6. SPAWN_ vs CHECKPOINT_ — What's the Actual Difference

This caused user confusion ("you shouldn't need both"). The distinction is real but subtle:

### SPAWN_ empties

- Exported as a **`continue-point` entry** in `level-info.gc` `:continues` list only.
- No in-game actor. The game uses the first `:continues` entry as the starting spawn point.
- Purpose: where Jak starts and where he respawns if he dies before hitting any checkpoint.

### CHECKPOINT_ empties

- Exported as a **`continue-point` entry** in `level-info.gc` `:continues` list **AND** a
  `checkpoint-trigger` actor in the JSONC.
- The `checkpoint-trigger` actor calls `set-continue!` when Jak walks into its sphere/AABB.
- Purpose: mid-level save point — once triggered, Jak respawns HERE instead of the start.

### Why you need at least one SPAWN_

The game always initialises to the **first** entry in the `:continues` list. Without a SPAWN_,
there's no "level entry" continue point — the list would only have mid-level checkpoints, which
is valid but means you always start mid-level.

### Suggested UI clarification

Rename the dropdown options:
- "Player Spawn" → **"Level Entry Spawn"** (clearer that this is the starting point)
- "Checkpoint" → **"Mid-Level Checkpoint"** (clearer that this is a triggered save point)

Add a tooltip: "Entry spawn = where Jak starts the level. Checkpoint = a trigger that updates
the spawn point when Jak walks through it."

---

## 7. Continue-Point Structure (for lev0/lev1 per-checkpoint feature)

### Full struct (from level-info.gc and game-info-h.gc)

```lisp
(new 'static 'continue-point
    :name    "my-level-start"     ; string — must be unique across ALL levels
    :level   'my-level            ; symbol — which level-load-info owns this
    :flags   (continue-flags ())  ; optional: warp, game-start, etc.
    :trans   (new 'static 'vector :x ... :y ... :z ... :w 1.0)
    :quat    (new 'static 'quaternion :x ... :y ... :z ... :w ...)
    :camera-trans (new 'static 'vector :x ... :y ... :z ... :w 1.0)
    :camera-rot   (new 'static 'array float 9 ...)
    :load-commands '()
    :vis-nick 'none               ; 'none for custom levels (no vis data)
    :lev0 'my-level               ; PRIMARY level to load on respawn
    :disp0 'display               ; display mode for lev0
    :lev1 #f                      ; SECONDARY level (e.g. 'village1 for backdrop)
    :disp1 #f)                    ; display mode for lev1 (#f = off)
```

### How lev0/lev1 work at runtime (target-death.gc:77)

On player death, the engine applies the current continue-point's lev0/lev1 to the load-state:
```lisp
(set! (-> *load-state* want 0 name)     (-> arg0 lev0))
(set! (-> *load-state* want 0 display?) (-> arg0 disp0))
(set! (-> *load-state* want 1 name)     (-> arg0 lev1))
(set! (-> *load-state* want 1 display?) (-> arg0 disp1))
```
Then waits for both levels to be `'active` before teleporting Jak to `:trans`.

### Display modes

- `'display` — load and fully display the level
- `'special` — load but use restricted display (used by vanilla for adjacent areas like
  beach when in village1)
- `#f` — don't load/display at all

### Addon currently generates

The addon hardcodes:
```python
f"             :lev0 '{name}\n"
f"             :disp0 'display\n"
f"             :lev1 #f\n"
f"             :disp1 #f)"
```

So on respawn, ONLY the custom level loads. If the custom level borders a vanilla level,
the backdrop disappears on death/respawn until the engine auto-loads the neighbor.

### Exposing lev1/disp1 per checkpoint

Most custom levels won't need this — `:lev1 #f` is correct for standalone levels.
For levels that border or overlay vanilla geometry, exposing these as optional dropdown
fields on the SPAWN_/CHECKPOINT_ empty would be useful:

```python
# On SPAWN_/CHECKPOINT_ empties:
og_lev1:  StringProperty(default="")      # blank = #f, otherwise e.g. "village1"
og_disp1: EnumProperty(items=[("none","None",""),("display","Display",""),
                               ("special","Special","")])
```

Effort: low. Already-existing lump pattern, just extend `_make_continues()` to read
these from the empty's custom properties.

---

## 8. Debug Spawn Point

### mod-settings.gc (mod-base only)

`*debug-continue-point*` is a **mod-base addition** — it does not exist in the vanilla
`goal_src`. The vanilla `play` function in `level.gc:986` just loads `village1` on boot:
```lisp
(('play) (if *debug-segment* 'village1 'title))
```

And picks the **first `:continues` entry** of whatever level is loaded:
```lisp
(if (-> gp-1 info continues)
    (set-continue! *game-info* (the-as continue-point (car (-> gp-1 info continues)))))
```

### What the addon can control today

The `:continues` list order in `level-info.gc` determines the default spawn. If the addon
exposes "default spawn" selection in the UI — just reordering which SPAWN_ empty appears
first in the list — it works identically on both vanilla and mod-base.

### mod-base approach

mod-base adds to `mod-settings.gc`:
```lisp
(define *debug-continue-point* "village1-hut")
```

The mod-base engine reads this at startup and calls `set-continue!` with it. The addon
could either:

**Option A (works for both):** Expose a "Default Spawn" dropdown showing all SPAWN_/
CHECKPOINT_ names, and reorder the `:continues` list so the selected one is first.

**Option B (mod-base only):** Detect `mod-settings.gc` exists and patch it automatically
on export to set `*debug-continue-point*` to the selected spawn name.

Option A is simpler and universal. Option B is a bonus for mod-base users.

File locations (from tester's notes):
- mod-base: `goal_src/jak1/engine/mods/mod-settings.gc` → `(define *debug-continue-point* "village1-hut")`
- vanilla:  `goal_src/jak1/engine/level/level.gc` → `play` function

---

## 9. Checkpoint Level Load State (lev0/lev1 UI)

See section 7 above. The short version: fully supported by engine, not exposed by addon.
Key valid values for `disp1` when using a vanilla level as backdrop:

| Level context | Suggested lev1 | disp1 |
|---|---|---|
| Custom level standalone | `#f` | `#f` |
| Custom level in beach area | `'beach` | `'special` |
| Custom level in village1 area | `'village1` | `'special` |
| Need full secondary level | any level symbol | `'display` |

The `'special` mode loads but limits which polygons are drawn — appropriate for backdrops.
`'display` would be used if two full levels should both be visibly active simultaneously.

---

## 10. Summary: What to Fix and In What Order

| # | Issue | Effort | Affects |
|---|---|---|---|
| 1 | `_data()` auto-detect (path bug) | Low — 1 helper function across 3 files | All dev users, completely blocked |
| 2 | Fix `vol_h` inverse bug in build.py | Trivial — 1 line | All release users, vol triggers |
| 3 | Update `data_path` description text | Trivial | Onboarding clarity |
| 4 | Rename "Level Flow" → "Checkpoints" | Trivial — 1 string | UI clarity |
| 5 | Rename spawn dropdown items | Trivial — 2 strings | UI clarity |
| 6 | Per-blend path override | Medium | Multi-project users |
| 7 | lev1/disp1 per checkpoint | Low | Adjacent-vanilla-level users |
| 8 | Default spawn ordering / mod-settings.gc | Low–Medium | All users (QoL) |
| 9 | Extracted models folder pref | Medium | Visual reference workflow |

Items 1–5 can all be done in one session. Items 6–9 are separate features.

---

## Appendix: File Reference

- `addons/opengoal_tools/export.py:27-38` — path helpers (all affected)
- `addons/opengoal_tools/build.py:79-100,216,249,276` — path helpers + vol-h inverse bug
- `addons/opengoal_tools/model_preview.py:25-36` — decompiler_out path affected
- `addons/opengoal_tools/panels.py:112,4050` — Level Flow label + missing-paths check
- `addons/opengoal_tools/properties.py:44-51` — data_path description
- `addons/opengoal_tools/export.py:1235-1330` — collect_spawns (SPAWN_ vs CHECKPOINT_)
- `addons/opengoal_tools/export.py:2285-2333` — _make_continues (lev0/lev1 hardcoded)
- `jak-project/goal_src/jak1/engine/target/target-death.gc:77` — how lev0/lev1 apply
- `jak-project/common/util/FileUtil.cpp:201` — how --proj-path is handled
