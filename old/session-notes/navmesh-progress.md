# OpenGOAL Navmesh — Session Notes
Last updated: April 2026

## Active Branch: `feature/navmesh`

---

## What's Implemented

### Core compute (`_navmesh_compute`)
- **Proper kd-tree BVH** — balanced recursive split on longest axis, not the old flat leaf-only structure. Interior nodes (type=0) have left/right byte offsets; leaves (type=1) hold up to 8 polys. Correct for `recursive-inside-poly` traversal in the engine.
- **PAT bit support** — gap polys (PAT bit 1) are tagged at compute time from `gap_tri_indices`. Gap polys appear in the route table but cause `nav-control-method-12` to fire the jump event.
- **Limit validation** — hard errors at 255 polys/verts (uint8 index ceiling). Warnings at 200+. Returns `warnings` list.
- **Mesh data cache** — `_collect_navmesh_actors` caches by mesh name so multiple enemies sharing one NAVMESH_ object only run compute once.

### Code generation (`_navmesh_to_goal`)
- Emits interior BVH nodes (`:type #x0 :left-offset #xNN :right-offset #xNN`) and leaves correctly.
- Emits `:pat` byte on nav-poly when non-zero (gap, or other PAT bits).
- scale-x/scale-z emitted as `1.0` (raw float, not meters — engine never reads these fields).
- Accepts `nav_max_users` param.

### Entity.gc patching (`patch_entity_gc`)
- Unpacks 3-tuple `(aid, mesh, nav_max_users)` from `_collect_navmesh_actors`.
- Engine initialization uses `res-lump-value 'nav-max-users` so the per-actor JSONC lump override is respected at runtime.

### JSONC export (`collect_actors`)
- `nearest-y-threshold` lump emitted if `og_nav_y_threshold` set on actor empty.
- `nav-max-users` lump emitted if `og_nav_max_users` set on actor empty.

### Gap face tools (Edit Mode)
- **`og.mark_gap_faces`** — marks selected faces as gap polys via `og_gap_faces` custom prop (comma-separated face indices).
- **`og.clear_gap_faces`** — removes gap marking from selected faces (or all if Object Mode).
- Also reads vertex group named `og_gap` as an alternative marking method.

### Validation
- **`og.navmesh_validate`** — runs `_navmesh_compute` and reports poly count, vert count, gap count, BVH node count, route table size, and any FATAL/WARNING messages.

### Per-actor nav tuning
- **`og.navmesh_set_default_props`** — adds/removes `og_nav_y_threshold` and `og_nav_max_users` on the actor. Supports a `clear` mode to remove overrides and restore engine defaults.

### Panel (`OG_PT_NavMesh`)
When actor selected:
- Poly/vert counts with ✓/ERROR icons
- Gap poly count
- Shared mesh indicator (lists other actors using same mesh)
- Validate button
- Per-actor tuning section: shows "engine default" label + Override button when no prop set; shows value + X button to remove override when set. No crash on missing props.

When NAVMESH_ mesh selected:
- Same stats
- Gap poly tools (Mark/Clear buttons, face count)
- Validate button

---

## Code Review Findings (April 2026)

### Second code review — additional bugs found and fixed
| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| A | **CRITICAL** | Level reload crash: static nav-mesh in GAME.CGO retains stale `user-list` pointer from freed level heap. On second visit, `(zero? user-list)` passes for a dangling ptr → dangling engine → crash | Removed `(zero? user-list)` guard; always allocate fresh on every `birth!` |
| B | Minor | `int("42.0")` raises `ValueError` → gap face marks silently lost if user typed a number into Blender's prop panel | Added `_parse_gap_faces()` helper using `float()→int()`; replaced all 6 inline parsing sites |

### Second code review — things verified correct
- `(new 'static 'nav-mesh ...)` is valid GOAL for `basic` types ✓
- Birth order: injection fires before `init-from-entity!` / `nav-mesh-connect` ✓
- Level reload: entity-actors recreated fresh from BSP; nav-mesh pointer is zero → our case runs cleanly ✓
- Shared meshes: multiple actors point to same struct, share user-list engine ✓
- Non-manifold edges: treated as boundary (adj=0xFF), no crash ✓
- `polygon_index` correctly maps Edit Mode face selection to loop triangles ✓
- Strip regex handles both injected blocks cleanly ✓
- BVH AABB Y-check: 5m padding + 10m engine threshold = 15m total Y tolerance ✓
- Gap poly routing through BFS is correct — engine intercepts gap as next-poly ✓
- Route table self-diagonal value 3: correct ("already there, no route needed") ✓
- GOAL `((N) body)` integer case syntax: valid ✓

---

## How Gap Polys Work (engine side)

1. Nav poly with `pat & 1` set = gap poly
2. Route table BFS routes through gap polys to find walkable polys beyond
3. `nav-mesh-method-16` (travel clip) detects when next-poly has pat&1
4. Sets `gap-poly` in return info
5. `nav-control-method-24` reads gap-poly → sets `nav-control.next-poly`
6. `nav-control-method-12` fires `send-event 'jump dest poly` with landing point
7. Enemy goes to `nav-enemy-jump` state → parabolic arc to far side

To use: in Edit Mode on the NAVMESH_ object, select the faces over the gap/ledge, click **Mark Gap** in the panel.

---

## Known Limitations / Next Work

1. **PAT bits 2-5** (surface type) not yet exposed in UI — only bit 1 (gap) is wired. Future: face material → PAT surface type.

2. **Static obstacle spheres** (`nav-mesh.static-sphere`) not yet supported. These are sphere obstacles embedded in the mesh itself (trees, pillars etc.).

3. **nav-mesh-actor sharing** — currently each enemy gets its own full mesh struct in the GOAL case statement. For large meshes shared by many enemies, the smarter approach is to emit one mesh and link others via `nav-mesh-actor` res-lump. Currently we cache compute but still emit per-actor code. Fine up to ~10 sharing enemies.

4. **BVH parent-offset** — always emitted as `#x0`. Engine may use this to walk back up the tree in some path not triggered during normal play.

---

## Testing Checklist

- [ ] Babak on a 4-poly quad mesh — chases Jak
- [ ] Multiple babaks sharing one mesh — all chase
- [ ] Gap poly: enemy jumps across a gap
- [ ] Mesh with >8 polys — BVH tree interior nodes work
- [ ] Validate operator correctly reports counts and warnings
- [ ] Mark/Clear gap faces in Edit Mode
- [ ] og_nav_y_threshold on actor → exported in JSONC, respects override
- [ ] Panel shows "engine default" when no prop set (no crash)
- [ ] Panel "Override" button adds prop; "X" button removes it
