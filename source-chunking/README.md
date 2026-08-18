# Blender source chunking

Goal: make Blender's editors into compile-time-toggleable "chunks" so a minimal,
purpose-built Blender (e.g. "just the image editor as a mood-board app") can be
produced by choosing which chunks to include - and so a user tool can let people
pick chunks and rebuild quickly.

Approach: **manifest-driven injection**, not a hard fork. A generic engine reads a
per-version manifest describing where each editor's plug points are, and injects
`WITH_SPACE_<NAME>` guards. Stock files stay close to upstream, so the scheme
ports to new Blender versions by writing a new manifest, not rewriting the tool.

## What the source actually looks like (Blender 4.4)

- `source/blender/editors/` is ~740K lines - nearly half the code - and it is
  exactly the toggleable units (each editor is a `space_*` folder).
- Editors register through **one hard-coded list**: `ED_spacetypes_init()` in
  `editors/space_api/spacetypes.cc`.
- 252 `WITH_*` compile flags already exist; Cycles already builds standalone;
  `WITH_HEADLESS` already builds with no UI. The architecture is ~halfway here.

### Chunk map (measured by external coupling to each editor's data struct)

- **Clean leaves** (remove with just the plug-point edits): console, info,
  spreadsheet, outliner, text.
- **Semi-independent**: sequencer, clip.
- **Clusters** (remove as a group): animation editors (action/graph/nla/dopesheet
  share the anim-channel system); node editor (nodes subsystem); image editor
  (texture paint + UV + imbuf).
- **Effectively core** (keep for a usable general app): 3D viewport (coupled via
  the `ED_view3d` API across 376 files), properties, file browser (backs every
  open/save dialog), topbar, statusbar, userpref, screen.

So the honest architecture is a mandatory spine + a ring of removable chunks -
a tiered model, not 25 flat independent toggles.

## The five plug points per editor

Two invariants keep removal clean:
1. **Never gate DNA.** Keep every `Space*` struct in `DNA_space_types.h` always -
   it's the `.blend` file-format contract, so files still load without the editor.
2. **The folder is the chunk**; gate it with a `WITH_SPACE_<NAME>` option.

For chunk `X` (see `manifests/blender-4.4.json` for the console instance):

1. `CMakeLists.txt` - add `option(WITH_SPACE_X ... ON)` + `add_definitions(-DWITH_SPACE_X)`.
2. `editors/CMakeLists.txt` - `if(WITH_SPACE_X)` around `add_subdirectory(space_X)`.
3. `editors/space_api/spacetypes.cc` - `#ifdef WITH_SPACE_X` around `ED_spacetype_X();`.
4. `makesrna/intern/rna_space.cc` - `#ifdef` around both `rna_def_space_X()` and its
   dispatch call. (This shared file is the one spot the "just drop a folder" model
   breaks; a future cleanup splits it into per-editor fragments.)
5. `scripts/startup/bl_ui/__init__.py` - register the UI only `if hasattr(bpy.types,
   "SpaceX")`. Because the RNA type only exists when the chunk is compiled, the
   Python side self-adapts with no extra build-option needed. Mirrors Blender's own
   `bpy.app.build_options.freestyle` pattern.

## The engine

`engine/chunk_engine.py` - manifest-driven, textual transform only (does not compile).
Contract: apply all plug points correctly, **idempotently**, and **reversibly**.

```
chunk_engine.py instrument <manifest.json> <chunk> <blender_tree>
chunk_engine.py verify     <manifest.json> <chunk> <blender_tree>
chunk_engine.py status     <manifest.json> <chunk> <blender_tree>
```

Every guard emitted is tagged (`#endif /* WITH_X */`, `endif() # WITH_X`) so
`verify` proves open/close balance exactly.

### Validation (console chunk, real v4.4.0 tree)

- 6 edits applied across 5 files; footprint = 17 insertions, 1 deletion.
- `verify`: all guard blocks balanced -> PASS.
- **Idempotent**: 2nd `instrument` applies 0 edits (identical diff).
- **Reversible**: `git checkout --` returns the tree byte-identical.

Not yet done: a real compile. The transform is proven correct textually; the exact
CMake macro-propagation point (top-level `add_definitions` vs per-target) still
needs confirmation on an actual build.

## Build speed (see experiments/ccache/RESULTS.md)

ccache + chunking is a strong match for rebuild-often use: after one cold build,
toggling chunks recompiles only the changed chunks (~15x faster reconfigure in the
model). Requirements: compile with **relative paths + `CCACHE_BASEDIR`** (absolute
paths give 0% cache hits across checkouts), use **mold**, and keep **unity blobs
chunk-aligned** (never mix spine + chunk files in one blob).

## Next steps

- Add the clean-leaf chunks (text, info, spreadsheet, outliner) to the manifest.
- Prototype a real build of a 1-2 chunk config to confirm CMake propagation.
- Design the cluster handling (image/paint, nodes, animation).
- Fold recommended fast-build settings into the manifest per app profile.
