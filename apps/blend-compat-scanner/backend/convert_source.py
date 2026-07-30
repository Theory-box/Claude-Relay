#!/usr/bin/env python3
"""Runs in SOURCE Blender. Applies source-side fixers for the selected nodes and
records the keep-node manifest, then saves an intermediate file. Uses the shared
scanner traversal so issue IDs match the UI exactly.
  blender-src -b in.blend --python convert_source.py -- --select sel.json --db db.json --manifest m.json --out inter.blend"""
import bpy, sys, os, json
def arg(n,d=None):
    a=sys.argv; a=a[a.index("--")+1:] if "--" in a else []
    return a[a.index(n)+1] if n in a and a.index(n)+1<len(a) else d
APP=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,APP); sys.path.insert(0,os.path.join(APP,"repair"))
import blend_compat_scanner as sc, fixers
from subtype_keep import at_risk_map

sel=set(json.load(open(arg("--select"))))
db=json.load(open(arg("--db"))); risk=at_risk_map(db)
manifest={}; fixed=0
for n,where in list(sc.collect_nodes()):
    iid=f"{where}::{n.name}"
    if iid not in sel: continue
    nt=n.id_data
    if n.bl_idname in fixers.FIXERS:
        if fixers.apply_fixer(nt,n)=="fixed": fixed+=1
    elif n.bl_idname in risk:                       # keep-node: record for stage 2
        for sname in risk[n.bl_idname]:
            s=n.inputs.get(sname)
            if s is not None and not s.is_linked:
                v=s.default_value
                manifest[f"{iid}::{sname}"]=list(v) if hasattr(v,"__len__") else v
json.dump(manifest, open(arg("--manifest"),"w"))
bpy.ops.wm.save_as_mainfile(filepath=arg("--out"))
print(f"SRC_OK fixed={fixed} keep_recorded={len(manifest)}")
