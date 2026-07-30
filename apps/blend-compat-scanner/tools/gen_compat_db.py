#!/usr/bin/env python3
"""
gen_compat_db.py
================
Regenerate a compatibility database for ANY two Blender versions, from the
binaries themselves (ground truth - not release notes).

  python3 gen_compat_db.py \
      --source-blender /path/to/blender-4.4/blender  --source-label 4.4.3 \
      --target-blender /path/to/blender-4.2/blender  --target-label 4.2.23 \
      --out ../compat_db_4.4_to_4.2.json

"Source" = the newer version the file is saved in.
"Target" = the older version the client opens it in.

Method:
  1. Launch each Blender headless and enumerate every registered
     geometry / function / shader node, recording each node's socket signature.
  2. Diff: nodes present in source but absent in target  -> hard break (Undefined).
           shared nodes whose sockets differ              -> soft break (may shift).
  3. Annotate the hard-break set with a suggested action (the ACTIONS map below -
     this is the ONLY judgement-based part; edit it freely per version pair).

The socket enumeration is exact and reproducible; the ACTIONS map is advisory.
"""

import argparse
import json
import subprocess
import sys
import tempfile
import os

# The enumeration script executed *inside* each Blender.
DUMP = r'''
import bpy, json
bpy.ops.wm.read_factory_settings(use_empty=True)
def sig(n): return {"in":[[s.name,s.type] for s in n.inputs],
                    "out":[[s.name,s.type] for s in n.outputs]}
def ids(pref):
    o=[]
    for nm in dir(bpy.types):
        c=getattr(bpy.types,nm)
        try:
            if not issubclass(c,bpy.types.Node): continue
        except TypeError: continue
        i=c.bl_rna.identifier
        if any(i.startswith(p) for p in pref): o.append(i)
    return sorted(set(o))
db={"version":bpy.app.version_string,"geometry":{},"shader":{}}
g=bpy.data.node_groups.new("g",'GeometryNodeTree')
for i in ids(("GeometryNode","FunctionNode")):
    try:
        n=g.nodes.new(i); db["geometry"][i]=sig(n); g.nodes.remove(n)
    except Exception as e: db["geometry"][i]={"err":type(e).__name__}
m=bpy.data.materials.new("m"); m.use_nodes=True; s=m.node_tree
for i in ids(("ShaderNode",)):
    try:
        n=s.nodes.new(i); db["shader"][i]=sig(n); s.nodes.remove(n)
    except Exception as e: db["shader"][i]={"err":type(e).__name__}
print("JSONSTART"+json.dumps(db)+"JSONEND")
'''

# Advisory fix strategies for the 4.x -> 4.2 hard-break set.
# class/action/note. action in: safe-drop | reconstruct | bake | manual
ACTIONS = {
 "GeometryNodeGizmoDial": ("cosmetic","safe-drop","Authoring gizmo; no effect on output geometry."),
 "GeometryNodeGizmoLinear": ("cosmetic","safe-drop","Authoring gizmo; no effect on output geometry."),
 "GeometryNodeGizmoTransform": ("cosmetic","safe-drop","Authoring gizmo; no effect on output geometry."),
 "GeometryNodeWarning": ("cosmetic","safe-drop","Only emits editor warnings; no geometry effect."),
 "GeometryNodeSetGeometryName": ("cosmetic","safe-drop","Sets a name string; cosmetic."),
 "GeometryNodeForeachGeometryElementInput": ("control-flow","manual","For-Each zone: no equivalent. User must restructure or remove."),
 "GeometryNodeForeachGeometryElementOutput": ("control-flow","manual","For-Each zone: no equivalent. User must restructure or remove."),
 "FunctionNodeIntegerMath": ("function","reconstruct","Rebuild with float Math + rounding (large-int precision)."),
 "FunctionNodeMatrixDeterminant": ("function","reconstruct","Rebuild from matrix component extraction + arithmetic."),
 "FunctionNodeHashValue": ("function","manual","No clean equivalent; approximate or remove."),
 "FunctionNodeFindInString": ("function","manual","String nodes limited in older versions; likely manual."),
 "GeometryNodeImportOBJ": ("import","bake","Realize imported geometry into stored mesh before downgrade."),
 "GeometryNodeImportPLY": ("import","bake","Realize imported geometry into stored mesh before downgrade."),
 "GeometryNodeImportSTL": ("import","bake","Realize imported geometry into stored mesh before downgrade."),
 "GeometryNodeInputObject": ("input","reconstruct","Replace with an Object group-input socket."),
 "GeometryNodeInputCollection": ("input","reconstruct","Replace with a Collection group-input socket."),
 "GeometryNodeCurvesToGreasePencil": ("grease-pencil","manual","Grease Pencil v3 dependent; manual."),
 "GeometryNodeGreasePencilToCurves": ("grease-pencil","manual","Grease Pencil v3 dependent; manual."),
 "GeometryNodeMergeLayers": ("grease-pencil","manual","Grease Pencil v3 dependent; manual."),
 "ShaderNodeBsdfMetallic": ("shader-bsdf","reconstruct","Approximate with Principled/Glossy BSDF (visual check)."),
 "ShaderNodeTexGabor": ("shader-texture","manual","No equivalent; approximate with Noise/Wave (visual)."),
}

# Non-node compatibility issues the node-diff cannot see (sourced from release notes).
NON_NODE = [
 {"id":"grease_pencil_v3","severity":"critical",
  "detail":"Grease Pencil objects created/saved in 4.3+ use GP v3 and do not open "
           "correctly in 4.2 or earlier. No node-level fix; handle before downgrade."},
]


def dump(blender_exe):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(DUMP)
        script = f.name
    try:
        out = subprocess.run([blender_exe, "-b", "--python", script],
                             capture_output=True, text=True, timeout=180).stdout
    finally:
        os.unlink(script)
    s = out.find("JSONSTART")
    e = out.find("JSONEND")
    if s < 0 or e < 0:
        sys.exit(f"enumeration failed for {blender_exe}\n{out[-800:]}")
    return json.loads(out[s + 9:e])


def build(new, old, src_label, tgt_label):
    db = {"source": src_label, "target": tgt_label,
          "note": "Node lists are EMPIRICAL (enumerated from both binaries). "
                  "Actions are suggested strategies.",
          "missing": {}, "changed": {}, "non_node_warnings": NON_NODE}
    for cat in ("geometry", "shader"):
        n, o = new[cat], old[cat]
        for k in sorted(n):
            if k not in o:
                c, a, note = ACTIONS.get(k, ("unknown", "manual", "Unclassified; treat as manual."))
                db["missing"][k] = {"node_category": cat, "class": c, "action": a, "note": note}
        for k in sorted(n):
            if k in o and "err" not in n[k] and "err" not in o[k] and n[k] != o[k]:
                ni = {tuple(x) for x in n[k]["in"]};  oi = {tuple(x) for x in o[k]["in"]}
                no = {tuple(x) for x in n[k]["out"]}; oo = {tuple(x) for x in o[k]["out"]}
                delta = {}
                if ni - oi: delta["in_added"] = sorted([list(x) for x in ni - oi])
                if oi - ni: delta["in_removed"] = sorted([list(x) for x in oi - ni])
                if no - oo: delta["out_added"] = sorted([list(x) for x in no - oo])
                if oo - no: delta["out_removed"] = sorted([list(x) for x in oo - no])
                db["changed"][k] = {"node_category": cat, "action": "review", "delta": delta}
    return db


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source-blender", required=True)
    p.add_argument("--target-blender", required=True)
    p.add_argument("--source-label", required=True)
    p.add_argument("--target-label", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    new = dump(a.source_blender)
    old = dump(a.target_blender)
    db = build(new, old, a.source_label, a.target_label)
    json.dump(db, open(a.out, "w"), indent=2)
    print(f"wrote {a.out}: {len(db['missing'])} missing, "
          f"{len(db['changed'])} changed, {len(db['non_node_warnings'])} non-node warnings")


if __name__ == "__main__":
    main()
