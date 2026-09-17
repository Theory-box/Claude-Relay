# Handoff: v0.16.5 (from the local Claude Code test machine)

**For:** Claude on the web, to review and push to `main`.
**Date:** 2026-09-16
**Status:** built, tested and installed locally. The user is testing it in Blender before the push.

**Not pushed from here:** that machine has no git, so **none of this has been pushed yet**. The zip also contains the test scripts and reports written there since v0.16.0.

## What to push

### 1. The addon: `addons/vertex_lit_renderer/` (v0.16.5)
- Only **`engine.py`** and **`__init__.py`** (version bump) changed since v0.16.4. All other files are identical to your v0.16.4 zip.
- **Geometry-first loading:**
  - one GPU batch per mesh: per-corner vertex buffers, plus a material-sorted index buffer drawn per slot with `GPUBatch.draw_range`;
  - textures stream in after the geometry, smallest files first;
  - no buffer hash on the load path;
  - linked duplicates share by evaluated-mesh pointer; modified duplicates share by a cheap group key plus a content hash only within groups;
  - the load budget is 1.5 s per frame.
- **Details and numbers:** `TEST_v0.16.5.md`. The design came from the prototype in `PROTO_geometry_first.md`.
- **Headline (Azola):**
  - geometry on screen 6.09 → 2.86 s;
  - fully loaded 6.69 → 5.17 s;
  - F12 14.6 → 12.4 s;
  - every object's data identical to the legacy extraction;
  - F12 image identical.

### 2. The test harness: `apps/splat-viewer/`
Needs a live Blender GPU session (not `-b`). The scripts never save, and exit via `os._exit`.

| script | purpose |
|---|---|
| `auto_test_v0161.py` | generated scene: edit-then-look (7 edit types + linked dup), edits made in Solid then re-entered, share-cache growth, instance streaming, click cost, instanced-mesh edits, F12 |
| `auto_bench_entry.py` | Rendered-view entry timing on a real .blend; `VLR_VERIFY_ALL=1` compares every cached object with a fresh `_extract_mesh_data` |
| `auto_f12.py` | F12 drain and timing; `VLR_F12_OLD=1` negative control; `VLR_PROFILE_EXTRACT=1` per-stage extraction times |
| `proto_geo_first.py` | the geometry-first prototype (standalone, engine untouched) |
| `benchmark_splats.py` | shared helpers (`_find_view3d`, `_gpu_sync`, …) plus the splat benchmarks |

Also: `tests/test_extract_identical.py` (permanent extraction-equivalence test) and `patches/`.

**Env flags:**
- `VLR_NO_SAVE=1`: required when opening a user's own .blend.
- `VLR_UNHIDE_EYE=1`: the Azola baseline configuration.
- `VLR_SKIP_AB=1`, `VLR_SKIP_GEOCOLD=1`: skip optional sections.
- `VLR_KEEP_CPU_ARRAYS=1`: needed with v0.16.5+ for the equivalence compares.

### 3. Reports (repo root)
- `REVIEW_v0.16.0.md`: full audit.
- `TEST_v0.16.1.md` … `TEST_v0.16.5.md`: per-version validation.
- `PROTO_geometry_first.md`: the prototype write-up.

## Still open (not fixed in v0.16.5)

1. **Solid-view edits within 2 s:** edits made in Solid within 2 s of leaving Rendered are lost. v0.16.4's `_on_depsgraph_update` uses a timestamp guard; replace it with a "does a Vertex-Lit Rendered viewport exist right now" check. Code in `TEST_v0.16.4.md`.
2. **Instanced meshes edited while in Solid are never refreshed.** The instance loop ignores `_EDITED_WHILE_AWAY`, and the handler records nothing when scatter sources aren't in the view layer (`TEST_v0.16.4.md`).
3. **Flat material colours are baked into vertex colours at extraction,** so viewport-colour changes don't update loaded objects (`TEST_v0.16.3.md`).
4. **Three 10,800×7,200 packed JPEGs in Azola cost ~0.5 s each on load.** Consider a downscaled display copy for images over about 16 MP.
5. **Everything else in `REVIEW_v0.16.0.md` not yet addressed:** colour management, Film Transparent, the node-group coercion bug, 8-bit bakes, splat alpha, splat ID collisions, and more.

## Not included
The `.blend` test scenes (Azola is 5.9 GB). Their names are in the reports.
