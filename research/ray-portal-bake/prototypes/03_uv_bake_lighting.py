# TEST 3: bakes real point-light LIGHTING into UV space (proves lightmap).
# Run: blender -b --python 03_uv_bake_lighting.py   (Cycles CPU, Blender 4.2+)
# Part of the Ray Portal UV baking research — see ../FINDINGS.md

import bpy, numpy as np
for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)
N=24
verts=[]; faces=[]
for j in range(N+1):
    for i in range(N+1):
        verts.append((-1+2*i/N,-1+2*j/N,0))
def idx(i,j): return j*(N+1)+i
for j in range(N):
    for i in range(N):
        faces.append((idx(i,j),idx(i+1,j),idx(i+1,j+1),idx(i,j+1)))
# M_real: DIFFUSE white, lit by a point light near +x+y corner
mr=bpy.data.meshes.new("real"); mr.from_pydata(verts,[],faces); mr.update()
Oreal=bpy.data.objects.new("Real",mr); bpy.context.scene.collection.objects.link(Oreal)
m=bpy.data.materials.new("d"); m.use_nodes=True
bsdf=m.node_tree.nodes.get("Principled BSDF"); bsdf.inputs["Base Color"].default_value=(0.8,0.8,0.8,1); bsdf.inputs["Roughness"].default_value=1.0
Oreal.data.materials.append(m)
light=bpy.data.lights.new("L","POINT"); light.energy=60
Lo=bpy.data.objects.new("L",light); Lo.location=(1,1,1); bpy.context.scene.collection.objects.link(Lo)
# M_flat at z=2 with orig_pos attribute + portal
fverts=[((v[0]+1)/2,(v[1]+1)/2,2) for v in verts]
mf=bpy.data.meshes.new("flat"); mf.from_pydata(fverts,[],faces); mf.update()
att=mf.attributes.new("orig_pos","FLOAT_VECTOR","POINT"); att.data.foreach_set("vector",[c for v in verts for c in v])
Oflat=bpy.data.objects.new("Flat",mf); bpy.context.scene.collection.objects.link(Oflat)
pm=bpy.data.materials.new("p"); pm.use_nodes=True; nt=pm.node_tree
for n in list(nt.nodes): nt.nodes.remove(n)
attr=nt.nodes.new("ShaderNodeAttribute"); attr.attribute_name="orig_pos"
addz=nt.nodes.new("ShaderNodeVectorMath"); addz.operation="ADD"; addz.inputs[1].default_value=(0,0,0.01)
nt.links.new(attr.outputs["Vector"], addz.inputs[0])
rp=nt.nodes.new("ShaderNodeBsdfRayPortal"); nt.links.new(addz.outputs[0], rp.inputs["Position"])
dr=nt.nodes.new("ShaderNodeCombineXYZ"); dr.inputs[2].default_value=-1; nt.links.new(dr.outputs[0], rp.inputs["Direction"])
out=nt.nodes.new("ShaderNodeOutputMaterial"); nt.links.new(rp.outputs["BSDF"], out.inputs["Surface"])
Oflat.data.materials.append(pm)
cd=bpy.data.cameras.new("c"); cd.type="ORTHO"; cd.ortho_scale=1.0
cam=bpy.data.objects.new("cam",cd); cam.location=(0.5,0.5,5); bpy.context.scene.collection.objects.link(cam); bpy.context.scene.camera=cam
sc=bpy.context.scene; sc.render.engine="CYCLES"; sc.cycles.device="CPU"; sc.cycles.samples=16
sc.world.use_nodes=True
for n in sc.world.node_tree.nodes:
    if n.type=="BACKGROUND": n.inputs["Color"].default_value=(0,0,0,1)
sc.render.resolution_x=sc.render.resolution_y=128; sc.view_settings.view_transform="Standard"
sc.render.filepath="/tmp/lit.png"; sc.render.image_settings.file_format="PNG"; sc.render.use_file_extension=False
bpy.ops.render.render(write_still=True)
im=bpy.data.images.load("/tmp/lit.png"); b=np.empty(128*128*4,np.float32); im.pixels.foreach_get(b); a=b.reshape(128,128,4)
lum=a[:,:,:3].mean(2)
BL=lum[5:15,5:15].mean(); TR=lum[113:123,113:123].mean(); BR=lum[5:15,113:123].mean(); TL=lum[113:123,5:15].mean()
print("LIT bake luminance: BL(far)=%.3f BR=%.3f TL=%.3f TR(near light)=%.3f"%(BL,BR,TL,TR))
print("LIGHTING BAKED:", TR>BL*1.5 and TR>0.1, "(TR near light should be brightest, BL far dimmest)")
