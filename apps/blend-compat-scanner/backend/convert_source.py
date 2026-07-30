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
apply_list=json.load(open(arg("--apply"))) if arg("--apply") else []
manifest={}; fixed=0; applied=0
# apply chosen modifiers first: bakes evaluated geometry into the mesh and removes
# the modifier (and its unfixable nodes) entirely.
for entry in apply_list:
    obj_name, mod_name = entry.split("::",1)
    obj=bpy.data.objects.get(obj_name)
    if obj and obj.modifiers.get(mod_name):
        try:
            with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[obj]):
                bpy.ops.object.modifier_apply(modifier=mod_name)
            applied+=1
        except Exception as e:
            print("APPLY_WARN", obj_name, mod_name, e)
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
# pack any staged images
packed=0
for iid in sel:
    if iid.startswith("image::"):
        img=bpy.data.images.get(iid.split("::",1)[1])
        if img:
            try: img.pack(); packed+=1
            except Exception as e: print("PACK_WARN", iid, e)
json.dump(manifest, open(arg("--manifest"),"w"))
bpy.ops.wm.save_as_mainfile(filepath=arg("--out"))
print(f"SRC_OK fixed={fixed} keep_recorded={len(manifest)} applied={applied} packed={packed}")
