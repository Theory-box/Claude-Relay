#!/usr/bin/env python3
"""Runs in TARGET Blender on the intermediate. Rebuilds each selected keep-node as
a fresh native node from the manifest, then saves the final target file.
  blender-tgt -b inter.blend --python convert_target.py -- --select sel.json --db db.json --manifest m.json --out final.blend"""
import bpy, sys, os, json
def arg(n,d=None):
    a=sys.argv; a=a[a.index("--")+1:] if "--" in a else []
    return a[a.index(n)+1] if n in a and a.index(n)+1<len(a) else d
APP=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,APP); sys.path.insert(0,os.path.join(APP,"repair"))
import blend_compat_scanner as sc
from subtype_keep import at_risk_map, rebuild_node

sel=set(json.load(open(arg("--select"))))
db=json.load(open(arg("--db"))); risk=at_risk_map(db)
manifest=json.load(open(arg("--manifest"))); rebuilt=0
for n,where in list(sc.collect_nodes()):
    iid=f"{where}::{n.name}"
    if iid not in sel or n.bl_idname not in risk: continue
    overrides={}
    for sname in risk[n.bl_idname]:
        key=f"{iid}::{sname}"
        if key in manifest: overrides[sname]=manifest[key]
    if overrides:
        rebuild_node(n.id_data, n, overrides); rebuilt+=1
bpy.ops.wm.save_as_mainfile(filepath=arg("--out"))
print(f"TGT_OK rebuilt={rebuilt}")
