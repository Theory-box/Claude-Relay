# OpenGOAL Addon — Session Notes

---

## ✅ Dev Build Path Bug — FIXED (research/community-feedback-apr15, commit 2bc1234)

**Root cause confirmed.** Both `export.py:35` and `build.py:86` define:
```python
def _data(): return _data_root() / "data"
```

For release builds, `data/` is a real subfolder — works. For dev env (jak-project clone),
there is NO `data/` subfolder. The addon creates it on first write, placing files at
`jak-project/data/custom_assets/...` instead of `jak-project/custom_assets/...`.

Consequence: `game.gp` and `level-info.gc` never patched → level never builds.
Also causes "Missing paths — open Developer Tools" in Build & Play panel (game.gp not found).
Also breaks enemy model previews (model_preview.py has same `/data` bug).
Also breaks `--proj-path` passed to gk/goalc.

**Full research in:** `scratch/research-community-feedback-apr15.md`

**Fix (one helper function, applied across 3 files):**
```python
def _data():
    root = _data_root()
    data_sub = root / "data"
    # Release: data/goal_src exists — use data_sub
    if (data_sub / "goal_src").exists() or (data_sub / "custom_assets").exists():
        return data_sub
    # Dev env: goal_src is at root — use root directly
    return root
```

Files to update: `export.py`, `build.py`, `model_preview.py`

**Also fix inverse bug:** `build.py:100` uses `_data_root() / "goal_src"` (vol-h.gc patch)
which WORKS on dev but BREAKS on release. Change to `_data() / "goal_src"`.

---

## Other Issues Found (same research session)

- **"Level Flow" rename:** trivial — `panels.py:112` `bl_label = "🗺  Level Flow"` → "🚩  Checkpoints"
- **Spawn vs Checkpoint confusion:** SPAWN_ = level-entry continue-point only. CHECKPOINT_ = continue-point + checkpoint-trigger actor. Both needed. Just need better labels.
- **lev1/disp1 per checkpoint:** engine supports it, addon hardcodes `lev1 #f`. Low effort to expose.
- **Debug spawn ordering:** reorder `:continues` list so chosen SPAWN_ is first — works for both vanilla and mod-base.
- **mod-settings.gc patch (mod-base):** bonus feature — detect and patch `*debug-continue-point*` on export.
- **Extracted models folder:** medium effort, decompiler_out GLBs already used for enemy previews.

---

## Current State (merged to main)
All features below are live on main.

## Features Shipped

### Waypoint Spawn Controls
- All "Add Waypoint at Cursor" buttons → "Spawn Waypoint"
- "Add Path B Waypoint" → "Spawn Path B Waypoint"  
- New "Spawn at Position" checkbox (waypoint_spawn_at_actor BoolProperty)
  - When checked: waypoint spawns at actor's world location
  - When unchecked (default): spawns at 3D cursor
  - Shared across all 6 waypoint buttons in 3 panels

### Duplicate Entity
- "Duplicate" button in Selected Object panel (ACTOR empties only)
- Operator: og.duplicate_entity
- Duplicates empty, strips inherited preview children, re-attaches fresh preview
- Inherits level collection membership from source (export-safe)
- Names follow ACTOR_<etype>_<n> convention

### Empty Fits to Viz Mesh Bounds
- On spawn, empty_display_size auto-set to largest bounding box half-extent
- Only runs on first GLB (double-lurker uses first mesh to size)
- Guarded: no-ops if mesh is degenerate (size <= 0.001)
- Purely cosmetic — never touches .scale, children unaffected

## Bug Fixed
- ctx->scene in _draw_selected_actor (standalone function, no ctx param)
