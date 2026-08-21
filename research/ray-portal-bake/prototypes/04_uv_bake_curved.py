# TEST 4: bakes a curved surface using per-point normals (proves non-flat geometry).
# Run: blender -b --python 04_uv_bake_curved.py   (Cycles CPU, Blender 4.2+)
# Part of the Ray Portal UV baking research — see ../FINDINGS.md

import bpy, numpy as np, math
for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)
N=24
verts=[]; faces=[]
for j in range(N+1):
    for i in range(N+1):
        x=-1+2*i/N; y=-1+2*j/N; z=0.4*(1-(x*x+y*y)/2)  # dome
        verts.append((x,y,z))
def idx(i,j): return j*(N+1)+i
for j in range(N):
    for i in range(N):
        faces.append((idx(i,j),idx(i+1,j),idx(i+1,j+1),idx(i,j+1)))
mr=bpy.data.meshes.new("real"); mr.from_pydata(verts,[],faces); mr.update()
Oreal=bpy.data.objects.new("Real",mr); bpy.context.scene.collection.objects.link(Oreal)
# emission = x,y gradient (independent of z) so we can verify mapping
m=bpy.data.materials.new("e"); m.use_nodes=True; nt=m.node_tree
for n in list(nt.nodes): nt.nodes.remove(n)
geo=nt.nodes.new("ShaderNodeNewGeometry"); sep=nt.nodes.new("ShaderNodeSeparateXYZ"); nt.links.new(geo.outputs["Position"],sep.inputs[0])
mad=nt.nodes.new("ShaderNodeVectorMath"); mad.operation="MULTIPLY_ADD"; mad.inputs[1].default_value=(0.5,0.5,0); mad.inputs[2].default_value=(0.5,0.5,0)
comb=nt.nodes.new("ShaderNodeCombineXYZ"); nt.links.new(sep.outputs["X"],comb.inputs[0]); nt.links.new(sep.outputs["Y"],comb.inputs[1])
nt.links.new(comb.outputs[0], mad.inputs[0])
e=nt.nodes.new("ShaderNodeEmission"); nt.links.new(mad.outputs[0], e.inputs["Color"])
out=nt.nodes.new("ShaderNodeOutputMaterial"); nt.links.new(e.outputs[0], out.inputs["Surface"])
Oreal.data.materials.append(m)
# per-vertex normals
mr.calc_loop_triangles()
nrm=[(0,0,0)]*len(verts)
for v in mr.vertices: nrm[v.index]=tuple(v.normal)
# flat mesh with orig_pos + orig_nrm
fverts=[((verts[k][0]+1)/2,(verts[k][1]+1)/2,3) for k in range(len(verts))]
mf=bpy.data.meshes.new("flat"); mf.from_pydata(fverts,[],faces); mf.update()
ap=mf.attributes.new("orig_pos","FLOAT_VECTOR","POINT"); ap.data.foreach_set("vector",[c for v in verts for c in v])
an=mf.attributes.new("orig_nrm","FLOAT_VECTOR","POINT"); an.data.foreach_set("vector",[c for v in nrm for c in v])
Oflat=bpy.data.objects.new("Flat",mf); bpy.context.scene.collection.objects.link(Oflat)
pm=bpy.data.materials.new("p"); pm.use_nodes=True; nt2=pm.node_tree
for n in list(nt2.nodes): nt2.nodes.remove(n)
ap_n=nt2.nodes.new("ShaderNodeAttribute"); ap_n.attribute_name="orig_pos"
an_n=nt2.nodes.new("ShaderNodeAttribute"); an_n.attribute_name="orig_nrm"
# Position = orig_pos + orig_nrm*0.02
scl=nt2.nodes.new("ShaderNodeVectorMath"); scl.operation="SCALE"; scl.inputs["Scale"].default_value=0.02
nt2.links.new(an_n.outputs["Vector"], scl.inputs[0])
pos=nt2.nodes.new("ShaderNodeVectorMath"); pos.operation="ADD"
nt2.links.new(ap_n.outputs["Vector"], pos.inputs[0]); nt2.links.new(scl.outputs[0], pos.inputs[1])
# Direction = -orig_nrm
neg=nt2.nodes.new("ShaderNodeVectorMath"); neg.operation="SCALE"; neg.inputs["Scale"].default_value=-1
nt2.links.new(an_n.outputs["Vector"], neg.inputs[0])
rp=nt2.nodes.new("ShaderNodeBsdfRayPortal"); nt2.links.new(pos.outputs[0],rp.inputs["Position"]); nt2.links.new(neg.outputs[0],rp.inputs["Direction"])
out2=nt2.nodes.new("ShaderNodeOutputMaterial"); nt2.links.new(rp.outputs["BSDF"],out2.inputs["Surface"])
Oflat.data.materials.append(pm)
cd=bpy.data.cameras.new("c"); cd.type="ORTHO"; cd.ortho_scale=1.0
cam=bpy.data.objects.new("cam",cd); cam.location=(0.5,0.5,6); bpy.context.scene.collection.objects.link(cam); bpy.context.scene.camera=cam
sc=bpy.context.scene; sc.render.engine="CYCLES"; sc.cycles.device="CPU"; sc.cycles.samples=8
sc.world.use_nodes=True
for n in sc.world.node_tree.nodes:
    if n.type=="BACKGROUND": n.inputs["Color"].default_value=(0,0,0,1)
sc.render.resolution_x=sc.render.resolution_y=128; sc.view_settings.view_transform="Standard"
sc.render.filepath="/tmp/curved.png"; sc.render.image_settings.file_format="PNG"; sc.render.use_file_extension=False
bpy.ops.render.render(write_still=True)
im=bpy.data.images.load("/tmp/curved.png"); b=np.empty(128*128*4,np.float32); im.pixels.foreach_get(b); a=b.reshape(128,128,4)
lum=a[:,:,:3].mean(2); coverage=(lum>0.02).mean()
BL=a[10:20,10:20,:3].mean((0,1)); TR=a[108:118,108:118,:3].mean((0,1))
r=lambda v:[round(float(x),2) for x in v]
print("CURVED bake: coverage=%.2f BL=%s TR=%s"%(coverage, r(BL), r(TR)))
print("CURVED WORKS:", coverage>0.9 and TR[0]>BL[0] and TR[1]>BL[1])
