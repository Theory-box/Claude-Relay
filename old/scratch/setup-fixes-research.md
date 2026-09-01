# Setup Fixes — Research Notes
Branch: `feature/setup-fixes`

---

## Bug 1: data/ subfolder path problem

### What's broken
In both `build.py` and `export.py`, `_data()` is hardcoded as:
```python
def _data(): return _data_root() / "data"
```

This always appends `"data"` to whatever `data_path` the user provides.

### Why it breaks on dev builds
OpenGOAL has two distinct folder layouts:

**Release build** (user downloaded an OpenGOAL release, ran the extractor):
```
<install>/
  data/
    goal_src/jak1/game.gp        ← what we need to edit
    goal_src/jak1/engine/level/level-info.gc
    custom_assets/jak1/levels/
    decompiler_out/jak1/
```
→ User should point `data_path` to `<install>/` — `_data()` appending `/data` is correct.

**Dev build** (user cloned jak-project and builds from source):
```
jak-project/
  goal_src/jak1/game.gp          ← flat, no data/ layer
  goal_src/jak1/engine/level/level-info.gc
  custom_assets/jak1/levels/
  decompiler_out/jak1/
```
→ User should point `data_path` to `jak-project/` — `_data()` appending `/data` makes all paths wrong.

**Confirmed via two sources:**
1. Sparse clone of `https://github.com/open-goal/jak-project` — `goal_src/` lives at repo root.
2. `Taskfile.yml` in jak-project — decompiler is run as `decompiler "./decompiler/config/..." "./iso_data" "./decompiler_out"` from the repo root, confirming `decompiler_out/` is also at root level with no `data/` layer.

### The fix (from feedback branch, confirmed correct)
Replace the simple `_data()` with auto-detection:
```python
def _data():
    root = _data_root()
    # Dev env: goal_src/jak1 is at root — no data/ layer
    if (root / "goal_src" / "jak1").exists():
        return root
    # Release layout: goal_src is inside data/
    return root / "data"
```

The heuristic is unambiguous — `goal_src/jak1/` is never created by the addon itself (addon only writes inside `goal_src/jak1/levels/` and `custom_assets/`).

### Also needs fixing
- `_user_base()` in `build.py` was `_data_root() / "data" / "goal_src" / "user"` — should use `_data()` instead
- `vol-h.gc` path was `_data_root() / "goal_src" / ...` — should also use `_data()`
- The `data_path` label in `properties.py` needs updating to be clear about both layouts
- Add live validation in `draw()` so users can confirm their path resolved correctly

---

## Bug 2 / Feature: decompiler_out path

### What it's for
The decompiler rips level GLBs and texture PNGs from the game. These are needed for:
- Enemy model previews (already partially implemented via `model_preview.py`)
- Texture browser
- Background geometry reference imports (new feature)

### Folder structure inside decompiler_out/jak1/
```
decompiler_out/jak1/
  textures/<tpage_name>/<texture>.png   (rip with save_texture_pngs: true)
  <level_name>/<actor>-lod0.glb         (rip with rip_levels: true — actor models)
  <level_name>/<level_name>-background.glb  (same — background geo)
```
Confirmed via: `decompiler/config/jak1/jak1_config.jsonc` comments AND `Taskfile.yml` — decompiler is run as `decompiler config iso_data ./decompiler_out` from the project root. The `/jak1/` subfolder is added by the decompiler tool itself based on the game config.

### Auto-detection
After the `_data()` fix, auto-detect is simply:
```python
_data() / "decompiler_out" / "jak1"
```
This is correct for both dev and release layouts — `decompiler_out/` sits at the same level as `goal_src/`.

### Implementation plan
1. Add `decompiler_path: StringProperty` to `OGPreferences` (new optional pref)
2. Add `_decompiler_path() -> Path` helper in `build.py` (and exported from `export.py`)
   - If pref is non-empty: use it directly
   - If empty: auto-detect as `_data() / "decompiler_out" / "jak1"`
3. Update `draw()` to show the path + validation status (is it populated?)
4. Wire the helper into `model_preview.py` (replaces any hardcoded paths)

---

## Feedback branch assessment (`research/community-feedback-apr15`)

The branch has started both of these changes but has issues — it's doing too much at once and the diff has broken code:
- A `_patch_vol_h_enabled()` function body is floating outside any function (orphaned after a bad edit)
- Docstring fragments left as orphaned strings
- Also making unrelated changes (vol-h patch opt-in pref, etc.)

**We're NOT pulling from that branch.** We implement cleanly from scratch on `feature/setup-fixes`.

---

## Implementation order (to be done in separate sessions)

1. **Fix `_data()` detection** — `build.py` + `export.py` + `properties.py` label + live validation UI
2. **Add `decompiler_path` pref** — `properties.py` + `build.py` helper + `model_preview.py` wire-up
3. Background geo import operator (separate session)
