# Session notes: source-chunking

Branch: `feature/source-chunking`
Topic: making Blender editors into compile-time-toggleable chunks (manifest-driven
injection), for building minimal purpose-built Blenders and a customize-and-rebuild tool.

## Status
- Design validated against real Blender **v4.4.0** source (cloned separately, not in repo).
- Engine `source-chunking/engine/chunk_engine.py` works end-to-end on the **console** chunk:
  instrument / verify / status; idempotent; reversible via git; 24 insertions / 1 deletion; 8 edits / 6 files.
- Manifest `source-chunking/manifests/blender-4.4.json` defines the console chunk (5 plug points).
- ccache + unity + path-normalization findings measured and written up in
  `source-chunking/experiments/ccache/RESULTS.md`.

## Key decisions
- Manifest-driven **injection** (stay close to upstream) over hard fork, so it ports across
  versions by writing a new manifest.
- Tiered chunk model: mandatory spine + removable ring. Not 25 flat toggles.
- Rebuild-often is the target use case -> unity ON but **chunk-aligned blobs**; ccache with
  **relative paths + CCACHE_BASEDIR**; mold linker.
- Python UI self-adapts via `hasattr(bpy.types, "SpaceX")` (no new bpy.app.build_options entry).

## Findings this pass
- Coupling by API-calls (not just struct refs) is the real removal blocker. Drop-ready: console,
  spreadsheet, outliner (0 external API callers). Needs work: text (undo/outliner/Text-RNA),
  and INFO especially - space_info/ contains shared scene-statistics utils (ED_info_statistics_string,
  ED_info_stats_clear, ED_info_draw_stats) used by statusbar/viewport/RNA; must be extracted first.
- gen_manifest.py turns compact specs into the full manifest -> scaling = add a spec.

## Open / next
- CMake propagation RESOLVED: define declared per-directory in editors/ and makesrna/intern/
  (mirrors Blender's own WITH_* re-declaration); confirmed by a standalone CMake replica.
- NOT YET COMPILED. A full build would confirm end-to-end drop + stock .blend still loads.
- DONE: added spreadsheet/outliner (ready) + text/info (flagged). Next leaves to consider: sequencer, clip.
- Handle coupled clusters: image editor (paint/uv), node editor (nodes), animation editors.
- Consider splitting `rna_space.cc` into per-editor fragments (keystone for truly clean source).

## Reproduce the engine test
Clone blender v4.4.0 separately, then from repo root:
`python3 source-chunking/engine/chunk_engine.py instrument source-chunking/manifests/blender-4.4.json space_console <blender_tree>`
then `verify`, then `git -C <blender_tree> checkout --` to revert.

## Notes
- Do NOT merge to main without explicit permission.
- Blender source is large; keep it OUT of this repo (clone separately for tests).
