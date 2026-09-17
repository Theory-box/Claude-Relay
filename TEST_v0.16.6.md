# v0.16.6: Test Results

**Date:** 2026-09-16
**What it is:** v0.16.5 (geometry-first loading) plus three forward-ported fixes.
**Changes:** only `engine.py` and `__init__.py` differ from v0.16.5.

**Status:** installed and left installed. The repo copy (`addons/vertex_lit_renderer`) is synced. v0.16.5 is backed up in the scratchpad (`backup_v0165_20260916_212547`).

**Verdict: no issues found.** All three fixes work, and nothing regressed.

## Diff review
- `_vlr_viewport_live()` replaces the 2 s timestamp guard. It uses `_ENGINE_ID` (`'VERTEX_LIT'`, defined at module level), so there's no swallowed `NameError`.
- `_LAST_VIEW_UPDATE` was removed, and no references remain.
- The handler now also records `'mesh:<data name>'` for Object updates.
- `away_hit` in the instance loop is evaluated before the away-set is cleared in the `_needs_verify` block. That ordering is also confirmed at runtime (below).

## Priority 1: the three fixes

| check (`auto_test_v0161.py`) | v0.16.5 | **v0.16.6** |
|---|---|---|
| edit in Solid **immediately** after Rendered activity (vertex move, paint, UV; obj + linked dup) | 0/6 (recorded `[]`) | **6/6** (recorded `EditDup, EditObj, mesh:VLR_T_EditMesh`) |
| edit in Solid after waiting 2.5 s | 6/6 | **6/6** |
| scatter source mesh edited in Solid, then re-enter | FAIL | **PASS**: the instance's cached `i:` geometry is identical to a fresh extraction of the edited mesh |

**Runtime proof that the instance path reads the populated set:**
- **What was recorded:** snapshotted just before re-entry, the away-set held `['VLR_T_ScatObj_011', 'mesh:VLR_T_Scat_011']`.
- **What happened on re-entry:** the cached `i:VLR_T_Scat_011` entry was re-extracted and matched.
- **Why this proves it:** the viewport engine didn't exist during the edit, so `away_hit` is the only path that could have refreshed that key.

*Note: the earlier harness line "handler recorded []" in the scatter test was a harness artifact. It printed the set after re-entry, by which point the engine had already cleared it. The harness now snapshots the set before re-entry.*

## Priority 2: regression check vs v0.16.5

| | v0.16.5 | **v0.16.6** |
|---|---|---|
| Azola geometry on screen | 2.86 s | **2.76 s** |
| Azola fully loaded | 5.17 s | **4.97 s** |
| Azola warm re-entry | 0.06 s | **0.05 s** |
| unique meshes / triangles | 269 / 12.76M | **269 / 12.76M** |
| every object vs fresh legacy extraction | 393/394 | **393/394** (only `Cube.124` colours, the known material-colour issue) |
| F12 Azola | 12.37 s, 382/382 | **12.36 s, 382/382**, image identical (mean 0.3987 / std 0.2462) |
| edits in Rendered | 12/12 | **12/12** |
| share cache | bounded | **bounded** |
| scatter streaming | 150/150 in 0.6 s | **150/150 in 0.6 s** |
| selection click, 150 instances | 2.7 ms | **2.5 ms** |
| F12 generated scene | 0.63 s | **0.62 s** |
| instanced mesh edit (Rendered) | PASS | **PASS** |

*The notes quoted 12.26M triangles as a target. That was v0.16.4's number. v0.16.5 and v0.16.6 hold 12.76M: the pointer-plus-candidate-hash sharing merges very slightly fewer meshes than v0.16.4's hash-everything approach, and gives the same image.*

## Still open (unchanged)
1. **Material colour:** flat material colour is baked into the vertex colours at extraction (`Cube.124`; see TEST_v0.16.3.md).
2. **Huge textures:** three 10,800×7,200 packed JPEGs in Azola cost about 0.5 s each while streaming.
3. **Remaining audit items** in `REVIEW_v0.16.0.md`.
