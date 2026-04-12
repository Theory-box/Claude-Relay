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

---

## Testing Session — April 12 2026

### What we tried
Changed `LEVEL_HEAP_SIZE` from `(* 10416 1024)` to `(* 24000 1024)` in `level.gc`.

### Result: NOT WORKING YET

The heap size reported in the crash log is still `11264000 bytes` (= `11000 * 1024`) across all three test attempts. The change is not reaching the compiled output.

### Root cause (suspected)
OpenGOAL has at least two copies of `level.gc`:
- `active/jak1/data/goal_src/jak1/engine/level/level.gc`
- `versions/official/v0.3.1/data/goal_src/jak1/engine/level/level.gc`

The build system compiled `level.gc` (confirmed in build log: `[0%] [goalc] 0.039 goal_src/jak1/engine/level/level.gc`) but the heap size didn't change — meaning the file that was edited is not the file the REPL/build system is actually reading. The REPL's working directory is unclear and `asm-file` returned no output, suggesting the relative path isn't resolving.

Note: `11264000 = 11000 * 1024` which is `LEVEL_HEAP_SIZE_DEBUG` from the PC_PORT branch — not the main value. This suggests the DEBUG path is being used, which means `compact-level-heaps` may be `#t` in some code path, or the wrong branch is being hit.

### What needs resolving next session
1. Find the exact file the REPL build system reads — use Windows search for all `level.gc` copies, open each and check which one still has `10416`
2. Alternatively: find `out/obj/level.o` and delete it, then edit every copy of `level.gc` to `24000`, then `(mi)`
3. Verify the change actually landed by checking the kheap dump in the log — should show `24576000` not `11264000`
4. Consider why `11000` (DEBUG value) is being used instead of `10416` (main value) — may indicate `compact-level-heaps` is `#f` after all and the DEBUG constant is what's active in this build

### Crash details (unchanged across all attempts)
```
used bot: 7012912 of 11264000 bytes
used top: 4194352 of 11264000 bytes
kmalloc: !alloc mem data-segment (404928 bytes) heap 4f00f0
dkernel: unable to malloc 404928 bytes for data-segment
```
Heap is completely full trying to load tpage-521 (last tpage in the level DGO).

### Tpages loading in MYL.DGO (a lot)
tpage-398, 400, 399, 401, 1470 (village1 sky — expected)
tpage-385, 531, 386, 388 (jungle)
tpage-212, 214, 213, 215 (beach)
tpage-516, 521 (unknown — crash happens here)

That's 13 tpages total. Even with 24MB heap this many tpages may be tight. Worth auditing the level's `"tpages"` list — some of these may be unnecessary.

---

## Third Test — Still failing (April 12 2026)

Heap size still showing `11264000` = `11000 * 1024`. The edited file is still not the one being compiled.

**New finding from log analysis:** The level is loading more tpages than expected:
- tpage-516 = `misty-vis-tfrag` (misty terrain)  
- tpage-521 = `misty-vis-pris` (misty enemies)
- tpage-531 = `jungle-vis-pris` (jungle enemies)

Plus beach (212-215), jungle (385-388), village sky (398-401, 1470). That's 13 tpages total — this is a very heavy level. Even 24MB heap may not be enough; 32MB+ would be safer.

**Next session priorities:**
1. Search ALL copies of `level.gc` in the JakAndDaxter folder, find the one still containing `10416`, edit it
2. Consider bumping to `32000` instead of `24000` given the tpage count
3. After heap fix confirms working, audit which tpages in the level are actually needed
