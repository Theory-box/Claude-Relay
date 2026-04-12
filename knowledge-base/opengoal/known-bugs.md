# OpenGOAL Jak 1 — Known Bugs & Engine Patches

Bugs confirmed via source analysis and/or REPL debugging. Entries marked **[PATCH REQUIRED]** need a manual engine source change before the feature will work.

---

## [PATCH REQUIRED] vol-control lookup fails for custom levels

**Affects:** Any entity using `vol-control` — water volumes, aggro triggers, camera triggers, checkpoint volumes.

**Symptom:** `pos-vol-count` stays 0. `point-in-vol?` always returns `#f`. Volumes never activate.

**Root cause:** `vol-h.gc` calls `lookup-tag-idx` with `'exact 0.0` to find the `'vol` lump tag. The custom level C++ builder stores ALL res-lump tags at `DEFAULT_RES_TIME = -1000000000.0`. These never match `'exact 0.0`, so the tag is never found.

**REPL diagnosis:**
```lisp
; vol-count should be > 0 after level loads
(let ((w (the water-vol (process-by-name "water-vol-0" *active-pool*))))
  (format #t "vol-count:~d~%" (-> w vol pos-vol-count)))
; If 0 → patch not applied
```

**Fix:** Edit `goal_src/jak1/engine/geometry/vol-h.gc`, change `'exact` to `'base` on two lines:

```lisp
; Line ~50 (pos-vol lookup)
; BEFORE:
(s4-0 (-> ((method-of-type res-lump lookup-tag-idx) (the-as entity-actor s5-1) 'vol 'exact 0.0) lo))
; AFTER:
(s4-0 (-> ((method-of-type res-lump lookup-tag-idx) (the-as entity-actor s5-1) 'vol 'base 0.0) lo))

; Line ~64 (neg-vol / cutoutvol lookup)
; BEFORE:
(s4-1 (-> ((method-of-type res-lump lookup-tag-idx) (the-as entity-actor s5-2) 'cutoutvol 'exact 0.0) lo))
; AFTER:
(s4-1 (-> ((method-of-type res-lump lookup-tag-idx) (the-as entity-actor s5-2) 'cutoutvol 'base 0.0) lo))
```

Recompile after applying. The change is safe for vanilla levels — `'base` ignores timestamp and finds by name only, which works for both vanilla (`key-frame=0.0`) and custom levels (`key-frame=-1e9`).

**Also fixed in:** LuminarLight's LL-OpenGOAL-ModBase ("Hat Kid water hack").

**Confirmed:** via REPL — `vol-count` went from 0 to 1 after patch, water volumes activated correctly.

---

## Vol plane normals must point outward

**Affects:** Any custom code generating `vector-vol` plane data for `vol-control`.

**Symptom:** `point-in-vol?` always returns `#f` even when position is mathematically inside the box.

**Root cause:** `point-in-vol?` returns `#f` (outside) when `dot(P,N) - w > 0`. This means normals must face **outward** from the box, and inside = the negative side of every plane. Inward-facing normals invert the logic.

**Correct plane format for an AABB:**
```json
["vector-vol",
  [0,  1, 0,  surface_m],   // top:   P.y <= surface
  [0, -1, 0, -bottom_m],    // floor: P.y >= bottom
  [1,  0, 0,  xmax_m],      // +X:    P.x <= xmax
  [-1, 0, 0, -xmin_m],      // -X:    P.x >= xmin
  [0,  0, 1,  zmax_m],      // +Z:    P.z <= zmax
  [0,  0,-1, -zmin_m]       // -Z:    P.z >= zmin
]
```

**Confirmed:** via REPL — all 6 planes showed correct raw values but `point-in-vol?` returned `#f`. After flipping normals, water activated correctly.

---

