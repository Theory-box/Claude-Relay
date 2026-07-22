# Upstream Engine Fixes To Watch / Backport

Tracking upstream OpenGOAL commits that fix bugs we may be hitting in our
custom levels. Listed newest first. Each entry should note: what the bug
is, how to detect we're affected, and what backporting would entail.

---

## Collision BVH wrapper fix — missing collision in custom levels

**Upstream commit:** [`e2f14f4`](https://github.com/open-goal/jak-project/commit/e2f14f459dfb2ab62c439925beb120f4d1b16af2)
**PR:** [#4060](https://github.com/open-goal/jak-project/pull/4060)
**Author:** gratefulforest
**Affects:** jak1, jak2, jak3 (single fix file is jak1-specific:
`goalc/build_level/collide/jak1/collide_bvh.cpp`, but the PR title says all 3
games)
**File:** `goalc/build_level/collide/jak1/collide_bvh.cpp` line ~219, function
`split_recursive`

### The bug

When `build-level` builds the collision BVH (bounding volume hierarchy) tree
from custom level mesh, it could lose entire faces. The pattern: a node that
contains a face-containing child alongside a non-face-containing parent in
the same level of the tree. The BVH walker apparently can't navigate
correctly when leaves and non-leaves coexist as siblings, so the
face-containing child becomes unreachable and its triangles are silently
dropped from the collision data. The level builds without errors. The
geometry renders fine. But you fall through specific patches of the floor.

### How to detect we're affected

Symptoms in our levels would be:
- Specific patches of geometry where you fall through despite the mesh
  being there visually
- Actor `move-to-ground` warnings (`WARNING: move-to-ground: ... failed
  to locate ground`) on entities placed over what looks like solid geometry
- Inconsistent: works in some areas, doesn't work in others, with no
  obvious geometric difference

We saw the second symptom (move-to-ground warnings on babaks) in the
feature/enemies debugging session — though in that specific case the
user confirmed it was placement, not the BVH bug. **But this same warning
is exactly what this fix addresses, so future occurrences should consider
this fix.**

### The fix (minimalist)

```cpp
// Old (broken)
for (auto& c : temp_children) {
  if (!c.faces.empty()) {
    to_split.child_nodes.emplace_back();
    to_split.child_nodes.emplace_back();
    split_node_once(c, &to_split.child_nodes[to_split.child_nodes.size() - 1],
                    &to_split.child_nodes[to_split.child_nodes.size() - 2]);
  } else {
    to_split.child_nodes.push_back(std::move(c));
  }
}

// New (fixed)
for (auto& c : temp_children) {
  if (!c.faces.empty()) {
    to_split.child_nodes.emplace_back();
    auto& wrapper = to_split.child_nodes.back();
    wrapper.child_nodes.clear();
    wrapper.child_nodes.push_back(std::move(c));
    compute_my_bsphere_ritters(wrapper);
  } else {
    to_split.child_nodes.push_back(std::move(c));
  }
}
```

When a face-containing child shows up, the fix wraps it in a parent node
of its own instead of putting it directly alongside non-face-containing
siblings. Net result: face-containing nodes and non-face-containing parents
are never siblings.

### Backport effort

**Tiny.** It's a 4-line diff in one C++ file (`collide_bvh.cpp`). No
Python/addon changes needed. The user's local jak-project clone needs the
patch applied and rebuilt.

### Action items if we hit this

1. Check the user's jak-project commit hash. If it's older than `e2f14f4`,
   the fix isn't in their build.
2. If the user is on a recent enough version (post-2026-04 roughly), they
   already have it.
3. If they're on an older version, they have two options:
   a. Pull upstream and rebuild (preferred — also gets all other fixes)
   b. Cherry-pick just this commit and rebuild (more surgical)
4. After applying, rebuild GOALC, re-run a full level build (not just `mi`),
   and re-test the affected area.

### Why the addon can't fix this

This is in the C++ build-level pipeline that processes the GLB into
collision BVH structures. The Python addon hands the GLB to GOALC and
GOALC does the BVH construction. Nothing the addon writes can work around
a BVH builder bug — by the time the bug manifests, the addon's job is done.

---
