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

### Chunk map (measured coupling)

Two signals matter. *Struct* references (who reads an editor's saved data) mostly
don't block removal, because we keep the DNA struct. *API* references (who calls an
editor's functions) DO block removal - those are what fail to link in an OFF build.

- **Drop-ready** (0 external API callers - the 8-edit recipe is enough): console,
  spreadsheet, outliner. (Outliner has 12 struct reads but 0 API calls, so it's clean.)
- **Leaf-but-needs-consumer-gating** (external API callers must be handled first):
  - text: undo registration, outliner's jump-to-text, the Text datablock RNA API.
  - info: `space_info/` also holds shared scene-statistics utilities
    (`ED_info_statistics_string`, `ED_info_stats_clear`, `ED_info_draw_stats`) used by
    the status bar, viewport, and RNA - so the stats code must be extracted from the
    editor folder before Info can drop cleanly.
- **Clusters** (remove as a group): animation editors (action/graph/nla/dopesheet share
  the anim-channel system); node editor (nodes subsystem); image editor (paint/UV/imbuf).
- **Effectively core**: 3D viewport (coupled via `ED_view3d` across 376 files),
  properties, file browser (backs every open/save dialog), topbar, statusbar, userpref, screen.

So the honest architecture is a mandatory spine + a ring of removable chunks -
a tiered model, not 25 flat independent toggles.

## The five plug points per editor

Two invariants keep removal clean:
1. **Never gate DNA.** Keep every `Space*` struct in `DNA_space_types.h` always -
   it's the `.blend` file-format contract, so files still load without the editor.
2. **The folder is the chunk**; gate it with a `WITH_SPACE_<NAME>` option.

For chunk `X` (see `manifests/blender-4.4.json` for the console instance):

1. `CMakeLists.txt` - add `option(WITH_SPACE_X ... ON)` (declaration only).
2. `editors/CMakeLists.txt` - `if(WITH_SPACE_X) add_definitions(-DWITH_SPACE_X)` near the
   top (before the subdirs, so it reaches `spacetypes.cc`), plus `if(WITH_SPACE_X)` around
   `add_subdirectory(space_X)`.
3. `makesrna/intern/CMakeLists.txt` - `if(WITH_SPACE_X) add_definitions(-DWITH_SPACE_X)`
   so the define reaches the **makesrna generator** that compiles `rna_space.cc`. This
   per-directory declaration mirrors how Blender itself re-declares WITH_PYTHON / WITH_CYCLES
   there, and is the guaranteed-correct propagation (see "CMake propagation" below).
4. `editors/space_api/spacetypes.cc` - `#ifdef WITH_SPACE_X` around `ED_spacetype_X();`.
5. `makesrna/intern/rna_space.cc` - `#ifdef` around both `rna_def_space_X()` and its
   dispatch call. (This shared file is the one spot the "just drop a folder" model
   breaks; a future cleanup splits it into per-editor fragments.)
6. `scripts/startup/bl_ui/__init__.py` - register the UI only `if hasattr(bpy.types,
   "SpaceX")`. Because the RNA type only exists when the chunk is compiled, the
   Python side self-adapts with no extra build-option needed. Mirrors Blender's own
   `bpy.app.build_options.freestyle` pattern.

### CMake propagation (resolved)

The `-DWITH_SPACE_X` define must reach two separate targets: the editors library
(compiles `spacetypes.cc`) and the makesrna generator (compiles `rna_space.cc`, whose
`#ifdef` decides what RNA gets emitted). A standalone CMake replica confirmed that
top-level `add_definitions` *does* inherit into a nested generator subdirectory - but
per-directory declaration also works and is what Blender ships, so the manifest declares
the define in `editors/` and `makesrna/intern/` directly. This removes the propagation
risk that was previously open.

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

### Validation (real v4.4.0 tree)

Manifest now covers **5 chunks** (console, spreadsheet, outliner = drop-ready;
text, info = need consumer-gating), generated from compact specs by
`manifests/gen_manifest.py` (adding an editor = adding a spec, not hand-writing edits).

All 5 instrumented onto one tree simultaneously (40 edits, incl. shared-anchor
stacking and spreadsheet's namespaced registration):

- `verify`: all guard blocks balanced across all 5 -> PASS.
- **Idempotent**: 2nd pass applies 0 edits.
- **Reversible**: `git checkout --` returns the tree byte-identical.
- Footprint: 6 files, 120 insertions, 5 deletions.
- **CMake propagation resolved** via replica + convention-matching (see above).

Not yet done: a real compile. The transform is proven correct textually, and the
macro-propagation path is settled; a full build (needs the prebuilt lib set and
significant time) would confirm end-to-end that a `-DWITH_SPACE_*=OFF` build drops
the editor cleanly and still loads a stock `.blend`. For the drop-ready chunks that
is the only remaining unknown; for text/info the listed consumers must be gated first.

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
