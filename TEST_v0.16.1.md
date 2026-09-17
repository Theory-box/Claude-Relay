# v0.16.1 (audit fixes): Test Results

**Date:** 2026-09-15
**Setup:** Blender 4.4.3, RTX 4090, live GPU session.
**Install:** v0.16.1 was installed over v0.16.0. Only 4 files changed: `engine.py`, `splat_render.py`, `splat_unified.py`, `__init__.py`. A backup of v0.16.0 is in the scratchpad (`backup_v0160_20260915_155034`).

**Tests** (in `apps/splat-viewer/`):

| Script | What it covers |
|---|---|
| `auto_test_v0161.py` | Generated scene: edit-then-look, share-cache growth, instance streaming, selection-click cost, F12 |
| `auto_f12.py` | F12 on a real scene: does the render drain the queue and draw everything? |
| `auto_bench_entry.py` | Rendered-view entry profile. It now also times `_geo_sig`. |

Every test has a **negative control**: the v0.16.0 behaviour is re-created in memory (the installed files aren't touched), to prove the test actually detects the bug.

---

## Bottom line

**Fixed and verified:**

| Fix | Result |
|---|---|
| **C1** F12 loop | The control hit the 120 s cap and drew 2 of 385 objects. v0.16.1 finishes in 38.9 s and draws every drawable object. |
| **C2** edits vanishing | 12/12 edit checks pass (vertex move, UV, material index, shading, vertex paint, shape key, modifier parameter, plus the linked duplicate). The control passes 0/12. |
| **M10** sort direction, **H2** unified `_last` | Correct by reading. |

**Not fixed:**

- **H1 (R3):** leftover instances still never load in the viewport (stuck at 5/150). The viewport now also redraws continuously. It's a one-line fix: the `else` branch sets `_dirty=False`.

**New regressions caused by the C2 fix:** the full-buffer `_geo_sig` hash is read through slow RNA and runs far too often.

| | v0.16.0 | v0.16.1 |
|---|---|---|
| **R4** Azola cold entry | 5.86 s | **12.82 s** |
| **R4** Azola warm re-entry | 0.05 s | **3.27 s** |
| **R4** share of F12 time spent hashing | – | **68%** |
| **R1** selection click, 150 instance meshes | 3.2 ms | **327 ms** |
| **R2** share cache | – | grows by one full mesh copy (plus GPU batches) **per edit**, never freed |

**Recommendation:** keep the v0.16.1 correctness fixes, but do a v0.16.2 before relying on it for heavy scenes:

1. Read the signature buffers via `mesh.attributes` (8× faster, measured), and hash once per object.
2. Don't hash untouched objects on re-entry, or cached instance meshes on every rebuild.
3. Rebuild `_geo_share` every pass.
4. Fix the R3 one-liner, and M1 (`'i:'` keys).

Then re-run `auto_test_v0161.py`, `auto_bench_entry.py` (Azola, `VLR_UNHIDE_EYE=1`) and `auto_f12.py`. They all have negative controls, so they will show whether each fix holds.

---

## Review of the diff

| Fix | Diff | Verdict |
|---|---|---|
| C1 `_force_full` consumed on the first pass | `engine.py` `_rebuild_inner` | Correct. See the F12 results below. |
| C2 `_geo_sig` hashes the full position/UV/material/smooth/colour buffers | `engine.py:103-157` | Correct for stale geometry: 12/12 pass. It introduces a cost regression (R1) and unbounded cache growth (R2). |
| H1 `_inst_pending` keeps `_geo_pending` | `engine.py` | **Incomplete** (R3). |
| H2 `_last` set after the sort succeeds | `splat_unified.py:275-297` | Correct by reading. The failure path is hard to force; not run. |
| M10 Mᵀ instead of M⁻¹ at 4 sites | `splat_render.py:435, 489, 505, 573` | Correct: fwd·(M·p) = (Mᵀ·fwd)·p. All 4 sites were changed, and no `minv.to_3x3()@fwd` is left. |

---

## 1. Edit-then-look: PASS (C2 fixed)

**Method:** in Rendered view, edit an object and let the engine settle. Then compare the engine's cached arrays (positions, normals, UVs, colours, slots) with a fresh extraction of the same evaluated object. The linked duplicate is checked too.

| Edit | v0.16.1 | v0.16.0 signature (control) |
|---|---|---|
| move one interior vertex | PASS (obj + linked dup) | FAIL: position off by 0.4 |
| UV edit | PASS | FAIL |
| material index change | PASS | FAIL: 1 slot vs 2 |
| flat → smooth shading | PASS | FAIL |
| vertex paint | PASS | FAIL |
| shape-key slider | PASS | FAIL: position off by 0.52 |
| Displace strength (vertex-group limited) | PASS | FAIL: position off by 0.59 |
| **total** | **12/12** | **0/12** |

With the old signature the engine did a "rebuild", but it made **0 extractions**: every edited object was served from the share cache. That reproduces the reported "edits vanish" bug exactly, and v0.16.1 fixes it.

---

## 2. New problems found in v0.16.1

### R1. Selection clicks got ~100× slower on scenes with instances [confirmed, measured]

| 150 unique instance meshes cached | rebuild per click | `_geo_sig` per click |
|---|---|---|
| v0.16.1 | **326.6 ms** | 323.7 ms (150 calls) |
| v0.16.0 signature | 3.2 ms | 0.6 ms |

- **Cause:** two existing issues combine with the new hash.
  - The instance loop (`engine.py:960`) computes `_geo_sig` for **every unique instance mesh on every rebuild**, before its "cached + unchanged" check.
  - Review item **M1** (`engine.py:900-902`) is still unfixed: `'i:'` keys are never in `bpy.data.objects`, so every depsgraph update (even a selection click) forces a rebuild.
  - The signature now hashes full buffers: about 2.2 ms per 10k-vertex mesh, rather than microseconds.
- **Result:** on a scatter scene every click, frame change or property tweak stalls for about a third of a second (with 150 meshes), and the stall scales with instance count.
- **Fix:**
  - Fix M1 (skip `i:` keys in the deleted-object check).
  - In the instance loop, only compute the signature for instances whose *source* object the depsgraph reported as updated; otherwise trust the cache.
  - Optionally, avoid hashing twice: `_share_sig` calls `_geo_sig` again at `engine.py:168`, right after the rebuild computed `gsig` at `:1042`, so every rebuilt object is hashed twice. Pass `gsig` in.

### R2. The share cache grows with every edit [confirmed, measured]

- **Measurement:** over 20 single-vertex edits, `_geo_share` grew from 10 to 30 entries, and the CPU arrays it holds from 10.4 MB to 31.1 MB. That's about 1 MB per edit on a 7k-triangle object.
- **Cause:** every edit now produces a new signature. `_geo_share[ssig] = (data, slots, shadow_batch)` is added at `engine.py:1065`. The cache is only reset on a full rebuild, so every past state is kept, including its **GPU batches**.
- **Scenario:** a 1M-triangle object keeps a copy of about 100 MB of CPU arrays plus its GPU buffers **per edit**. An hour of sculpting or vertex painting in Rendered view would exhaust RAM/VRAM. (With the old signature this didn't grow, because edits were wrongly served stale data instead.)
- **Fix:** build `_geo_share` fresh at the start of every `_rebuild_inner` (sharing only needs to find linked duplicates within one pass). Or evict the entry an object previously used when it is re-extracted.

### R3. Leftover instances still never load in the viewport; it now redraws forever [confirmed, measured]

**Trace:** a collection instance of 150 unique meshes was added while in Rendered view.

```
f1:   5/150 loaded, _geo_pending=True, _dirty=False, rebuilds 1
...
f240: 5/150 loaded, _geo_pending=True, _dirty=False, rebuilds 1   <- stuck
```

- **Cause:** `view_draw` rebuilds only `if self._dirty:` (`engine.py:1646`). The non-instance loop's `else` branch still sets `self._dirty=False` (`:1075`), so the new `_inst_pending` only keeps `_geo_pending`.
  - `_geo_pending=True` makes `view_draw` call `tag_redraw()` every frame (`:1802`, `:1823`), so the viewport now **redraws continuously**, doing no work, forever.
  - It also sets the material-compile budget to 0 (`:1254`) while geometry is "pending".
- **Fix:** in that `else` branch, use `self._dirty = bool(getattr(self, '_inst_pending', False))`, or set `_dirty=True` alongside `_inst_pending` after the branch.
- **F12:** unaffected here, because F12's loop calls `_rebuild` directly while `_geo_pending` is set (see F12 below).

---

## 3. F12: C1 FIXED (confirmed with a negative control)

**Setup:** `auto_f12.py` on the Azola file (opened in place, never saved), 25% of 1920×1080, `Camera.009`. Viewports were forced to Solid, so only the F12 engine extracted anything. The render depsgraph ignores the eye-hide, so the vegetation is included: **385 mesh objects**.

| | wall | rebuild passes | extractions | objects drawn | queue drained |
|---|---|---|---|---|---|
| v0.16.0 `_force_full` behaviour (control, re-created in memory) | **120.6 s (hit the cap)** | 735 | 1470 | **2 / 385** | **no** |
| **v0.16.1** | **38.0 s** (38.9 s on rerun) | 114 | 357 | **382 / 385** (= all 382 with faces) | yes |

The control re-extracted the **same 2 objects 1,470 times** and rendered an almost empty frame (image std 0.046 vs 0.246). That is exactly the non-terminating loop the audit described, so v0.16.1 fixes it.

**Remaining F12 notes:**

- **The 3 "missing" objects have no faces**, so there is nothing to draw and this is correct behaviour. `Cube.012` and `Cube.065` have 0 vertices; `Plane.016` is 24 loose vertices. I checked with a read-only `-b` inspection (`scratchpad/inspect_missing.txt`). So F12 drew **382 / 382 drawable objects: PASS**. My test should exclude faceless meshes from the expected set.
- **Two-thirds of F12's time is the new signature hash** (rerun with `_geo_sig` timed):

  | component | time |
  |---|---|
  | F12 wall | 38.9 s |
  | `_geo_sig` | **26.3 s (68%)**, 996 calls, ~26 ms each on render-resolution meshes |
  | extraction | 9.7 s |
  | everything else in 114 rebuild passes | 1.5 s |

  So the many budgeted passes cost little in themselves. F12 is slow because of R4. Also, inside one F12 render every object is extracted fresh anyway, so the hash only serves to find linked duplicates. A cheap key (mesh datablock + modifier state + materials) is enough there.
- **Generated scene (4 objects + 150 instance meshes of 20k triangles):** F12 passes (4/4 objects, 150/150 instance meshes), but takes **53.6 s over 143 passes**. That is R1 in action: every pass re-hashes every cached instance mesh (≈150 × 2.2 ms ≈ 0.33 s per pass) before loading ~1 new instance under the 30 ms instance budget.
- **Fix direction:** fix R4 (cheap reads, hash once, and no hash needed for dedup inside F12) and R1. Dropping the streaming budget in `render()` would only save part of the ~1.5 s.
- **Viewport after F12:** it picks up F12's cache contents. With the generated scene this was harmless: 154 entries, EditObj identical. On scenes where render and viewport geometry differ (Subdivision levels, GN viewport-vs-render, Simplify), expect the viewport to show render-resolution meshes after an F12 until the next edit (review M2).

## 5. Where `_geo_sig`'s time goes (CPU microbenchmark, `scratchpad/sig_microbench.py`)

**Setup:** grid meshes with a UV map, a corner colour attribute, and non-default material index and smooth values. Best of 5 runs.

| mesh | RNA reads as in v0.16.1 (`polygons.foreach_get`, `uv_layers…data`) | same data via `mesh.attributes[...]` | `hash(tobytes())` | `zlib.crc32` |
|---|---|---|---|---|
| 10k verts | 2.3 ms | 0.2 ms | 0.2 ms | 0.25 ms |
| 90k verts | 21.1 ms | 1.9 ms | 1.9 ms | 2.2 ms |
| 1M verts | **231.7 ms** | **28.9 ms** | 37.3 ms | 33.4 ms |

Breakdown of the RNA reads at 1M: `material_index` 100 ms, `uv` 61 ms, `use_smooth` 30 ms, `co` 15 ms.
Breakdown of the attribute reads at 1M: `material_index` 27 ms, `uv` 1.2 ms, `sharp_face` 0.02 ms, `position` 0.5 ms.
The attribute reads returned identical values (checked).

**Takeaways for the fix:**

1. **Reads:** read through the generic attribute API (`position` / `material_index` / `sharp_face` / the UV map's attribute, `foreach_get('vector'|'value')`), or through the extractor's own `_raw_attr`. That makes them about **8× faster**. Hashing then becomes the main cost.
2. **Hash once per object:** pass `gsig` into `_share_sig`, which saves 2×.
3. **Don't hash unchanged objects on re-entry.** That's the 3.2 s warm re-entry: only verify objects that were tagged while the viewport was away. Likewise, don't hash cached instance meshes on every rebuild (R1).
4. **Choice of hash:** Python `hash` and `zlib.crc32` cost about the same. Swapping the hash function gains little. blake2b is 4–5× slower, so avoid it.

*Estimate, not measured:* combining 1–3 should bring cold entry back near the 5.86 s baseline and restore instant re-entry, while keeping the 12/12 edit correctness. Re-run `auto_bench_entry.py` and `auto_test_v0161.py` after the change to confirm.

## 4. Azola entry time: REGRESSION (R4)

**Setup:** the same configuration as the 5.86 s baseline: Azola file opened in place (never saved), 393 eye-hidden vegetation meshes unhidden in memory, 394 objects / 268 unique meshes / 12.26M triangles, `auto_bench_entry.py`.

| | v0.16.0 (baseline) | v0.16.1 | change |
|---|---|---|---|
| **COLD entry** | **5.86 s** (13 rebuild frames) | **12.82 s** (25 rebuild frames) | **+6.96 s (2.2×)** |
| extraction | 3.82 s | 3.75 s | same |
| `_geo_sig` | ~0 | **6.45 s over 826 calls** | new |
| first frame | 600 ms | 398 ms | |
| **WARM re-entry** (leave to Solid and come back) | **0.05 s** | **3.27 s** | **65×** |
| `_geo_sig` on re-entry | ~0 | **3.21 s over 400 calls** | new |
| GEO-COLD (geometry cleared, shaders kept) | not re-measured | 10.26 s (`_geo_sig` 6.35 s) | |

**Why:** the full-buffer hash averages about 7.8 ms per call on this scene's meshes, and it runs more often than it looks:

- **Every re-entry:** it runs for every cached object (`engine.py:1001`, the `_needs_verify` pass: 400 calls = 3.2 s). Re-entry used to be instant, and now blocks one frame for 3.3 s every time you switch back to Rendered.
- **Twice per rebuilt object:** `gsig` at `:1042`, then again inside `_share_sig` at `:168`. That's 826 calls for 287 extractions (plus the verify pass).
- **Inside the streaming budget:** the hash counts against the 0.10 s per-frame window, so each frame loads fewer objects (25 rebuild frames instead of 13), and every extra frame also pays the partial-scene redraw.

**Fix direction:** keep the cheap signature for *when to look*, and hash only when needed.

- **Re-entry:** only re-hash objects the depsgraph reported as changed while the viewport was away. Or compare cheap fields first (counts, modifier state, the mesh's `session_uid` / pointer), and hash only when they are equal but the object was tagged.
- **Rebuild:** compute the hash once per object and pass it to `_share_sig`.
- **Share lookup:** the full hash is what the share lookup needs (C2). The dirty-object path could skip the share lookup entirely and extract directly. Then the rebuild path only needs the cheap signature, plus the hash for non-dirty objects looking for a linked-duplicate share.
- **Hash speed:** `hash(buf.tobytes())` makes an extra copy of each buffer before hashing. A subsample is **not** a safe substitute, because it misses single-vertex edits exactly like the old 3-vertex signature did. See section 5 for measured costs of the alternatives.
