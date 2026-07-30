#!/usr/bin/env python3
"""
apply_repair.py — apply value-preserving fixers, in the SOURCE version.
======================================================================
Run this in the version the file was made in (e.g. 4.4). It walks every node
tree, applies the registered fixers, reports what was fixed vs flagged for manual
handling, and saves a downgraded-safe copy. It does NOT save over the input.

  blender-4.4 -b myfile.blend --python apply_repair.py -- --out myfile_for_4.2.blend

Only nodes with a verified fixer are touched. Everything else is left exactly as
is (and should be checked with the scanner first).
"""

import bpy
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fixers  # noqa: E402


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    out = None
    if "--out" in argv:
        i = argv.index("--out")
        if i + 1 < len(argv):
            out = argv[i + 1]
    return out


def all_trees():
    seen = set()
    trees = []

    def add(tree, where):
        if tree is None or tree.name in seen:
            return
        seen.add(tree.name)
        trees.append((tree, where))
        for n in tree.nodes:
            sub = getattr(n, "node_tree", None)
            if sub is not None:
                add(sub, f"{where} > Group '{sub.name}'")

    for obj in bpy.data.objects:
        for mod in obj.modifiers:
            if mod.type == "NODES" and mod.node_group:
                add(mod.node_group, f"Object '{obj.name}' > '{mod.name}'")
    for mat in bpy.data.materials:
        if mat.use_nodes and mat.node_tree:
            add(mat.node_tree, f"Material '{mat.name}'")
    for lt in bpy.data.lights:
        if lt.use_nodes and lt.node_tree:
            add(lt.node_tree, f"Light '{lt.name}'")
    for w in bpy.data.worlds:
        if w.use_nodes and w.node_tree:
            add(w.node_tree, f"World '{w.name}'")
    for sc in bpy.data.scenes:
        if sc.use_nodes and sc.node_tree:
            add(sc.node_tree, f"Scene '{sc.name}' compositor")
    for g in bpy.data.node_groups:
        add(g, f"Node group '{g.name}'")
    return trees


def main():
    out = parse_args()
    # collect (tree, node) first — fixers mutate the tree
    todo = []
    for tree, where in all_trees():
        for node in list(tree.nodes):
            if node.bl_idname in fixers.FIXERS:
                todo.append((tree, node, where))

    fixed, flagged = [], []
    for tree, node, where in todo:
        label = f"{node.bl_idname} ('{node.name}') at {where}"
        try:
            status = fixers.apply_fixer(tree, node)
        except Exception as e:
            flagged.append(f"{label} -- ERROR: {e}")
            continue
        if status == "fixed":
            fixed.append(label)
        elif status == "flagged":
            flagged.append(f"{label} -- no safe reconstruction, left in place")

    print("\n" + "=" * 64)
    print(f" REPAIR: {len(fixed)} fixed, {len(flagged)} flagged for manual handling")
    print("=" * 64)
    for f in fixed:
        print("  [fixed] ", f)
    for f in flagged:
        print("  [manual]", f)

    # blackbody: recommend the node-preserving two-stage tool rather than baking
    bb = [(t, n) for t, _ in all_trees() for n in t.nodes
          if n.bl_idname in fixers.NEEDS_TWO_STAGE]
    if bb:
        print(f"\n  {len(bb)} Blackbody node(s): run keep_blackbody_run.py to preserve "
              f"them as real nodes across the downgrade (recommended), or use the "
              f"bake alternative if a colour is acceptable.")

    if out:
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print(f"\n saved repaired copy -> {out}")
    else:
        print("\n (no --out given; nothing saved)")


if __name__ == "__main__":
    main()
