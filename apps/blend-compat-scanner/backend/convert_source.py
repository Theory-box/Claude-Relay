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
remove_list=json.load(open(arg("--remove"))) if arg("--remove") else []
manifest={}; fixed=0; applied=0; removed=0
def _shared_targets(obj, mod_name):
    """All (object, modifier_name) pairs using the same node group as obj.mod_name."""
    m0 = obj.modifiers.get(mod_name)
    grp = getattr(m0, "node_group", None)
    targets = [(obj, mod_name)]
    if grp:
        for o in bpy.data.objects:
            for m in o.modifiers:
                if getattr(m, "node_group", None) is grp and (o.name, m.name) != (obj.name, mod_name):
                    targets.append((o, m.name))
    return targets

# remove chosen modifiers entirely, across every object sharing the group
for entry in remove_list:
    obj_name, mod_name = entry.split("::",1)
    obj=bpy.data.objects.get(obj_name)
    if not (obj and obj.modifiers.get(mod_name)): continue
    for o, mn in _shared_targets(obj, mod_name):
        if o.modifiers.get(mn):
            o.modifiers.remove(o.modifiers[mn]); removed+=1
# apply chosen modifiers first: bakes evaluated geometry into the mesh and removes
# the modifier (and its unfixable nodes) entirely.
for entry in apply_list:
    obj_name, mod_name = entry.split("::",1)
    obj=bpy.data.objects.get(obj_name)
    if not (obj and obj.modifiers.get(mod_name)): continue
    for o, mn in _shared_targets(obj, mod_name):
        if not o.modifiers.get(mn): continue
        try:
            with bpy.context.temp_override(object=o, active_object=o, selected_objects=[o]):
                bpy.ops.object.modifier_apply(modifier=mn)
            applied+=1
        except Exception as e:
            print("APPLY_WARN", o.name, mn, e)
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
purged=0
if arg("--purge")=="1":
    before=sum(len(getattr(bpy.data,c)) for c in ("node_groups","meshes","materials","images","curves"))
    for _ in range(4):
        try: bpy.ops.outliner.orphans_purge(do_recursive=True)
        except Exception: break
    after=sum(len(getattr(bpy.data,c)) for c in ("node_groups","meshes","materials","images","curves"))
    purged=max(0, before-after)
bpy.ops.wm.save_as_mainfile(filepath=arg("--out"))
print(f"SRC_OK fixed={fixed} keep_recorded={len(manifest)} applied={applied} removed={removed} packed={packed} purged={purged}")
