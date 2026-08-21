# TEST 2: bakes a 3D position-gradient surface into UV space (proves UV mapping).
# Run: blender -b --python 02_uv_bake_gradient.py   (Cycles CPU, Blender 4.2+)
# Part of the Ray Portal UV baking research — see ../FINDINGS.md

import bpy, numpy as np
for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)
N=24
# ---- M_real: grid plane -1..1 at z=0, emission = position gradient (R=(x+1)/2, G=(y+1)/2) ----
verts=[]; faces=[]
for j in range(N+1):
    for i in range(N+1):
        x=-1+2*i/N; y=-1+2*j/N; verts.append((x,y,0))
def idx(i,j): return j*(N+1)+i
for j in range(N):
    for i in range(N):
        faces.append((idx(i,j),idx(i+1,j),idx(i+1,j+1),idx(i,j+1)))
mr=bpy.data.meshes.new("real"); mr.from_pydata(verts,[],faces); mr.update()
Oreal=bpy.data.objects.new("Real",mr); bpy.context.scene.collection.objects.link(Oreal)
m=bpy.data.materials.new("realmat"); m.use_nodes=True; nt=m.node_tree
for n in list(nt.nodes): nt.nodes.remove(n)
geo=nt.nodes.new("ShaderNodeNewGeometry"); sep=nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(geo.outputs["Position"], sep.inputs[0])
# map x,y from -1..1 to 0..1 : *0.5+0.5
def maprange(inp):
    mr_=nt.nodes.new("ShaderNodeMapRange"); mr_.inputs["From Min"].default_value=-1; mr_.inputs["From Max"].default_value=1
    nt.links.new(inp, mr_.inputs["Value"]); return mr_
rx=maprange(sep.outputs["X"]); ry=maprange(sep.outputs["Y"])
comb=nt.nodes.new("ShaderNodeCombineColor")
nt.links.new(rx.outputs[0], comb.inputs[0]); nt.links.new(ry.outputs[0], comb.inputs[1])
emi=nt.nodes.new("ShaderNodeEmission"); nt.links.new(comb.outputs[0], emi.inputs["Color"])
out=nt.nodes.new("ShaderNodeOutputMaterial"); nt.links.new(emi.outputs[0], out.inputs["Surface"])
Oreal.data.materials.append(m)
pass  # keep visible to portal rays

# ---- M_flat: verts at UV=((x+1)/2,(y+1)/2,0); attribute orig_pos = original 3D co ----
fverts=[((v[0]+1)/2,(v[1]+1)/2,2) for v in verts]
mf=bpy.data.meshes.new("flat"); mf.from_pydata(fverts,[],faces); mf.update()
att=mf.attributes.new("orig_pos","FLOAT_VECTOR","POINT")
flat=[c for v in verts for c in v]
att.data.foreach_set("vector", flat)
Oflat=bpy.data.objects.new("Flat",mf); bpy.context.scene.collection.objects.link(Oflat)
pm=bpy.data.materials.new("portalmat"); pm.use_nodes=True; nt2=pm.node_tree
for n in list(nt2.nodes): nt2.nodes.remove(n)
attr=nt2.nodes.new("ShaderNodeAttribute"); attr.attribute_name="orig_pos"
addz=nt2.nodes.new("ShaderNodeVectorMath"); addz.operation="ADD"; addz.inputs[1].default_value=(0,0,0.01)
nt2.links.new(attr.outputs["Vector"], addz.inputs[0])
rp=nt2.nodes.new("ShaderNodeBsdfRayPortal"); nt2.links.new(addz.outputs[0], rp.inputs["Position"])
dr=nt2.nodes.new("ShaderNodeCombineXYZ"); dr.inputs[2].default_value=-1
nt2.links.new(dr.outputs[0], rp.inputs["Direction"])
o2=nt2.nodes.new("ShaderNodeOutputMaterial"); nt2.links.new(rp.outputs["BSDF"], o2.inputs["Surface"])
Oflat.data.materials.append(pm)

# ---- ortho camera framing UV 0..1 ----
cd=bpy.data.cameras.new("c"); cd.type="ORTHO"; cd.ortho_scale=1.0
cam=bpy.data.objects.new("cam",cd); cam.location=(0.5,0.5,5); bpy.context.scene.collection.objects.link(cam); bpy.context.scene.camera=cam
sc=bpy.context.scene; sc.render.engine="CYCLES"; sc.cycles.device="CPU"; sc.cycles.samples=4
sc.world.use_nodes=True
for n in sc.world.node_tree.nodes:
    if n.type=="BACKGROUND": n.inputs["Color"].default_value=(0,0,0,1)
sc.render.resolution_x=sc.render.resolution_y=128
sc.render.filepath="/tmp/bake.png"; sc.render.image_settings.file_format="PNG"; sc.render.use_file_extension=False
sc.view_settings.view_transform="Standard"
bpy.ops.render.render(write_still=True)
im=bpy.data.images.load("/tmp/bake.png"); b=np.empty(128*128*4,np.float32); im.pixels.foreach_get(b); a=b.reshape(128,128,4)
# corners (row 0 = bottom = v=0). BL=(0,0) TR=(1,1)
BL=a[5:15,5:15,:3].mean(axis=(0,1)); BR=a[5:15,113:123,:3].mean(axis=(0,1))
TL=a[113:123,5:15,:3].mean(axis=(0,1)); TR=a[113:123,113:123,:3].mean(axis=(0,1))
r=lambda v:[round(float(x),2) for x in v]
print("BAKE corners: BL(0,0)=%s BR(1,0)=%s TL(0,1)=%s TR(1,1)=%s"%(r(BL),r(BR),r(TL),r(TR)))
print("EXPECT:       BL~[0,0,0] BR~[1,0,0] TL~[0,1,0] TR~[1,1,0]")
ok = BL[0]<0.2 and BR[0]>0.8 and BR[1]<0.2 and TL[1]>0.8 and TL[0]<0.2 and TR[0]>0.8 and TR[1]>0.8
print("UV BAKE WORKS:", ok)
