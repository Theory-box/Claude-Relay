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
def sval(s):
    dv=getattr(s,"default_value",None)
    if dv is None: return None
    try:
        return [round(float(x),4) for x in dv] if hasattr(dv,"__len__") else round(float(dv),4)
    except Exception:
        try: return str(dv)
        except Exception: return None
_BASE={p.identifier for p in bpy.types.Node.bl_rna.properties}
def nprops(n):
    out={}
    for p in n.bl_rna.properties:
        if p.identifier in _BASE or p.identifier in ("inputs","outputs"): continue
        e={"t":p.type}
        if p.type=="ENUM":
            try: e["enum"]=sorted(x.identifier for x in p.enum_items)
            except Exception: pass
        sub=getattr(p,"subtype",None)
        if sub and sub!="NONE": e["sub"]=sub
        try:
            if p.type in ("BOOLEAN","INT","FLOAT","ENUM","STRING"):
                d=getattr(p,"default",None)
                if d is not None and not hasattr(d,"__len__"):
                    e["def"]=round(float(d),4) if p.type=="FLOAT" else d
        except Exception: pass
        out[p.identifier]=e
    return out
def sig(n): return {"in":[[s.name,s.type,s.bl_idname,sval(s)] for s in n.inputs],
                    "out":[[s.name,s.type,s.bl_idname] for s in n.outputs],
                    "props":nprops(n)}
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
db={"version":bpy.app.version_string,"geometry":{},"shader":{},"compositor":{},"texture":{}}
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
bpy.context.scene.use_nodes=True; ct=bpy.context.scene.node_tree
for i in ids(("CompositorNode",)):
    try:
        n=ct.nodes.new(i); db["compositor"][i]=sig(n); ct.nodes.remove(n)
    except Exception as e: db["compositor"][i]={"err":type(e).__name__}
try:
    tx=bpy.data.node_groups.new("tx",'TextureNodeTree')
    for i in ids(("TextureNode",)):
        try:
            n=tx.nodes.new(i); db["texture"][i]=sig(n); tx.nodes.remove(n)
        except Exception as e: db["texture"][i]={"err":type(e).__name__}
except Exception: pass
# settings structs + type enums (non-node compatibility surface)
STRUCTS=["World","WorldLighting","SceneEEVEE","RenderSettings","Material",
         "Object","SunLight","PointLight","AreaLight","Mesh","Curves"]
db["structs"]={}
for sn in STRUCTS:
    t=getattr(bpy.types,sn,None)
    if t is not None:
        db["structs"][sn]=sorted(p.identifier for p in t.bl_rna.properties)
db["enums"]={}
for sn,pn in [("Modifier","type"),("Constraint","type"),
              ("LightProbe","type"),("Object","type")]:
    t=getattr(bpy.types,sn,None)
    if t is not None:
        p=t.bl_rna.properties.get(pn)
        if p is not None and hasattr(p,"enum_items"):
            db["enums"][pn]=sorted(e.identifier for e in p.enum_items)
# socket TYPE universe (a new socket subtype is the root cause of value drops)
db["socket_types"]=sorted({c.bl_rna.identifier for nm in dir(bpy.types)
    for c in [getattr(bpy.types,nm)]
    if isinstance(c,type) and issubclass(c,bpy.types.NodeSocket)})
# modifier / constraint class property schemas (non-node datablocks)
def _dbcls(basecls):
    base={p.identifier for p in basecls.bl_rna.properties}
    out={}
    for nm in dir(bpy.types):
        c=getattr(bpy.types,nm)
        try:
            if not (isinstance(c,type) and issubclass(c,basecls) and c is not basecls): continue
        except TypeError: continue
        props={}
        for p in c.bl_rna.properties:
            if p.identifier in base: continue
            props[p.identifier]={"t":p.type}
        out[c.bl_rna.identifier]=props
    return out
db["mods"]=_dbcls(bpy.types.Modifier)
db["cons"]=_dbcls(bpy.types.Constraint)
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
 {"id":"slotted_actions","severity":"moderate",
  "detail":"4.4 introduced the slotted-actions animation system (action slots). "
           "Slot links on actions/constraints (e.g. ActionConstraint.action_slot) "
           "have no 4.2 equivalent and are lost on downgrade; action assignment "
           "may need to be re-linked in 4.2."},
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


def _by_name(sockets):
    # inputs: [name,type,bl_idname,default]; outputs: [name,type,bl_idname]
    d = {}
    for s in sockets:
        name = s[0]
        typ = s[1]
        bl = s[2] if len(s) > 2 else None
        dflt = s[3] if len(s) > 3 else None
        d[name] = (typ, bl, dflt)
    return d


def diff_sockets(new_sig, old_sig):
    """new = source (e.g. 4.4), old = target (e.g. 4.2). Report what a file
    from `new` loses/shifts when opened in `old`."""
    delta = {}
    for side in ("in", "out"):
        nn = _by_name(new_sig[side])
        oo = _by_name(old_sig[side])
        added   = sorted([n, nn[n][0]] for n in nn if n not in oo)
        removed = sorted([n, oo[n][0]] for n in oo if n not in nn)
        retyped = sorted([n, oo[n][0], nn[n][0]] for n in nn
                         if n in oo and nn[n][0] != oo[n][0])
        # same coarse type but the source uses a specialised socket SUBTYPE the
        # target lacks -> the socket degrades and its value is dropped on load.
        subtype = sorted([n, oo[n][1], nn[n][1]] for n in nn
                         if n in oo and nn[n][0] == oo[n][0]
                         and nn[n][1] != oo[n][1])
        if added:   delta[f"{side}_added"] = added
        if removed: delta[f"{side}_removed"] = removed
        if retyped: delta[f"{side}_retyped"] = retyped
        if subtype: delta[f"{side}_subtype_changed"] = subtype
        if side == "in":
            dchg = sorted([n, oo[n][2], nn[n][2]] for n in nn
                          if n in oo and nn[n][0] == oo[n][0] and nn[n][1] == oo[n][1]
                          and nn[n][2] is not None and oo[n][2] is not None
                          and nn[n][2] != oo[n][2])
            if dchg:
                delta["in_default_changed"] = dchg
    return delta


def diff_props(new_props, old_props):
    """Non-socket node properties: what a source-version node loses/uses that the
    target can't represent."""
    d = {}
    added = sorted(p for p in new_props if p not in old_props)
    removed = sorted(p for p in old_props if p not in new_props)
    if added:   d["added"] = added
    if removed: d["removed"] = removed
    for p in sorted(new_props):
        if p not in old_props:
            continue
        a, b = new_props[p], old_props[p]
        if a.get("t") != b.get("t"):
            d.setdefault("type_changed", []).append([p, b.get("t"), a.get("t")])
        if a.get("t") == "ENUM" and "enum" in a and "enum" in b:
            new_vals = sorted(set(a["enum"]) - set(b["enum"]))   # usable in source only
            if new_vals:
                d.setdefault("enum_values_added", {})[p] = new_vals
        if a.get("sub") != b.get("sub"):
            d.setdefault("subtype_changed", []).append([p, b.get("sub"), a.get("sub")])
        if "def" in a and "def" in b and a["def"] != b["def"]:
            d.setdefault("default_changed", []).append([p, b["def"], a["def"]])
    return d


def build(new, old, src_label, tgt_label):
    db = {"source": src_label, "target": tgt_label,
          "note": "Node lists are EMPIRICAL (enumerated from both binaries). "
                  "Actions are suggested strategies.",
          "missing": {}, "changed": {}, "prop_changed": {}, "non_node_warnings": NON_NODE}
    for cat in ("geometry", "shader", "compositor", "texture"):
        n, o = new.get(cat,{}), old.get(cat,{})
        for k in sorted(n):
            if k not in o:
                c, a, note = ACTIONS.get(k, ("unknown", "manual", "Unclassified; treat as manual."))
                db["missing"][k] = {"node_category": cat, "class": c, "action": a, "note": note}
        for k in sorted(n):
            if k in o and "err" not in n[k] and "err" not in o[k] and n[k] != o[k]:
                delta = diff_sockets(n[k], o[k])
                if delta:
                    db["changed"][k] = {"node_category": cat, "action": "review", "delta": delta}
        for k in sorted(n):
            if k in o and "err" not in n[k] and "err" not in o[k]:
                pd = diff_props(n[k].get("props", {}), o[k].get("props", {}))
                if pd:
                    db["prop_changed"][k] = dict(node_category=cat, **pd)

    # non-node: settings properties present in source but missing in target
    # (i.e. LOST when the file is opened/saved in the older target version)
    db["settings_lost"] = {}
    for sn, sprops in new.get("structs", {}).items():
        lost = sorted(set(sprops) - set(old.get("structs", {}).get(sn, [])))
        if lost:
            db["settings_lost"][sn] = lost
    # new object/modifier/constraint/probe types that don't exist in target
    db["types_new"] = {}
    for en, items in new.get("enums", {}).items():
        added = sorted(set(items) - set(old.get("enums", {}).get(en, [])))
        if added:
            db["types_new"][en] = added
    # socket TYPE universe: types present only in source (root cause of value drops)
    db["socket_types_new"] = sorted(set(new.get("socket_types", []))
                                    - set(old.get("socket_types", [])))
    # non-node datablock property changes (modifiers, constraints)
    db["datablock_changes"] = {}
    for key in ("mods", "cons"):
        nd, od = new.get(key, {}), old.get(key, {})
        for cls in sorted(nd):
            if cls not in od:
                db["datablock_changes"].setdefault(key, {})[cls] = {"new_class": True}
                continue
            added = sorted(set(nd[cls]) - set(od[cls]))
            if added:
                db["datablock_changes"].setdefault(key, {})[cls] = {"props_added": added}
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
