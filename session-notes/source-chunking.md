# Session notes: source-chunking

Branch: `feature/source-chunking`
Topic: making Blender editors into compile-time-toggleable chunks (manifest-driven
injection), for building minimal purpose-built Blenders and a customize-and-rebuild tool.

## Status
- Design validated against real Blender **v4.4.0** source (cloned separately, not in repo).
- Engine `source-chunking/engine/chunk_engine.py` works end-to-end on the **console** chunk:
  instrument / verify / status; idempotent; reversible via git; 17 insertions / 1 deletion.
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

## Open / next
- NOT YET COMPILED. Confirm CMake `-DWITH_SPACE_*` propagation reaches both the editors lib
  and the makesrna generator on a real build.
- Add clean-leaf chunks to manifest: text, info, spreadsheet, outliner.
- Handle coupled clusters: image editor (paint/uv), node editor (nodes), animation editors.
- Consider splitting `rna_space.cc` into per-editor fragments (keystone for truly clean source).

## Reproduce the engine test
Clone blender v4.4.0 separately, then from repo root:
`python3 source-chunking/engine/chunk_engine.py instrument source-chunking/manifests/blender-4.4.json space_console <blender_tree>`
then `verify`, then `git -C <blender_tree> checkout --` to revert.

## Notes
- Do NOT merge to main without explicit permission.
- Blender source is large; keep it OUT of this repo (clone separately for tests).
