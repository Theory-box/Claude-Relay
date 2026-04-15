# Community Feedback & Feature Tracking — Jak 1 Addon

Collected from community testing. Last updated 15/04/2026.

---

## Status Key
- ✅ Fixed / implemented
- 🔬 Researched, documented, not yet in code
- 🏗 Future work (significant scope)
- ❌ Not addon issue

---

## CRITICAL

### ✅ Folder Structure Bug
Addon created `data/` subfolder instead of using existing structure. Dev builds wrote to the wrong location, `game.gp` and `level-info.gc` were never edited, levels never built.

**Fix:** Auto-detect in `_data()`: checks if `goal_src/jak1/` exists at the given root → dev env; otherwise appends `/data/` → release layout. Works for all four user configurations:
- Dev env pointing to repo root → `✓ goal_src found here`
- Release pointing to `data/` directly → `✓ goal_src found here`
- Release pointing to parent of `data/` → `✓ goal_src found in data/`
- Wrong path → warning label in preferences

Also fixed: inverse bug where vol-h.gc engine patch worked on dev but broke on release.

---

## Setup

### 🔬 Per-Blend File Path Override
`data_path` is an addon-level preference, shared across all `.blend` files. Needed for multi-project workflows.

**Plan:** Add `data_path_override: StringProperty` to `OGProperties` (scene-level). `_data_root()` reads scene override first, falls back to addon prefs. Medium effort.

### 🏗 Extracted Game Models Folder
A third preference path pointing to extracted game models from the decompiler. Two uses:
1. Actor model loading without bundling game assets (legal + file size)
2. Background geometry placement reference when working adjacent to vanilla levels

The decompiler already outputs level GLBs to `decompiler_out/jak1/levels/` when `rip_levels: true`. The addon's `model_preview.py` already loads these for enemy previews — same infrastructure. Needs a UI entry point and an import operator.

---

## Naming / UX

### ✅ "Level Flow" → "Checkpoints"
Panel renamed to `🚩  Checkpoints`. Enum labels updated: "Player Spawn" → "Entry Spawn" with clear descriptions explaining the distinction. Audit messages updated.

### ✅ Spawn/Checkpoint distinction clarified
UI now explains: Entry Spawn = where Jak starts and respawns before any checkpoint triggers. Checkpoint = mid-level trigger that updates the respawn point when Jak walks into it.

---

## Checkpoints

### 🔬 Quaternion Rotation Bug
Tester reports: rotation only works correctly when checkpoint empty is aligned to global axis.

**Analysis:** The `R_remap @ m3 @ R_remap^T` then conjugate formula is mathematically correct for single-axis rotations (verified). Bug may be in combined-axis rotations or user expectation about which Blender arrow = game forward direction.

**Convention:** Green arrow (+Y) = Jak's facing direction in game. The blue (+Z) arrow is NOT forward.

**For next test session:** Test with specific combined rotations to reproduce the exact failure case. The tester offered more detail — should follow up.

### 🔬 Checkpoint Radius Does Nothing
Tester: "radius field does nothing even at 10 meters."

**Most likely cause:** The `og_no_export` bug (see below) was dropping checkpoints from the JSONC entirely. The radius lump itself (`["meters", r]` read by `res-lump-float`) looks correct in code. Verify in next test session after og_no_export fix is deployed.

### ✅ Volume Triggers Broken / Invisible in Debug
Root cause: `_level_objects()` defaulted to `exclude_no_export=True`. Any collection marked no-export silently dropped ALL its objects — including checkpoints and trigger volumes — from the level data.

**Fix:** Changed default to `False`. The no-export flag now only affects GLB geometry collection in `export_glb`.

Additionally: vol-mark debug display doesn't show our triggers because our `process-drawable` subtypes never initialize their `vol` field. This is by design — the native vol-control system (see volume overhaul below) would fix this.

### ✅ Multi-Arrow Display
Checkpoint empties now use `ARROWS` display type instead of `SINGLE_ARROW`. Facing direction is immediately visible in viewport.

### ✅ Camera as Child of Checkpoint
`spawn_cam_anchor` now parents the camera empty to the spawn/checkpoint. Moving/rotating the spawn drags the camera. `collect_spawns` updated to use `matrix_world.translation` for correct world-space export of parented cameras.

### 🔬 Per-Checkpoint Level Load State
The `lev1`/`disp1` fields on `continue-point` structs control which secondary level loads on respawn. The addon hardcodes `lev1 #f`. Exposing this per-checkpoint would allow custom levels adjacent to vanilla geometry to keep the backdrop loaded on death.

**Plan:** Add `og_lev1: StringProperty` and `og_disp1: EnumProperty` to spawn/checkpoint empties. Read in `_make_continues()`. Low effort.

### 🔬 Debug Spawn Selector (`*debug-continue-point*`)
`*debug-continue-point*` is a mod-base addition. Vanilla `play` picks the first `:continues` entry.

**Plan (works for both vanilla and mod-base):** Expose "Default Spawn" dropdown in panel showing all SPAWN_/CHECKPOINT_ names. Reorder `:continues` list so selected one is first on export. Bonus for mod-base: auto-patch `mod-settings.gc` on export.

### 🔬 Per-Level `deftype` Architecture
`checkpoint-trigger`, `camera-trigger`, `camera-marker`, `aggro-trigger` defined per-level in `*-obs.gc`. If two custom levels load simultaneously, the type gets defined twice.

**Conclusion from research:** This IS the vanilla pattern — `launcherdoor.o` appears in `JUN.DGO`, `MAI.DGO` etc. Safe when only one level loads at a time. Problematic for multi-level mods with simultaneous loading.

**Plan:** For future multi-level mod support, move shared types to a community common file coordinated with mod-base maintainers. Not a blocking issue for single-level use.

### 🏗 Volume System Overhaul (AABB → Native Volumes)
Current trigger volumes are axis-aligned bounding boxes only. Game's native vol-control system supports arbitrary concave shapes and is what vol-mark debug display renders.

Tester provided a Discord script for creating volumes from mesh geometry using the game's native res-lump volume format. This would also fix water volumes.

**Discord resource:** https://discord.com/channels/967812267351605298/973327696459358218/1280548232283557938

**Impact:** Major architectural change to trigger/volume system. Also required for water volumes. High priority for usability.

---

## Other Bugs

### ✅ Collections "Ignored for Export" Also Suppressed Checkpoints
Same root cause as volume trigger bug. Fixed by og_no_export default change.

### ✅ REPL Warning "Compilation generated code, but wasn't supposed to"
Caused by `user.gc` containing `define-extern` declarations compiled with `allow_emit=false`. 

**Fix:** Removed the `define-extern` declarations — `bg`, `bg-custom`, `*artist-all-visible*` are already in the game's symbol table when connected via `(lt)`.

### ❌ Blender 5.0.1 GLTF Exporter Drops Custom Properties
Not addon-related. Blender upstream regression. Use Blender 4.5.2 until fixed.

---

## Q&A — Previously Documented Community Questions

### Q1 — Custom Actors & Custom Lumps
See original Q&A below for full analysis.

`og_lump_*` passthrough pattern documented. Custom actor Option A (catch-all type) documented.

### Q2 — Multiple Levels Per Blend File
One level per scene currently. Per-collection level settings needed for full support. Workaround: multiple Blender scenes in same .blend file.

### Q3 — Full JSON Regeneration vs Incremental
Full regen every time. Best long-term fix: implement Q1 so manual JSONC edits aren't needed.

---

## Positive Feedback

- **Quick Geo Rebuild works well** ✅
- **Core export pipeline functional on release builds** ✅ (after path fix)

---

## Priority Order for Next Work

| # | Item | Effort | Blocks |
|---|---|---|---|
| 1 | Checkpoint rotation quaternion — diagnose with tester | Low | Usability |
| 2 | Checkpoint radius verify after og_no_export fix | Test only | Usability |
| 3 | Per-checkpoint lev1/disp1 exposure | Low | Multi-area levels |
| 4 | Debug spawn selector | Low–Med | Testing speed |
| 5 | Per-blend path override | Medium | Multi-project |
| 6 | Native volume system overhaul | High | Water volumes, debug display |
| 7 | Extracted models folder | Medium | Legal/size |
