#!/usr/bin/env python3
"""
subtype_keep.py — preserve nodes whose socket SUBTYPE is missing in the target.
==============================================================================
Some nodes exist in both versions but have an input socket whose *subtype* only
exists in the source (e.g. Blackbody / Volume Principled Temperature, subtype
NodeSocketFloatColorTemperature). On load in the target that socket degrades and
its value is lost — and a *link* into it crashes the target. So the value must be
re-applied by rebuilding a fresh, native node in the target.

This keeps the node (not a bake). Two stages, usually run via keep_nodes_run.py:

  stage extract (SOURCE): record each at-risk socket value to a manifest.
  stage apply   (TARGET): rebuild each affected node fresh, preserving all its
                          other sockets / links / properties, and re-applying the
                          recorded value.

Which nodes/sockets are "at risk" comes from the compat DB (in_subtype_changed
whose new subtype is in socket_types_new). Linked/animated at-risk sockets can't
be restored to a constant and are reported for manual handling.
"""

import bpy
import sys
import os
import json


def parse():
    a = sys.argv
    a = a[a.index("--") + 1:] if "--" in a else []
    o = {"stage": None, "manifest": None, "out": None, "db": None}
    for k in o:
        if f"--{k}" in a:
            i = a.index(f"--{k}")
            if i + 1 < len(a):
                o[k] = a[i + 1]
    if o["db"] is None:
        here = os.path.dirname(os.path.abspath(__file__))
        app = os.path.dirname(here)
        for f in sorted(os.listdir(app)):
            if f.startswith("compat_db_") and f.endswith(".json"):
                o["db"] = os.path.join(app, f); break
    return o


def at_risk_map(db):
    """{node_bl_idname: [socket_name, ...]} for subtype changes the target lacks."""
    new_types = set(db.get("socket_types_new", []))
    out = {}
    for nid, info in db.get("changed", {}).items():
        for e in info.get("delta", {}).get("in_subtype_changed", []):
            if e[2] in new_types:
                out.setdefault(nid, []).append(e[0])
    return out


def hosts():
    for m in bpy.data.materials:
        if m.use_nodes and m.node_tree:
            yield f"MATERIAL::{m.name}", m.node_tree
    for lt in bpy.data.lights:
        if lt.use_nodes and lt.node_tree:
            yield f"LIGHT::{lt.name}", lt.node_tree
    for w in bpy.data.worlds:
        if w.use_nodes and w.node_tree:
            yield f"WORLD::{w.name}", w.node_tree
    for g in bpy.data.node_groups:
        yield f"NODEGROUP::{g.name}", g


def affected(risk):
    for prefix, tree in hosts():
        for n in tree.nodes:
            if n.bl_idname in risk:
                yield f"{prefix}::{n.name}", tree, n


def rebuild_node(tree, old, overrides):
    """Fresh native node copying all readable sockets / links / node-properties,
    with `overrides` (socket_name -> value) applied for the lost sockets."""
    new = tree.nodes.new(old.bl_idname)
    base = {p.identifier for p in bpy.types.Node.bl_rna.properties}
    for p in old.bl_rna.properties:
        if p.identifier in base or p.identifier in ("inputs", "outputs") or p.is_readonly:
            continue
        try:
            setattr(new, p.identifier, getattr(old, p.identifier))
        except Exception:
            pass
    for i, s in enumerate(old.inputs):
        if s.name in overrides:
            try: new.inputs[i].default_value = overrides[s.name]
            except Exception: pass
        else:
            try: new.inputs[i].default_value = s.default_value
            except Exception: pass
    for l in list(tree.links):
        if l.to_node == old:
            tree.links.new(l.from_socket, new.inputs[list(old.inputs).index(l.to_socket)])
        if l.from_node == old:
            tree.links.new(new.outputs[list(old.outputs).index(l.from_socket)], l.to_socket)
    name = old.name
    tree.nodes.remove(old)
    new.name = name
    return new


def stage_extract(db, manifest_path):
    risk = at_risk_map(db)
    manifest, skipped = {}, []
    for loc, tree, node in affected(risk):
        for sname in risk[node.bl_idname]:
            s = node.inputs.get(sname)
            if s is None:
                continue
            if s.is_linked:
                skipped.append(f"{loc}::{sname}")
                continue
            manifest[f"{loc}::{sname}"] = list(s.default_value) if hasattr(s.default_value, "__len__") \
                else s.default_value
    json.dump(manifest, open(manifest_path, "w"))
    print(f"[extract] {len(manifest)} at-risk socket value(s) recorded"
          + (f"; {len(skipped)} linked/animated skipped (manual): {skipped}" if skipped else ""))


def stage_apply(db, manifest_path, out_path):
    risk = at_risk_map(db)
    manifest = json.load(open(manifest_path))
    todo = list(affected(risk))
    rebuilt = 0
    for loc, tree, node in todo:
        overrides = {}
        for sname in risk[node.bl_idname]:
            key = f"{loc}::{sname}"
            if key in manifest:
                overrides[sname] = manifest[key]
        if overrides:
            rebuild_node(tree, node, overrides)
            rebuilt += 1
    print(f"[apply] rebuilt {rebuilt} node(s), preserving other sockets/links")
    if out_path:
        bpy.ops.wm.save_as_mainfile(filepath=out_path)
        print(f"[apply] saved -> {out_path}")


def main():
    o = parse()
    db = json.load(open(o["db"])) if o["db"] and os.path.exists(o["db"]) else {}
    if o["stage"] == "extract":
        stage_extract(db, o["manifest"])
    elif o["stage"] == "apply":
        stage_apply(db, o["manifest"], o["out"])
    else:
        print("need --stage extract|apply")


if __name__ == "__main__":
    main()
