# v0.16.2: Test Results

**Date:** 2026-09-15
**Setup:** Blender 4.4.3, RTX 4090.
**Changes:** only `engine.py` and `__init__.py`; v0.16.1 is backed up in the scratchpad (`backup_v0161_20260915_163226`).
**Test time:** about 95 s for the whole chain (last round was about 15 min). The negative controls were skipped, because v0.16.1's round already showed the tests catch these bugs.

| Test | Result |
|---|---|
| `auto_test_v0161.py` (generated scene) | 17 s |
| `auto_bench_entry.py` (Azola, vegetation unhidden, `VLR_SKIP_GEOCOLD=1 VLR_SKIP_AB=1`) | 34 s |
| `auto_f12.py` (Azola, 25%) | 44 s |

## Results

| | v0.16.0 | v0.16.1 | **v0.16.2** |
|---|---|---|---|
| Edit-then-look (7 edit types + linked dup) | 0/12 | 12/12 | **12/12 ✅** |
| Share cache over 20 edits | – | 10 → 30 entries (leak) | **1 → 1 ✅** |
| Viewport instance streaming (150 unique meshes) | stuck | stuck at 5/150, endless redraw | **150/150 in 5.1 s ✅** |
| F12, generated scene (instances) | – | 53.6 s | **4.5 s ✅** |
| F12, Azola | 120 s cap, 2/385 objects | 38.9 s, 382/382 | **28.6 s, 382/382 ✅** |
| Selection click with 150 instance meshes | 3.2 ms | 327 ms | **45 ms ⚠️** |
| Azola cold entry | 5.86 s | 12.82 s | **10.77 s ⚠️** |
| Azola warm re-entry | 0.05 s | 3.27 s | **0.87 s ⚠️** |
| `_geo_sig` time, cold entry | ~0 | 6.45 s | 1.77 s |

(Faceless meshes are now excluded from the F12 expected set, which is why the count reads 382/382: the 3 faceless objects have nothing to draw.)

## Remaining issues in v0.16.2

### A. Linked duplicates stopped sharing during streaming (+50% GPU geometry) [measured]
- **Symptom:** Azola now loads **355 unique meshes / 448 slots / 18.52M triangles**, where v0.16.0 and v0.16.1 loaded **268 / 330 / 12.26M** for the same 394 objects.
- **Cost:** 91 extra extractions (378 vs 287, 4.86 s vs 3.82 s) and more streaming frames (39 vs 22). That accounts for much of the cold-entry gap. F12 also extracted 425 times instead of 357.
- **Cause:** `_geo_share` is now rebuilt on *every pass*. I recommended that in the v0.16.1 report, and it was the wrong call. A linked duplicate that falls into a later streaming pass than its original no longer finds it, so it gets its own copy of the geometry and GPU buffers.
- **Fix:** keep `_geo_share` for the whole load, and clear it only when the queue drains (the `else` branch, where `_dirty_objects` is cleared) and at the start of a full pass.
  - Edits are single-pass rebuilds that drain immediately, so the cache is cleared after each edit, which still fixes the leak.
  - Streaming loads keep sharing across passes.
  - The full-buffer signature means no stale entry can be served.

### B. The instance-hash skip never fires [measured]
- **Measurement:** 150 `_geo_sig` calls per selection click (900 over 6 clicks), the same count as v0.16.1. The click went from 327 to 45 ms only because the reads are 8× faster.
- **Cause:** the skip is `if cached_ok and not (self._dirty or self._dirty_objects)`. But `_rebuild` only runs when `self._dirty` is True, and nothing clears it before the instance loop (it's only reset at the end, `engine.py:1114`), so the condition is always false.
- **Also:** M1 (`engine.py:~920`, `'i:'` keys never in `bpy.data.objects`) still turns every click into a full rebuild.
- **Fix:**
  - Fix M1.
  - Decide per instance *before* the rebuild. For example, collect in `view_update` the names of the meshes and objects the depsgraph reported with `is_updated_geometry`, and hash a cached instance only if its mesh or source object is in that set.

### C. The `_geo_sig` memo is a no-op [confirmed]
- **Check:** `mesh._vlr_sig_cache = sig` raises `AttributeError: 'Mesh' object has no attribute '_vlr_sig_cache'` on both original and evaluated meshes (`scratchpad/memo_check.py`). The `try/except` swallows it.
- **Effect:** every object is still hashed twice: 834 calls for 378 extractions on entry, 872 for 425 in F12.
- **Why it's harmless:** a memo that never stores can't go stale. Had it worked, it would have been dangerous: evaluated meshes persist across edits, so a stored signature would have hidden edits again.
- **Fix:** compute `gsig` once in the rebuild loop and pass it into `_share_sig(obj, me, va, gsig=gsig)`. Delete the memo.

### D. Warm re-entry still hashes every object (0.87 s, was 0.05 s) [measured]
- **Cause:** the `_needs_verify` pass hashes all 400 cached objects, taking 0.81 s.
- **Fix:** only verify objects the depsgraph tagged while the viewport was not in Rendered view (the addon would need to record them in a handler), or accept the 0.87 s.

### Minor
- **Faceless meshes:** `_extract_mesh_data` returns None, so they never enter `_batch_dict`, and they are re-queued and re-"extracted" in every streaming pass. Three are in Azola. Cache a "nothing to draw" marker instead.
- **Stalls:** a single 2.7 s F12 pass shows the known big-mesh stall (review M7).

## Suggested v0.16.3 (small)
1. **A:** move the `_geo_share = {}` reset to the queue-drained branch and full-pass start. One line moved.
2. **C:** pass `gsig` into `_share_sig`, and delete the memo.
3. **B:** fix M1, and base the instance skip on the depsgraph-updated set.
4. **D:** optional.

**Expected result (estimate):** cold entry back near the 5.86 s baseline, with 268 unique meshes again.
