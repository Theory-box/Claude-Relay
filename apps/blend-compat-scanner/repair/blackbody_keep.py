#!/usr/bin/env python3
"""
blackbody_keep.py — preserve Blackbody nodes across a downgrade (two-stage).
===========================================================================
Blackbody exists in both versions; only its Temperature socket subtype is newer,
so the value drops in the target and the node can't hold it until rebuilt. This
keeps the node a real Blackbody (not an RGB bake) by:

  stage 1  (run in SOURCE, e.g. 4.4): record each Blackbody's temperature to a
           manifest, keyed by a location that survives the version change.
  stage 2  (run in TARGET, e.g. 4.2): rebuild each Blackbody as a fresh native
           node with its saved temperature, reconnecting its output.

Usually invoked via keep_blackbody_run.py (orchestrates both stages). Manually:

  blender-4.4 -b in.blend  --python blackbody_keep.py -- --stage extract --manifest m.json
  blender-4.2 -b in.blend  --python blackbody_keep.py -- --stage apply   --manifest m.json --out out.blend

Only constant (unlinked) temperatures are handled; a linked/animated temperature
is reported and left for manual handling.
"""

import bpy
import sys
import json


def parse():
    a = sys.argv
    a = a[a.index("--") + 1:] if "--" in a else []
    o = {"stage": None, "manifest": None, "out": None}
    for k in ("stage", "manifest", "out"):
        if f"--{k}" in a:
            i = a.index(f"--{k}")
            if i + 1 < len(a):
                o[k] = a[i + 1]
    return o


def blackbody_locations():
    """Yield (key, tree, node) for every Blackbody in the file."""
    hosts = []
    for m in bpy.data.materials:
        if m.use_nodes and m.node_tree:
            hosts.append((f"MATERIAL::{m.name}", m.node_tree))
    for lt in bpy.data.lights:
        if lt.use_nodes and lt.node_tree:
            hosts.append((f"LIGHT::{lt.name}", lt.node_tree))
    for w in bpy.data.worlds:
        if w.use_nodes and w.node_tree:
            hosts.append((f"WORLD::{w.name}", w.node_tree))
    for g in bpy.data.node_groups:
        hosts.append((f"NODEGROUP::{g.name}", g))
    for prefix, tree in hosts:
        for n in tree.nodes:
            if n.bl_idname == "ShaderNodeBlackbody":
                yield (f"{prefix}::{n.name}", tree, n)


def stage_extract(manifest_path):
    manifest, skipped = {}, []
    for key, tree, node in blackbody_locations():
        t = node.inputs["Temperature"]
        if t.is_linked:
            skipped.append(key)
            continue
        manifest[key] = t.default_value
    json.dump(manifest, open(manifest_path, "w"))
    print(f"[extract] {len(manifest)} blackbody temperature(s) recorded"
          + (f"; {len(skipped)} linked/animated skipped (manual): {skipped}" if skipped else ""))


def stage_apply(manifest_path, out_path):
    manifest = json.load(open(manifest_path))
    rebuilt, missing = 0, []
    # collect first (we mutate trees)
    todo = list(blackbody_locations())
    for key, tree, node in todo:
        if key not in manifest:
            missing.append(key)
            continue
        targets = [l.to_socket for l in tree.links if l.from_node == node]
        orig_name = node.name
        tree.nodes.remove(node)                 # free the name first
        fresh = tree.nodes.new("ShaderNodeBlackbody")
        fresh.name = orig_name
        fresh.inputs["Temperature"].default_value = manifest[key]
        for t in targets:
            tree.links.new(fresh.outputs["Color"], t)
        rebuilt += 1
    print(f"[apply] rebuilt {rebuilt} blackbody node(s)"
          + (f"; {len(missing)} not in manifest (left as-is): {missing}" if missing else ""))
    if out_path:
        bpy.ops.wm.save_as_mainfile(filepath=out_path)
        print(f"[apply] saved -> {out_path}")


def main():
    o = parse()
    if o["stage"] == "extract":
        stage_extract(o["manifest"])
    elif o["stage"] == "apply":
        stage_apply(o["manifest"], o["out"])
    else:
        print("need --stage extract|apply")


if __name__ == "__main__":
    main()
