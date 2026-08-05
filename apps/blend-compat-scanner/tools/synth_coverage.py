# Synthetic coverage test — systematically verifies the scanner catches EVERY
# known-breaking node for a version pair, instead of relying on demo files to trip them.
#
# Flow (any version pair):
#   1. gen_compat_db.py  -> compat_db_SRC_to_TGT.json
#   2. SRC_blender -b --python tools/synth_coverage.py -- <db.json> <placed.json>
#        builds /home/claude/synth.blend placing every missing + changed node
#   3. SRC_blender -b synth.blend --python backend/scan_ui.py -- --db <db.json> --out scan.json
#        then assert every type in placed.json appears in scan.json  (0 gaps = full coverage)
#
import bpy, json, sys
db=json.load(open(sys.argv[-2]))
missing=db["missing"]; changed=db["changed"]
placed={"missing":[], "changed":[]}
bpy.ops.wm.read_factory_settings(use_empty=True)

# 1) all MISSING geometry/function nodes -> a GN group on an object (scanner walks node_groups)
ng=bpy.data.node_groups.new("SynthGeo",'GeometryNodeTree')
for nid in missing:
    if nid.startswith(("GeometryNode","FunctionNode")):
        try: ng.nodes.new(nid); placed["missing"].append(nid)
        except Exception: pass
me=bpy.data.meshes.new("m"); ob=bpy.data.objects.new("SynthObj",me); bpy.context.collection.objects.link(ob)
mod=ob.modifiers.new("Synth",'NODES'); mod.node_group=ng

# 2) all MISSING shader nodes -> a material
mat=bpy.data.materials.new("SynthMat"); mat.use_nodes=True; st=mat.node_tree
for nid in missing:
    if nid.startswith("ShaderNode"):
        try: st.nodes.new(nid); placed["missing"].append(nid)
        except Exception: pass
ob.data.materials.append(mat)

# 3) CHANGED nodes (shader/compositor/geo) with their added socket made non-default (linked)
def perturb_added(node, tree, delta):
    for entry in delta.get("in_added",[]):
        sname=entry[0]; sk=node.inputs.get(sname)
        if sk is None: continue
        try:
            v=sk.default_value
            if hasattr(v,"__len__"): sk.default_value=[min(1.0,x+0.37) for x in v]
            else: sk.default_value = (v if isinstance(v,bool) else v+0.37) if not isinstance(v,bool) else (not v)
            return True
        except Exception: return False
    return False
for nid,info in changed.items():
    d=info.get("delta",{})
    if not d.get("in_added"): continue
    try:
        if nid.startswith("ShaderNode"):
            n=st.nodes.new(nid)
            if perturb_added(n,st,d): placed["changed"].append(nid)
        elif nid.startswith("GeometryNode") or nid.startswith("FunctionNode"):
            n=ng.nodes.new(nid)
            if perturb_added(n,ng,d): placed["changed"].append(nid)
        elif nid.startswith("CompositorNode"):
            bpy.context.scene.use_nodes=True; ct=bpy.context.scene.node_tree
            n=ct.nodes.new(nid)
            if perturb_added(n,ct,d): placed["changed"].append(nid)
    except Exception: pass

json.dump(placed, open(sys.argv[-1],"w"))
bpy.ops.wm.save_as_mainfile(filepath="/home/claude/synth.blend")
print(f"placed {len(placed['missing'])} missing + {len(placed['changed'])} changed nodes")
