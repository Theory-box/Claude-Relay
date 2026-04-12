# Tpage Heap Research — Session Notes
**Last updated:** April 2026  
**Branch:** feature/tpage-combine (read-only research, no code changes this session)

## Status
Research complete. Knowledge doc written at `knowledge-base/opengoal/tpage-heap-research.md`.

## Key Finding
`LEVEL_HEAP_SIZE` is a single compile-time GOAL constant in `level.gc`. Changing it requires only a GOAL recompile (`goalc`), not a C++ rebuild. This is the easiest fix — one line, no C++ patching.

## Session Summary
Researched all vanilla escape routes for the tpage heap problem in OpenGOAL Jak 1. Found no way to avoid heap cost entirely without either:
- (A) Increasing `LEVEL_HEAP_SIZE` in level.gc (GOAL-only change), or
- (B) The custom_tex_remap C++ patch (already on feature/tpage-combine)

Full analysis of every vanilla JSON field and exploit path in the knowledge doc.

## Exploits Ruled Out
- `"textures"` selective list → FR3 only, no heap effect (but still worth using)
- `texture_replacements` → pixel swap only, art group still loads tpage
- `merc_replacements` → mesh/texture swap, auto weight transfer (no rigging needed!), still loads tpage
- `custom_models` → GLTF textures are heap-free, but can't remove art_groups (GOAL process dies without it)
- `tex_remap` copy → only copies existing level's remap table verbatim, no vanilla level covers cross-zone enemies

## Next Steps
1. Add `"textures"` selective lists to current custom levels (free FR3 savings, do now)
2. Choose between Track A (increase LEVEL_HEAP_SIZE locally) or Track B (upstream PR)
3. Consider upstream PRs for both the heap size increase and the custom_tex_remap patch
